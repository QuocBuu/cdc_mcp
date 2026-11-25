"""Boot submodule: BootROM boot modes and the procedure the user follows on the board."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("programming", "boot", READ_ONLY)
    def prog_list_boot_modes(target: str | None = None) -> dict[str, Any]:
        """Boot modes (logical SYSCSR_STATUS[2:0] values), which image profile each needs, and the
        UART programming procedure the user must follow on the board."""
        tgt = app.target(target)
        return {"target": tgt.name, "boot_modes": tgt.profile.get("boot_modes", []),
                "flash_procedure": tgt.profile.get("flash_procedure", []),
                "note": "Codes are logical SoC values, not switch positions; see the board schematic."}
