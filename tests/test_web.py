"""Install page and pack files served by the Streamable HTTP transport."""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.testclient import TestClient

from neon_mcp.adapters import knowledge_pack as packs
from neon_mcp.core.server import create_server

from .conftest import make_app


def _page_data(html: str) -> dict:
    match = re.search(r'<script id="neon-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    return json.loads(match.group(1))


def test_install_page_over_http(tmp_path: Path):
    server = create_server(make_app(tmp_path))
    with TestClient(server.streamable_http_app()) as client:
        page = client.get("/")
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        data = _page_data(page.text)
        assert data["server_url"] == "http://testserver/mcp"  # the page connects clients to this server
        assert data["catalog"]["tool_count"] == len(data["tools"]) > 0
        assert data["demos"] and data["pack_status"]["status"]

        assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
        listed = client.get("/packs/index.json").json()
        assert [p["pack"] for p in listed] == [p.name for p in packs.find_packs([packs.BUNDLED_DIR])]
        for pack in listed:
            assert client.get(f"/packs/{pack['pack']}/manifest.json").json()["name"] == pack["pack"]
        assert client.get("/packs/%2E%2E/%2E%2E/pyproject.toml").status_code == 404
        assert client.get("/packs/nope/manifest.json").status_code == 404
