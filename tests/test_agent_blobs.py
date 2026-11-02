"""Blobs sur mesure ecrits gratuitement par un agent."""
from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from pathlib import Path

from backend import blob
from mascotforge import cli
from mascotforge.client import MascotForgeClient


ROOT = Path(__file__).resolve().parents[1]
HORNED = json.loads((ROOT / "tests" / "fixtures" / "blob-deux-cornes.json").read_text(encoding="utf-8"))


def _api(test_client) -> MascotForgeClient:  # type: ignore[no-untyped-def]
    return MascotForgeClient(base_url="http://testserver", http_client=test_client)


def _messages(spec: dict) -> str:
    return " ".join(item["message"] for item in blob.check_spec(spec)["issues"])


def test_blob_guide_contains_three_complete_valid_examples(client):
    response = client.get("/api/engines/blob/guide")
    assert response.status_code == 200
    guide = response.json()["guide"]
    examples = [json.loads(raw) for raw in re.findall(r"```json\n(.*?)\n```", guide, re.DOTALL)]
    assert len(examples) == 3
    assert {example["name"] for example in examples} == {"Cornu", "Etoile", "Haricot tordu"}
    assert all(blob.check_spec(example)["ok"] for example in examples)


def test_blob_check_accepts_horns_and_returns_72_numeric_points(client):
    response = client.post("/api/engines/blob/specs/check", json={"spec": HORNED})
    assert response.status_code == 200
    report = response.json()
    assert report["ok"] and len(report["points"]) == 72
    assert all(len(point) == 2 and all(isinstance(value, float) for value in point) for point in report["points"])


def test_blob_check_rejects_crossing_thin_small_large_and_out_of_bounds():
    crossing = copy.deepcopy(HORNED)
    crossing["contour"] = {
        "base": {"kind": "round", "width": 1.1357, "height": 0.2789, "roundness": 4.4439},
        "bumps": [
            {"angle": 160.61, "height": -0.404, "width": 36.87},
            {"angle": 84.34, "height": -0.42, "width": 77.61},
        ],
    }
    assert "se croise" in _messages(crossing)

    thin = copy.deepcopy(HORNED)
    thin["contour"] = {"base": {"kind": "oval", "width": 0.2, "height": 1.2, "roundness": 2}, "bumps": []}
    assert "trop fin" in _messages(thin)

    small = copy.deepcopy(HORNED)
    small["contour"] = {"base": {"kind": "round", "width": 0.25, "height": 0.25, "roundness": 2}, "bumps": []}
    assert "trop petit" in _messages(small)

    large = copy.deepcopy(HORNED)
    large["contour"] = {"base": {"kind": "round", "width": 1.5, "height": 1.5, "roundness": 2}, "bumps": [{"angle": 0, "height": 1.2, "width": 30}]}
    assert "trop grand" in _messages(large)

    bounded = copy.deepcopy(HORNED)
    bounded["contour"]["bumps"][0]["width"] = 2
    assert "hors bornes" in _messages(bounded)


def test_blob_check_detects_a_crossing_created_by_the_rendered_cubic_curve():
    points = [
        [0.14972269447744863, 0.0],
        [0.4070976327949263, 1.2529176824759611],
        [-0.7640325416058574, 0.5551021342566809],
        [-1.0626818214740117, -0.7720835370390698],
        [0.04803582152524493, -0.1478390571029351],
    ]
    assert not blob._polyline_self_intersects(points)
    assert blob._self_intersects(points)


def test_blob_export_contains_custom_points_and_keeps_code_blob_path(client):
    response = client.post("/api/engines/blob/specs/export", json={"spec": HORNED})
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(client.get(response.json()["download_url"]).content))
    manifest = json.loads(archive.read("mascot/manifest.json"))
    assert manifest["engine"] == "blob"
    assert len(manifest["engine_shape"]["points"]) == 72
    assert manifest["engine_config"]["shape"].startswith("custom-")
    assert b"AgentMascot.defineShape" in archive.read("mascot/engines/agent-mascot.js")

    legacy = client.post("/api/engines/blob/export", json={"config": {"shape": "cloud"}})
    assert legacy.status_code == 200


def test_blob_cli_check_preview_and_export(client, monkeypatch, tmp_path, capsys):
    spec_file = tmp_path / "cornes.json"
    spec_file.write_text(json.dumps(HORNED), encoding="utf-8")
    bad_file = tmp_path / "bad.json"
    bad = copy.deepcopy(HORNED)
    bad["contour"]["base"]["width"] = 9
    bad_file.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(blob, "render_agent_sheet", lambda _spec: b"\x89PNG\r\n\x1a\nblob")
    api = _api(client)

    guide_file = tmp_path / "guide.md"
    assert cli.main(["blob", "guide", "--out", str(guide_file)], client=api) == 0
    capsys.readouterr()
    assert "Etoile" in guide_file.read_text(encoding="utf-8")

    assert cli.main(["blob", "check", str(spec_file), "--json"], client=api) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert cli.main(["blob", "check", str(bad_file), "--json"], client=api) == 2
    assert not json.loads(capsys.readouterr().out)["ok"]

    sheet = tmp_path / "sheet.png"
    assert cli.main(["blob", "preview", str(spec_file), "--out", str(sheet)], client=api) == 0
    capsys.readouterr()
    assert sheet.read_bytes().startswith(b"\x89PNG")

    out = tmp_path / "export"
    assert cli.main(["blob", "export", str(spec_file), "--out", str(out)], client=api) == 0
    capsys.readouterr()
    assert json.loads((out / "mascot" / "manifest.json").read_text())["engine_shape"]["points"]


def test_blob_preview_api_reports_validation_and_renderer_errors(client, monkeypatch):
    invalid = copy.deepcopy(HORNED)
    invalid["color"] = "javascript:alert(1)"
    response = client.post("/api/engines/blob/specs/preview", json={"spec": invalid})
    assert response.status_code == 422
    assert response.json()["issues"]

    def fail(_spec: dict) -> bytes:
        raise blob.BlobRenderError("delai depasse")

    monkeypatch.setattr(blob, "render_agent_sheet", fail)
    response = client.post("/api/engines/blob/specs/preview", json={"spec": HORNED})
    assert response.status_code == 503
    assert "Blob Atelier" in response.json()["detail"]
