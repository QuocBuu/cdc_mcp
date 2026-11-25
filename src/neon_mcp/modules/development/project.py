"""Project submodule: create an application from the SDK templates (guide/FirstApp.md, VS Code wizard)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...adapters.neon_mdf import NeonMdfSdk
from ...core.tools import WRITES_FILES, ToolRegistry
from ...system.errors import InvalidArgumentError, NotFoundError
from ...system.security import Permission

if TYPE_CHECKING:
    from ...core.app import NeonApp

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def create(sdk: NeonMdfSdk, name: str, parent: Path, template: str) -> dict:
    if not _NAME.match(name):
        raise InvalidArgumentError(
            f"Invalid application name '{name}'.",
            "Use a letter followed by letters, digits or underscores (it becomes the CMake project/ELF name).")
    source = sdk.template_dir(template)
    if not source.is_dir():
        raise NotFoundError(f"Template '{template}' not found at {source}.")
    destination = parent / name
    if destination.exists():
        raise InvalidArgumentError(f"'{destination}' already exists; choose another name or directory.")
    relative_sdk = Path(os.path.relpath(sdk.sdk_dir, destination)).as_posix()
    shutil.copytree(source, destination)
    created = []
    for path in sorted(destination.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text.replace("__APP_NAME__", name).replace("__NEON_MDF_RELATIVE_PATH__", relative_sdk)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
        created.append(path.relative_to(destination).as_posix())
    return {
        "app_dir": str(destination), "name": name, "template": template,
        "sdk_relative_path": relative_sdk, "files": created,
        "next_steps": [
            f"dev_build(app_dir='{destination}') to configure and build",
            "Edit Src/main.c; add sources to neon_mdf_add_executable() in CMakeLists.txt",
            "Known 10 MHz FPGA clock: dev_configure(..., cache_variables={'NEON_APP_FIXED_CLOCK_HZ': 10000000})",
        ],
    }


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("development", "project", WRITES_FILES)
    def dev_create_project(name: str, parent_dir: str, template: Literal["baremetal", "freertos"] = "baremetal",
                           set_as_current: bool = True) -> dict[str, Any]:
        """Create a new NEON-MDF application from the SDK template (bare-metal or FreeRTOS).

        parent_dir: existing directory inside the workspace; the app is created at <parent_dir>/<name>
        with CMakeLists.txt, CMakePresets.json, Kconfig, Src/main.c (and Inc/FreeRTOSConfig.h).
        The SDK path is written relative to the new project.
        """
        app.policy.require(Permission.WRITE, "dev_create_project")
        parent = app.workspace.resolve(parent_dir, kind="dir")
        result = create(app.sdk, name, parent, template)
        if set_as_current:
            app.session.app_dir = result["app_dir"]
        return result
