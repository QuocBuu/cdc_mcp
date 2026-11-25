"""Session Manager: defaults remembered between tool calls (one stdio connection = one session)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..system.errors import InvalidArgumentError
from ..system.security import Permission
from .tools import READ_ONLY, ToolRegistry

if TYPE_CHECKING:
    from .app import NeonApp


@dataclass
class Session:
    target: str | None = None
    app_dir: str | None = None
    serial_port: str | None = None
    flash_baud: int | None = None
    monitor_baud: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("core", "session_manager", READ_ONLY)
    def session_get_context() -> dict[str, Any]:
        """Current session defaults (target, application, serial port, baud rates), the SDK in use,
        allowed workspace roots, granted permissions (read/write/hardware) and debug state."""
        debug = app.services.get("debug")
        pack = app.services.get("pack")
        return {
            "session": app.session.to_dict(),
            "sdk_root": str(app.sdk.root),
            "sdk_version": app.sdk.version,
            "knowledge_pack": {"status": pack.status, "pack": pack.pack.name if pack.pack else None} if pack else None,
            "workspace_roots": [str(r) for r in app.workspace.roots],
            "permissions": app.policy.describe(),
            "targets": app.targets.names(),
            "debug_connected": bool(debug and debug.connected),
        }

    @registry.tool("core", "session_manager", READ_ONLY)
    def session_set_context(target: str | None = None, app_dir: str | None = None,
                            serial_port: str | None = None, flash_baud: int | None = None,
                            monitor_baud: int | None = None) -> dict[str, Any]:
        """Remember defaults so later tools can omit them. app_dir may be SDK-relative
        (e.g. "examples/Printf_Log") or a workspace path. Pass "" (or 0 for baud) to clear."""
        if target is not None:
            app.session.target = app.target(target).name if target else None
        if app_dir is not None:
            app.session.app_dir = str(app.app_dir(app_dir)) if app_dir else None
        if serial_port is not None:
            app.session.serial_port = serial_port or None
        for name, value in (("flash_baud", flash_baud), ("monitor_baud", monitor_baud)):
            if value is not None:
                if value < 0:
                    raise InvalidArgumentError(f"{name} must be positive.")
                setattr(app.session, name, value or None)
        return {"session": app.session.to_dict(), "hardware_allowed": app.policy.allowed(Permission.HARDWARE)}
