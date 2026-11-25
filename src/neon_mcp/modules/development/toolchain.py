"""Toolchain submodule: check the host build environment the way guide/Setup.md describes."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry
from ...system.process import run

if TYPE_CHECKING:
    from ...core.app import NeonApp

_PY_CHECK = (
    "import importlib.util, json, sys; "
    "print(json.dumps({'version': list(sys.version_info[:3]), 'modules': "
    "{m: importlib.util.find_spec(m) is not None for m in ('yaml', 'kconfiglib', 'serial', 'cryptography')}}))"
)


def _version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(g) for g in match.groups() if g is not None) if match else None


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def check(python: str, cwd: Path) -> dict:
    checks = []

    def add(name: str, ok: bool, detail: str, hint: str | None = None, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail,
                       "hint": None if ok else hint})

    gcc = shutil.which("arm-none-eabi-gcc")
    if gcc:
        version = run([gcc, "--version"], cwd, timeout_s=30)
        add("arm-none-eabi-gcc", version.ok, _first_line(version.output) or gcc)
        for spec in ("nano.specs", "nosys.specs"):
            res = run([gcc, f"-print-file-name={spec}"], cwd, timeout_s=30)
            path = res.output.strip()
            add(spec, res.ok and path != spec and Path(path).exists(), path or "not found",
                "Install an Arm GNU toolchain distribution that includes newlib.")
    else:
        add("arm-none-eabi-gcc", False, "not found on PATH",
            "Ubuntu/Debian: sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi; "
            "macOS: brew install --cask gcc-arm-embedded; Windows: Arm GNU Toolchain installer.")

    cmake = shutil.which("cmake")
    if cmake:
        res = run([cmake, "--version"], cwd, timeout_s=30)
        version = _version(res.output)
        add("cmake", bool(version and version >= (3, 25)), _first_line(res.output),
            "CMake 3.25 or later is required for the SDK presets.")
    else:
        add("cmake", False, "not found on PATH", "Install CMake 3.25 or later.")

    ninja = shutil.which("ninja")
    if ninja:
        res = run([ninja, "--version"], cwd, timeout_s=30)
        add("ninja", res.ok, res.output.strip())
    else:
        add("ninja", False, "not found on PATH", "Install Ninja (apt install ninja-build / brew install ninja).")

    res = run([python, "-c", _PY_CHECK], cwd, timeout_s=60)
    try:
        info = json.loads(res.output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        add("python", False, f"{python}: {res.output.strip()[:200]}", "Install Python 3.10+.")
    else:
        version = tuple(info["version"])
        add("python", version >= (3, 10), f"{python} ({'.'.join(map(str, version))})",
            "Python 3.10 or later is required.")
        modules = info["modules"]
        add("python: PyYAML", modules["yaml"], "device YAML code generation",
            "pip install -r neon-mdf/tools/requirements.txt in the interpreter CMake uses.")
        add("python: kconfiglib", modules["kconfiglib"], "Kconfig/sdkconfig processing",
            "pip install -r neon-mdf/tools/requirements.txt in the interpreter CMake uses.")
        add("python: pyserial", modules["serial"], "UART on Windows and port detection",
            "pip install pyserial", required=False)
        add("python: cryptography", modules["cryptography"], "only for -DNEON_MDF_SECURE_BOOT=ON signing",
            "pip install cryptography", required=False)

    ready = all(c["ok"] for c in checks if c["required"])
    return {"ready_to_build": ready, "python_for_cmake": python, "checks": checks}


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("development", "toolchain", READ_ONLY)
    def dev_check_environment(app_dir: str | None = None) -> dict[str, Any]:
        """Check the build host: arm-none-eabi-gcc with newlib specs, CMake >= 3.25, Ninja, and the
        Python interpreter CMake will use (PyYAML, kconfiglib; pyserial, cryptography optional).

        The interpreter is chosen like the VS Code extension: NEON_MCP_SDK_PYTHON, else the app's
        or SDK checkout's .venv, else NEON MCP's own Python.
        """
        directory = app.app_dir(app_dir) if (app_dir or app.session.app_dir) else None
        return check(app.python(directory), directory or app.sdk.root)
