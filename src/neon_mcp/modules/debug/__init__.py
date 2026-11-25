"""05 Debug Module: hardware and source-level debugging through GDB (OpenOCD or any GDB server)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import breakpoint, cpu, memory, peripheral, register_access, session, source_debug

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=5, id="debug", title="Debug Module",
    description="GDB/MI session (OpenOCD or existing GDB server), CPU control, registers, memory, "
                "peripherals, breakpoints and source-level backtraces.",
    submodules=[
        Submodule("session", "Debug Session", "Connect/disconnect, OpenOCD lifecycle, target state.",
                  source="modules/debug/session.py"),
        Submodule("cpu", "CPU Control", "Halt, continue, step, next, finish, reset.", source="modules/debug/cpu.py"),
        Submodule("register", "Register Access", "Core registers with xPSR decoding.",
                  source="modules/debug/register_access.py"),
        Submodule("memory", "Memory Access", "Aligned word read/write with memory-map labels.",
                  source="modules/debug/memory.py"),
        Submodule("peripheral", "Peripheral Debug", "Live peripheral registers decoded with the device YAML.",
                  source="modules/debug/peripheral.py"),
        Submodule("breakpoint", "Breakpoint Manager", "Hardware breakpoints and watchpoints.",
                  source="modules/debug/breakpoint.py"),
        Submodule("source_debug", "Source Debug", "Backtrace, source lines and local variables.",
                  source="modules/debug/source_debug.py"),
        Submodule("multicore", "Multicore Debug", "Per-core selection and state (GT32U2086 is single-core).",
                  status="planned"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (session, cpu, register_access, memory, peripheral, breakpoint, source_debug):
        submodule.register(registry, app)
