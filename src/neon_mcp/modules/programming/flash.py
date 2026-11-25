"""Flash submodule: serial ports and UART programming through the SDK's gt32u2086_flash.py,
using the exact image CMake selected for the flash target (signed/unsigned, normal/XIP)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...adapters import cmake, uart
from ...core.tools import READ_ONLY, TOUCHES_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.process import run
from ...system.security import Permission
from ..development import build as build_flow

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("programming", "flash", READ_ONLY)
    def prog_list_serial_ports() -> dict[str, Any]:
        """List serial ports (USB-UART adapters) visible to the host. Does not open any port."""
        ports = uart.list_ports()
        return {"count": len(ports), "ports": ports,
                "note": None if ports else "No ports found: check the USB-UART adapter, its driver, and "
                                           "permissions (Linux: dialout group)."}

    @registry.tool("programming", "flash", TOUCHES_HARDWARE)
    def prog_flash_uart(port: str | None = None, baud: int | None = None, app_dir: str | None = None,
                        build_dir: str | None = None, wait_for_reset_s: float = 60,
                        byte_gap_ms: float | None = None, target: str | None = None) -> dict[str, Any]:
        """Build the application and program it into internal Flash through the ROMCODE UART update.

        BEFORE calling, tell the user to: close serial monitors on the port, set boot mode 100, and
        press RESET on the board when asked. The tool waits up to wait_for_reset_s for RESET, then
        streams the image; it ends at '[PASS] Image transfer completed' (ROMCODE then runs the app)
        or a timeout. Afterwards the board should be switched to boot mode 000.
        baud must match the board ROMCODE (default from the target profile, 19200).
        byte_gap_ms: delay between reply bytes (SDK default 2; 0 is faster but less tolerant).
        Requires the server to run with --allow-hardware.
        """
        app.policy.require(Permission.HARDWARE, "prog_flash_uart")
        app.policy.require(Permission.WRITE, "prog_flash_uart (builds the application first)")
        tgt = app.target(target)
        tgt.require("uart_flash", "UART programming")
        port = uart.validate_port(port or app.session.serial_port or "")
        board = tgt.profile.get("board", {})
        baud = baud or app.session.flash_baud or board.get("flash_baud") or 19200
        if not 0 < wait_for_reset_s <= 600:
            raise InvalidArgumentError("wait_for_reset_s must be in (0, 600].")
        if byte_gap_ms is not None and not 0 <= byte_gap_ms <= 50:
            raise InvalidArgumentError("byte_gap_ms must be within 0..50.")
        directory = app.app_dir(app_dir)
        report, lay = build_flow.build(app, tgt, directory, build_dir=build_dir)
        if not report.get("ok"):
            return {"ok": False, "stage": report.get("stage"), "build": report}
        command = cmake.flash_command(lay, board.get("flash_target", "flash_uart_gt32u2086"))
        if "--profile" in command and command[command.index("--profile") + 1] == "xip":
            raise InvalidArgumentError("This build uses the XIP profile; ROMCODE UART update only writes internal "
                                       "Flash. Rebuild with profile='normal'.")
        command += ["--port", port, "--baud", str(baud), "--wait-timeout", str(wait_for_reset_s),
                    "--log-mode", "progress", "--no-monitor"]
        if byte_gap_ms is not None:
            command += ["--byte-gap-ms", str(byte_gap_ms)]
        result = run(command, directory, timeout_s=wait_for_reset_s + 900)
        passed = "[PASS]" in result.output and result.ok
        image = command[command.index("--image") + 1] if "--image" in command else None
        app.session.serial_port, app.session.flash_baud = port, baud
        return {
            "ok": passed, "stage": "flash", "image": image, "port": port, "baud": baud,
            "status": "programmed" if passed else ("timeout" if result.timed_out else "failed"),
            "next_step": "Switch the board to boot mode 000 for later resets." if passed else
                         "Check boot mode 100, TX/RX/GND wiring, baud, and that RESET was pressed in time.",
            "build_artifacts": report.get("artifacts"),
            "flash": result.summary(6000),
        }
