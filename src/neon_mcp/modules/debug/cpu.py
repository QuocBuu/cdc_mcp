"""CPU Control submodule: halt, continue, step, next, step-instruction, finish and reset."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ...core.tools import TOUCHES_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission
from .session import frame_summary, get_manager

if TYPE_CHECKING:
    from ...core.app import NeonApp

Action = Literal["halt", "continue", "step", "next", "step_instruction", "finish", "reset"]
_MI = {"continue": "-exec-continue", "step": "-exec-step", "next": "-exec-next",
       "step_instruction": "-exec-step-instruction", "finish": "-exec-finish"}


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "cpu", TOUCHES_HARDWARE)
    def debug_control(action: Action, wait_s: float = 5.0) -> dict[str, Any]:
        """Control the CPU: halt, continue, step (source line, into calls), next (over calls),
        step_instruction, finish (run to caller) or reset (`monitor reset halt` via OpenOCD).

        Running actions wait up to wait_s for the target to stop (breakpoint, step end); if it is
        still running the result says so and debug_control('halt') stops it.
        """
        app.policy.require(Permission.HARDWARE, "debug_control")
        if not 0 <= wait_s <= 120:
            raise InvalidArgumentError("wait_s must be within 0..120.")
        with manager.lock:
            gdb = manager.require()
            if action == "halt":
                if gdb.state != "running":
                    return {"action": action, "state": gdb.state, "frame": manager.current_frame()}
                seq = gdb.stop_seq
                gdb.command("-exec-interrupt")
                stop = gdb.wait_for_stop(seq, max(wait_s, 1.0))
                return {"action": action, "state": gdb.state, "stop": frame_summary(stop)}
            if action == "reset":
                manager.require_halted()
                command = app.target().profile.get("debug", {}).get("reset_command", "monitor reset halt")
                output = gdb.console(command, timeout_s=30)
                gdb.console("maintenance flush register-cache")
                return {"action": action, "command": command, "output": output.strip(), "state": gdb.state,
                        "frame": manager.current_frame()}
            manager.require_halted()
            seq = gdb.stop_seq
            gdb.command(_MI[action])
            stop = gdb.wait_for_stop(seq, wait_s)
            return {"action": action, "state": gdb.state, "stop": frame_summary(stop),
                    "note": None if stop else "Target still running; call debug_control(action='halt')."}
