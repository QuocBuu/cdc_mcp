"""Application context shared by all tools: settings, SDK, workspace guard, policy, targets,
session and lazily created services (documentation index, API index, debug session)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from ..adapters.neon_mdf import NeonMdfSdk, discover_sdk
from ..system.config import Settings
from ..system.errors import InvalidArgumentError, NotFoundError
from ..system.security import SecurityPolicy
from ..system.workspace import Workspace
from ..targets.registry import Target, TargetRegistry
from .session import Session

log = logging.getLogger(__name__)
T = TypeVar("T")


class NeonApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings.resolve()
        self.sdk = NeonMdfSdk(discover_sdk(self.settings.sdk_path, self.settings.workspace_roots))
        self.workspace = Workspace([*self.settings.workspace_roots, self.sdk.root])
        self.policy = SecurityPolicy(self.settings)
        self.targets = TargetRegistry(self.sdk, self.settings.targets_dir)
        self.session = Session()
        self.services: dict[str, Any] = {}
        self.registry: Any = None  # ToolRegistry, set by core.server.create_server
        self._services_lock = threading.Lock()
        log.info("NEON-MDF SDK %s at %s; workspace roots: %s; permissions: %s",
                 self.sdk.version or "(unversioned)", self.sdk.root, self.workspace.roots,
                 self.policy.describe())

    def service(self, key: str, factory: Callable[[], T]) -> T:
        """Return the shared service `key`, creating it once (tools run in worker threads)."""
        with self._services_lock:
            if key not in self.services:
                self.services[key] = factory()
            return self.services[key]

    # --- Defaults ----------------------------------------------------------------------------------
    def target(self, name: str | None = None) -> Target:
        return self.targets.get(name or self.session.target)

    def app_dir(self, path: str | None) -> Path:
        """Resolve an application directory (argument, else session default) inside the workspace."""
        chosen = path or self.session.app_dir
        if not chosen:
            raise InvalidArgumentError(
                "No application directory given.",
                "Pass app_dir (e.g. 'examples/Printf_Log' relative to the SDK) or call session_set_context.")
        candidate = Path(chosen).expanduser()
        if not candidate.is_absolute():
            # Relative paths are tried against the SDK first (examples/...), then the workspace.
            for base in [self.sdk.root, *self.workspace.roots]:
                if (base / candidate).is_dir():
                    candidate = base / candidate
                    break
        resolved = self.workspace.resolve(candidate, kind="dir")
        if not (resolved / "CMakeLists.txt").is_file():
            raise NotFoundError(f"'{resolved}' is not a NEON-MDF application (no CMakeLists.txt).")
        return resolved

    def python(self, app_dir: Path | None) -> str:
        return self.sdk.python_for(app_dir, self.settings.sdk_python)

    def close(self) -> None:
        """Release services holding processes (debug session, OpenOCD)."""
        for service in list(self.services.values()):
            closer = getattr(service, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    log.exception("error while closing a service")
