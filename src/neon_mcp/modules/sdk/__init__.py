"""03 SDK Module: help the AI understand and use NEON-MDF."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import api, component, dependency, example, sdk_discovery, source

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=3, id="sdk", title="SDK Module",
    description="Discovery, components, public C API, source code, examples and dependencies of NEON-MDF.",
    submodules=[
        Submodule("sdk_discovery", "SDK Discovery", "SDK version, path, git revision, presets, tools.",
                  source="modules/sdk/sdk_discovery.py"),
        Submodule("component", "Component Manager", "Drivers, console and FreeRTOS with Kconfig switches.",
                  source="modules/sdk/component.py"),
        Submodule("api", "API Search", "Functions, types and macros with Doxygen, parsed from headers.",
                  source="modules/sdk/api.py"),
        Submodule("source", "Source Explorer", "grep-like search and line-numbered reading.",
                  source="modules/sdk/source.py"),
        Submodule("example", "Example Manager", "Example applications by keyword or driver used.",
                  source="modules/sdk/example.py"),
        Submodule("dependency", "Dependency Resolver",
                  "Kconfig switches, includes, CRM clocks and CMake needed for a set of components.",
                  source="modules/sdk/dependency.py"),
        Submodule("knowledge_pack", "Knowledge Pack",
                  "Device, API and docs data pre-generated per NEON-MDF release; used when the checkout matches.",
                  source="modules/sdk/knowledge_pack.py"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (sdk_discovery, component, api, source, example, dependency):
        submodule.register(registry, app)
