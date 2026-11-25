"""Example Manager submodule: catalog of SDK example applications."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters.neon_mdf import NeonMdfSdk
from ...core.tools import READ_ONLY, ToolRegistry
from .api import get_api

if TYPE_CHECKING:
    from ...core.app import NeonApp

_CALL = re.compile(r"\bneon_([a-z0-9]+)_[a-z0-9_]+\s*\(")
_PROJECT = re.compile(r"project\(\s*([A-Za-z0-9_\-]+)")


def _readme_summary(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None
    title, paragraph = None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
            continue
        if title is not None:
            if not stripped:
                if paragraph:
                    break
                continue
            if stripped.startswith(("#", "|", "```", "-", "![")):
                if paragraph:
                    break
                continue
            paragraph.append(stripped)
    return title, " ".join(paragraph) or None


def examples(sdk: NeonMdfSdk, known_modules: set[str]) -> list[dict]:
    result = []
    for cmake in sorted(sdk.examples_dir.glob("*/CMakeLists.txt")):
        app_dir = cmake.parent
        text = cmake.read_text(encoding="utf-8", errors="replace")
        project = _PROJECT.search(text)
        code = "\n".join(src.read_text(encoding="utf-8", errors="replace") for src in app_dir.glob("Src/*.c"))
        used = {m for m in _CALL.findall(code) if m in known_modules}
        if "printf" in code:
            used.add("console")
        options = []
        kconfig = app_dir / "Kconfig"
        if kconfig.is_file():
            options = [f"CONFIG_{m}" for m in re.findall(r"^\s*config\s+(\w+)", kconfig.read_text(encoding="utf-8"), re.MULTILINE)]
        title, summary = _readme_summary(app_dir / "README.md")
        result.append({
            "name": app_dir.name, "path": sdk.relative(app_dir),
            "firmware_target": project.group(1) if project else None,
            "title": title, "summary": summary,
            "uses_modules": sorted(used),
            "freertos": "neon_mdf_add_freertos" in text,
            "interactive_terminal": "fpga:>>" in code,
            "app_kconfig_options": options,
            "sources": sorted(sdk.relative(p) for p in app_dir.glob("Src/*.c")),
            "readme": sdk.relative(app_dir / "README.md") if (app_dir / "README.md").is_file() else None,
        })
    return result


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("sdk", "example", READ_ONLY)
    def sdk_find_examples(query: str | None = None, module: str | None = None) -> dict[str, Any]:
        """Find SDK example applications, optionally by keyword or by driver module used.

        Each result lists the firmware target, README summary, driver modules called, whether it
        uses FreeRTOS or the interactive `fpga:>>` UART terminal (press `r` to run), and its
        application Kconfig options. module examples: gpio, uart, spi, i2c, qspi, dma, tim, pwm.
        """
        known = set(get_api(app).modules()) | {"console"}
        items = examples(app.sdk, known)
        if module:
            items = [e for e in items if module.lower() in e["uses_modules"]]
        if query:
            terms = [t for t in query.lower().split() if t]
            items = [e for e in items if all(t in " ".join(str(v) for v in e.values()).lower() for t in terms)]
        return {"count": len(items), "examples": items}
