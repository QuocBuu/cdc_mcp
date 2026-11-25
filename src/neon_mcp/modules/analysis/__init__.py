"""07 Analysis Module: collect and analyze firmware, CPU and peripheral data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import elf, exception, log_analyzer, register_decoder

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=7, id="analysis", title="Analysis Module",
    description="ELF memory/symbols, register decoding, Cortex-M0 exception decoding and UART log analysis.",
    submodules=[
        Submodule("elf", "ELF", "Sections, Flash/RAM usage per profile, largest symbols, address → file:line.",
                  source="modules/analysis/elf.py"),
        Submodule("exception", "Exception Decoder",
                  "HardFault frame, EXC_RETURN, faulting instruction and probable causes.",
                  source="modules/analysis/exception.py"),
        Submodule("register_decoder", "Register Decoder", "Raw value → named fields from the device YAML.",
                  source="modules/analysis/register_decoder.py"),
        Submodule("log_analyzer", "Log Analyzer", "Capture UART output and summarize logs.",
                  source="modules/analysis/log_analyzer.py"),
        Submodule("memory_analyzer", "Memory Analyzer",
                  "Linker map breakdown per object file/library and stack usage (-fstack-usage).",
                  status="planned"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (elf, exception, register_decoder, log_analyzer):
        submodule.register(registry, app)
