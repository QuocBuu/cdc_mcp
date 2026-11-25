"""Breakpoint Manager submodule: hardware breakpoints and watchpoints.

Code runs from Flash, so breakpoints default to hardware comparators (Cortex-M0: up to 4
breakpoints and 2 watchpoints, implementation defined).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from ...adapters.gdb import c_quote
from ...core.tools import TOUCHES_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission
from .session import get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp

BreakAction = Literal["set", "watch", "delete", "list"]
WatchAccess = Literal["write", "read", "access"]
_LOCATION = re.compile(r"^[\w./:*+\-]+$")


def _bkpt(item: dict[str, Any]) -> dict[str, Any]:
    return {k: item.get(k) for k in ("number", "type", "disp", "enabled", "addr", "func", "file", "line",
                                      "times", "cond", "what", "exp") if item.get(k) is not None}


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "breakpoint", TOUCHES_HARDWARE)
    def debug_breakpoint(action: BreakAction, location: str | None = None, number: int | None = None,
                         hardware: bool = True, condition: str | None = None,
                         access: WatchAccess = "write") -> dict[str, Any]:
        """Manage breakpoints and watchpoints.

        set: location is a function ("main"), "file.c:42" or "*0x00020100"; hardware=True (default)
        uses a hardware comparator, required for code in Flash. condition: optional C expression.
        watch: location is a variable/expression; access = write | read | access.
        delete: number from set/list. list: all breakpoints with hit counts.
        """
        app.policy.require(Permission.HARDWARE, "debug_breakpoint")
        limits = app.target().profile.get("debug", {})
        with manager.lock:
            gdb = manager.require()
            if action == "list":
                _, payload, _ = gdb.command("-break-list")
                body = payload.get("BreakpointTable", {}).get("body", [])
                return {"breakpoints": [_bkpt(b) for b in body], "limits": limits}
            if action == "delete":
                if number is None:
                    raise InvalidArgumentError("number is required for delete.")
                gdb.command(f"-break-delete {int(number)}")
                return {"deleted": number}
            if not location or not _LOCATION.match(location):
                raise InvalidArgumentError("location must be a function, file:line, *address or variable name.")
            if action == "watch":
                flag = {"write": "", "read": "-r ", "access": "-a "}[access]
                _, payload, _ = gdb.command(f"-break-watch {flag}{location}")
                item = payload.get("wpt") or payload.get("hw-rwpt") or payload.get("hw-awpt") or {}
                return {"watchpoint": _bkpt(item), "access": access, "limits": limits}
            options = "-h " if hardware else ""
            if condition:
                options += f"-c {c_quote(condition)} "
            _, payload, _ = gdb.command(f"-break-insert {options}{location}")
            return {"breakpoint": _bkpt(payload.get("bkpt", {})), "hardware": hardware, "limits": limits,
                    "note": "Use debug_control('continue') to run until it is hit."}
