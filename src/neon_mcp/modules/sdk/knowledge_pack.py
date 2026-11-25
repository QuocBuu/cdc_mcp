"""Knowledge Pack submodule: device, C API, documentation and SDK data pre-generated for each
NEON-MDF release, and its use at runtime.

At startup the server looks for the pack named after the checkout's `neon-mdf/VERSION`. When the
checkout's fingerprint matches the pack (an unmodified release), device, API and documentation
data are served from the pack. Otherwise (a modified checkout, a branch between releases, or a
version without a pack) they are parsed live from the checkout, so answers always match the code
that is compiled.

Generate a pack with `neon-mcp-pack --sdk <checkout>`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters import knowledge_pack as packs
from ...adapters.device import DeviceDescription, parse_device, preload_device
from ...system.errors import InvalidArgumentError
from ..knowledge.documentation import Document, DocumentIndex, Section, get_index
from .api import ApiEntry, ApiIndex, get_api
from .component import components
from .example import examples

if TYPE_CHECKING:
    from ...core.app import NeonApp

log = logging.getLogger(__name__)

_NOTES = {
    "verified": "Device, API and documentation data come from the pre-generated pack of NEON-MDF {v}.",
    "modified": "The checkout differs from released NEON-MDF {v}; data is parsed live from the checkout.",
    "unavailable": "No knowledge pack for NEON-MDF {v}; data is parsed live from the checkout.",
    "error": "The knowledge pack could not be used; data is parsed live from the checkout.",
}


# --- Generation ------------------------------------------------------------------------------------
def build(app: NeonApp) -> tuple[dict, dict[str, Any]]:
    """Parse the checkout itself (never a pack) into (manifest, files)."""
    sdk = app.sdk
    version = sdk.version
    if not version:
        raise InvalidArgumentError(f"{sdk.sdk_dir / 'VERSION'} is missing: packs are made for released SDKs only.")
    api = ApiIndex(sdk)
    entries = api.entries()
    documents = DocumentIndex(sdk).documents()
    files: dict[str, Any] = {
        "sdk.json": {
            "version": version,
            "presets": sdk.presets,
            "components": components(sdk, api, app.target(None).profile),
            "examples": examples(sdk, set(api.modules())),
        },
        "api.json": {"modules": api.modules(), "entries": [asdict(e) for e in entries]},
        "docs.json": {"documents": [
            {"path": d.path, "title": d.title, "category": d.category, "lines": d.lines,
             "sections": [{k: v for k, v in asdict(s).items() if k != "doc"} for s in d.sections]}
            for d in documents]},
    }
    contents: dict[str, dict] = {
        "sdk.json": {"components": len(files["sdk.json"]["components"]),
                     "examples": len(files["sdk.json"]["examples"])},
        "api.json": {"entries": len(entries), "modules": len(files["api.json"]["modules"])},
        "docs.json": {"documents": len(documents), "sections": sum(len(d.sections) for d in documents)},
    }
    for path in sdk.device_files():
        device = parse_device(path)
        rel = f"devices/{path.stem}.json"
        files[rel] = device.to_pack()
        contents[rel] = {"device": device.name, "vendor": device.vendor, "arch": device.arch,
                         "peripherals": len(device.peripherals),
                         "registers": sum(len(p.registers) for p in device.peripherals)}
    manifest = {"schema": packs.SCHEMA, "name": packs.pack_name(version), "sdk": {"version": version},
                "fingerprint": packs.fingerprint(sdk), "contents": contents}
    return manifest, files


def compare(out_dir: Path, manifest: dict, files: dict[str, Any]) -> list[str]:
    """Files of the pack in `out_dir` that differ from a fresh build (missing, changed or extra)."""
    target = out_dir / manifest["name"]
    expected = {rel: packs.dumps(data) for rel, data in {**files, "manifest.json": manifest}.items()}
    present = {p.relative_to(target).as_posix() for p in target.rglob("*.json")} if target.is_dir() else set()
    differ = sorted(present - set(expected))
    for rel, text in expected.items():
        path = target / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            differ.append(rel)
    return sorted(differ)


# --- Runtime ---------------------------------------------------------------------------------------
@dataclass
class PackState:
    status: str                      # verified | modified | unavailable | error
    sdk_version: str | None
    pack: packs.KnowledgePack | None = None
    available: list[str] = field(default_factory=list)
    detail: str | None = None

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"status": self.status, "sdk_version": self.sdk_version,
                                "pack": self.pack.name if self.pack else None,
                                "note": _NOTES[self.status].format(v=self.sdk_version)}
        if self.status == "verified" and self.pack:
            data["contents"] = self.pack.manifest.get("contents", {})
        if self.status == "unavailable":
            data["available_packs"] = self.available
        if self.detail:
            data["detail"] = self.detail
        return data


def _dirs(app: NeonApp) -> list[Path]:
    return [d for d in (app.settings.packs_dir, packs.BUNDLED_DIR) if d is not None]


def _seed(app: NeonApp, pack: packs.KnowledgePack) -> None:
    get_api(app).seed([ApiEntry(**e) for e in pack.read("api.json")["entries"]])
    get_index(app).seed([
        Document(d["path"], d["title"], d["category"], d["lines"], [Section(d["path"], **s) for s in d["sections"]])
        for d in pack.read("docs.json")["documents"]])
    for path in app.sdk.device_files():
        rel = f"devices/{path.stem}.json"
        if (pack.path / rel).is_file():
            preload_device(path, DeviceDescription.from_pack(path, pack.read(rel)))


def activate(app: NeonApp) -> PackState:
    """Select the pack for the checkout's version and serve its data when the checkout matches."""
    version = app.sdk.version
    try:
        pack = packs.pack_for(version, _dirs(app))
        if pack is None:
            state = PackState("unavailable", version, available=[p.version for p in packs.find_packs(_dirs(app))])
        elif packs.fingerprint(app.sdk) != pack.fingerprint:
            state = PackState("modified", version, pack)
        else:
            _seed(app, pack)
            state = PackState("verified", version, pack)
    except Exception as exc:  # a broken pack must never stop the server: fall back to live parsing
        log.warning("Knowledge pack not used: %s", exc)
        state = PackState("error", version, detail=str(exc))
    log.info("Knowledge pack: %s (%s)", state.status, state.pack.name if state.pack else version)
    app.services["pack"] = state
    return state


def status(app: NeonApp) -> dict:
    """Pack status now; a checkout edited after startup reports `modified` (indexes then re-parse)."""
    state = app.services.get("pack") or activate(app)
    if state.status == "verified" and state.pack and packs.fingerprint(app.sdk) != state.pack.fingerprint:
        return PackState("modified", state.sdk_version, state.pack).to_dict()
    return state.to_dict()


# --- CLI: neon-mcp-pack ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from ...core.app import NeonApp
    from ...system.config import Settings

    parser = argparse.ArgumentParser(prog="neon-mcp-pack",
                                     description="Generate the knowledge pack of a NEON-MDF release checkout.")
    parser.add_argument("--sdk", type=Path, required=True, help="NEON-MDF checkout (repository root)")
    parser.add_argument("--out", type=Path, default=packs.BUNDLED_DIR,
                        help="directory receiving neon-mdf-<version>/ (default: the packs bundled with NEON MCP)")
    parser.add_argument("--force", action="store_true", help="replace an existing pack of the same version")
    parser.add_argument("--check", action="store_true", help="only report whether the existing pack is up to date")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    with tempfile.TemporaryDirectory() as workspace:
        app = NeonApp(Settings(sdk_path=args.sdk, workspace_roots=[Path(workspace)]))
        manifest, files = build(app)
    if args.check:
        differ = compare(args.out, manifest, files)
        print(f"{manifest['name']}: " + ("up to date" if not differ else "out of date: " + ", ".join(differ)))
        return 1 if differ else 0
    try:
        target = packs.write_pack(args.out, manifest, files, force=args.force)
    except FileExistsError as exc:
        print(f"neon-mcp-pack: {exc}", file=sys.stderr)
        return 1
    counts = "; ".join(f"{rel}: " + ", ".join(f"{v} {k}" for k, v in c.items() if isinstance(v, int))
                       for rel, c in manifest["contents"].items())
    print(f"{target}\n  {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
