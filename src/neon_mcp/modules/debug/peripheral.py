"""Peripheral Debug submodule: read live peripheral registers and decode them with the device YAML."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READS_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission
from .session import get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "peripheral", READS_HARDWARE)
    def debug_read_peripheral(peripheral: str, registers: list[str] | None = None,
                              all_registers: bool = False, target: str | None = None) -> dict[str, Any]:
        """Read live register values of a peripheral (e.g. UART0, GPIOB, SPI1) and decode their fields.

        Reading some registers changes hardware state (UART RBR pops the RX FIFO, IIR acknowledges
        interrupts, some status bits clear on read), so name the registers to read; all_registers=True
        reads every readable register and accepts those side effects. Write-only registers are skipped.
        """
        app.policy.require(Permission.HARDWARE, "debug_read_peripheral")
        if not registers and not all_registers:
            raise InvalidArgumentError(
                "Name the registers to read, or pass all_registers=True to accept read side effects.",
                "See knowledge_get_peripheral for register names.")
        periph = app.target(target).device().peripheral(peripheral)
        chosen = [periph.register(name) for name in registers] if registers else \
            [(r, r.main) for r in periph.registers]
        results, skipped = [], []
        with manager.lock:
            for reg, view in chosen:
                if view.access == "wo" and not reg.aliases:
                    skipped.append(reg.name)
                    continue
                value = manager.read_words(reg.address, 1)[0]
                views = (view,) if view is not reg.main or not reg.aliases else reg.views()
                results.append({
                    "register": reg.name, "address": f"0x{reg.address:08X}", "value": f"0x{value:08X}",
                    "views": [{"name": v.name, "fields": v.decode(value)} for v in views if v.access != "wo"],
                })
        return {"peripheral": periph.name, "base": f"0x{periph.base:08X}", "registers": results,
                "skipped_write_only": skipped}
