"""Memory Access submodule: aligned word reads/writes, labelled with the device memory map.

GT32U2086 SRAM accepts only aligned 32-bit accesses, so addresses and lengths must be
multiples of 4. Flash and ROM are never written here (use the programming module).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...adapters.device import parse_int
from ...core.tools import READS_HARDWARE, TOUCHES_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission
from .session import get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp

MAX_READ = 4096
MAX_WRITE_WORDS = 64


def _check_aligned(address: int, length: int) -> None:
    if address % 4 or length % 4:
        raise InvalidArgumentError("Address and length must be multiples of 4 (aligned 32-bit word access).")
    if address < 0 or address + length > 0x1_0000_0000:
        raise InvalidArgumentError("Address range exceeds 32 bits.")


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "memory", READS_HARDWARE)
    def debug_read_memory(address: int | str, length: int = 64) -> dict[str, Any]:
        """Read target memory as little-endian 32-bit words (address/length multiples of 4, at most
        4096 bytes). Reading peripheral registers can have side effects (e.g. FIFO pops, IRQ
        acknowledge): prefer debug_read_peripheral for MMIO."""
        app.policy.require(Permission.HARDWARE, "debug_read_memory")
        start = parse_int(address, "address")
        if not 4 <= length <= MAX_READ:
            raise InvalidArgumentError(f"length must be 4..{MAX_READ}.")
        _check_aligned(start, length)
        with manager.lock:
            words = manager.read_words(start, length // 4)
        device = app.target().device()
        return {
            "address": f"0x{start:08X}", "length": length, "location": device.locate(start),
            "words": [{"address": f"0x{start + 4 * i:08X}", "value": f"0x{w:08X}"} for i, w in enumerate(words)],
        }

    @registry.tool("debug", "memory", TOUCHES_HARDWARE)
    def debug_write_memory(address: int | str, words: list[int | str]) -> dict[str, Any]:
        """Write 32-bit words to target RAM or peripheral registers (aligned, at most 64 words).
        Writes to Flash/ROM are refused. Peripheral writes take effect immediately on hardware."""
        app.policy.require(Permission.HARDWARE, "debug_write_memory")
        start = parse_int(address, "address")
        if not 1 <= len(words) <= MAX_WRITE_WORDS:
            raise InvalidArgumentError(f"Pass 1..{MAX_WRITE_WORDS} words.")
        values = [parse_int(w, "word") for w in words]
        if any(not 0 <= v <= 0xFFFFFFFF for v in values):
            raise InvalidArgumentError("Each word must fit in 32 bits.")
        _check_aligned(start, 4 * len(values))
        device = app.target().device()
        first, last = device.locate(start), device.locate(start + 4 * len(values) - 4)
        for where in (first, last):
            if where["kind"] in ("flash", "rom", "unmapped"):
                raise InvalidArgumentError(
                    f"Refusing to write {where.get('region', 'unmapped memory')} ({where['kind']}).",
                    "Only RAM and peripheral registers can be written; program Flash with prog_flash_uart.")
        payload = b"".join(v.to_bytes(4, "little") for v in values).hex()
        with manager.lock:
            gdb = manager.require_halted()
            gdb.command(f"-data-write-memory-bytes 0x{start:X} {payload}")
            readback = manager.read_words(start, len(values))
        return {"address": f"0x{start:08X}", "location": first,
                "written": [f"0x{v:08X}" for v in values], "readback": [f"0x{v:08X}" for v in readback],
                "matches": readback == values}
