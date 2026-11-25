"""OpenOCD adapter: run OpenOCD with board-verified configuration files as a GDB server.

The NEON-MDF SDK ships only a placeholder (`neon-mdf/cmake/openocd/GT32U2086_openocd.cfg`),
so the caller must supply configs verified for the probe and board.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from ..system.errors import CommandError

_LISTENING = re.compile(r"Listening on port (\d+) for gdb connections", re.IGNORECASE)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OpenOcdServer:
    def __init__(self, configs: list[Path], cwd: Path, openocd: str | None = None,
                 extra_commands: list[str] | None = None, startup_timeout_s: float = 15.0) -> None:
        executable = openocd or shutil.which("openocd")
        if not executable:
            raise CommandError("OpenOCD is not installed or not on PATH.",
                               "Install OpenOCD, or start your GDB server yourself and pass gdb_server.")
        self.port = _free_port()
        command = [executable]
        for cfg in configs:
            command += ["-f", str(cfg)]
        command += ["-c", f"gdb_port {self.port}", "-c", "telnet_port disabled", "-c", "tcl_port disabled"]
        for extra in extra_commands or []:
            command += ["-c", extra]
        self.command = command
        self._output: list[str] = []
        self._proc = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, errors="replace",
                                      start_new_session=(os.name == "posix"))
        self._ready = threading.Event()
        threading.Thread(target=self._read, name="openocd-reader", daemon=True).start()
        deadline = time.monotonic() + startup_timeout_s
        while not self._ready.wait(0.1):
            if self._proc.poll() is not None or time.monotonic() > deadline:
                output = self.output()
                self.close()
                raise CommandError("OpenOCD did not start a GDB server.",
                                   "OpenOCD output:\n" + output[-2000:])

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._output.append(line)
            if _LISTENING.search(line):
                self._ready.set()

    @property
    def address(self) -> str:
        return f"localhost:{self.port}"

    def output(self) -> str:
        return "".join(self._output)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
