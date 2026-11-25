"""Shared fixtures. Tests run against a real NEON-MDF checkout.

Set NEON_MCP_TEST_SDK to the checkout; by default ../neon_mdf next to this repository is used.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from neon_mcp.core.app import NeonApp
from neon_mcp.core.server import create_server
from neon_mcp.system.config import Settings

REPO = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("NEON_MCP_TEST_SDK", REPO.parent / "neon_mdf")).resolve()

if not (SDK / "neon-mdf" / "tools" / "neon_mdf.py").is_file():
    pytest.skip(f"NEON-MDF checkout not found at {SDK} (set NEON_MCP_TEST_SDK)", allow_module_level=True)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def sdk_root() -> Path:
    return SDK


def make_app(tmp_path: Path, **overrides: Any) -> NeonApp:
    settings = Settings(sdk_path=SDK, workspace_roots=[tmp_path], **overrides)
    return NeonApp(settings)


@pytest.fixture
def app(tmp_path: Path) -> NeonApp:
    return make_app(tmp_path)


class ToolCaller:
    def __init__(self, client: Client) -> None:
        self.client = client

    async def __call__(self, tool: str, /, **arguments: Any) -> dict:
        result = await self.client.call_tool(tool, arguments)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise ToolFailed(text)
        return result.structured_content

    async def error(self, tool: str, /, **arguments: Any) -> str:
        result = await self.client.call_tool(tool, arguments)
        assert result.is_error, f"{tool} unexpectedly succeeded: {result.structured_content}"
        return " ".join(getattr(c, "text", "") for c in result.content)


class ToolFailed(AssertionError):
    pass


@pytest.fixture
async def call(app: NeonApp):
    async with Client(create_server(app)) as client:
        yield ToolCaller(client)
