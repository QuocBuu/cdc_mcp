"""Regenerate the module catalog at the end of docs/ARCHITECTURE.md from the live tool registry.

    python docs/update_catalog.py --sdk ../neon_mdf
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from neon_mcp.core.app import NeonApp
from neon_mcp.core.server import create_server
from neon_mcp.system.config import Settings

DOC = Path(__file__).resolve().parent / "ARCHITECTURE.md"
MARKER = "## Module catalog (generated from code)"


def render(catalog: list[dict]) -> str:
    out = [MARKER, ""]
    for m in catalog:
        out += [f"### {m['number']} {m['title']} (`{m['id']}`) — {m['submodules_implemented']} submodules", "",
                m["description"], "",
                "| Submodule | Status | File | Tools / prompts / resources |", "|---|---|---|---|"]
        for s in m["submodules"]:
            items = [f"`{t}`" for t in s["tools"]] + [f"prompt `{p}`" for p in s.get("prompts", [])]
            items += [f"`{r}`" for r in s.get("resources", [])]
            status = "✅" if s["status"] == "implemented" else "⏳ planned"
            source = f"`{s['source']}`" if s["source"] else "—"
            out.append(f"| **{s['name']}** — {s['description']} | {status} | {source} | {', '.join(items) or '—'} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdk", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as workspace:
        app = NeonApp(Settings(sdk_path=args.sdk, workspace_roots=[Path(workspace)]))
        create_server(app)
        catalog = app.registry.catalog()
    text = DOC.read_text(encoding="utf-8")
    DOC.write_text(text[:text.index(MARKER)] + render(catalog), encoding="utf-8")
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
