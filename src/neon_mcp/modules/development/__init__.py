"""04 Development Module: the NEON-MDF firmware development workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import build, code_generation, configuration, project, toolchain

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=4, id="development", title="Development Module",
    description="Toolchain check, project creation, Kconfig configuration, device code generation and builds.",
    submodules=[
        Submodule("toolchain", "Toolchain", "Check arm-none-eabi-gcc/newlib, CMake >= 3.25, Ninja, Python deps.",
                  source="modules/development/toolchain.py"),
        Submodule("project", "Project", "Create bare-metal or FreeRTOS apps from SDK templates.",
                  source="modules/development/project.py"),
        Submodule("configuration", "Configuration", "Read and change sdkconfig (menuconfig rules).",
                  source="modules/development/configuration.py"),
        Submodule("code_generation", "Code Generation", "Preview device files generated from the YAML.",
                  source="modules/development/code_generation.py"),
        Submodule("build", "Build", "CMake configure/build with diagnostics, memory usage and artifacts.",
                  source="modules/development/build.py"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (toolchain, project, configuration, code_generation, build):
        submodule.register(registry, app)
