"""Verify submodule: validate an image before programming (no hardware access)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import NeonError
from ...system.process import run
from .image import header_info, resolve_images

if TYPE_CHECKING:
    from ...core.app import NeonApp

_FIELD = re.compile(r"^(Image profile|Application version|Image base)\s*:\s*(.+)$")


def verify(app: NeonApp, image: Path, python: str, expected_profile: str | None = None) -> dict[str, Any]:
    """Run `gt32u2086_flash.py --check-only` and compare the image with the device profile."""
    command = [python, str(app.sdk.tool("gt32u2086_flash.py")), "--image", str(image), "--check-only"]
    if expected_profile:
        command += ["--profile", expected_profile]
    result = run(command, app.sdk.root, timeout_s=60)
    fields = {}
    for line in result.output.splitlines():
        match = _FIELD.match(line.strip())
        if match:
            fields[match.group(1).lower().replace(" ", "_")] = match.group(2).strip()
    checks = [{"check": "SDK flash tool --check-only (header, size, CRC, vectors)", "ok": result.ok}]
    header = header_info(app, image, python)
    try:
        device = app.target().device()
        profile = fields.get("image_profile") or ("xip" if header["header"].get("flash_addr") == "0x30000000"
                                                  else "normal")
        start, capacity = device.application_range(profile, "flash")
        payload = int(header["header"].get("payload_size", "0x0"), 16)
        checks.append({"check": f"payload fits the {profile} application area ({capacity} bytes from 0x{start:08X})",
                       "ok": 0 < payload <= capacity, "detail": f"payload {payload} bytes"})
        checks.append({"check": "UART programming possible (ROMCODE USART update writes internal Flash only)",
                       "ok": profile == "normal", "informational": True})
    except NeonError as exc:
        checks.append({"check": "device profile comparison", "ok": False, "detail": str(exc)})
    blocking = [c for c in checks if not c["ok"] and not c.get("informational")]
    return {"image": str(image), "valid": not blocking and header["ok"], **fields,
            "signed": int(header["header"].get("signature_size", "0x0"), 16) > 0,
            "checks": checks, "problems": header["problems"],
            "tool_output": result.output.strip()[-2000:]}


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("programming", "verify", READ_ONLY)
    def prog_verify_image(image_path: str | None = None, app_dir: str | None = None,
                          build_dir: str | None = None, expected_profile: str | None = None) -> dict[str, Any]:
        """Validate boot images before programming, without opening a serial port: runs the SDK's
        `gt32u2086_flash.py --check-only` (header, size, CRC, vector table), checks the payload fits
        the profile's application area, and reports whether UART programming can write it.
        A valid image does not prove the board's NVR policy will accept it (secure boot)."""
        images, directory = resolve_images(app, image_path, app_dir, build_dir)
        python = app.python(directory)
        return {"images": [verify(app, i, python, expected_profile) for i in images]}
