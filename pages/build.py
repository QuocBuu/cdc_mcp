"""Build the NEON MCP install page (static site for GitHub Pages).

The page data comes from a live in-process NEON MCP server: the module catalog, tool
descriptions and annotations, prompts, resources, and real outputs of a few read-only tool
calls against the NEON-MDF checkout given with --sdk.

    python pages/build.py --sdk ../neon_mdf --out _site
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client

from neon_mcp import __version__
from neon_mcp.adapters import knowledge_pack as packs
from neon_mcp.core.app import NeonApp
from neon_mcp.core.server import create_server
from neon_mcp.system.config import Settings

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# (tool, arguments, title shown on the page). Read-only calls only: the build has no board.
DEMOS: list[tuple[str, dict[str, Any], str]] = [
    ("neon_list_modules", {"module": "programming"}, "Kiến trúc: module Programming và các tool của nó"),
    ("knowledge_get_peripheral", {"peripheral": "UART0", "register": "LSR"}, "Tra register LSR của UART0"),
    ("analysis_decode_register", {"value": "0x61", "peripheral": "UART0", "register": "LSR"},
     "Giải mã giá trị 0x61 của UART0.LSR"),
    ("sdk_search_api", {"query": "uart transmit", "limit": 3}, "Tìm C API để gửi dữ liệu UART"),
    ("sdk_resolve_dependencies", {"modules": ["adc"]}, "Cần gì để dùng ADC (Kconfig, clock CRM, include)"),
    ("analysis_decode_exception",
     {"stack_frame": ["0x01001001", "0x0", "0x0", "0x0", "0x0", "0x00020211", "0x0002013C", "0x01000000"],
      "exc_return": "0xFFFFFFF9", "handler_xpsr": "0x3"},
     "Phân tích HardFault từ stack frame (không cần ELF)"),
    ("prog_list_boot_modes", {}, "Các boot mode của GT32U2086"),
    ("knowledge_search", {"query": "boot mode 100 UART update", "limit": 3}, "Tìm trong tài liệu NEON-MDF"),
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
            items.append(f"… còn {len(value) - MAX_ITEMS} mục")
        return items
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + "…"
    return value


def first_paragraph(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().split("\n\n")[0])


def git(*args: str, cwd: Path) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def detect_repo() -> str | None:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = git("remote", "get-url", "origin", cwd=REPO) or ""
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return match.group(1) if match else None


async def collect(app: NeonApp) -> dict[str, Any]:
    async with Client(create_server(app)) as client:
        tools = (await client.list_tools()).tools
        catalog = (await client.call_tool("neon_list_modules", {})).structured_content
        prompts = (await client.list_prompts()).prompts
        resources = (await client.list_resources()).resources
        templates = (await client.list_resource_templates()).resource_templates
        info = (await client.call_tool("sdk_get_info", {})).structured_content
        demos = []
        for tool, arguments, title in DEMOS:
            result = await client.call_tool(tool, arguments)
            if result.is_error:
                text = " ".join(getattr(c, "text", "") for c in result.content)
                raise SystemExit(f"demo {tool} failed: {text}")
            demos.append({"tool": tool, "title": title, "arguments": arguments,
                          "result": trim(result.structured_content)})

    def kind(tool: Any) -> str:
        notes = tool.annotations
        if notes and notes.destructive_hint:
            return "hardware"
        if notes and notes.read_only_hint:
            return "read"
        return "write"

    return {
        "catalog": catalog,
        "tools": {t.name: {"description": first_paragraph(t.description), "kind": kind(t),
                           "params": sorted((t.input_schema or {}).get("properties", {}))} for t in tools},
        "prompts": [{"name": p.name, "description": p.description,
                     "arguments": [a.name for a in p.arguments or []]} for p in prompts],
        "resources": [{"uri": str(r.uri), "description": first_paragraph(r.description)} for r in resources]
        + [{"uri": t.uri_template, "description": first_paragraph(t.description)} for t in templates],
        "demos": demos,
        "pack_status": info["knowledge_pack"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdk", type=Path, required=True, help="NEON-MDF checkout used for the demos")
    parser.add_argument("--sdk-ref", help="NEON-MDF tag/branch shown on the page (default: git describe)")
    parser.add_argument("--out", type=Path, default=REPO / "_site")
    parser.add_argument("--repo", default=detect_repo(), help="owner/name on GitHub (default: origin remote)")
    parser.add_argument("--install-ref", help="git ref pinned in install commands (default: default branch)")
    args = parser.parse_args()
    if not args.repo:
        parser.error("cannot detect the GitHub repository; pass --repo owner/name")

    sdk = args.sdk.resolve()
    workspace = Path(tempfile.mkdtemp(prefix="neon-mcp-pages-"))
    app = NeonApp(Settings(sdk_path=sdk, workspace_roots=[workspace]).resolve())
    try:
        data = asyncio.run(collect(app))
    finally:
        app.close()
        shutil.rmtree(workspace, ignore_errors=True)

    sdk_git = app.sdk.git_info() or {}
    bundled = packs.find_packs([packs.BUNDLED_DIR])
    data.update({
        "packs": [{"name": p.name, "version": p.version, "contents": p.manifest.get("contents", {}),
                   "status": data["pack_status"]["status"] if p.name == data["pack_status"].get("pack") else None}
                  for p in sorted(bundled, key=lambda p: [int(x) if x.isdigit() else x for x in p.version.split(".")],
                                  reverse=True)],
        "version": __version__,
        "repo": args.repo,
        "install_ref": args.install_ref,
        "commit": (os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD", cwd=REPO) or "")[:7],
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sdk": {"version": app.sdk.version, "ref": args.sdk_ref or sdk_git.get("describe"),
                "commit": sdk_git.get("commit")},
    })

    # Absolute build-machine paths mean nothing to readers.
    payload = json.dumps(data, ensure_ascii=False)
    for path, label in ((str(sdk), "<NEON_MDF>"), (str(workspace.resolve()), "<WORKSPACE>")):
        payload = payload.replace(json.dumps(path)[1:-1], label)
    payload = payload.replace("</", "<\\/")  # keep the JSON inert inside <script>

    template = (HERE / "template.html").read_text(encoding="utf-8")
    html = template.replace("__NEON_DATA__", payload).replace("__VERSION__", __version__)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(HERE / "favicon.svg", args.out / "favicon.svg")
    # Knowledge packs at packs/<name>/..., plus packs/index.json for tools and scripts.
    shutil.rmtree(args.out / "packs", ignore_errors=True)
    for pack in bundled:
        shutil.copytree(pack.path, args.out / "packs" / pack.name)
    (args.out / "packs" / "index.json").write_text(packs.dumps([p.summary() for p in bundled]), encoding="utf-8")
    (args.out / ".nojekyll").write_text("")
    print(f"wrote {args.out / 'index.html'} ({len(html) // 1024} KiB, {len(data['tools'])} tools, "
          f"{len(data['demos'])} demos)")


if __name__ == "__main__":
    main()
