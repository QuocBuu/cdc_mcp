"""Knowledge packs: the device, C API, documentation and SDK data of one NEON-MDF release,
pre-generated as JSON.

A pack is a directory `neon-mdf-<version>/` holding `manifest.json` and the data files. The
manifest names the SDK version and commit and carries one fingerprint of every source file the
data was derived from, so a checkout can be checked against the pack without listing files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .neon_mdf import NeonMdfSdk

SCHEMA = 1
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "packs"

log = logging.getLogger(__name__)


def pack_name(version: str) -> str:
    return f"neon-mdf-{version}"


def fingerprint(sdk: NeonMdfSdk) -> str:
    """SHA-256 over the relative path and content of every knowledge source of the checkout."""
    digest = hashlib.sha256()
    for path in sdk.knowledge_sources():
        digest.update(sdk.relative(path).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def dumps(data: Any) -> str:
    """Stable JSON so regenerated packs diff cleanly."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


@dataclass(frozen=True)
class KnowledgePack:
    path: Path
    manifest: dict

    @property
    def name(self) -> str:
        return self.manifest["name"]

    @property
    def version(self) -> str:
        return self.manifest["sdk"]["version"]

    @property
    def fingerprint(self) -> str:
        return self.manifest["fingerprint"]

    def read(self, rel: str) -> Any:
        return json.loads((self.path / rel).read_text(encoding="utf-8"))

    def summary(self) -> dict:
        return {"pack": self.name, "sdk_version": self.version, "contents": self.manifest.get("contents", {})}


def _open(directory: Path) -> KnowledgePack | None:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if manifest.get("schema") != SCHEMA or manifest.get("name") != directory.name:
        log.warning("Ignoring knowledge pack %s (schema %s)", directory, manifest.get("schema"))
        return None
    return KnowledgePack(directory, manifest)


def find_packs(dirs: list[Path]) -> list[KnowledgePack]:
    """Packs in `dirs`, earlier directories first; a version found twice keeps the first."""
    packs: dict[str, KnowledgePack] = {}
    for base in dirs:
        for manifest in sorted(base.glob("*/manifest.json")) if base.is_dir() else []:
            pack = _open(manifest.parent)
            if pack is not None:
                packs.setdefault(pack.version, pack)
    return list(packs.values())


def pack_for(version: str | None, dirs: list[Path]) -> KnowledgePack | None:
    if not version:
        return None
    return next((p for p in find_packs(dirs) if p.version == version), None)


def write_pack(out_dir: Path, manifest: dict, files: dict[str, Any], *, force: bool = False) -> Path:
    """Write `files` (relative path → JSON data) and the manifest to `out_dir/<name>/`."""
    target = out_dir / manifest["name"]
    if target.exists():
        if not force:
            raise FileExistsError(f"{target} exists (use --force to regenerate)")
        shutil.rmtree(target)
    for rel, data in {**files, "manifest.json": manifest}.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(data), encoding="utf-8")
    return target
