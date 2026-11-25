"""Drive the application's CMake/Ninja build exactly like the SDK documentation does.

Configure: `cmake --preset <PRESET> [-B <dir>] [--fresh] -D...` from the application directory.
Build:     `cmake --build <dir> [--target <t>]`.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from ..system.errors import InvalidArgumentError, NotFoundError
from ..system.process import ProcessResult, run

_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(:[A-Z]+)?$")
_DIAG = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
                   r"(?P<severity>fatal error|error|warning|note):\s*(?P<message>.*)$")
_CMAKE_ERROR = re.compile(r"^CMake (Error|Warning)(?: \(dev\))? at (?P<file>[^:]+):(?P<line>\d+)")
_SIZE_HEADER = re.compile(r"^\s*text\s+data\s+bss\s+dec\s+hex\s+filename", re.IGNORECASE)
_ELF_MAGIC = b"\x7fELF"


@dataclass
class BuildLayout:
    app_dir: Path
    build_dir: Path
    preset: str

    @property
    def configured(self) -> bool:
        return (self.build_dir / "CMakeCache.txt").is_file()


def layout(app_dir: Path, preset: str, build_dir: Path | None) -> BuildLayout:
    if not (app_dir / "CMakeLists.txt").is_file():
        raise NotFoundError(f"'{app_dir}' has no CMakeLists.txt; it is not a NEON-MDF application.")
    if not (app_dir / "CMakePresets.json").is_file():
        raise NotFoundError(f"'{app_dir}' has no CMakePresets.json.",
                            "NEON-MDF applications include <sdk>/cmake/presets/targets.json from CMakePresets.json.")
    return BuildLayout(app_dir, build_dir or app_dir / "build" / preset, preset)


def read_cache(build_dir: Path) -> dict[str, str]:
    cache = {}
    path = build_dir / "CMakeCache.txt"
    if not path.is_file():
        return cache
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("#", "//")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cache[key.split(":", 1)[0]] = value
    return cache


def configure(lay: BuildLayout, *, python: str, fresh: bool, cache_vars: dict[str, str],
              timeout_s: float) -> ProcessResult:
    command = ["cmake", "--preset", lay.preset]
    if lay.build_dir != lay.app_dir / "build" / lay.preset:
        command += ["-B", str(lay.build_dir)]
    if fresh:
        command.append("--fresh")
    variables = {"Python3_EXECUTABLE": python, **cache_vars}
    for name, value in variables.items():
        if not _VAR_NAME.match(name):
            raise InvalidArgumentError(f"Invalid CMake cache variable name '{name}'.")
        text = str(value)
        if "\n" in text or "\r" in text:
            raise InvalidArgumentError(f"CMake variable {name} must be a single line.")
        command.append(f"-D{name}={text}")
    return run(command, lay.app_dir, timeout_s=timeout_s)


def build(lay: BuildLayout, *, target: str | None, timeout_s: float, env: dict[str, str] | None = None) -> ProcessResult:
    command = ["cmake", "--build", str(lay.build_dir)]
    if target:
        if not re.match(r"^[A-Za-z0-9_.+-]+$", target):
            raise InvalidArgumentError(f"Invalid build target name '{target}'.")
        command += ["--target", target]
    return run(command, lay.app_dir, timeout_s=timeout_s, env=env)


def parse_diagnostics(output: str, limit: int = 50) -> list[dict]:
    diagnostics = []
    for line in output.splitlines():
        match = _DIAG.match(line.strip())
        if match and match.group("severity") != "note":
            diagnostics.append({
                "file": match.group("file"), "line": int(match.group("line")),
                "column": int(match.group("col")) if match.group("col") else None,
                "severity": "error" if "error" in match.group("severity") else "warning",
                "message": match.group("message").strip(),
            })
            continue
        match = _CMAKE_ERROR.match(line.strip())
        if match:
            diagnostics.append({"file": match.group("file"), "line": int(match.group("line")), "column": None,
                                "severity": "error" if match.group(1) == "Error" else "warning",
                                "message": "CMake " + match.group(1).lower() + " (see output)"})
    errors = [d for d in diagnostics if d["severity"] == "error"]
    warnings = [d for d in diagnostics if d["severity"] == "warning"]
    return (errors + warnings)[:limit]


def parse_size_report(output: str) -> list[dict]:
    """Parse `arm-none-eabi-size` (Berkeley format) lines printed after linking."""
    lines = output.splitlines()
    report = []
    for i, line in enumerate(lines):
        if _SIZE_HEADER.match(line) and i + 1 < len(lines):
            parts = lines[i + 1].split()
            if len(parts) >= 6 and all(p.isdigit() for p in parts[:4]):
                text, data, bss, total = (int(p) for p in parts[:4])
                report.append({"file": Path(parts[5]).name, "text": text, "data": data, "bss": bss,
                               "flash_bytes": text + data, "ram_bytes": data + bss, "total": total})
    return report


_MEM_USAGE = re.compile(r"^\s*(?P<region>[A-Za-z0-9_.]+):\s+(?P<used>[\d.]+)\s*(?P<uu>B|KB|MB|GB)\s+"
                        r"(?P<size>[\d.]+)\s*(?P<su>B|KB|MB|GB)\s+(?P<pct>[\d.]+)%")
_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}


def parse_memory_usage(output: str) -> list[dict]:
    """Parse the linker's `--print-memory-usage` table (enabled by the SDK toolchain file)."""
    usage = []
    for line in output.splitlines():
        match = _MEM_USAGE.match(line)
        if match:
            usage.append({
                "region": match.group("region"),
                "used_bytes": int(float(match.group("used")) * _UNITS[match.group("uu")]),
                "region_bytes": int(float(match.group("size")) * _UNITS[match.group("su")]),
                "percent": float(match.group("pct")),
            })
    return usage


def artifacts(build_dir: Path) -> dict[str, list[str]]:
    """Firmware outputs in the build directory (ELF, maps, raw payloads and boot images)."""
    found: dict[str, list[str]] = {"elf": [], "map": [], "payload_bin": [], "boot_image": []}
    if not build_dir.is_dir():
        return found
    for path in sorted(build_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix == ".map":
            found["map"].append(str(path))
        elif path.suffix == ".bin":
            found["boot_image" if "_image" in path.stem else "payload_bin"].append(str(path))
        elif path.suffix in ("", ".elf"):
            try:
                with path.open("rb") as f:
                    if f.read(4) == _ELF_MAGIC:
                        found["elf"].append(str(path))
            except OSError:
                continue
    return found


def flash_command(lay: BuildLayout, target: str, timeout_s: float = 60) -> list[str]:
    """Return the exact flash-tool command CMake generated for `target`.

    `ninja -t commands <target>` lists the commands the target would run; the last one
    is the `gt32u2086_flash.py --image ... --profile ...` call, so the image CMake
    selected (signed or unsigned, normal or XIP) is reused rather than guessed.
    """
    cache = read_cache(lay.build_dir)
    generator = cache.get("CMAKE_GENERATOR", "")
    if "Ninja" not in generator:
        raise InvalidArgumentError(f"Build directory uses generator '{generator}', expected Ninja.")
    ninja = cache.get("CMAKE_MAKE_PROGRAM") or "ninja"
    result = run([ninja, "-C", str(lay.build_dir), "-t", "commands", target], lay.app_dir, timeout_s=timeout_s)
    if not result.ok:
        raise NotFoundError(f"Build target '{target}' is not available in {lay.build_dir}.",
                            result.output.strip()[-500:] or None)
    for line in reversed(result.output.strip().splitlines()):
        if "gt32u2086_flash.py" in line:
            # Ninja wraps custom commands as `cd <dir> && <cmd>`; keep the tool invocation.
            segment = line.split("&&")[-1].strip()
            return shlex.split(segment)
    raise NotFoundError(f"Target '{target}' does not invoke gt32u2086_flash.py.")
