"""Dependency Resolver submodule: what an application needs to use a set of SDK components."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...adapters.kconfig import KconfigProject
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import NotFoundError
from .api import get_api
from .component import components
from .example import examples

if TYPE_CHECKING:
    from ...core.app import NeonApp

_ALIASES = {"printf": "console", "log": "console", "rtos": "freertos", "rng": "trng", "otp": "efuse"}
_FREERTOS_CMAKE = [
    "include(${NEON_MDF_PATH}/cmake/freertos.cmake)",
    "neon_mdf_add_freertos(${NEON_MDF_TARGET} ${CMAKE_CURRENT_SOURCE_DIR}/Inc)",
    "target_link_libraries(<app> PRIVATE freertos_kernel)",
]


def _crm_constant(api_names: set[str], module: str) -> list[str]:
    """CRM peripheral IDs for a module, e.g. dma → NEON_CRM_PERIPHERAL_DMA0/1."""
    pattern = re.compile(rf"^NEON_CRM_PERIPHERAL_{module.upper()}\d*$")
    return sorted(n for n in api_names if pattern.match(n))


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("sdk", "dependency", READ_ONLY)
    def sdk_resolve_dependencies(modules: list[str], app_dir: str | None = None,
                                 target: str | None = None) -> dict[str, Any]:
        """Resolve what an application needs to use SDK components (e.g. ["spi", "dma", "printf"]).

        For each component: the Kconfig switch that must be y (and its current value in the app's
        sdkconfig when app_dir/session app is given), headers to include, CRM clock/reset calls
        required before register access, CMake lines (FreeRTOS) and examples that use it.
        `set_config` can be passed directly to dev_set_config.
        """
        tgt = app.target(target)
        api = get_api(app)
        comps = {c["name"]: c for c in components(app.sdk, api, tgt.profile)}
        enum_names = {e_member["name"] for e in api.entries() if e.kind == "enum" for e_member in e.members}
        directory = app.app_dir(app_dir) if (app_dir or app.session.app_dir) else None
        current: dict[str, str] = {}
        if directory is not None:
            current = {o["name"]: o["value"] for o in KconfigProject(app.sdk.sdk_dir, directory).describe()}
        catalog = examples(app.sdk, set(api.modules()) | {"console"})

        resolved, set_config, includes, cmake, steps = [], {}, [], [], []
        for requested in modules:
            name = _ALIASES.get(requested.strip().lower(), requested.strip().lower())
            comp = comps.get(name)
            if comp is None:
                raise NotFoundError(f"Unknown component '{requested}'.", "Components: " + ", ".join(sorted(comps)))
            entry: dict[str, Any] = {"component": name, "kind": comp["kind"], "include": comp["include"],
                                     "header": comp["header"]}
            symbol = comp["kconfig"]
            if name == "efuse":
                entry["blocked"] = comp.get("note")
            elif symbol:
                entry["kconfig"] = {"option": symbol, "required": "y",
                                    "current": current.get(symbol) if directory else None}
                if not directory or current.get(symbol) != "y":
                    set_config[symbol] = True
            if comp["requires_crm_clock"]:
                ids = _crm_constant(enum_names, name) or [f"NEON_CRM_PERIPHERAL_{name.upper()}"]
                entry["crm"] = {
                    "required": True, "peripheral_ids": ids,
                    "calls": [f"neon_crm_peripheral_clock_enable({i});" for i in ids]
                    + [f"neon_crm_peripheral_release_reset({i});" for i in ids],
                }
                steps.append(f"{name}: enable its CRM clock and release reset before touching registers "
                             "(see examples using it).")
                includes.append('#include "crm/neon_crm.h"')
            if name == "gpio":
                steps.append("gpio: call neon_gpio_clock_enable(<GPIOx>) before neon_gpio_init().")
            if name == "console":
                steps.append("console: printf works after enabling UART; integers/strings only, not from ISRs.")
            if name == "freertos":
                cmake.extend(_FREERTOS_CMAKE)
                steps.append("freertos: provide Inc/FreeRTOSConfig.h (start from neon-mdf/tools/templates_freertos) "
                             "with configCHECK_HANDLER_INSTALLATION=0, configUSE_PORT_OPTIMISED_TASK_SELECTION=0, "
                             "configENABLE_MPU=0, configCPU_CLOCK_HZ=SystemCoreClock.")
            else:
                includes.append(comp["include"].split("  ")[0])
            entry["examples"] = [e["name"] for e in catalog
                                 if (name in e["uses_modules"]) or (name == "freertos" and e["freertos"])]
            resolved.append(entry)

        return {
            "target": tgt.name, "app_dir": str(directory) if directory else None,
            "components": resolved,
            "set_config": set_config,
            "includes": sorted(dict.fromkeys(includes)),
            "cmake": cmake,
            "steps": steps,
            "note": "Apply set_config with dev_set_config, then dev_build." if set_config else
                    "All required Kconfig switches are already enabled.",
        }
