"""ELF submodule: sections, Flash/RAM usage against the device profile, symbols and address lookup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters.device import parse_int
from ...adapters.elf import ElfImage
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError, NeonError, NotFoundError
from ..development.build import find_elf

if TYPE_CHECKING:
    from ...core.app import NeonApp


def usage(app: NeonApp, segments: list[dict]) -> list[dict]:
    """Compare PT_LOAD segments with the allocatable Flash/RAM ranges of each memory profile."""
    try:
        device = app.target().device()
    except NeonError:
        return []
    rows = []
    for profile in device.profiles():
        try:
            flash_start, flash_size = device.application_range(profile["name"], "flash")
            ram_start, ram_size = device.application_range(profile["name"], "ram")
        except NotFoundError:
            continue
        flash_used = sum(s["filesz"] for s in segments if flash_start <= s["paddr"] < flash_start + flash_size)
        if not flash_used:
            continue
        ram_used = sum(s["memsz"] for s in segments if ram_start <= s["vaddr"] < ram_start + ram_size)
        rows.append({
            "profile": profile["name"],
            "flash": {"start": f"0x{flash_start:08X}", "used": flash_used, "capacity": flash_size,
                      "percent": round(100 * flash_used / flash_size, 2)},
            "ram": {"start": f"0x{ram_start:08X}", "used": ram_used, "capacity": ram_size,
                    "percent": round(100 * ram_used / ram_size, 2),
                    "note": "includes .data, .bss and the reserved heap/stack section"},
        })
    return rows


def resolve_addresses(path: Path, addresses: list[int]) -> list[dict[str, Any]]:
    results = []
    with ElfImage(path) as elf:
        for address in addresses:
            lookup = address & ~1 if elf.is_thumb_arm else address
            sym = elf.symbol_for(lookup)
            results.append({
                "address": f"0x{address:08X}",
                "symbol": sym[0].name if sym else None,
                "offset": sym[1] if sym else None,
                "kind": sym[0].kind if sym else None,
                "section": sym[0].section if sym else None,
                "source": elf.source_line(lookup),
            })
    return results


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("analysis", "elf", READ_ONLY)
    def analysis_elf_summary(elf_path: str | None = None, app_dir: str | None = None,
                             build_dir: str | None = None, top_symbols: int = 15) -> dict[str, Any]:
        """Summarize a firmware ELF: allocated sections, Flash/RAM use against the device profile's
        application areas, entry point and the largest functions/objects.

        Pass elf_path, or app_dir to use the ELF from its build directory.
        """
        if not 0 <= top_symbols <= 100:
            raise InvalidArgumentError("top_symbols must be 0..100.")
        path = find_elf(app, elf_path, app_dir, build_dir)
        with ElfImage(path) as elf:
            sections = elf.sections()
            symbols = sorted((s for s in elf.symbols() if s.size), key=lambda s: s.size, reverse=True)
            segments = elf.load_segments()
            entry = elf.elf.header["e_entry"]
        return {
            "elf": str(path), "entry_point": f"0x{entry:08X}", "sections": sections, "usage": usage(app, segments),
            "largest_symbols": [{"name": s.name, "kind": s.kind, "size": s.size, "address": f"0x{s.address:08X}",
                                 "section": s.section} for s in symbols[:top_symbols]],
        }

    @registry.tool("analysis", "elf", READ_ONLY)
    def analysis_resolve_address(addresses: list[int | str], elf_path: str | None = None,
                                 app_dir: str | None = None, build_dir: str | None = None) -> dict[str, Any]:
        """Map code/data addresses (e.g. a stacked PC/LR from a fault, a value in a log) to
        symbol+offset and, when the ELF has debug info, source file:line.

        Thumb bit 0 is ignored for Arm code addresses. Up to 64 addresses per call.
        """
        if not 1 <= len(addresses) <= 64:
            raise InvalidArgumentError("Pass 1..64 addresses.")
        path = find_elf(app, elf_path, app_dir, build_dir)
        return {"elf": str(path), "results": resolve_addresses(path, [parse_int(a, "address") for a in addresses])}
