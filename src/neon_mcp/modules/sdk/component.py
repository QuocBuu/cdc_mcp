"""Component Manager submodule: drivers, console and RTOS with their build switches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...adapters.kconfig import KconfigProject
from ...adapters.neon_mdf import NeonMdfSdk
from ...core.tools import READ_ONLY, ToolRegistry
from .api import ApiIndex, get_api

if TYPE_CHECKING:
    from ...core.app import NeonApp


def components(sdk: NeonMdfSdk, api: ApiIndex, profile: dict) -> list[dict]:
    project = KconfigProject(sdk.sdk_dir, None)
    symbols = {info["name"]: info for info in project.describe()}
    always = set(profile.get("always_built_drivers", []))
    needs_crm = set(profile.get("requires_crm_clock", []))
    functions: dict[str, int] = {}
    for entry in api.entries():
        if entry.kind in ("function", "inline_function"):
            functions[entry.module] = functions.get(entry.module, 0) + 1
    result = []
    for header in sorted(sdk.driver_dir.glob("*/neon_*.h")):
        module = header.parent.name
        if header.stem != f"neon_{module}":
            continue
        symbol = symbols.get(f"CONFIG_NEON_MDF_DRIVER_{module.upper()}")
        entry = {
            "name": module, "kind": "driver",
            "header": sdk.relative(header),
            "include": f'#include "{module}/{header.name}"',
            "backends": sorted(sdk.relative(p) for p in header.parent.glob("platform/*/*.c")),
            "public_functions": functions.get(module, 0),
            "kconfig": symbol["name"] if symbol else None,
            "enabled_by_default": (symbol["default"] == "y") if symbol else module in always,
            "always_built": module in always,
            "selectable": bool(symbol and symbol["visible"]),
            "requires_crm_clock": module in needs_crm,
            "description": symbol["help"] if symbol else None,
        }
        if module == "efuse":
            entry["note"] = "Legacy OTP driver; disabled because OTP is not in the current memory map (use Flash NVR APIs)."
        result.append(entry)
    result.append({
        "name": "console", "kind": "middleware", "header": sdk.relative(sdk.console_dir / "neon_console.h"),
        "include": '#include "console/neon_console.h"  (printf needs only <stdio.h>)',
        "backends": sorted(sdk.relative(p) for p in sdk.console_dir.glob("platform/*/*.c")),
        "public_functions": functions.get("console", 0),
        "kconfig": "CONFIG_NEON_MDF_DRIVER_UART", "enabled_by_default": True, "always_built": False,
        "selectable": False, "requires_crm_clock": False,
        "description": "printf/vprintf/puts/putchar and _write over UART0 (19200 8N1 by default). "
                       "Built whenever the UART driver is enabled. Integers and strings only, no float.",
    })
    result.append({
        "name": "freertos", "kind": "rtos", "header": "neon-mdf/rtos/FreeRTOS-Kernel/include/FreeRTOS.h",
        "include": '#include "FreeRTOS.h"', "backends": ["neon-mdf/rtos/FreeRTOS-Kernel/portable/GCC/ARM_CM0/port.c"],
        "public_functions": None, "kconfig": None, "enabled_by_default": False, "always_built": False,
        "selectable": False, "requires_crm_clock": False,
        "description": "FreeRTOS kernel with GCC ARM_CM0 port and heap_4, added per application with "
                       "include(${NEON_MDF_PATH}/cmake/freertos.cmake) + neon_mdf_add_freertos(...) and linking "
                       "freertos_kernel. The app owns Inc/FreeRTOSConfig.h.",
    })
    return result


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("sdk", "component", READ_ONLY)
    def sdk_list_components(target: str | None = None) -> dict[str, Any]:
        """List drivers and middleware: header/include, backends, Kconfig switch, defaults and dependencies.

        Optional drivers are compiled only when their CONFIG_NEON_MDF_DRIVER_* option is y; calling
        a disabled driver is a link error. GPIO/Flash/CRM/SYSCSR are always built. The console
        (printf) comes with the UART driver. FreeRTOS is added per application in CMake.
        """
        tgt = app.target(target)
        return {"target": tgt.name, "components": components(app.sdk, get_api(app), tgt.profile)}
