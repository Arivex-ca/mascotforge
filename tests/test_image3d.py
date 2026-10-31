"""Image -> personnage 3D Wobnimo : boucle modele + verificateur, cout, manifest, export."""
from __future__ import annotations

import copy
import io
import json
import zipfile

import pytest

from backend import image3d
from conftest import ARIVEX_SPEC_TEXT, VISION_COST

EM_DASH = "\u2014"
PNG = ("robot.png", b"\x89PNG-donnees-factices", "image/png")
ERROR = {"level": "error", "where": "parts[4]", "message": "parts[4] is completely hidden.",
         "fix": "Move it outward: at [0, 0.585, 0.155]."}


@pytest.fixture
def checker(monkeypatch):
    """Verificateur simule : rend les rapports de `reports` dans l'ordre, puis un rapport propre."""
    reports: list[list[dict]] = []
    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(
        image3d, "check_spec",
        lambda spec: {"ok": not reports or not reports[0], "issues": reports.pop(0) if reports else []},
    )
    return reports


def _create(client):
    resp = client.post("/api/engines/3d/from-image", files={"file": PNG})
    assert resp.status_code == 200, resp.text
    spec_id = resp.json()["spec_id"]
    return spec_id, client.get(f"/api/engines/3d/specs/{spec_id}").json()


def test_image_becomes_a_checked_3d_character(client, fal_fake, checker):
    spec_id, job = _create(client)
    assert job["status"] == "done", job
    assert job["rounds"] == 1 and job["cost_usd"] == VISION_COST
    assert job["name"] == "Arivex"
    cost = client.get("/api/cost").json()
    assert cost["reserved_usd"] == 0
    assert cost["spent_usd"] == VISION_COST, "le cout reel renvoye par fal.ai est compte"

    manifest = client.get(f"/api/engines/3d/manifest.json?spec={spec_id}").json()
    assert manifest["engine"] == "3d" and manifest["engine_config"] == {}
    assert manifest["engine_spec"]["id"] == spec_id, "l'identifiant est impose, pas laisse au modele"
    assert manifest["engine_spec"]["parts"]

    resp = client.post("/api/engines/3d/export", json={"config": {"spec": spec_id}})
    assert resp.status_code == 200, resp.text
    archive = zipfile.ZipFile(io.BytesIO(client.get(resp.json()["download_url"]).content))
    exported = json.loads(archive.read("mascot/manifest.json"))
    assert exported["engine_spec"]["name"] == "Arivex"
    assert "mascot/engines/wobnimo.js" in archive.namelist()


def test_checker_fixes_go_back_to_the_model(client, fal_fake, checker):
    checker.append([ERROR])
    _, job = _create(client)
    assert job["status"] == "done" and job["rounds"] == 2
    assert len(fal_fake.vision_prompts) == 2
    assert "Move it outward: at [0, 0.585, 0.155]." in fal_fake.vision_prompts[1]
    assert job["cost_usd"] == round(2 * VISION_COST, 4)


def test_gives_up_after_the_last_round_and_still_counts_the_cost(client, fal_fake, checker):
    checker.extend([[ERROR], [ERROR], [ERROR]])
    _, job = _create(client)
    assert job["status"] == "failed"
    assert "verification" in job["error"] and EM_DASH not in job["error"]
    assert job["cost_usd"] == round(3 * VISION_COST, 4)
    cost = client.get("/api/cost").json()
    assert cost["spent_usd"] == round(3 * VISION_COST, 4) and cost["reserved_usd"] == 0


def test_unreadable_answer_is_asked_again(client, fal_fake, checker):
    fal_fake.vision_answers.append("Voici ma mascotte, sans JSON.")
    _, job = _create(client)
    assert job["status"] == "done" and job["rounds"] == 2
    assert "not a valid JSON object" in fal_fake.vision_prompts[1]


def test_refusals(client, checker, monkeypatch):
    assert client.get("/api/engines/3d/manifest.json?spec=0123456789ab").status_code == 400
    assert client.get("/api/engines/3d/manifest.json?spec=volt").status_code == 400
    assert client.get("/api/engines/3d/specs/inconnu").status_code == 404
    bad = client.post("/api/engines/3d/from-image", files={"file": ("robot.txt", b"x", "text/plain")})
    assert bad.status_code == 400
    monkeypatch.setattr(image3d, "available", lambda: False)
    resp = client.post("/api/engines/3d/from-image", files={"file": PNG})
    assert resp.status_code == 503 and "Node" in resp.json()["detail"]
    assert EM_DASH not in resp.json()["detail"]


@pytest.mark.skipif(not image3d.available(), reason="Node absent")
def test_real_checker_accepts_the_robot_and_catches_a_buried_part():
    spec = json.loads(ARIVEX_SPEC_TEXT)
    report = image3d.check_spec(spec)
    assert report["ok"] and report["issues"] == []

    broken = copy.deepcopy(spec)
    head = next(b for b in broken["bones"] if b["name"] == "head")
    head["pivot"] = [0, 0.56, 0]  # la tete descend et avale la bague du cou
    report = image3d.check_spec(broken)
    assert not report["ok"]
    assert any(i["level"] == "error" and i["where"] == "parts[4]" for i in report["issues"])


def test_extract_spec_reads_a_json_block():
    spec = image3d.extract_spec(f"Plan : un robot.\n```json\n{ARIVEX_SPEC_TEXT}\n```")
    assert spec["name"] == "Arivex"
    with pytest.raises(ValueError):
        image3d.extract_spec("```json\n{\"name\": \"sans pieces\"}\n```")
