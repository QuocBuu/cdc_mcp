"""02 Knowledge Module: technical knowledge about the MCU and SDK for the AI agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import device_knowledge, documentation, register_knowledge, search

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=2, id="knowledge", title="Knowledge Module",
    description="SDK documentation, device data and register knowledge, read from the NEON-MDF checkout.",
    submodules=[
        Submodule("documentation", "Documentation", "Index, list and read README, guide/ and example READMEs.",
                  source="modules/knowledge/documentation.py"),
        Submodule("search", "Search", "Ranked keyword search over documentation sections.",
                  source="modules/knowledge/search.py"),
        Submodule("device_knowledge", "Device Knowledge",
                  "CPU, memory map, profiles, IRQs, boot modes, debug limits, firmware rules.",
                  source="modules/knowledge/device_knowledge.py"),
        Submodule("register_knowledge", "Register Knowledge", "Peripheral registers, fields, aliases and IRQs.",
                  source="modules/knowledge/register_knowledge.py"),
        Submodule("external_documents", "Datasheet / TRM / Errata",
                  "Index vendor PDFs (datasheet, technical reference manual, errata) for search.",
                  status="planned"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (documentation, search, device_knowledge, register_knowledge):
        submodule.register(registry, app)
