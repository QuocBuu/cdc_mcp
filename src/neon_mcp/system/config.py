"""Server settings resolved from command-line options and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_SDK = "NEON_MCP_SDK_PATH"
ENV_WORKSPACE = "NEON_MCP_WORKSPACE"
ENV_ALLOW_HARDWARE = "NEON_MCP_ALLOW_HARDWARE"
ENV_READ_ONLY = "NEON_MCP_READ_ONLY"
ENV_SDK_PYTHON = "NEON_MCP_SDK_PYTHON"
ENV_TARGETS_DIR = "NEON_MCP_TARGETS_DIR"
ENV_PACKS_DIR = "NEON_MCP_PACKS_DIR"
ENV_BUILD_TIMEOUT = "NEON_MCP_BUILD_TIMEOUT"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime configuration. Paths are absolute once `resolve()` has run."""

    sdk_path: Path | None = None
    """NEON-MDF checkout (repository root or its `neon-mdf/` directory). None = discover."""

    workspace_roots: list[Path] = field(default_factory=list)
    """Directories NEON MCP may read and write. The SDK root is always added."""

    allow_hardware: bool = False
    """Allow serial-port access and UART programming of a connected board."""

    read_only: bool = False
    """Forbid every operation that writes files (project creation, config edits, builds)."""

    sdk_python: Path | None = None
    """Interpreter passed to CMake and SDK tools. None = SDK/app `.venv`, else this server's Python."""

    targets_dir: Path | None = None
    """Extra directory of target profile YAML files."""

    packs_dir: Path | None = None
    """Extra directory of knowledge packs, searched before the packs bundled with NEON MCP."""

    build_timeout_s: float = 900.0

    @classmethod
    def from_env(cls) -> Settings:
        roots = [Path(p) for p in os.environ.get(ENV_WORKSPACE, "").split(os.pathsep) if p.strip()]
        sdk = os.environ.get(ENV_SDK) or None
        python = os.environ.get(ENV_SDK_PYTHON) or None
        targets = os.environ.get(ENV_TARGETS_DIR) or None
        packs = os.environ.get(ENV_PACKS_DIR) or None
        timeout = os.environ.get(ENV_BUILD_TIMEOUT)
        return cls(
            sdk_path=Path(sdk) if sdk else None,
            workspace_roots=roots,
            allow_hardware=_env_flag(ENV_ALLOW_HARDWARE),
            read_only=_env_flag(ENV_READ_ONLY),
            sdk_python=Path(python) if python else None,
            targets_dir=Path(targets) if targets else None,
            packs_dir=Path(packs) if packs else None,
            build_timeout_s=float(timeout) if timeout else 900.0,
        )

    def resolve(self) -> Settings:
        """Make paths absolute; default the workspace to the current directory."""
        if not self.workspace_roots:
            self.workspace_roots = [Path.cwd()]
        self.workspace_roots = [p.expanduser().resolve() for p in self.workspace_roots]
        if self.sdk_path is not None:
            self.sdk_path = self.sdk_path.expanduser().resolve()
        if self.sdk_python is not None:
            self.sdk_python = self.sdk_python.expanduser()
        if self.targets_dir is not None:
            self.targets_dir = self.targets_dir.expanduser().resolve()
        if self.packs_dir is not None:
            self.packs_dir = self.packs_dir.expanduser().resolve()
        return self
