"""Register Access submodule: CPU core registers with xPSR decoding."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READS_HARDWARE, ToolRegistry
from ...system.security import Permission
from ...targets.arch import cortex_m
from .session import get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "register", READS_HARDWARE)
    def debug_read_registers(names: list[str] | None = None, all_registers: bool = False) -> dict[str, Any]:
        """Read CPU registers of the halted target. Default: r0-r12, sp, lr, pc, xpsr and, when the
        GDB server exposes them, msp, psp, primask, control. xPSR is decoded (current exception,
        Thumb bit, flags). names selects specific registers; all_registers returns everything GDB knows."""
        app.policy.require(Permission.HARDWARE, "debug_read_registers")
        with manager.lock:
            wanted = None if all_registers else (names or list(cortex_m.CORE_REGISTERS))
            values = manager.registers(wanted)
        result: dict[str, Any] = {"registers": {k: f"0x{v:08X}" for k, v in values.items()}}
        if "xpsr" in values:
            result["xpsr_decoded"] = cortex_m.decode_xpsr(values["xpsr"], app.target().device().interrupts)
        return result
