"""Run external commands with a timeout, combined output and a bounded result size."""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import CommandError

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    command: list[str]
    cwd: str
    returncode: int | None
    output: str
    duration_s: float
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def summary(self, max_chars: int = 8000) -> dict:
        return {
            "command": shlex.join(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 2),
            "output": tail(self.output, max_chars),
        }


def tail(text: str, max_chars: int) -> str:
    """Keep the end of long output, where build and tool errors usually are."""
    if len(text) <= max_chars:
        return text
    cut = text[-max_chars:]
    newline = cut.find("\n")
    if 0 <= newline < 200:
        cut = cut[newline + 1:]
    return f"[... {len(text) - len(cut)} characters omitted ...]\n{cut}"


def run(command: list[str], cwd: Path, *, timeout_s: float, env: dict[str, str] | None = None) -> ProcessResult:
    """Run `command` without a shell. stdin is closed so tools never wait for input."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    log.info("run: %s (cwd=%s)", shlex.join(command), cwd)
    started = time.monotonic()
    popen_kwargs: dict = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command, cwd=str(cwd), env=full_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"Command not found: {command[0]}.",
                           "Check the tool is installed and on PATH (see dev_check_environment).") from exc
    except OSError as exc:
        raise CommandError(f"Cannot start {command[0]}: {exc}.") from exc
    timed_out = False
    try:
        raw, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(proc)
        raw, _ = proc.communicate()
    output = raw.decode("utf-8", errors="replace") if raw else ""
    return ProcessResult(command, str(cwd), proc.returncode, output, time.monotonic() - started, timed_out)


def _terminate(proc: subprocess.Popen) -> None:
    """Stop the process and its children (CMake spawns compilers and Python tools)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGINT)
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
