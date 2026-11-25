"""Register knowledge submodule: peripheral registers, fields, aliases and IRQs from the device YAML."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry

if TYPE_CHECKING:
    from ...core.app import NeonApp


def irq_serves(irq_name: str, peripheral: str) -> bool:
    """Match YAML IRQ names to peripheral instances: USART0→UART0, TIM2_3→TIM2/TIM3,
    ADC0→ADC, QSPI→QSPI_APB."""
    irq = irq_name.upper().replace("USART", "UART")
    periph = peripheral.upper()
    names = {irq}
    shared = re.fullmatch(r"([A-Z]+)(\d+)_(\d+)", irq)
    if shared:
        names = {shared.group(1) + shared.group(2), shared.group(1) + shared.group(3)}
    single = re.fullmatch(r"([A-Z]+)0", irq)
    if single:
        names.add(single.group(1))
    return periph in names or any(periph.startswith(n + "_") for n in names)


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("knowledge", "register_knowledge", READ_ONLY)
    def knowledge_get_peripheral(peripheral: str, register: str | None = None,
                                 target: str | None = None) -> dict[str, Any]:
        """Registers of a peripheral instance (e.g. UART0, SPI1, GPIOB, CRM) from the device YAML.

        Without `register`: every register with offset, absolute address, access, reset and
        fields. With `register` (name or alias, e.g. "LSR", "IER"): that register only.
        Aliases are alternate views of one address (e.g. UART RBR/THR/DLL).
        """
        device = app.target(target).device()
        periph = device.peripheral(peripheral)
        irqs = [i for i in device.interrupts if irq_serves(i["name"], periph.name)]
        result: dict[str, Any] = {
            "peripheral": periph.name, "type": periph.type, "base": f"0x{periph.base:08X}",
            "description": periph.description,
            "interrupts": [{"number": i["number"], "name": i["name"]} for i in irqs],
            "source": str(device.path),
        }
        if register:
            reg, view = periph.register(register)
            result["register"] = reg.to_dict()
            if view is not reg.main:
                result["matched_alias"] = view.name
        else:
            result["registers"] = [r.to_dict() for r in periph.registers]
        return result
