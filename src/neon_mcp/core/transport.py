"""Transport: stdio for local agents (default), Streamable HTTP for remote clients."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer

TransportName = Literal["stdio", "streamable-http"]


def run(server: MCPServer, transport: TransportName, host: str = "127.0.0.1", port: int = 8000) -> None:
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=host, port=port)
