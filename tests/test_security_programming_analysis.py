import shutil
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from neon_mcp.core.server import create_server

from .conftest import ToolCaller, make_app

pytestmark = pytest.mark.anyio


async def test_hardware_tools_disabled_by_default(call):
    message = await call.error("prog_flash_uart", port="/dev/ttyUSB0", app_dir="examples/Printf_Log")
    assert "--allow-hardware" in message
    assert "--allow-hardware" in await call.error("analysis_capture_uart", port="/dev/ttyUSB0")


async def test_read_only_mode(tmp_path: Path):
    async with Client(create_server(make_app(tmp_path, read_only=True))) as client:
        call = ToolCaller(client)
        assert "read-only" in await call.error("dev_create_project", name="X", parent_dir=str(tmp_path))
        assert (await call("session_get_context"))["permissions"] == {"read": True, "write": False,
                                                                      "hardware": False}


async def test_paths_outside_workspace_rejected(call):
    assert "outside the allowed workspace" in await call.error("sdk_read_source", path="/etc/hostname")
    assert "outside the allowed workspace" in await call.error("dev_create_project", name="X", parent_dir="/tmp")


async def test_session_defaults(call):
    ctx = await call("session_set_context", app_dir="examples/Printf_Log", serial_port="/dev/ttyUSB0")
    assert ctx["session"]["app_dir"].endswith("examples/Printf_Log")
    config = await call("dev_get_config", filter="PRINTF")
    assert config["app_dir"].endswith("examples/Printf_Log")


async def test_boot_modes_and_ports(call):
    modes = await call("prog_list_boot_modes")
    assert [m["code"] for m in modes["boot_modes"]] == ["000", "100", "101", "111"]
    ports = await call("prog_list_serial_ports")
    assert isinstance(ports["ports"], list)


async def test_inspect_invalid_image(call, tmp_path: Path):
    bogus = tmp_path / "bogus_image.bin"
    bogus.write_bytes(b"\x00" * 256)
    report = await call("prog_inspect_image", image_path=str(bogus))
    assert report["images"][0]["ok"] is False and report["images"][0]["problems"]
    verified = await call("prog_verify_image", image_path=str(bogus))
    assert verified["images"][0]["valid"] is False


async def test_decode_register(call):
    by_name = await call("analysis_decode_register", peripheral="UART0", register="LSR", value="0x60")
    fields = {f["field"]: f["value"] for f in by_name["views"][0]["fields"]}
    assert by_name["register"] == "LSR" and fields.get("THRE", fields.get("THRF")) is not None
    by_address = await call("analysis_decode_register", address=by_name["address"], value=0x60)
    assert by_address["register"] == "LSR"


@pytest.mark.skipif(shutil.which("gcc") is None, reason="host gcc not available")
async def test_resolve_address_with_dwarf(call, tmp_path: Path):
    source = tmp_path / "prog.c"
    source.write_text("int helper(int x) {\n    return x * 3;\n}\nint main(void) {\n    return helper(2);\n}\n")
    elf = tmp_path / "prog"
    subprocess.run(["gcc", "-g", "-O0", "-o", str(elf), str(source)], check=True)
    symbols = subprocess.run(["nm", str(elf)], capture_output=True, text=True, check=True).stdout
    helper = next(int(line.split()[0], 16) for line in symbols.splitlines() if line.endswith(" helper"))
    result = await call("analysis_resolve_address", addresses=[hex(helper + 4)], elf_path=str(elf))
    hit = result["results"][0]
    assert hit["symbol"] == "helper" and hit["offset"] == 4
    assert hit["source"]["file"].endswith("prog.c") and hit["source"]["line"] in (1, 2)
    summary = await call("analysis_elf_summary", elf_path=str(elf))
    assert any(s["name"] == ".text" for s in summary["sections"])
