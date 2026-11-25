"""Target registry.

A target is known when the SDK ships its device description
(`mcu-description/devices/<NAME>.yaml`). A NEON MCP profile
(`targets/<name>/target.yaml`, or one in NEON_MCP_TARGETS_DIR) adds the build preset,
capabilities, board defaults and rules. Devices without a profile are still listed so
their documentation and registers can be queried, but build/flash tools refuse them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..adapters.device import DeviceDescription, load_device
from ..adapters.neon_mdf import NeonMdfSdk
from ..core.tools import READ_ONLY, ToolRegistry
from ..system.errors import CapabilityError, NotFoundError
from .capabilities import UNAVAILABLE_NOTES, describe

if TYPE_CHECKING:
    from ..core.app import NeonApp

_PROFILE_DIR = Path(__file__).parent


@dataclass
class Target:
    name: str
    device_file: Path | None
    profile: dict[str, Any] = field(default_factory=dict)

    @property
    def has_profile(self) -> bool:
        return bool(self.profile)

    @property
    def preset(self) -> str:
        return self.profile.get("preset", self.name)

    @property
    def capabilities(self) -> dict[str, bool]:
        return dict(self.profile.get("capabilities", {}))

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability, False))

    def require(self, capability: str, action: str) -> None:
        if not self.has_profile:
            raise CapabilityError(
                f"Target {self.name} has a device description but no NEON MCP profile, so '{action}' is unavailable.",
                f"Add targets/profiles/{self.name.lower()}.yaml (see gt32u2086.yaml).")
        if not self.supports(capability):
            raise CapabilityError(f"Target {self.name} does not support '{capability}' (needed for {action}).",
                                  UNAVAILABLE_NOTES.get(capability))

    def device(self) -> DeviceDescription:
        if self.device_file is None:
            raise NotFoundError(f"Target {self.name} has no device description in the SDK.")
        return load_device(self.device_file)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "core": self.profile.get("core"),
            "architecture": self.profile.get("architecture"),
            "preset": self.preset if self.has_profile else None,
            "profiles": self.profile.get("profiles", []),
            "capabilities": self.capabilities,
            "capability_details": describe(self.capabilities),
            "has_mcp_profile": self.has_profile,
            "device_description": str(self.device_file) if self.device_file else None,
        }


class TargetRegistry:
    def __init__(self, sdk: NeonMdfSdk, extra_profile_dir: Path | None = None) -> None:
        profiles: dict[str, dict] = {}
        for directory in [_PROFILE_DIR, extra_profile_dir]:
            if directory is None or not directory.is_dir():
                continue
            for path in sorted([*directory.glob("*/target.yaml"), *directory.glob("*.yaml")]):
                with path.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if "name" in data:
                    profiles[data["name"].upper()] = data
        devices = {p.stem.upper(): p for p in sdk.device_files()}
        self._targets: dict[str, Target] = {}
        for key in sorted(set(devices) | set(profiles)):
            profile = profiles.get(key, {})
            device_name = str(profile.get("device", key)).upper()
            self._targets[key] = Target(profile.get("name", devices.get(key, Path(key)).stem),
                                        devices.get(device_name), profile)

    def names(self) -> list[str]:
        return [t.name for t in self._targets.values()]

    def all(self) -> list[Target]:
        return list(self._targets.values())

    def get(self, name: str | None) -> Target:
        if name is None:
            usable = [t for t in self._targets.values() if t.has_profile and t.device_file]
            if len(usable) == 1:
                return usable[0]
            raise NotFoundError("No target selected.",
                                "Pass target=<name> or call session_set_context. Known: " + ", ".join(self.names()))
        target = self._targets.get(name.strip().upper())
        if target is None:
            raise NotFoundError(f"Unknown target '{name}'.", "Known targets: " + ", ".join(self.names()))
        return target


def register(registry: ToolRegistry, app: NeonApp) -> None:
    @registry.tool("target", "registry", READ_ONLY)
    def target_list() -> dict[str, Any]:
        """Targets known from the SDK device descriptions and NEON MCP profiles, with capabilities
        (build, uart_flash, secure_boot, jtag_debug, exception_decode, ...) and why any are missing."""
        return {"targets": [t.summary() for t in app.targets.all()]}
