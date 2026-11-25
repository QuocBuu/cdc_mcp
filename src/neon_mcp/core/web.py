"""Install page: one page for GitHub Pages (static build) and for the Streamable HTTP transport,
which serves it at `/` with the server's own URL filled in.

It shows what NEON MCP is, the NEON-MDF releases and chips it supports, how to add it to each
client, and what users can ask the agent to do.
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

# What users can ask the agent to do, grouped by task. Every tool belongs to exactly one group
# (tests/test_web.py checks it); groups with "card": False only appear in the tool reference.
CAPABILITIES: list[dict[str, Any]] = [
    {"id": "chip", "title": "Look up the chip", "access": "read",
     "summary": "Documentation, memory map, boot modes, peripherals, registers and bit fields, and what a raw register value means.",
     "examples": ["What does UART0.LSR = 0x61 mean?", "Explain boot mode 100 on the GT32U2086.",
                  "Which registers configure SPI1?"],
     "tools": ["knowledge_search", "knowledge_list_documents", "knowledge_read_document", "knowledge_get_device",
               "knowledge_get_peripheral", "analysis_decode_register", "target_list"]},
    {"id": "sdk", "title": "Use the SDK", "access": "read",
     "summary": "The C API with its documentation, driver sources, examples, and what a feature needs: Kconfig, clocks, includes.",
     "examples": ["How do I send data over UART with NEON-MDF?", "Find an example that uses SPI.",
                  "What do I need to enable to use the ADC?"],
     "tools": ["sdk_get_info", "sdk_list_components", "sdk_search_api", "sdk_search_source", "sdk_read_source",
               "sdk_find_examples", "sdk_resolve_dependencies"]},
    {"id": "build", "title": "Create and build projects", "access": "write",
     "summary": "New projects from the SDK templates, sdkconfig options and CMake builds, with errors at file:line and memory usage.",
     "examples": ["Create a project that toggles a GPIO, then build it.", "Enable the I2C driver and rebuild.",
                  "Is my toolchain ready to build?"],
     "tools": ["dev_check_environment", "dev_create_project", "dev_get_config", "dev_set_config",
               "dev_generate_device_files", "dev_configure", "dev_build"]},
    {"id": "flash", "title": "Flash and run on the board", "access": "hardware",
     "summary": "Check the image, program it over UART, then capture and summarize the board's log.",
     "examples": ["Flash my app over /dev/ttyUSB0 and show the log.", "Is this image valid for boot mode 100?"],
     "tools": ["prog_inspect_image", "prog_verify_image", "prog_list_boot_modes", "prog_list_serial_ports",
               "prog_flash_uart", "analysis_capture_uart", "analysis_analyze_log"]},
    {"id": "debug", "title": "Debug on hardware", "access": "hardware",
     "summary": "A GDB session through OpenOCD or a running GDB server: breakpoints, stepping, registers, memory, peripherals, backtraces.",
     "examples": ["Break in main and show the UART0 registers.", "Step through spi_init and show the local variables."],
     "tools": ["debug_connect", "debug_disconnect", "debug_control", "debug_read_registers", "debug_read_memory",
               "debug_write_memory", "debug_read_peripheral", "debug_breakpoint", "debug_backtrace"]},
    {"id": "analyze", "title": "Analyze crashes and binaries", "access": "read",
     "summary": "Decode a HardFault down to the faulting instruction and source line; flash/RAM usage and symbols of the ELF.",
     "examples": ["My firmware hit a HardFault, here is the stack frame: …", "Which function is at 0x00020A3C?",
                  "How much flash and RAM does my app use?"],
     "tools": ["analysis_decode_exception", "analysis_elf_summary", "analysis_resolve_address"]},
    {"id": "session", "title": "Session and server", "access": "read", "card": False,
     "summary": "Defaults shared by the other tools (target, application, serial port) and the server's own catalog.",
     "examples": [], "tools": ["session_get_context", "session_set_context", "neon_list_modules"]},
]


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


def _version_key(version: str) -> list:
    return [int(x) if x.isdigit() else x for x in version.split(".")]


def releases(app: NeonApp) -> list[dict[str, Any]]:
    """NEON-MDF releases this NEON MCP has data for, newest first, with their chips."""
    dirs = [d for d in (app.settings.packs_dir, packs.BUNDLED_DIR) if d is not None]
    found = sorted(packs.find_packs(dirs), key=lambda p: _version_key(p.version), reverse=True)
    return [{"version": p.version,
             "devices": [{k: v for k, v in info.items() if k in ("device", "vendor", "arch")}
                         for rel, info in p.manifest.get("contents", {}).items() if rel.startswith("devices/")],
             "release_url": f"https://github.com/{NEON_MDF_REPO}/releases/tag/v{p.version}"} for p in found]


async def collect(server: MCPServer, app: NeonApp) -> dict[str, Any]:
    """Everything the page shows."""
    names = {t.name for t in await server.list_tools()}
    capabilities = [{**c, "tools": [t for t in c["tools"] if t in names]} for c in CAPABILITIES]
    unlisted = sorted(names - {t for c in CAPABILITIES for t in c["tools"]})
    if unlisted:  # keep the grouping complete; tests require every tool to have a group
        capabilities.append({"id": "other", "title": "Other tools", "access": "read", "card": False,
                             "summary": "", "examples": [], "tools": unlisted})
    git = app.sdk.git_info() or {}
    return {
        "capabilities": capabilities,
        "tools": sorted(names),
        "releases": releases(app),
        "version": __version__,
        "repo": project_repo(),
        "install_ref": None,
        "commit": None,
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sdk": {"version": app.sdk.version, "ref": git.get("describe")},
        "neon_mdf_repo": NEON_MDF_REPO,
        "server_url": None,
    }


def render(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # keep the JSON inert inside <script>
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("__NEON_DATA__", payload).replace("__VERSION__", __version__)


def register_routes(server: MCPServer, app: NeonApp) -> None:
    """GET / (install page) and /favicon.svg on the Streamable HTTP transport."""
    from starlette.responses import FileResponse, HTMLResponse

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
