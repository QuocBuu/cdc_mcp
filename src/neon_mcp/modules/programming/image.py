"""Image submodule: locate boot images and decode their BootROM header with the SDK image tool."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters import cmake
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import NotFoundError
from ...system.process import run
from ..development import build as build_flow

if TYPE_CHECKING:
    from ...core.app import NeonApp

_INFO_LINE = re.compile(r"^(?P<key>[a-z_]+)\s+0x(?P<value>[0-9a-fA-F]+)$")


def resolve_images(app: NeonApp, image_path: str | None, app_dir: str | None,
                   build_dir: str | None) -> tuple[list[Path], Path | None]:
    """Images to examine: an explicit file, or every *_image*.bin of the app's build directory."""
    if image_path:
        candidate = Path(image_path)
        directory = app.app_dir(app_dir) if app_dir else None
        if not candidate.is_absolute() and directory is not None:
            candidate = directory / candidate
        return [app.workspace.resolve(candidate, kind="file")], directory
    directory = app.app_dir(app_dir)
    lay = build_flow.build_layout(app, app.target(), directory, build_dir)
    images = [Path(p) for p in cmake.artifacts(lay.build_dir)["boot_image"]]
    if not images:
        raise NotFoundError(f"No boot image in {lay.build_dir}.", "Build the application first (dev_build).")
    return images, directory


def header_info(app: NeonApp, image: Path, python: str) -> dict[str, Any]:
    result = run([python, str(app.sdk.tool("gt32u2086_image.py")), "info", str(image)], app.sdk.root, timeout_s=60)
    fields: dict[str, str] = {}
    digest = None
    problems = []
    for line in result.output.splitlines():
        line = line.strip()
        match = _INFO_LINE.match(line)
        if match:
            fields[match.group("key")] = "0x" + match.group("value").upper()
        elif line.startswith("image_digest"):
            digest = line.split()[-1]
        elif line.startswith("ERROR:"):
            problems.append(line[6:].strip())
    if not result.ok and not problems:
        problems.append(result.output.strip()[-500:])
    return {"header": fields, "digest": digest, "problems": problems, "ok": result.ok and not problems}


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("programming", "image", READ_ONLY)
    def prog_inspect_image(image_path: str | None = None, app_dir: str | None = None,
                           build_dir: str | None = None) -> dict[str, Any]:
        """Decode BootROM image headers with the SDK's `gt32u2086_image.py info`: magic, version,
        payload size, Flash base (0x00020000 normal / 0x30000000 XIP), entry point, app version,
        CRCs, signature size and digest. Works on one image or every image of an app build."""
        images, directory = resolve_images(app, image_path, app_dir, build_dir)
        python = app.python(directory)
        return {"images": [{"image": str(i), "size_bytes": i.stat().st_size, **header_info(app, i, python)}
                           for i in images]}
