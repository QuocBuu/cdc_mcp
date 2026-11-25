"""Device knowledge submodule: CPU, memory map, profiles, IRQs, boot modes and firmware rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("knowledge", "device_knowledge", READ_ONLY)
    def knowledge_get_device(target: str | None = None) -> dict[str, Any]:
        """Device facts for a target from its SDK YAML description plus NEON MCP's profile.

        Includes CPU, physical memory map, normal/XIP memory profiles (image header, vector
        base, application RAM), peripheral instances with base addresses, the full IRQ
        table, boot modes, board defaults, debug limits and the firmware rules an agent must follow.
        """
        tgt = app.target(target)
        data: dict[str, Any] = tgt.device().summary()
        profile = tgt.profile
        data.update({
            "capabilities": tgt.capabilities,
            "board": profile.get("board"),
            "boot_modes": profile.get("boot_modes"),
            "debug": profile.get("debug"),
            "requires_crm_clock": profile.get("requires_crm_clock"),
            "always_built_drivers": profile.get("always_built_drivers"),
            "rules": profile.get("rules"),
        })
        return data
