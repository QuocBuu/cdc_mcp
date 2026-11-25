"""GDB/MI adapter: drive `arm-none-eabi-gdb` or `gdb-multiarch` through the Machine Interface.

One GdbMi instance owns one GDB process. Commands are serialized; a reader thread parses
MI output, matches result records to command tokens and tracks the target's run state
from `*running` / `*stopped` async records.
"""

from __future__ import annotations

import itertools
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..system.errors import CommandError, NeonError

log = logging.getLogger(__name__)

GDB_CANDIDATES = ("arm-none-eabi-gdb", "gdb-multiarch")


class MiError(NeonError):
    """GDB rejected a command (`^error`)."""


@dataclass
class MiRecord:
    token: int | None
    kind: str            # result | exec | status | notify | console | target | log
    cls: str = ""
    payload: Any = field(default_factory=dict)


# --- MI output syntax ---------------------------------------------------------------------------
class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char: str) -> None:
        if self.peek() != char:
            raise ValueError(f"expected {char!r} at {self.pos} in {self.text!r}")
        self.pos += 1

    def results(self, end: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}
        while self.pos < len(self.text) and self.peek() != end:
            name, value = self.result()
            if name in out:  # repeated keys (e.g. frame=..,frame=..) become lists
                existing = out[name]
                out[name] = existing + [value] if isinstance(existing, list) else [existing, value]
            else:
                out[name] = value
            if self.peek() == ",":
                self.pos += 1
        return out

    def result(self) -> tuple[str, Any]:
        start = self.pos
        while self.peek() not in ("=", ""):
            self.pos += 1
        name = self.text[start:self.pos]
        self.expect("=")
        return name, self.value()

    def value(self) -> Any:
        char = self.peek()
        if char == '"':
            return self.cstring()
        if char == "{":
            self.pos += 1
            value = self.results("}")
            self.expect("}")
            return value
        if char == "[":
            self.pos += 1
            items: list[Any] = []
            while self.peek() != "]":
                if self.peek() in ('"', "{", "["):
                    items.append(self.value())
                else:
                    items.append(self.result()[1])  # name=value inside a list: keep the value
                if self.peek() == ",":
                    self.pos += 1
            self.expect("]")
            return items
        raise ValueError(f"unexpected {char!r} at {self.pos} in {self.text!r}")

    def cstring(self) -> str:
        self.expect('"')
        out = []
        while True:
            char = self.peek()
            if char == "":
                raise ValueError("unterminated string")
            self.pos += 1
            if char == '"':
                return "".join(out)
            if char != "\\":
                out.append(char)
                continue
            esc = self.peek()
            self.pos += 1
            if esc in "01234567":
                digits = esc
                while len(digits) < 3 and self.peek() in "01234567" and self.peek():
                    digits += self.peek()
                    self.pos += 1
                out.append(chr(int(digits, 8)))
            else:
                out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(esc, esc))


def parse_line(line: str) -> MiRecord | None:
    line = line.rstrip("\r\n")
    if not line or line.strip() == "(gdb)":
        return None
    if line[0] in "~@&":
        kind = {"~": "console", "@": "target", "&": "log"}[line[0]]
        try:
            return MiRecord(None, kind, payload=_Parser(line[1:]).cstring())
        except ValueError:
            return MiRecord(None, kind, payload=line[1:])
    index = 0
    while index < len(line) and line[index].isdigit():
        index += 1
    token = int(line[:index]) if index else None
    if index >= len(line) or line[index] not in "^*+=":
        return MiRecord(token, "console", payload=line + "\n")  # program output on GDB's stdout
    kind = {"^": "result", "*": "exec", "+": "status", "=": "notify"}[line[index]]
    rest = line[index + 1:]
    cls, _, body = rest.partition(",")
    try:
        payload = _Parser(body).results() if body else {}
    except ValueError:
        payload = {"raw": body}
    return MiRecord(token, kind, cls, payload)


def c_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_gdb(explicit: str | None) -> str:
    candidates = [explicit] if explicit else [os.environ.get("NEON_MCP_GDB"), *GDB_CANDIDATES]
    for candidate in [c for c in candidates if c]:
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if path:
            return path
    raise CommandError(
        "No GDB with Arm support found (" + ", ".join(GDB_CANDIDATES) + ").",
        "Install the Arm GNU Toolchain (arm-none-eabi-gdb) or `apt install gdb-multiarch`, "
        "or pass gdb=/path/to/gdb (env NEON_MCP_GDB).")


# --- GDB process ---------------------------------------------------------------------------------
class GdbMi:
    def __init__(self, gdb_path: str, elf: Path | None, cwd: Path) -> None:
        command = [gdb_path, "--interpreter=mi3", "--nx", "--quiet"]
        if elf is not None:
            command.append(str(elf))
        try:
            self._proc = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace",
                                          start_new_session=(os.name == "posix"))
        except OSError as exc:
            raise CommandError(f"Cannot start {gdb_path}: {exc}") from exc
        self.gdb_path = gdb_path
        self._tokens = itertools.count(1)
        self._command_lock = threading.Lock()
        self._results: dict[int, queue.Queue[MiRecord]] = {}
        self._results_lock = threading.Lock()
        self._console: list[str] = []
        self._state_cond = threading.Condition()
        self.state = "unknown"           # unknown | stopped | running | exited
        self.last_stop: dict[str, Any] | None = None
        self._stop_seq = 0
        self._reader = threading.Thread(target=self._read_loop, name="gdb-mi-reader", daemon=True)
        self._reader.start()

    # --- reader -----------------------------------------------------------------------------------
    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            record = parse_line(line)
            if record is None:
                continue
            if record.kind == "result" and record.token is not None:
                with self._results_lock:
                    waiter = self._results.get(record.token)
                if waiter is not None:
                    waiter.put(record)
                if record.cls == "running":
                    self._set_state("running")
                continue
            if record.kind in ("console", "target", "log"):
                self._console.append(str(record.payload))
                continue
            if record.kind == "exec":
                if record.cls == "running":
                    self._set_state("running")
                elif record.cls == "stopped":
                    reason = record.payload.get("reason", "")
                    with self._state_cond:
                        self.last_stop = record.payload
                        self._stop_seq += 1
                        self.state = "exited" if reason.startswith("exited") else "stopped"
                        self._state_cond.notify_all()
        self._set_state("exited")

    def _set_state(self, state: str) -> None:
        with self._state_cond:
            self.state = state
            self._state_cond.notify_all()

    # --- commands -----------------------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    @property
    def stop_seq(self) -> int:
        with self._state_cond:
            return self._stop_seq

    def command(self, mi_command: str, timeout_s: float = 15.0) -> tuple[str, Any, str]:
        """Send one MI command; return (result class, payload, console text). Raises MiError on ^error."""
        if not self.alive:
            raise CommandError("The GDB process has exited.", "Reconnect with debug_connect.")
        with self._command_lock:
            token = next(self._tokens)
            waiter: queue.Queue[MiRecord] = queue.Queue()
            with self._results_lock:
                self._results[token] = waiter
            self._console.clear()
            log.debug("gdb <- %s%s", token, mi_command)
            assert self._proc.stdin is not None
            self._proc.stdin.write(f"{token}{mi_command}\n")
            self._proc.stdin.flush()
            try:
                record = waiter.get(timeout=timeout_s)
            except queue.Empty as exc:
                raise CommandError(f"GDB did not answer '{mi_command}' within {timeout_s} s.") from exc
            finally:
                with self._results_lock:
                    self._results.pop(token, None)
            time.sleep(0.02)  # let trailing console records for this command arrive
            console = "".join(self._console)
        if record.cls == "error":
            raise MiError(f"GDB error for '{mi_command}': {record.payload.get('msg', record.payload)}")
        return record.cls, record.payload, console

    def console(self, cli_command: str, timeout_s: float = 15.0) -> str:
        return self.command(f"-interpreter-exec console {c_quote(cli_command)}", timeout_s)[2]

    def mark_stopped(self) -> None:
        """Record that the target is halted when GDB reports no *stopped (e.g. right after attach)."""
        if self.state in ("unknown", "stopped"):
            self._set_state("stopped")

    def wait_for_stop(self, after_seq: int, timeout_s: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_s
        with self._state_cond:
            while self._stop_seq <= after_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.state == "exited":
                    return None
                self._state_cond.wait(remaining)
            return self.last_stop

    def close(self) -> None:
        if self.alive:
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.write("-gdb-exit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
        self._set_state("exited")
