"""Permission policy for operations requested by the AI agent.

Levels:
- READ: inspect SDK, docs, device data, project files and build outputs. Always allowed.
- WRITE: create projects, edit sdkconfig, configure and build. Disabled by --read-only.
- HARDWARE: open serial ports and program a connected board. Disabled unless
  --allow-hardware / NEON_MCP_ALLOW_HARDWARE=1.
"""

from __future__ import annotations

import enum

from .config import ENV_ALLOW_HARDWARE, ENV_READ_ONLY, Settings
from .errors import PermissionDeniedError
from .logging import audit


class Permission(enum.Enum):
    READ = "read"
    WRITE = "write"
    HARDWARE = "hardware"


class SecurityPolicy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def allowed(self, permission: Permission) -> bool:
        if permission is Permission.READ:
            return True
        if permission is Permission.WRITE:
            return not self._settings.read_only
        return self._settings.allow_hardware

    def require(self, permission: Permission, action: str) -> None:
        allowed = self.allowed(permission)
        if permission is not Permission.READ:
            audit("permission", action=action, level=permission.value, allowed=allowed)
        if allowed:
            return
        if permission is Permission.WRITE:
            raise PermissionDeniedError(
                f"'{action}' writes files, but the server runs in read-only mode.",
                f"Restart the server without --read-only / {ENV_READ_ONLY}.",
            )
        raise PermissionDeniedError(
            f"'{action}' accesses connected hardware, which is disabled.",
            f"Ask the user to restart the server with --allow-hardware or {ENV_ALLOW_HARDWARE}=1.",
        )

    def describe(self) -> dict[str, bool]:
        return {p.value: self.allowed(p) for p in Permission}
