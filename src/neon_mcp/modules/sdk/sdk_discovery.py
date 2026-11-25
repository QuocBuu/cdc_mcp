"""SDK Discovery submodule: identify the NEON-MDF checkout, version and tooling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ... import __version__
from ...core.tools import READ_ONLY, ToolRegistry
from .api import get_api

if TYPE_CHECKING:
    from ...core.app import NeonApp

_TOOLS = ("neon_mdf.py", "gt32u2086_flash.py", "gt32u2086_image.py", "gt32u2086_secure_image.py",
          "gt32u2086_uart.py")


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("sdk", "sdk_discovery", READ_ONLY)
    def sdk_get_info() -> dict[str, Any]:
        """Identify the NEON-MDF SDK in use: version, location, git revision, presets, devices and tools."""
        sdk = app.sdk
        return {
            "neon_mcp_version": __version__,
            "sdk_version": sdk.version,
            "sdk_root": str(sdk.root),
            "neon_mdf_path": str(sdk.sdk_dir),
            "git": sdk.git_info(),
            "presets": sdk.presets,
            "targets": [t.summary() for t in app.targets.all()],
            "device_descriptions": [sdk.relative(p) for p in sdk.device_files()],
            "vscode_extension_version": sdk.extension_version(),
            "tools": {name: sdk.relative(sdk.tool(name)) for name in _TOOLS if sdk.tool(name).exists()},
            "templates": {kind: sdk.relative(sdk.template_dir(kind)) for kind in ("baremetal", "freertos")},
            "api_modules": get_api(app).modules(),
            "docs": {"guide_index": "guide/README.md", "examples_index": "examples/README.md"},
        }
