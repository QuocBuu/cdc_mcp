"""01 MCP Core: communication between the AI agent and NEON MCP."""

from .tools import Module, Submodule

MODULE = Module(
    number=1, id="core", title="MCP Core", kind="infrastructure",
    description="MCP server lifecycle, tool/resource/prompt registries, sessions and transports.",
    submodules=[
        Submodule("server", "MCP Server", "Builds the server and assembles every module.", source="core/server.py"),
        Submodule("tool_registry", "Tool Registry",
                  "Registers tools under module/submodule and publishes the catalog.", source="core/tools.py"),
        Submodule("resource_registry", "Resource Registry",
                  "neon:// resources with SDK, documentation and device data.", source="core/resources.py"),
        Submodule("prompt_manager", "Prompt Manager",
                  "Workflow prompts: new peripheral app, firmware review, HardFault debugging.",
                  source="core/prompts.py"),
        Submodule("session_manager", "Session Manager",
                  "Per-connection defaults (target, app, serial port, baud).", source="core/session.py"),
        Submodule("transport", "Transport", "stdio (default) and Streamable HTTP.", source="core/transport.py"),
        Submodule("install_page", "Install Page",
                  "Install guide: supported releases and chips, client setup, example requests; at / and on GitHub Pages.",
                  source="core/web.py"),
    ],
)
