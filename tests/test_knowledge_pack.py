"""Knowledge packs: generation, selection by SDK version, verification and use at runtime."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from neon_mcp.adapters import knowledge_pack as packs
from neon_mcp.adapters.device import load_device, parse_device
from neon_mcp.adapters.neon_mdf import NeonMdfSdk
from neon_mcp.core.server import create_server
from neon_mcp.modules.knowledge.documentation import DocumentIndex, get_index
from neon_mcp.modules.sdk import knowledge_pack
from neon_mcp.modules.sdk.api import ApiIndex, get_api

from .conftest import SDK, make_app

pytestmark = pytest.mark.anyio

BUNDLED = packs.pack_for(NeonMdfSdk(SDK).version, [packs.BUNDLED_DIR])
CLEAN_RELEASE = BUNDLED is not None and packs.fingerprint(NeonMdfSdk(SDK)) == BUNDLED.fingerprint
needs_release = pytest.mark.skipif(not CLEAN_RELEASE, reason="test SDK is not an unmodified release with a bundled pack")


@needs_release
def test_bundled_pack_is_up_to_date(tmp_path: Path):
    """The committed pack must equal a fresh build: regenerate with `neon-mcp-pack --sdk <sdk> --force`."""
    manifest, files = knowledge_pack.build(make_app(tmp_path))
    assert knowledge_pack.compare(packs.BUNDLED_DIR, manifest, files) == []
    assert "/" + "home" not in json.dumps(files)  # no build-machine paths


@needs_release
async def test_verified_pack_serves_same_data_as_live_parsing(tmp_path: Path):
    app = make_app(tmp_path)
    server = create_server(app)
    assert app.services["pack"].status == "verified"

    device_file = app.target(None).device_file
    from_pack, live = load_device(device_file), parse_device(device_file)
    assert from_pack.raw is None  # really came from the pack
    assert from_pack.summary() == live.summary()
    for a, b in zip(from_pack.peripherals, live.peripherals, strict=True):
        assert [r.to_dict() for r in a.registers] == [r.to_dict() for r in b.registers]
    assert from_pack.locate(0x440D0014) == live.locate(0x440D0014)

    assert [e.full() for e in get_api(app).entries()] == [e.full() for e in ApiIndex(app.sdk).entries()]
    live_docs = DocumentIndex(app.sdk)
    for query in ("boot mode 100", "printf uart console", "secure boot signing"):
        assert get_index(app).search(query, 5, None) == live_docs.search(query, 5, None)

    from mcp import Client
    async with Client(server) as client:
        info = (await client.call_tool("sdk_get_info", {})).structured_content["knowledge_pack"]
        assert info["status"] == "verified" and info["pack"] == BUNDLED.name
        assert info["contents"]["api.json"]["entries"] > 0
        ctx = (await client.call_tool("session_get_context", {})).structured_content
        assert ctx["knowledge_pack"] == {"status": "verified", "pack": BUNDLED.name}


@needs_release
def test_modified_checkout_falls_back_to_live(tmp_path: Path):
    packs_dir = tmp_path / "packs"
    shutil.copytree(BUNDLED.path, packs_dir / BUNDLED.name)
    manifest_path = packs_dir / BUNDLED.name / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["fingerprint"] = "sha256:" + "0" * 64  # as if the checkout had been edited
    manifest_path.write_text(json.dumps(manifest))

    app = make_app(tmp_path, packs_dir=packs_dir)  # searched before the bundled packs
    state = knowledge_pack.activate(app)
    assert state.status == "modified" and state.pack.path.parent == packs_dir
    assert "parsed live" in knowledge_pack.status(app)["note"]
    assert get_api(app).entries()  # parsed from the headers


def test_unknown_version_has_no_pack(tmp_path: Path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(NeonMdfSdk, "version", property(lambda self: "99.0.0"))
    status = knowledge_pack.status(app)
    assert status["status"] == "unavailable" and status["pack"] is None
    if BUNDLED is not None:
        assert BUNDLED.version in status["available_packs"]


def test_broken_pack_does_not_stop_the_server(tmp_path: Path):
    version = NeonMdfSdk(SDK).version
    if version is None:
        pytest.skip("test SDK has no VERSION")
    broken = tmp_path / "packs" / packs.pack_name(version)
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text(json.dumps({
        "schema": packs.SCHEMA, "name": broken.name, "sdk": {"version": version},
        "fingerprint": packs.fingerprint(NeonMdfSdk(SDK)), "contents": {}}))  # data files missing
    app = make_app(tmp_path, packs_dir=tmp_path / "packs")
    create_server(app)
    assert app.services["pack"].status == "error"
    assert get_api(app).entries()


def test_write_pack_refuses_to_overwrite(tmp_path: Path):
    manifest = {"schema": packs.SCHEMA, "name": "neon-mdf-0.0.1", "sdk": {"version": "0.0.1"},
                "fingerprint": "sha256:x", "contents": {}}
    target = packs.write_pack(tmp_path, manifest, {"api.json": {"entries": []}})
    assert packs.pack_for("0.0.1", [tmp_path]).path == target
    with pytest.raises(FileExistsError):
        packs.write_pack(tmp_path, manifest, {})
    packs.write_pack(tmp_path, manifest, {}, force=True)
    assert not (target / "api.json").exists()
