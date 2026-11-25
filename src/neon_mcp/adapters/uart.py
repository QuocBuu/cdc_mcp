"""UART adapter: enumerate serial ports and capture output for a bounded time.

Interpretation of the captured text lives in modules/analysis/log_analyzer.py.
"""

from __future__ import annotations

import glob
import os
import time

from ..system.errors import CommandError, InvalidArgumentError

_PORT_PATTERNS = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/tty.usbserial*")


def list_ports() -> list[dict]:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        lp = None
    if lp is not None:
        return [{"device": p.device, "description": p.description, "hwid": p.hwid,
                 "manufacturer": getattr(p, "manufacturer", None)}
                for p in sorted(lp.comports(), key=lambda p: p.device)]
    devices = sorted({d for pattern in _PORT_PATTERNS for d in glob.glob(pattern)})
    return [{"device": d, "description": None, "hwid": None, "manufacturer": None} for d in devices]


def validate_port(port: str) -> str:
    port = port.strip()
    if not port or "\n" in port:
        raise InvalidArgumentError("Serial port name is empty or malformed.")
    if os.name != "nt" and not port.startswith("/dev/"):
        raise InvalidArgumentError(f"'{port}' is not a serial device path (expected /dev/...).")
    return port


def capture(port: str, baud: int, duration_s: float, send: str | None = None, max_bytes: int = 65536) -> dict:
    """Open `port` 8N1 without flow control, optionally send text, and read for `duration_s`."""
    try:
        import serial
    except ImportError as exc:
        raise CommandError("pyserial is not installed in the NEON MCP environment.") from exc
    port = validate_port(port)
    if not 0 < duration_s <= 300:
        raise InvalidArgumentError("duration_s must be between 0 and 300 seconds.")
    if baud <= 0:
        raise InvalidArgumentError("baud must be positive.")
    received = bytearray()
    try:
        with serial.Serial(port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.1,
                           xonxoff=False, rtscts=False, dsrdtr=False) as ser:
            ser.reset_input_buffer()
            if send:
                ser.write(send.encode("utf-8"))
                ser.flush()
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline and len(received) < max_bytes:
                chunk = ser.read(max(1, min(4096, ser.in_waiting or 1)))
                if chunk:
                    received.extend(chunk)
    except serial.SerialException as exc:
        raise CommandError(f"Cannot use serial port {port}: {exc}",
                           "Close other monitors/flash tools holding the port and check permissions "
                           "(Linux: dialout group).") from exc
    text = received.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return {"port": port, "baud": baud, "duration_s": duration_s, "bytes": len(received),
            "truncated": len(received) >= max_bytes, "sent": send, "text": text}
