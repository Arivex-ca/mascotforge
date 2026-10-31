"""Mascottes en code : catalogue, manifest d'apercu, export avec licence."""
from __future__ import annotations

import io
import json
import zipfile

from backend import engines as engines_module

EM_DASH = "\u2014"


def test_catalog_lists_both_engines_with_credits(client):
    body = client.get("/api/engines").json()
    assert set(body) == {"blob", "3d"}
    assert "Victoria Wu" in body["blob"]["credit"] and "MIT" in body["blob"]["credit"]
    assert "Pourya Akhbari" in body["3d"]["credit"]
    assert "talking" in body["blob"]["states"] and "speaking" in body["3d"]["states"]
    assert "volt" in body["3d"]["options"]["character"]


def test_engine_files_are_served(client):
    for engine in ("blob", "3d"):
        script = engines_module.ENGINES[engine]["script"]
        resp = client.get(f"/engines/{script}")
        assert resp.status_code == 200 and len(resp.content) > 10_000


def test_preview_manifest_validates_config(client):
    resp = client.get("/api/engines/blob/manifest.json?shape=cloud&color=%23ff5d8f&eyes=dot")
    assert resp.status_code == 200, resp.text
    manifest = resp.json()
    assert manifest["engine"] == "blob"
    assert manifest["engine_src"] == "/engines/blob-atelier/agent-mascot.js"
    assert manifest["engine_config"] == {
        "shape": "cloud", "material": "soft", "color": "#ff5d8f", "eyes": "dot", "cheeks": "true",
    }
    assert manifest["default_state"] == "idle"
    assert list(manifest["states"]) == engines_module.ENGINES["blob"]["states"]

    for bad in ("shape=dragon", "material=chrome", "color=rouge", "volume=11"):
        resp = client.get(f"/api/engines/blob/manifest.json?{bad}")
        assert resp.status_code == 400, bad
        assert EM_DASH not in resp.json()["detail"]
    assert client.get("/api/engines/pixel/manifest.json").status_code == 400


def test_engine_export_ships_engine_licence_and_credits(client):
    resp = client.post("/api/engines/3d/export", json={"config": {"character": "volt"}})
    assert resp.status_code == 200, resp.text
    archive = zipfile.ZipFile(io.BytesIO(client.get(resp.json()["download_url"]).content))
    names = archive.namelist()
    for expected in ("mascot/mascot.js", "mascot/manifest.json", "mascot/README.md",
                     "mascot/engines/wobnimo.js", "mascot/engines/LICENSE"):
        assert expected in names, expected

    manifest = json.loads(archive.read("mascot/manifest.json"))
    assert manifest["engine"] == "3d"
    assert manifest["engine_src"] == "engines/wobnimo.js", "chemin relatif dans l'export"
    assert manifest["engine_config"] == {"character": "volt"}
    assert "Pourya Akhbari" in archive.read("mascot/engines/LICENSE").decode("utf-8")

    readme = archive.read("mascot/README.md").decode("utf-8")
    assert "Wobnimo, par Pourya Akhbari (licence MIT)" in readme
    assert "https://github.com/Pouryaak/wobnimo" in readme
    assert EM_DASH not in readme

    assert client.post("/api/engines/3d/export", json={"config": {"character": "godzilla"}}).status_code == 400
