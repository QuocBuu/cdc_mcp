"""Install page served by the Streamable HTTP transport."""

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

        grouped = [t for c in data["capabilities"] for t in c["tools"]]
        assert sorted(grouped) == data["tools"], "every tool belongs to exactly one capability group"
        assert all(c["id"] != "other" for c in data["capabilities"]), "give new tools a group in core/web.py"

        bundled = sorted(p.version for p in packs.find_packs([packs.BUNDLED_DIR]))
        assert sorted(r["version"] for r in data["releases"]) == bundled
        for release in data["releases"]:
            assert release["devices"] and release["release_url"].endswith(f"/tag/v{release['version']}")

        assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
