"""Debug Session submodule: connect GDB to a target (through OpenOCD or an existing GDB server),
track its state and disconnect cleanly."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters.gdb import GdbMi, find_gdb
from ...adapters.openocd import OpenOcdServer
from ...core.tools import TOUCHES_HARDWARE, ToolRegistry
from ...system.errors import CapabilityError, InvalidArgumentError, NeonError
from ...system.security import Permission
from ..development.build import find_elf

if TYPE_CHECKING:
    from ...core.app import NeonApp


def frame_summary(stop: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stop:
        return None
    frame = stop.get("frame") or {}
    summary = {
        "reason": stop.get("reason"),
        "address": frame.get("addr"),
        "function": frame.get("func"),
        "file": frame.get("fullname") or frame.get("file"),
        "line": int(frame["line"]) if str(frame.get("line", "")).isdigit() else None,
    }
    for key in ("bkptno", "signal-name", "signal-meaning", "exit-code"):
        if key in stop:
            summary[key.replace("-", "_")] = stop[key]
    return summary


class DebugManager:
    """At most one debug session per server (GT32U2086 is single-core)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.gdb: GdbMi | None = None
        self.openocd: OpenOcdServer | None = None
        self.info: dict[str, Any] = {}

    @property
    def connected(self) -> bool:
        return self.gdb is not None and self.gdb.alive

    def require(self) -> GdbMi:
        if not self.connected:
            raise NeonError("No debug session.", "Call debug_connect first.")
        assert self.gdb is not None
        return self.gdb

    def require_halted(self) -> GdbMi:
        gdb = self.require()
        if gdb.state == "running":
            raise InvalidArgumentError("The target is running.", "Halt it first: debug_control(action='halt').")
        if gdb.state == "exited":
            raise NeonError("The debugged program has exited.", "Reconnect with debug_connect.")
        return gdb

    def current_frame(self) -> dict[str, Any] | None:
        gdb = self.require()
        if gdb.state == "running":
            return None
        try:
            _, payload, _ = gdb.command("-stack-info-frame")
        except NeonError:
            return None
        return frame_summary({"frame": payload.get("frame", {})})

    def read_bytes(self, address: int, length: int) -> bytes:
        gdb = self.require_halted()
        _, payload, _ = gdb.command(f"-data-read-memory-bytes 0x{address:X} {length}")
        blocks = payload.get("memory") or []
        data = bytearray()
        for block in blocks if isinstance(blocks, list) else [blocks]:
            data.extend(bytes.fromhex(block.get("contents", "")))
        if len(data) != length:
            raise NeonError(f"Read {len(data)} of {length} bytes at 0x{address:08X} (memory not accessible).")
        return bytes(data)

    def read_words(self, address: int, count: int) -> list[int]:
        data = self.read_bytes(address, count * 4)
        return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]

    def registers(self, names: list[str] | None = None) -> dict[str, int]:
        gdb = self.require_halted()
        _, payload, _ = gdb.command("-data-list-register-names")
        all_names = payload.get("register-names", [])
        _, values, _ = gdb.command("-data-list-register-values --skip-unavailable x")
        result: dict[str, int] = {}
        wanted = {n.lower() for n in names} if names else None
        for item in values.get("register-values", []):
            index = int(item["number"])
            name = all_names[index] if index < len(all_names) else ""
            if not name or (wanted is not None and name.lower() not in wanted):
                continue
            try:
                result[name] = int(item["value"], 16)
            except (ValueError, KeyError):
                continue
        return result

    def close(self) -> None:
        with self.lock:
            if self.gdb is not None:
                try:
                    if self.gdb.alive and self.gdb.state != "exited":
                        self.gdb.command("-target-detach", timeout_s=5)
                except NeonError:
                    pass
                self.gdb.close()
            if self.openocd is not None:
                self.openocd.close()
            self.gdb, self.openocd, self.info = None, None, {}


def get_manager(app: NeonApp) -> DebugManager:
    return app.service("debug", DebugManager)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    manager = get_manager(app)

    @registry.tool("debug", "session", TOUCHES_HARDWARE)
    def debug_connect(gdb_server: str | None = None, openocd_config: list[str] | None = None,
                      elf_path: str | None = None, app_dir: str | None = None, build_dir: str | None = None,
                      gdb: str | None = None, target: str | None = None) -> dict[str, Any]:
        """Attach GDB to the board for source-level debugging; the target is halted on attach.

        Give either gdb_server ("host:port" of a running OpenOCD/J-Link/pyOCD GDB server) or
        openocd_config (config files verified for your probe and board; NEON MCP starts OpenOCD).
        The SDK's GT32U2086 OpenOCD config is a placeholder, so one of these is required.
        Symbols come from elf_path or the app's build ELF; the board must run that same firmware
        (program it first with prog_flash_uart). GDB: arm-none-eabi-gdb or gdb-multiarch
        (override with gdb=...). Requires --allow-hardware.
        """
        app.policy.require(Permission.HARDWARE, "debug_connect")
        tgt = app.target(target)
        if not gdb_server and not openocd_config:
            if tgt.supports("jtag_debug"):
                raise InvalidArgumentError("Pass gdb_server or openocd_config.")
            raise CapabilityError(
                f"{tgt.name} has no verified SDK debug configuration.",
                "Pass openocd_config=[<board-verified .cfg files>] or gdb_server='localhost:3333' "
                "for a GDB server you started yourself.")
        with manager.lock:
            if manager.connected:
                raise InvalidArgumentError("A debug session is already open.", "Call debug_disconnect first.")
            warnings = []
            elf = None
            if elf_path or app_dir:
                elf = find_elf(app, elf_path, app_dir, build_dir)
            elif app.session.app_dir:
                try:
                    elf = find_elf(app, None, None, build_dir)
                except NeonError as exc:
                    warnings.append(f"Session app has no usable ELF ({exc}).")
            gdb_path = find_gdb(gdb)
            if not tgt.supports("jtag_debug"):
                warnings.append("Using a user-supplied debug setup: the SDK's OpenOCD config for "
                                f"{tgt.name} is not verified.")
            if elf is None:
                warnings.append("No ELF loaded: no symbols, source lines or breakpoints by name.")
            server = gdb_server
            if openocd_config:
                configs = [app.workspace.resolve(c, kind="file") for c in openocd_config]
                manager.openocd = OpenOcdServer(configs, app.sdk.root)
                server = manager.openocd.address
            assert server is not None
            if not all(part for part in server.rsplit(":", 1)) or ":" not in server:
                raise InvalidArgumentError(f"gdb_server must look like host:port, got '{server}'.")
            session = GdbMi(gdb_path, elf, Path(elf).parent if elf else app.sdk.root)
            manager.gdb = session
            try:
                for setting in ("mi-async on", "confirm off", "pagination off", "print pretty off"):
                    session.command(f"-gdb-set {setting}")
                seq = session.stop_seq
                session.command(f"-target-select remote {server}", timeout_s=30)
                stop = session.wait_for_stop(seq, 5)
                session.mark_stopped()  # a remote attach leaves the target halted
            except NeonError:
                manager.close()
                raise
            manager.info = {"target": tgt.name, "server": server, "gdb": gdb_path,
                            "elf": str(elf) if elf else None,
                            "openocd": manager.openocd.command if manager.openocd else None}
            return {"connected": True, **manager.info, "state": session.state,
                    "frame": frame_summary(stop) or manager.current_frame(), "warnings": warnings,
                    "limits": tgt.profile.get("debug", {})}

    @registry.tool("debug", "session", TOUCHES_HARDWARE)
    def debug_disconnect() -> dict[str, Any]:
        """Detach GDB (the target keeps running its firmware) and stop OpenOCD if NEON MCP started it."""
        was = dict(manager.info)
        manager.close()
        return {"connected": False, "previous": was or None}
