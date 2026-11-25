"""Resource Registry: read-only SDK data an MCP client can attach as context (neon://...)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from ..modules.knowledge.documentation import get_index
from ..system.errors import NeonError
from .tools import ToolRegistry

if TYPE_CHECKING:
    from .app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.resource("neon://sdk/info", name="sdk-info", mime_type="application/json",
                       description="NEON-MDF SDK version, location, revision, presets and targets.")
    def sdk_info() -> str:
        return json.dumps({
            "sdk_version": app.sdk.version, "sdk_root": str(app.sdk.root), "git": app.sdk.git_info(),
            "presets": app.sdk.presets, "targets": [t.summary() for t in app.targets.all()],
        }, indent=2)

    @registry.resource("neon://architecture", name="architecture", mime_type="application/json",
                       description="NEON MCP modules, submodules (implemented/planned) and their tools.")
    def architecture() -> str:
        return json.dumps(registry.catalog(), indent=2)

    @registry.resource("neon://docs/index", name="docs-index", mime_type="application/json",
                       description="Documentation files available as neon://guide/{name} and neon://examples/{name}.")
    def docs_index() -> str:
        return json.dumps([{"path": d.path, "title": d.title, "category": d.category}
                           for d in get_index(app).documents()], indent=2)

    @registry.resource("neon://guide/{name}", name="guide", mime_type="text/markdown",
                       description="A NEON-MDF guide by file stem, e.g. neon://guide/Setup or neon://guide/GT32U2086.")
    def guide(name: str) -> str:
        path = app.sdk.guide_dir / f"{name.removesuffix('.md')}.md"
        if not path.is_file():
            raise ResourceNotFoundError(f"No guide '{name}'.")
        return path.read_text(encoding="utf-8")

    @registry.resource("neon://examples/{name}", name="example-readme", mime_type="text/markdown",
                       description="README of an SDK example, e.g. neon://examples/SPI_W5500.")
    def example(name: str) -> str:
        path = app.sdk.examples_dir / name / "README.md"
        if not path.is_file():
            raise ResourceNotFoundError(f"No example README for '{name}'.")
        return path.read_text(encoding="utf-8")

    @registry.resource("neon://device/{target}", name="device", mime_type="application/json",
                       description="Device summary (CPU, memory, profiles, peripherals, IRQs) for a target.")
    def device(target: str) -> str:
        try:
            return json.dumps(app.target(target).device().summary(), indent=2)
        except NeonError as exc:
            raise ResourceNotFoundError(str(exc)) from exc
