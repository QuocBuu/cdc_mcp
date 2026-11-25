"""MCP Server: assemble core services, infrastructure and the six functional modules."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .. import __version__, adapters, system, targets
from ..modules import analysis, debug, development, knowledge, programming, sdk
from ..modules.sdk import knowledge_pack
from ..targets import registry as target_registry
from . import MODULE as CORE_MODULE
from . import prompts, resources, session, tools, web
from .app import NeonApp
from .tools import ToolRegistry

FUNCTIONAL_MODULES = (knowledge, sdk, development, debug, programming, analysis)

INSTRUCTIONS = """\
NEON MCP gives you the NEON-MDF firmware SDK: documentation, device/register data, C API,
examples, dependencies, project creation, sdkconfig, CMake builds, image checks, UART programming,
GDB debugging and firmware analysis. neon_list_modules shows every module, submodule and tool.

Typical flow: session_get_context → session_set_context(app_dir/target) → knowledge_search /
sdk_search_api / sdk_find_examples / sdk_resolve_dependencies → dev_create_project or edit sources →
dev_build → prog_verify_image → prog_flash_uart → analysis_capture_uart; for crashes
analysis_decode_exception and the debug_* tools.

Ground every claim in tool results (cite file:line). Hardware tools (prog_flash_uart, debug_*,
analysis_capture_uart) need --allow-hardware and often a physical action by the user (boot mode 100
and RESET for programming); say so before calling them. A successful build is not hardware validation.
Rules for GT32U2086 firmware are in knowledge_get_device ("rules"): SRAM is aligned-32-bit-word only,
timeout_polls are poll counts (not ms), BootROM starts the app with interrupts masked (__enable_irq()
is required), and SystemCoreClock must match the board clock. The SDK's OpenOCD config for GT32U2086
is a placeholder: debug_connect needs a board-verified config or a running GDB server.
"""


def create_server(app: NeonApp) -> MCPServer:
    mcp = MCPServer(name="neon-mcp", title="NEON MCP", version=__version__, instructions=INSTRUCTIONS,
                    website_url="https://github.com/ftel-cdc/neon_mdf")
    registry = ToolRegistry(mcp)
    for spec in (CORE_MODULE, *(m.MODULE for m in FUNCTIONAL_MODULES), targets.MODULE, adapters.MODULE,
                 system.MODULE):
        registry.add_module(spec)

    tools.register(registry)
    session.register(registry, app)
    resources.register(registry, app)
    prompts.register(registry, app)
    target_registry.register(registry, app)
    for module in FUNCTIONAL_MODULES:
        module.register(registry, app)
    knowledge_pack.activate(app)  # serve the release's pre-generated data when the checkout matches it
    web.register_routes(mcp, app)  # install page at / when running over Streamable HTTP
    app.registry = registry
    return mcp
