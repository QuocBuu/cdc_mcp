"""Capability vocabulary used by target profiles (`targets/<name>/target.yaml`)."""

from __future__ import annotations

CAPABILITIES: dict[str, str] = {
    "build": "CMake/Ninja build through the SDK preset",
    "menuconfig": "Kconfig/sdkconfig configuration",
    "secure_boot": "Signed images (-DNEON_MDF_SECURE_BOOT=ON)",
    "uart_flash": "Programming internal Flash through the ROMCODE UART update",
    "serial_monitor": "Reading the application UART",
    "qspi_programming": "Writing external QSPI Flash (boot modes 101/111)",
    "jtag_debug": "On-chip debugging with an SDK-provided, verified OpenOCD configuration",
    "exception_decode": "Decoding fault stack frames for the CPU architecture",
}

UNAVAILABLE_NOTES: dict[str, str] = {
    "jtag_debug": "The SDK's OpenOCD configuration for this target is still a placeholder; "
                  "pass a board-verified openocd_config or a running gdb_server to debug_connect.",
    "qspi_programming": "The SDK has no loader for writing external QSPI Flash yet.",
}


def describe(capabilities: dict[str, bool]) -> list[dict]:
    return [{"name": name, "supported": bool(capabilities.get(name, False)), "description": text,
             "note": None if capabilities.get(name) else UNAVAILABLE_NOTES.get(name)}
            for name, text in CAPABILITIES.items()]
