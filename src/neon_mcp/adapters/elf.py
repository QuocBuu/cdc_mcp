"""ELF inspection with pyelftools: sections, memory usage, symbols and address → source line."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

from ..system.errors import InvalidArgumentError

_SHF_ALLOC = 0x2
_SHF_EXECINSTR = 0x4


@dataclass
class Symbol:
    name: str
    address: int
    size: int
    kind: str
    section: str | None


class ElfImage:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._file = path.open("rb")
            self.elf = ELFFile(self._file)
        except (OSError, ELFError) as exc:
            raise InvalidArgumentError(f"'{path}' is not a readable ELF file: {exc}") from exc
        self._symbols: list[Symbol] | None = None
        self._lines: tuple[list[int], list[tuple[str, int]]] | None = None

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> ElfImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def is_thumb_arm(self) -> bool:
        return self.elf.header["e_machine"] == "EM_ARM"

    def sections(self) -> list[dict]:
        result = []
        for s in self.elf.iter_sections():
            flags = s["sh_flags"]
            if not flags & _SHF_ALLOC or s["sh_size"] == 0:
                continue
            result.append({
                "name": s.name, "address": f"0x{s['sh_addr']:08X}", "size": s["sh_size"],
                "load": s["sh_type"] != "SHT_NOBITS", "exec": bool(flags & _SHF_EXECINSTR),
                "write": bool(flags & 0x1),
            })
        return result

    def load_segments(self) -> list[dict]:
        """PT_LOAD segments: where bytes live in Flash (paddr) vs. where they run (vaddr)."""
        result = []
        for seg in self.elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            result.append({"vaddr": seg["p_vaddr"], "paddr": seg["p_paddr"],
                           "filesz": seg["p_filesz"], "memsz": seg["p_memsz"]})
        return result

    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            sections = list(self.elf.iter_sections())
            syms = []
            for table in sections:
                if not isinstance(table, SymbolTableSection):
                    continue
                for sym in table.iter_symbols():
                    kind = sym["st_info"]["type"]
                    if kind not in ("STT_FUNC", "STT_OBJECT") or not sym.name:
                        continue
                    shndx = sym["st_shndx"]
                    section = sections[shndx].name if isinstance(shndx, int) and shndx < len(sections) else None
                    address = sym["st_value"]
                    if kind == "STT_FUNC" and self.is_thumb_arm:
                        address &= ~1
                    syms.append(Symbol(sym.name, address, sym["st_size"],
                                       "function" if kind == "STT_FUNC" else "object", section))
            syms.sort(key=lambda s: s.address)
            self._symbols = syms
        return self._symbols

    def symbol_for(self, address: int) -> tuple[Symbol, int] | None:
        best = None
        for sym in self.symbols():
            if sym.address > address:
                break
            if sym.address <= address < sym.address + max(sym.size, 1):
                best = sym
        return (best, address - best.address) if best else None

    def _line_table(self) -> tuple[list[int], list[tuple[str, int]]]:
        if self._lines is None:
            rows: list[tuple[int, str, int]] = []
            if self.elf.has_dwarf_info():
                dwarf = self.elf.get_dwarf_info()
                for cu in dwarf.iter_CUs():
                    program = dwarf.line_program_for_CU(cu)
                    if program is None:
                        continue
                    header = program.header
                    files = header["file_entry"]
                    dirs = header["include_directory"]
                    version = header["version"]
                    for entry in program.get_entries():
                        state = entry.state
                        if state is None or state.end_sequence:
                            continue
                        index = state.file if version >= 5 else state.file - 1
                        if not 0 <= index < len(files):
                            continue
                        fe = files[index]
                        name = fe.name.decode(errors="replace") if isinstance(fe.name, bytes) else str(fe.name)
                        dir_index = fe.dir_index if version >= 5 else fe.dir_index - 1
                        if 0 <= dir_index < len(dirs) and not name.startswith("/"):
                            d = dirs[dir_index]
                            d = d.decode(errors="replace") if isinstance(d, bytes) else str(d)
                            name = f"{d}/{name}"
                        rows.append((state.address, name, state.line))
            rows.sort(key=lambda r: r[0])
            self._lines = ([r[0] for r in rows], [(r[1], r[2]) for r in rows])
        return self._lines

    def source_line(self, address: int) -> dict | None:
        addresses, locations = self._line_table()
        index = bisect.bisect_right(addresses, address) - 1
        if index < 0:
            return None
        sym = self.symbol_for(address)
        # Reject matches that belong to a different function than the address.
        if sym is not None and addresses[index] < sym[0].address:
            return None
        file, line = locations[index]
        return {"file": file, "line": line}
