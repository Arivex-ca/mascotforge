"""Fiches Wobnimo ecrites gratuitement par un agent."""
from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

from backend import image3d
from conftest import ARIVEX_SPEC_TEXT


def _use_fake_checker_if_needed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    if image3d.available():
        return
    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(image3d, "check_spec", lambda _spec: {"ok": True, "issues": []})


def test_guide_contains_sources_and_mascotforge_rules(client):
    response = client.get("/api/engines/3d/guide")
    assert response.status_code == 200
    guide = response.json()["guide"]
    assert "<wobnimo-skill>" in guide
    assert "CharacterSpec" in guide
    assert "<wobnimo-spec-reference>" in guide
    assert '"name":"Volt"' in guide
    assert "serveur impose l'identifiant" in guide
    assert "haut a gauche" in guide
    assert "ecran LED" in guide


def test_agent_spec_can_be_checked_saved_and_exported_for_free(
    client, fal_fake, monkeypatch
):
    _use_fake_checker_if_needed(monkeypatch)
    spec = json.loads(ARIVEX_SPEC_TEXT)
    spec["id"] = "id-choisi-par-agent"

    checked = client.post("/api/engines/3d/specs/check", json={"spec": spec})
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"], checked.json()

    saved = client.post("/api/engines/3d/specs", json={"spec": spec})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["name"] == "Arivex" and body["warnings"] == []
    spec_id = body["spec_id"]
    job = image3d.get_job(spec_id)
    assert job["source"] == "agent"
    assert job["cost_usd"] == 0.0 and job["model"] is None
    assert job["spec"]["id"] == image3d.wobnimo_id(spec_id)
    assert fal_fake.vision_prompts == []

    manifest = client.get(f"/api/engines/3d/manifest.json?spec={spec_id}")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["engine_spec"]["name"] == "Arivex"

    exported = client.post("/api/engines/3d/export", json={"config": {"spec": spec_id}})
    assert exported.status_code == 200, exported.text
    archive = zipfile.ZipFile(io.BytesIO(client.get(exported.json()["download_url"]).content))
    export_manifest = json.loads(archive.read("mascot/manifest.json"))
    assert export_manifest["engine_spec"]["id"] == image3d.wobnimo_id(spec_id)


def test_agent_spec_with_checker_error_returns_422(client, monkeypatch):
    spec = json.loads(ARIVEX_SPEC_TEXT)
    if image3d.available():
        broken = copy.deepcopy(spec)
        head = next(bone for bone in broken["bones"] if bone["name"] == "head")
        head["pivot"] = [0, 0.56, 0]
    else:
        broken = spec
        issue = {
            "level": "error",
            "where": "parts[4]",
            "message": "piece cachee",
            "fix": "deplacer la piece",
        }
        monkeypatch.setattr(image3d, "available", lambda: True)
        monkeypatch.setattr(
            image3d, "check_spec", lambda _spec: {"ok": False, "issues": [issue]}
        )

    response = client.post("/api/engines/3d/specs", json={"spec": broken})
    assert response.status_code == 422, response.text
    assert any(item["level"] == "error" for item in response.json()["issues"])


def test_agent_spec_rejects_malformed_and_oversized_payloads(client):
    cases = [
        {"spec": []},
        {"spec": {"name": "Sans pieces"}},
        ["pas un objet"],
    ]
    for body in cases:
        response = client.post("/api/engines/3d/specs/check", json=body)
        assert response.status_code == 400, response.text
        assert isinstance(response.json()["detail"], str)

    huge = {"spec": {"parts": [], "padding": "x" * (201 * 1024)}}
    response = client.post("/api/engines/3d/specs/check", json=huge)
    assert response.status_code == 413
    assert "200 Ko" in response.json()["detail"]


def test_agent_spec_preview_returns_png_or_clear_503(client, monkeypatch):
    spec = json.loads(ARIVEX_SPEC_TEXT)
    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(image3d, "render_agent_sheet", lambda _spec: b"\x89PNG\r\n\x1a\nplanche")
    response = client.post("/api/engines/3d/specs/preview", json={"spec": spec})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")

    def no_browser(_spec: dict) -> bytes:
        raise image3d.RenderError("Chrome introuvable")

    monkeypatch.setattr(image3d, "render_agent_sheet", no_browser)
    response = client.post("/api/engines/3d/specs/preview", json={"spec": spec})
    assert response.status_code == 503
    assert "navigateur" in response.json()["detail"]


def test_agent_spec_check_returns_503_without_node(client, monkeypatch):
    monkeypatch.setattr(image3d, "available", lambda: False)
    response = client.post(
        "/api/engines/3d/specs/check", json={"spec": {"parts": []}}
    )
    assert response.status_code == 503
    assert "Node" in response.json()["detail"]
