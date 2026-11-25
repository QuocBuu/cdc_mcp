"""Source Explorer submodule: grep-like search and line-numbered reading of SDK files."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError

if TYPE_CHECKING:
    from ...core.app import NeonApp

_TEXT_SUFFIXES = {".c", ".h", ".s", ".S", ".ld", ".cmake", ".txt", ".py", ".yaml", ".yml", ".json", ".md",
                  ".ts", ".cfg"}
_TEXT_NAMES = {"Kconfig", "CMakeLists.txt", "sdkconfig", "VERSION"}
_SKIP_DIRS = {".git", "build", "node_modules", "dist", ".venv", "__pycache__"}
_VENDOR_DIRS = ("neon-mdf/arch/CortexM/CMSIS/CMSIS_5", "neon-mdf/rtos/FreeRTOS-Kernel")
_MAX_FILE_BYTES = 1_000_000


def iter_text_files(root: Path, include_vendor: bool):
    vendor = tuple(root / v for v in _VENDOR_DIRS)
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir(), reverse=True)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS or (not include_vendor and entry in vendor):
                    continue
                stack.append(entry)
            elif (entry.suffix in _TEXT_SUFFIXES or entry.name in _TEXT_NAMES) and \
                    entry.stat().st_size <= _MAX_FILE_BYTES:
                yield entry


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("sdk", "source", READ_ONLY)
    def sdk_search_source(pattern: str, path_glob: str | None = None, regex: bool = False,
                          include_vendor: bool = False, ignore_case: bool = True,
                          limit: int = 100) -> dict[str, Any]:
        """Search SDK files (C sources, headers, CMake, Kconfig, Python tools, YAML, docs) like grep.

        path_glob filters SDK-relative paths, e.g. "neon-mdf/components/driver/spi/*" or "*.cmake".
        Vendored CMSIS_5 and FreeRTOS-Kernel are skipped unless include_vendor is true.
        """
        if not pattern:
            raise InvalidArgumentError("pattern must not be empty.")
        if not 1 <= limit <= 500:
            raise InvalidArgumentError("limit must be 1..500.")
        try:
            matcher = re.compile(pattern if regex else re.escape(pattern), re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            raise InvalidArgumentError(f"Invalid regular expression: {exc}") from exc
        root = app.sdk.root
        matches = []
        files_scanned = 0
        truncated = False
        for path in iter_text_files(root, include_vendor):
            rel = path.relative_to(root).as_posix()
            if path_glob and not fnmatch.fnmatch(rel, path_glob):
                continue
            files_scanned += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if matcher.search(line):
                    matches.append({"file": rel, "line": number, "text": line.strip()[:300]})
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break
        return {"pattern": pattern, "files_scanned": files_scanned, "truncated": truncated, "matches": matches}

    @registry.tool("sdk", "source", READ_ONLY)
    def sdk_read_source(path: str, start_line: int = 1, end_line: int | None = None,
                        max_lines: int = 400) -> dict[str, Any]:
        """Read a text file from the SDK or workspace with line numbers.

        path: SDK-relative (e.g. "neon-mdf/components/driver/uart/neon_uart.h") or a workspace path.
        Use the file:line locations returned by sdk_search_api / sdk_search_source.
        """
        candidate = Path(path)
        if not candidate.is_absolute() and (app.sdk.root / candidate).exists():
            candidate = app.sdk.root / candidate
        resolved = app.workspace.resolve(candidate, kind="file")
        if resolved.stat().st_size > 5_000_000:
            raise InvalidArgumentError(f"'{resolved}' is too large to read as text.")
        if start_line < 1 or not 1 <= max_lines <= 2000:
            raise InvalidArgumentError("start_line must be >= 1 and max_lines 1..2000.")
        raw = resolved.read_bytes()
        if b"\x00" in raw[:8192]:
            raise InvalidArgumentError(f"'{resolved}' looks like a binary file.")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        last = min(end_line or len(lines), len(lines), start_line + max_lines - 1)
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start_line, last + 1))
        return {"file": str(resolved), "total_lines": len(lines), "start_line": start_line,
                "end_line": last, "truncated": last < (end_line or len(lines)), "content": body}
