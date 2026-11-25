"""Debug and exception analysis against a real Cortex-M0 ELF.

Needs arm-none-eabi-gcc/objdump; the debug test also needs a GDB with Arm support
(arm-none-eabi-gdb or gdb-multiarch, or NEON_MCP_GDB). The target is tests/fake_gdbserver.py.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from neon_mcp.adapters.gdb import find_gdb
from neon_mcp.core.server import create_server
from neon_mcp.system.errors import NeonError

from .conftest import ToolCaller, make_app
from .fake_gdbserver import FakeCortexM, FakeGdbServer

pytestmark = pytest.mark.anyio

SOURCE = """
volatile unsigned int counter;
unsigned int buffer[4] = {1, 2, 3, 4};

__attribute__((noinline)) unsigned char read_byte(volatile unsigned char *p) { return *p; }

__attribute__((noinline)) int helper(int x) {
    counter += (unsigned int)x;
    return x * 3;
}

int main(void) {
    int total = 0;
    for (int i = 0; i < 4; i++) {
        total += helper(i);
    }
    return total + read_byte((volatile unsigned char *)buffer);
}

void Reset_Handler(void) { main(); for (;;) { } }
"""

needs_gcc = pytest.mark.skipif(shutil.which("arm-none-eabi-gcc") is None or shutil.which("arm-none-eabi-objdump") is None,
                               reason="arm-none-eabi-gcc/objdump not installed")


def _gdb() -> str | None:
    try:
        return find_gdb(None)
    except NeonError:
        return None


def symbols(elf: Path) -> dict[str, int]:
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], capture_output=True, text=True, check=True).stdout
    return {parts[2]: int(parts[0], 16) for parts in (line.split() for line in out.splitlines()) if len(parts) == 3}


@pytest.fixture
def arm_elf(tmp_path: Path) -> Path:
    source = tmp_path / "prog.c"
    source.write_text(SOURCE)
    elf = tmp_path / "prog.elf"
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=cortex-m0", "-mthumb", "-g", "-O1", "-nostdlib",
                    "-Wl,-Ttext=0x20080", "-Wl,-Tdata=0x01001000", "-Wl,-e,Reset_Handler",
                    "-o", str(elf), str(source)], check=True, capture_output=True)
    return elf


def ldrb_address(elf: Path) -> int:
    out = subprocess.run(["arm-none-eabi-objdump", "-d", str(elf)], capture_output=True, text=True, check=True).stdout
    in_func = False
    for line in out.splitlines():
        if line.endswith("<read_byte>:"):
            in_func = True
        elif in_func and "\tldrb" in line:
            return int(line.split(":")[0], 16)
    raise AssertionError("no ldrb in read_byte")


@needs_gcc
async def test_exception_word_only_sram_violation(call, arm_elf: Path):
    pc = ldrb_address(arm_elf)
    frame = ["0x01001001", "0", "0", "0", "0", hex(symbols(arm_elf)["main"] + 8), hex(pc), "0x01000000"]
    result = await call("analysis_decode_exception", stack_frame=frame, exc_return="0xFFFFFFF9",
                        handler_xpsr="0x3", elf_path=str(arm_elf))
    assert result["instruction"]["class"] == "narrow_memory_access"
    assert result["instruction"]["effective_address"] == "0x01001001"
    assert result["pc"]["symbol"]["symbol"] == "read_byte"
    assert result["pc"]["symbol"]["source"]["file"].endswith("prog.c")
    assert any("SRAM" in f["cause"] and f["severity"] == "high" for f in result["findings"])


@needs_gcc
@pytest.mark.skipif(_gdb() is None, reason="no GDB with Arm support (arm-none-eabi-gdb / gdb-multiarch)")
async def test_debug_session_end_to_end(tmp_path: Path, arm_elf: Path):
    syms = symbols(arm_elf)
    target = FakeCortexM(arm_elf)
    server = FakeGdbServer(target)
    try:
        async with Client(create_server(make_app(tmp_path, allow_hardware=True))) as client:
            call = ToolCaller(client)
            assert "openocd_config" in await call.error("debug_connect")

            connected = await call("debug_connect", gdb_server=f"localhost:{server.port}", elf_path=str(arm_elf))
            assert connected["connected"] and connected["state"] == "stopped"
            assert any("not verified" in w for w in connected["warnings"])

            regs = await call("debug_read_registers")
            assert int(regs["registers"]["pc"], 16) == syms["main"] & ~1
            assert regs["xpsr_decoded"]["thumb"] is True

            bp = await call("debug_breakpoint", action="set", location="helper")
            assert bp["breakpoint"]["type"] == "hw breakpoint"
            hit = await call("debug_control", action="continue")
            assert hit["stop"]["reason"] == "breakpoint-hit" and hit["stop"]["function"] == "helper"
            trace = await call("debug_backtrace")
            assert trace["frames"][0]["function"] == "helper" and trace["frames"][0]["file"].endswith("prog.c")

            memory = await call("debug_read_memory", address=hex(syms["buffer"]), length=16)
            assert [w["value"] for w in memory["words"]] == ["0x00000001", "0x00000002", "0x00000003", "0x00000004"]
            assert memory["location"]["kind"] == "ram"
            written = await call("debug_write_memory", address=hex(syms["buffer"]), words=["0xDEADBEEF"])
            assert written["matches"]
            assert "Refusing" in await call.error("debug_write_memory", address="0x00020080", words=[0])
            assert "multiples of 4" in await call.error("debug_read_memory", address="0x01001001", length=4)

            periph = await call("debug_read_peripheral", peripheral="UART0", registers=["LSR"])
            assert periph["registers"][0]["value"] == "0x00000060"
            assert "Name the registers" in await call.error("debug_read_peripheral", peripheral="UART0")

            listed = await call("debug_breakpoint", action="list")
            assert listed["breakpoints"][0]["func"] == "helper"
            await call("debug_breakpoint", action="delete", number=int(listed["breakpoints"][0]["number"]))

            running = await call("debug_control", action="continue", wait_s=0.5)
            assert running["state"] == "running"
            assert "running" in await call.error("debug_read_registers")
            halted = await call("debug_control", action="halt")
            assert halted["state"] == "stopped" and halted["stop"]["signal_name"] == "SIGINT"

            # Simulate a HardFault: handler LR = EXC_RETURN (MSP), xPSR = 3, frame on MSP.
            msp = 0x0101FF00
            frame = [0x01001001, 0, 0, 0, 0, syms["main"] | 1, ldrb_address(arm_elf), 0x01000000]
            await call("debug_write_memory", address=hex(msp), words=[hex(w) for w in frame])
            target.regs.update(lr=0xFFFFFFF9, xpsr=0x00000003, msp=msp)
            await call("debug_control", action="reset")  # flushes GDB's register cache
            assert target.monitor_log == ["reset halt"]
            fault = await call("analysis_decode_exception", from_debug_session=True, elf_path=str(arm_elf))
            assert fault["active_exception"] == "HardFault" and fault["stack_pointer"] == f"0x{msp:08X}"
            assert fault["pc"]["symbol"]["symbol"] == "read_byte"
            assert any("SRAM" in f["cause"] for f in fault["findings"])

            assert (await call("session_get_context"))["debug_connected"] is True
            done = await call("debug_disconnect")
            assert done["connected"] is False
            assert "No debug session" in await call.error("debug_read_registers")
    finally:
        server.close()
