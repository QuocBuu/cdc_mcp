"""Minimal GDB Remote Serial Protocol stub that imitates a halted Cortex-M0 target.

It serves registers, memory loaded from an ELF's PT_LOAD segments, a zeroed SRAM window,
a few peripheral words, hardware/software breakpoints (continue jumps to the next inserted
breakpoint), Ctrl-C interrupts and `monitor` commands. Enough to exercise NEON MCP's GDB/MI
debug tools end to end without hardware.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from elftools.elf.elffile import ELFFile

REG_NAMES = [*(f"r{i}" for i in range(13)), "sp", "lr", "pc", "xpsr", "msp", "psp", "primask", "control"]
REG_NUMS = [*range(16), 25, 26, 27, 28, 29]

TARGET_XML = (
    '<?xml version="1.0"?><!DOCTYPE target SYSTEM "gdb-target.dtd"><target><architecture>arm</architecture>'
    '<feature name="org.gnu.gdb.arm.m-profile">'
    + "".join(f'<reg name="r{i}" bitsize="32" regnum="{i}"/>' for i in range(13))
    + '<reg name="sp" bitsize="32" type="data_ptr" regnum="13"/><reg name="lr" bitsize="32" regnum="14"/>'
    '<reg name="pc" bitsize="32" type="code_ptr" regnum="15"/><reg name="xpsr" bitsize="32" regnum="25"/>'
    '</feature><feature name="org.gnu.gdb.arm.m-system">'
    '<reg name="msp" bitsize="32" type="data_ptr" regnum="26"/><reg name="psp" bitsize="32" type="data_ptr" regnum="27"/>'
    '<reg name="primask" bitsize="32" regnum="28"/><reg name="control" bitsize="32" regnum="29"/>'
    "</feature></target>"
)


def _checksum(data: str) -> str:
    return f"{sum(data.encode('latin-1')) % 256:02x}"


class FakeCortexM:
    def __init__(self, elf: Path, entry_symbol: str = "main") -> None:
        self.memory: dict[int, int] = {}
        with elf.open("rb") as f:
            image = ELFFile(f)
            for seg in image.iter_segments():
                if seg["p_type"] == "PT_LOAD":
                    data = seg.data()
                    for base in {seg["p_vaddr"], seg["p_paddr"]}:
                        for i, byte in enumerate(data):
                            self.memory[base + i] = byte
            symtab = image.get_section_by_name(".symtab")
            entry = next(s for s in symtab.iter_symbols() if s.name == entry_symbol)["st_value"] & ~1
        self.ram = (0x01000000, 0x01020000)
        self.periph = {0x440D0014: 0x60}  # UART0 LSR: THR empty + transmitter empty
        self.regs = dict.fromkeys(REG_NAMES, 0)
        self.regs.update(pc=entry, sp=0x0101FF00, msp=0x0101FF00, lr=0xFFFFFFFF, xpsr=0x01000000)
        self.breakpoints: set[int] = set()
        self.monitor_log: list[str] = []

    # memory -------------------------------------------------------------------------------------
    def read(self, address: int, length: int) -> bytes | None:
        out = bytearray()
        for a in range(address, address + length):
            if a in self.memory:
                out.append(self.memory[a])
            elif self.ram[0] <= a < self.ram[1]:
                out.append(0)
            elif (a & ~3) in self.periph:
                out.append(self.periph[a & ~3] >> (8 * (a & 3)) & 0xFF)
            else:
                return None
        return bytes(out)

    def write(self, address: int, data: bytes) -> None:
        for i, byte in enumerate(data):
            self.memory[address + i] = byte


class FakeGdbServer:
    def __init__(self, target: FakeCortexM) -> None:
        self.target = target
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.running = False
        self.packets: list[str] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.sock.close()

    def _send(self, conn: socket.socket, data: str) -> None:
        conn.sendall(f"${data}#{_checksum(data)}".encode("latin-1"))

    def _serve(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        buffer = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while buffer:
                    head = buffer[:1]
                    if head in (b"+", b"-"):
                        buffer = buffer[1:]
                    elif head == b"\x03":
                        buffer = buffer[1:]
                        if self.running:
                            self.running = False
                            self._send(conn, "S02")
                    elif head == b"$":
                        end = buffer.find(b"#")
                        if end < 0 or len(buffer) < end + 3:
                            break
                        packet = buffer[1:end].decode("latin-1")
                        buffer = buffer[end + 3:]
                        conn.sendall(b"+")
                        self.packets.append(packet)
                        reply = self._handle(packet)
                        if reply is not None:
                            self._send(conn, reply)
                        if packet in ("D", "k"):
                            return
                    else:
                        buffer = buffer[1:]

    def _regs_hex(self) -> str:
        return "".join(self.target.regs[name].to_bytes(4, "little").hex() for name in REG_NAMES)

    def _handle(self, packet: str) -> str | None:
        t = self.target
        if packet.startswith("qSupported"):
            return "PacketSize=1000;qXfer:features:read+"
        if packet.startswith("qXfer:features:read:target.xml:"):
            offset, length = (int(x, 16) for x in packet.rsplit(":", 1)[1].split(","))
            chunk = TARGET_XML[offset:offset + length]
            return ("l" if offset + length >= len(TARGET_XML) else "m") + chunk
        if packet == "?":
            return "S05"
        if packet == "qC":
            return "QC1"
        if packet == "qfThreadInfo":
            return "m1"
        if packet == "qsThreadInfo":
            return "l"
        if packet == "qAttached":
            return "1"
        if packet.startswith(("H", "qSymbol")):
            return "OK"
        if packet == "g":
            return self._regs_hex()
        if packet.startswith("p"):
            number = int(packet[1:], 16)
            if number in REG_NUMS:
                return t.regs[REG_NAMES[REG_NUMS.index(number)]].to_bytes(4, "little").hex()
            return "E01"
        if packet.startswith("P"):
            number, value = packet[1:].split("=")
            if int(number, 16) in REG_NUMS:
                t.regs[REG_NAMES[REG_NUMS.index(int(number, 16))]] = int.from_bytes(bytes.fromhex(value), "little")
                return "OK"
            return "E01"
        if packet.startswith("m"):
            address, length = (int(x, 16) for x in packet[1:].split(","))
            data = t.read(address, length)
            return data.hex() if data is not None else "E01"
        if packet.startswith("M"):
            header, data = packet[1:].split(":")
            address = int(header.split(",")[0], 16)
            t.write(address, bytes.fromhex(data))
            return "OK"
        if packet[:2] in ("Z0", "Z1"):
            t.breakpoints.add(int(packet.split(",")[1], 16))
            return "OK"
        if packet[:2] in ("z0", "z1"):
            t.breakpoints.discard(int(packet.split(",")[1], 16))
            return "OK"
        if packet[:2] in ("Z2", "Z3", "Z4", "z2", "z3", "z4"):
            return "OK"
        if packet == "c" or packet.startswith("c"):
            targets = sorted(a for a in t.breakpoints if a != t.regs["pc"])
            if targets:
                t.regs["pc"] = targets[0]
                return "S05"
            self.running = True
            return None
        if packet.startswith("qRcmd,"):
            command = bytes.fromhex(packet[6:]).decode()
            t.monitor_log.append(command)
            return "OK"
        if packet in ("D", "k"):
            return "OK"
        return ""
