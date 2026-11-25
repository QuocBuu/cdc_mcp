"""Tool Registry: the module → submodule → tool catalog of NEON MCP.

Every MCP tool is registered through `ToolRegistry.tool(module, submodule)`, so the
architecture (10 modules and their submodules, implemented or planned) is explicit in
code, attached to each tool as `_meta`, and queryable with the `neon_list_modules` tool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

Status = Literal["implemented", "planned"]
F = TypeVar("F", bound=Callable[..., Any])

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES_FILES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                               open_world_hint=False)
TOUCHES_HARDWARE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                                   open_world_hint=True)
READS_HARDWARE = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@dataclass
class Submodule:
    name: str
    title: str
    description: str
    status: Status = "implemented"
    source: str | None = None          # file implementing it, relative to src/neon_mcp
    tools: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {"name": self.name, "title": self.title, "description": self.description,
                "status": self.status, "source": self.source, "tools": list(self.tools)}
        if self.prompts:
            data["prompts"] = list(self.prompts)
        if self.resources:
            data["resources"] = list(self.resources)
        return data


@dataclass
class Module:
    number: int
    id: str
    title: str
    description: str
    submodules: list[Submodule]
    kind: Literal["functional", "infrastructure"] = "functional"

    def submodule(self, name: str) -> Submodule:
        for sub in self.submodules:
            if sub.name == name:
                return sub
        raise KeyError(f"Module {self.id} has no submodule {name}")

    def to_dict(self) -> dict[str, Any]:
        implemented = sum(1 for s in self.submodules if s.status == "implemented")
        return {"number": f"{self.number:02d}", "id": self.id, "title": self.title, "kind": self.kind,
                "description": self.description,
                "submodules_implemented": f"{implemented}/{len(self.submodules)}",
                "tools": [t for s in self.submodules for t in s.tools],
                "submodules": [s.to_dict() for s in self.submodules]}


class ToolRegistry:
    def __init__(self, mcp: MCPServer) -> None:
        self.mcp = mcp
        self.modules: dict[str, Module] = {}

    def add_module(self, module: Module) -> None:
        self.modules[module.id] = module

    def tool(self, module: str, submodule: str, annotations: ToolAnnotations) -> Callable[[F], F]:
        """Register an MCP tool and record which module/submodule owns it."""
        sub = self.modules[module].submodule(submodule)
        if sub.status != "implemented":
            raise ValueError(f"{module}/{submodule} is planned; implement it before adding tools")

        def decorator(fn: F) -> F:
            self.mcp.add_tool(fn, annotations=annotations,
                              meta={"neon-mcp/module": module, "neon-mcp/submodule": submodule})
            sub.tools.append(fn.__name__)
            return fn

        return decorator

    def prompt(self, name: str, description: str) -> Callable[[F], F]:
        """Register an MCP prompt under the Prompt Manager submodule."""
        sub = self.modules["core"].submodule("prompt_manager")

        def decorator(fn: F) -> F:
            self.mcp.prompt(name=name, description=description)(fn)
            sub.prompts.append(name)
            return fn

        return decorator

    def resource(self, uri: str, **kwargs: Any) -> Callable[[F], F]:
        """Register an MCP resource under the Resource Registry submodule."""
        sub = self.modules["core"].submodule("resource_registry")

        def decorator(fn: F) -> F:
            self.mcp.resource(uri, **kwargs)(fn)
            sub.resources.append(uri)
            return fn

        return decorator

    def catalog(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in sorted(self.modules.values(), key=lambda m: m.number)]

    def owner_of(self, tool: str) -> tuple[str, str] | None:
        for module in self.modules.values():
            for sub in module.submodules:
                if tool in sub.tools:
                    return module.id, sub.name
        return None


def register(registry: ToolRegistry) -> None:
    @registry.tool("core", "tool_registry", READ_ONLY)
    def neon_list_modules(module: str | None = None) -> dict[str, Any]:
        """NEON MCP architecture: the 10 modules, their submodules (implemented or planned) and
        the tools each submodule provides. Use it to find the right tool for a task."""
        catalog = registry.catalog()
        if module:
            catalog = [m for m in catalog if m["id"] == module.lower()]
        subs = [s for m in catalog for s in m["submodules"]]
        return {"modules": catalog,
                "tool_count": sum(len(m["tools"]) for m in catalog),
                "submodules_implemented": sum(1 for s in subs if s["status"] == "implemented"),
                "submodules_planned": sum(1 for s in subs if s["status"] == "planned")}
