"""Install page: one page for GitHub Pages (static build) and for the Streamable HTTP transport,
which serves it at `/` with the server's own URL filled in.

The page data comes from the server itself: module catalog, tools, prompts, resources, knowledge
packs and the real output of a few read-only tool calls.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer

from .. import __version__
from ..adapters import knowledge_pack as packs

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from .app import NeonApp

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEFAULT_REPO = "QuocBuu/cdc_mcp"
NEON_MDF_REPO = "ftel-cdc/neon_mdf"

# (tool, arguments, title shown on the page). Read-only calls only.
DEMOS: list[tuple[str, dict[str, Any], str]] = [
    ("neon_list_modules", {"module": "programming"}, "Architecture: the Programming module and its tools"),
    ("knowledge_get_peripheral", {"peripheral": "UART0", "register": "LSR"}, "Look up the UART0 LSR register"),
    ("analysis_decode_register", {"value": "0x61", "peripheral": "UART0", "register": "LSR"},
     "Decode 0x61 read from UART0.LSR"),
    ("sdk_search_api", {"query": "uart transmit", "limit": 3}, "Find the C API that sends UART data"),
    ("sdk_resolve_dependencies", {"modules": ["adc"]}, "What using the ADC requires (Kconfig, CRM clock, include)"),
    ("analysis_decode_exception",
     {"stack_frame": ["0x01001001", "0x0", "0x0", "0x0", "0x0", "0x00020211", "0x0002013C", "0x01000000"],
      "exc_return": "0xFFFFFFF9", "handler_xpsr": "0x3"},
     "Analyze a HardFault from its stack frame (no ELF needed)"),
    ("prog_list_boot_modes", {}, "GT32U2086 boot modes"),
    ("knowledge_search", {"query": "boot mode 100 UART update", "limit": 3}, "Search the NEON-MDF documentation"),
]

MAX_ITEMS = 8
MAX_STRING = 600


def trim(value: Any) -> Any:
    """Shorten long lists/strings so each demo stays readable on the page."""
    if isinstance(value, dict):
        return {k: trim(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [trim(v) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"… {len(value) - MAX_ITEMS} more")
        return items
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + "…"
    return value


def _first_paragraph(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().split("\n\n")[0])


def project_repo() -> str:
    """owner/name of the GitHub repository, from the package's Repository URL."""
    try:
        for entry in metadata.metadata("neon-mcp").get_all("Project-URL") or []:
            match = re.search(r"github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?/?$", entry)
            if match:
                return match.group(1)
    except metadata.PackageNotFoundError:
        pass
    return DEFAULT_REPO


def pack_dirs(app: NeonApp) -> list[Path]:
    return [d for d in (app.settings.packs_dir, packs.BUNDLED_DIR) if d is not None]


def _version_key(version: str) -> list:
    return [int(x) if x.isdigit() else x for x in version.split(".")]


async def collect(server: MCPServer, app: NeonApp, *, strict: bool = False) -> dict[str, Any]:
    """Everything the page shows. `strict` raises when a demo call fails (static builds)."""
    def tool_kind(tool: Any) -> str:
        notes = tool.annotations
        if notes and notes.destructive_hint:
            return "hardware"
        if notes and notes.read_only_hint:
            return "read"
        return "write"

    tools = await server.list_tools()
    catalog = (await server.call_tool("neon_list_modules", {})).structured_content
    info = (await server.call_tool("sdk_get_info", {})).structured_content
    demos = []
    for tool, arguments, title in DEMOS:
        result = await server.call_tool(tool, arguments)
        if result.is_error:
            if strict:
                text = " ".join(getattr(c, "text", "") for c in result.content)
                raise RuntimeError(f"demo {tool} failed: {text}")
            continue
        demos.append({"tool": tool, "title": title, "arguments": arguments, "result": trim(result.structured_content)})
    pack_status = info["knowledge_pack"]
    found = sorted(packs.find_packs(pack_dirs(app)), key=lambda p: _version_key(p.version), reverse=True)
    git = app.sdk.git_info() or {}
    return {
        "catalog": catalog,
        "tools": {t.name: {"description": _first_paragraph(t.description), "kind": tool_kind(t),
                           "params": sorted((t.input_schema or {}).get("properties", {}))} for t in tools},
        "prompts": [{"name": p.name, "description": p.description, "arguments": [a.name for a in p.arguments or []]}
                    for p in await server.list_prompts()],
        "resources": [{"uri": str(r.uri), "description": _first_paragraph(r.description)}
                      for r in await server.list_resources()]
        + [{"uri": t.uri_template, "description": _first_paragraph(t.description)}
           for t in await server.list_resource_templates()],
        "demos": demos,
        "pack_status": pack_status,
        "packs": [{"name": p.name, "version": p.version, "contents": p.manifest.get("contents", {}),
                   "devices": [{k: v for k, v in info.items() if k in ("device", "vendor", "arch")}
                               for rel, info in p.manifest.get("contents", {}).items() if rel.startswith("devices/")],
                   "release_url": f"https://github.com/{NEON_MDF_REPO}/releases/tag/v{p.version}",
                   "status": pack_status["status"] if p.name == pack_status.get("pack") else None} for p in found],
        "neon_mdf_repo": NEON_MDF_REPO,
        "version": __version__,
        "repo": project_repo(),
        "install_ref": None,
        "commit": None,
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sdk": {"version": app.sdk.version, "ref": git.get("describe"), "commit": git.get("commit")},
        "server_url": None,
    }


def render(data: dict[str, Any], *, hide_paths: dict[str, str] | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    for path, label in (hide_paths or {}).items():
        payload = payload.replace(json.dumps(path)[1:-1], label)
    payload = payload.replace("</", "<\\/")  # keep the JSON inert inside <script>
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("__NEON_DATA__", payload).replace("__VERSION__", __version__)


def register_routes(server: MCPServer, app: NeonApp) -> None:
    """GET / (install page), /favicon.svg and /packs/... on the Streamable HTTP transport."""
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse

    cache: dict[str, Any] = {}

    @server.custom_route("/", methods=["GET"], include_in_schema=False)
    async def install_page(request: Request) -> Response:
        if "data" not in cache:
            cache["data"] = await collect(server, app)
        url = str(request.base_url).rstrip("/") + "/mcp"
        return HTMLResponse(render({**cache["data"], "server_url": url}))

    @server.custom_route("/favicon.svg", methods=["GET"], include_in_schema=False)
    async def favicon(request: Request) -> Response:
        return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")

    @server.custom_route("/packs/{path:path}", methods=["GET"], include_in_schema=False)
    async def pack_file(request: Request) -> Response:
        rel = request.path_params["path"]
        if rel == "index.json":
            return JSONResponse([p.summary() for p in packs.find_packs(pack_dirs(app))])
        for base in pack_dirs(app):
            root = base.resolve()
            candidate = (root / rel).resolve()
            if candidate.is_relative_to(root) and candidate.suffix == ".json" and candidate.is_file():
                return FileResponse(candidate, media_type="application/json")
        return JSONResponse({"error": "not found"}, status_code=404)
