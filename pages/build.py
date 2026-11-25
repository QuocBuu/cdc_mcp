"""Build the NEON MCP install page as a static site for GitHub Pages.

The page is the one the Streamable HTTP transport serves at `/` (src/neon_mcp/web/index.html),
filled with data from a live in-process server running against the NEON-MDF checkout in --sdk.

    python pages/build.py --sdk ../neon_mdf --out _site
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from neon_mcp.adapters import knowledge_pack as packs
from neon_mcp.core import web
from neon_mcp.core.app import NeonApp
from neon_mcp.core.server import create_server
from neon_mcp.system.config import Settings

REPO = Path(__file__).resolve().parent.parent


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def detect_repo() -> str | None:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", git("remote", "get-url", "origin") or "")
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdk", type=Path, required=True, help="NEON-MDF checkout used for the demos")
    parser.add_argument("--sdk-ref", help="NEON-MDF tag/branch shown on the page (default: git describe)")
    parser.add_argument("--out", type=Path, default=REPO / "_site")
    parser.add_argument("--repo", default=detect_repo(), help="owner/name on GitHub (default: origin remote)")
    parser.add_argument("--install-ref", help="git ref pinned in install commands (default: default branch)")
    args = parser.parse_args()

    sdk = args.sdk.resolve()
    workspace = Path(tempfile.mkdtemp(prefix="neon-mcp-pages-"))
    app = NeonApp(Settings(sdk_path=sdk, workspace_roots=[workspace]))
    try:
        data = asyncio.run(web.collect(create_server(app), app, strict=True))
    finally:
        app.close()
        shutil.rmtree(workspace, ignore_errors=True)

    data.update({"repo": args.repo or data["repo"], "install_ref": args.install_ref,
                 "commit": (os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD") or "")[:7] or None})
    if args.sdk_ref:
        data["sdk"]["ref"] = args.sdk_ref
    # Build-machine paths mean nothing to readers.
    html = web.render(data, hide_paths={str(sdk): "<NEON_MDF>", str(workspace.resolve()): "<WORKSPACE>"})

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(html, encoding="utf-8")
    shutil.copy(web.WEB_DIR / "favicon.svg", args.out / "favicon.svg")
    (args.out / ".nojekyll").write_text("")
    # Knowledge packs at packs/<name>/..., plus packs/index.json for tools and scripts.
    shutil.rmtree(args.out / "packs", ignore_errors=True)
    bundled = packs.find_packs([packs.BUNDLED_DIR])
    for pack in bundled:
        shutil.copytree(pack.path, args.out / "packs" / pack.name)
    (args.out / "packs" / "index.json").write_text(packs.dumps([p.summary() for p in bundled]), encoding="utf-8")
    print(f"wrote {args.out / 'index.html'} ({len(html) // 1024} KiB, {len(data['tools'])} tools, "
          f"{len(data['demos'])} demos, {len(bundled)} packs)")


if __name__ == "__main__":
    main()
