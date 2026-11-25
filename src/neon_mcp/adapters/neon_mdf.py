"""Locate a NEON-MDF checkout and expose its well-known paths.

NEON MCP never copies SDK content: documentation, device YAML, headers, templates
and tools are always read from the checkout found here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from ..system.errors import SdkNotFoundError

_MARKER = Path("neon-mdf") / "tools" / "neon_mdf.py"


def _repo_root_of(candidate: Path) -> Path | None:
    """Accept either the repository root or its `neon-mdf/` directory."""
    candidate = candidate.expanduser().resolve()
    if (candidate / _MARKER).is_file():
        return candidate
    if candidate.name == "neon-mdf" and (candidate.parent / _MARKER).is_file():
        return candidate.parent
    return None


def discover_sdk(explicit: Path | None, search_from: list[Path]) -> Path:
    """Find the SDK repository root.

    Order: explicit setting → NEON_MDF_PATH (the SDK's own variable, points at
    `neon-mdf/`) → each search directory, its parents, and a `neon_mdf/` child of each.
    """
    if explicit is not None:
        root = _repo_root_of(explicit)
        if root is None:
            raise SdkNotFoundError(f"'{explicit}' is not a NEON-MDF checkout (missing {_MARKER}).")
        return root
    env = os.environ.get("NEON_MDF_PATH")
    if env:
        root = _repo_root_of(Path(env))
        if root is not None:
            return root
    package_repo = Path(__file__).resolve().parents[3]
    for start in [*search_from, package_repo]:
        start = start.resolve()
        for directory in (start, *start.parents):
            for candidate in (directory, directory / "neon_mdf"):
                root = _repo_root_of(candidate)
                if root is not None:
                    return root
    raise SdkNotFoundError(
        "Cannot find the NEON-MDF SDK.",
        "Pass --sdk /path/to/neon_mdf or set NEON_MCP_SDK_PATH "
        "(clone https://github.com/ftel-cdc/neon_mdf.git).",
    )


@dataclass(frozen=True)
class NeonMdfSdk:
    root: Path

    # --- Well-known locations -------------------------------------------------------------------
    @property
    def sdk_dir(self) -> Path:
        """The `neon-mdf/` directory, i.e. the value of NEON_MDF_PATH."""
        return self.root / "neon-mdf"

    @property
    def guide_dir(self) -> Path:
        return self.root / "guide"

    @property
    def examples_dir(self) -> Path:
        return self.root / "examples"

    @property
    def driver_dir(self) -> Path:
        return self.sdk_dir / "components" / "driver"

    @property
    def console_dir(self) -> Path:
        return self.sdk_dir / "components" / "console"

    @property
    def devices_dir(self) -> Path:
        return self.sdk_dir / "mcu-description" / "devices"

    @property
    def tools_dir(self) -> Path:
        return self.sdk_dir / "tools"

    @property
    def kconfig_root(self) -> Path:
        return self.sdk_dir / "Kconfig"

    def template_dir(self, kind: str) -> Path:
        return self.tools_dir / ("templates_freertos" if kind == "freertos" else "templates")

    def tool(self, name: str) -> Path:
        return self.tools_dir / name

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    # --- Metadata ---------------------------------------------------------------------------------
    @property
    def version(self) -> str | None:
        """SDK release from `neon-mdf/VERSION` (added in v1.0.0; None for older checkouts)."""
        try:
            text = (self.sdk_dir / "VERSION").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return text or None

    @cached_property
    def presets(self) -> list[str]:
        path = self.sdk_dir / "cmake" / "presets" / "targets.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [p["name"] for p in data.get("configurePresets", []) if "name" in p]

    def device_files(self) -> list[Path]:
        return sorted(self.devices_dir.glob("*.yaml"))

    def extension_version(self) -> str | None:
        try:
            data = json.loads((self.root / "vscode-extension" / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get("version")

    def git_info(self) -> dict:
        def git(*args: str) -> str | None:
            try:
                out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                     text=True, timeout=10, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                return None
            return out.stdout.strip() if out.returncode == 0 else None

        status = git("status", "--porcelain")
        return {
            "commit": git("rev-parse", "--short", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "describe": git("describe", "--tags", "--always", "--dirty"),
            "last_commit": git("log", "-1", "--format=%cs %s"),
            "dirty": bool(status) if status is not None else None,
        }

    # --- Python interpreter for CMake and SDK tools ----------------------------------------------
    def python_for(self, app_dir: Path | None, explicit: Path | None) -> str:
        """Same lookup as the VS Code extension: explicit → app/.venv → SDK/.venv → this Python."""
        if explicit is not None:
            return str(explicit)
        bin_name = Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
        for base in [p for p in (app_dir, self.root) if p is not None]:
            candidate = base / ".venv" / bin_name
            if candidate.exists():
                return str(candidate)
        return sys.executable
