"""Configuration submodule: read and change Kconfig/sdkconfig options like menuconfig."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...adapters.kconfig import KconfigProject
from ...core.tools import READ_ONLY, WRITES_FILES, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission

if TYPE_CHECKING:
    from ...core.app import NeonApp

ConfigValue = bool | int | str


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("development", "configuration", READ_ONLY)
    def dev_get_config(app_dir: str | None = None, filter: str | None = None,
                       changed_only: bool = False) -> dict[str, Any]:
        """Read an application's Kconfig options and current sdkconfig values (like menuconfig).

        Lists SDK options (CONFIG_NEON_MDF_DRIVER_* driver switches) and the app's own Kconfig
        options with type, value, default, prompt, help, range and where they are defined.
        filter: substring of name/prompt/help, e.g. "UART", "clock". changed_only: values that
        differ from their default.
        """
        directory = app.app_dir(app_dir)
        proj = KconfigProject(app.sdk.sdk_dir, directory)
        options = proj.describe(filter)
        if changed_only:
            options = [o for o in options if o["default"] is not None and o["value"] != o["default"]]
        return {"app_dir": str(directory), "sdkconfig": str(proj.sdkconfig),
                "sdkconfig_exists": bool(proj.sdkconfig and proj.sdkconfig.exists()),
                "options": options, "warnings": proj.warnings}

    @registry.tool("development", "configuration", WRITES_FILES)
    def dev_set_config(values: dict[str, ConfigValue], app_dir: str | None = None) -> dict[str, Any]:
        """Change sdkconfig options non-interactively (same rules as menuconfig, via kconfiglib).

        values: {"CONFIG_NEON_MDF_DRIVER_SPI": true, "CONFIG_GT32U2086_EXAMPLE_FIXED_CLOCK_HZ": 10000000}.
        Every value is validated (existence, type, range, dependencies) before sdkconfig is written.
        The next dev_build applies the change automatically. Disabling a driver makes calls to it
        link errors.
        """
        app.policy.require(Permission.WRITE, "dev_set_config")
        if not values:
            raise InvalidArgumentError("values must contain at least one option.")
        directory = app.app_dir(app_dir)
        proj = KconfigProject(app.sdk.sdk_dir, directory)
        changes = proj.set_values(values)
        return {"app_dir": str(directory), "sdkconfig": str(proj.sdkconfig), "changes": changes,
                "note": "Rebuild (dev_build) to apply; CMake tracks sdkconfig and reconfigures automatically."}
