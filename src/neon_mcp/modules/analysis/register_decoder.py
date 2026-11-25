"""Register Decoder submodule: raw register value → named bit fields (device YAML)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...adapters.device import parse_int
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("analysis", "register_decoder", READ_ONLY)
    def analysis_decode_register(value: int | str, peripheral: str | None = None, register: str | None = None,
                                 address: int | str | None = None, target: str | None = None) -> dict[str, Any]:
        """Decode a raw register value into its bit fields using the device YAML.

        Identify the register by peripheral + register name/alias (e.g. UART0 + LSR) or by its
        absolute address (e.g. 0x440D0014). value accepts decimal or 0x hex. For registers with
        aliases (one address, several views) every view is decoded unless a specific alias is named.
        """
        device = app.target(target).device()
        raw = parse_int(value, "value")
        if raw < 0 or raw > 0xFFFFFFFF:
            raise InvalidArgumentError("value must fit in 32 bits.")
        if address is not None:
            reg = device.register_at(parse_int(address, "address"))
            views = reg.views()
        elif peripheral and register:
            reg, view = device.peripheral(peripheral).register(register)
            views = (view,) if view is not reg.main or not reg.aliases else reg.views()
        else:
            raise InvalidArgumentError("Pass peripheral and register, or address.")
        return {
            "peripheral": reg.peripheral, "register": reg.name, "address": f"0x{reg.address:08X}",
            "value": f"0x{raw:08X}",
            "views": [{"name": v.name, "access": v.access, "description": v.description,
                       "reset": f"0x{v.reset:08X}" if v.reset is not None else None,
                       "differs_from_reset": v.reset is not None and v.reset != raw,
                       "fields": v.decode(raw)} for v in views],
        }
