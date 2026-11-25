"""Log Analyzer submodule: capture application UART output and summarize logs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...adapters import uart
from ...core.tools import READ_ONLY, READS_HARDWARE, ToolRegistry
from ...system.errors import InvalidArgumentError
from ...system.security import Permission

if TYPE_CHECKING:
    from ...core.app import NeonApp

_TAG = re.compile(r"\[(INFO|PASS|FAIL|ERROR|WARN|WARNING|RUN|DBG|DEBUG)\]", re.IGNORECASE)
_HEX = re.compile(r"\b0x[0-9A-Fa-f]{6,8}\b")
_FAULT = re.compile(r"hard ?fault|bus ?fault|assert|panic|stack overflow|timeout", re.IGNORECASE)


def summarize(text: str) -> dict[str, Any]:
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    tags: dict[str, int] = {}
    problems: list[str] = []
    suspicious: list[str] = []
    for line in lines:
        found = [t.upper() for t in _TAG.findall(line)]
        for tag in found:
            tags[tag] = tags.get(tag, 0) + 1
        if any(t in ("FAIL", "ERROR") for t in found):
            problems.append(line.strip())
        elif _FAULT.search(line):
            suspicious.append(line.strip())
    addresses = sorted(set(_HEX.findall(text)))
    verdict = "fail" if problems else ("pass" if tags.get("PASS") else ("suspicious" if suspicious else "no verdict"))
    return {
        "line_count": len(lines), "tags": tags, "verdict": verdict,
        "problem_lines": problems[:50], "suspicious_lines": suspicious[:50],
        "terminal_prompt_seen": "fpga:>>" in text,
        "addresses": addresses[:32],
        "hint": "Resolve addresses with analysis_resolve_address." if addresses else None,
    }


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("analysis", "log_analyzer", READS_HARDWARE)
    def analysis_capture_uart(port: str | None = None, baud: int | None = None, duration_s: float = 5.0,
                              send: str | None = None, max_bytes: int = 65536) -> dict[str, Any]:
        """Capture the application's UART output for duration_s seconds (8N1, no flow control) and
        summarize it (tag counts, FAIL/ERROR lines, fault keywords, addresses, verdict).

        send: optional text written right after opening (e.g. "r" to start an example at the
        `fpga:>>` prompt). The port must not be held by a monitor or flash tool. Output printed
        before the port opens is missed; ask the user to press RESET (boot mode 000) during capture.
        Requires the server to run with --allow-hardware.
        """
        app.policy.require(Permission.HARDWARE, "analysis_capture_uart")
        board = app.target().profile.get("board", {})
        port = port or app.session.serial_port
        if not port:
            raise InvalidArgumentError("No serial port given.", "Use prog_list_serial_ports, then pass port.")
        baud = baud or app.session.monitor_baud or board.get("console", {}).get("baud") or 19200
        if not 1 <= max_bytes <= 1_000_000:
            raise InvalidArgumentError("max_bytes must be 1..1000000.")
        captured = uart.capture(port, baud, duration_s, send, max_bytes)
        app.session.serial_port, app.session.monitor_baud = captured["port"], baud
        return {**captured, "summary": summarize(captured["text"])}

    @registry.tool("analysis", "log_analyzer", READ_ONLY)
    def analysis_analyze_log(text: str) -> dict[str, Any]:
        """Summarize a firmware log pasted by the user or saved earlier: [INFO]/[PASS]/[FAIL]/...
        tag counts, failing lines, fault keywords (HardFault, assert, timeout), addresses to resolve
        and an overall verdict."""
        if len(text) > 1_000_000:
            raise InvalidArgumentError("Log text is limited to 1 MB.")
        return summarize(text)
