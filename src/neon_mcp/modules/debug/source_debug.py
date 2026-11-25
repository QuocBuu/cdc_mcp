"""Source Debug submodule: backtrace with source lines and local variables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...core.tools import READS_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError, NeonError
from ...system.security import Permission
from .session import frame_summary, get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "source_debug", READS_HARDWARE)
    def debug_backtrace(max_frames: int = 32, with_locals: bool = True) -> dict[str, Any]:
        """Call stack of the halted target (function, file:line, address per frame) and, for the
        innermost frame, local variables and arguments with their current values."""
        app.policy.require(Permission.HARDWARE, "debug_backtrace")
        if not 1 <= max_frames <= 256:
            raise InvalidArgumentError("max_frames must be 1..256.")
        with manager.lock:
            gdb = manager.require_halted()
            _, payload, _ = gdb.command(f"-stack-list-frames 0 {max_frames - 1}")
            frames = [dict(frame_summary({"frame": f}) or {}, level=int(f.get("level", i)))
                      for i, f in enumerate(payload.get("stack", []))]
            for frame in frames:
                frame.pop("reason", None)
            variables = []
            if with_locals:
                try:
                    _, local_payload, _ = gdb.command("-stack-list-variables --simple-values")
                    variables = [{k: v for k, v in var.items()} for var in local_payload.get("variables", [])]
                except NeonError as exc:
                    variables = [{"error": str(exc)}]
        return {"frames": frames, "locals": variables,
                "note": None if frames else "No frames: the ELF may not match the running firmware."}
