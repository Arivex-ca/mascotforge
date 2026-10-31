"""Tests API MascotForge V2 (fal.ai entierement mocke, aucun appel reseau reel)."""
from __future__ import annotations

import io
import json
import zipfile

from backend import pipeline as pipeline_module
from backend import settings

EM_DASH = "\u2014"
EXPECTED_STATES = ["idle", "talking", "thinking", "clicked", "error", "sleeping"]


def _no_em_dash(text: str) -> None:
    assert EM_DASH not in text, f"Em dash interdit dans les textes utilisateur : {text!r}"


# ---------------------------------------------------------------------------
# Sante
# ---------------------------------------------------------------------------
def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["fal_key_configured"] is True


def test_health_no_key(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    resp = client.get("/api/health")
    assert resp.json()["fal_key_configured"] is False


# ---------------------------------------------------------------------------
# Cycle complet : prompt -> personnage -> generation -> export
# ---------------------------------------------------------------------------
def test_full_cycle_prompt_to_export(client):
    # 1. Personnage depuis un prompt
    resp = client.post("/api/character/from-prompt", json={"prompt": "un renard orange"})
    assert resp.status_code == 200, resp.text
    character = resp.json()
    assert character["image_url"] == "https://fal.media/fake/character.png"

    # 2. Generation (synchrone via MASCOTFORGE_SYNC_JOBS=1)
    resp = client.post("/api/generate", json={"character_id": character["character_id"]})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # 3. Job termine, 6 etats OK
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "done"
    assert sorted(job["states"].keys()) == sorted(EXPECTED_STATES)
    for state in EXPECTED_STATES:
        info = job["states"][state]
        assert info["status"] == "done", f"{state}: {info}"
        assert info["video_url"] == f"/videos/{job_id}/{state}.mp4"
        assert info["model"], f"{state}: modele non journalise"
        assert info["error"] is None
    assert job["cost_usd_estimate"] == round(6 * 3 * 0.084, 4)

    # 4. Le fallback a bien pris le relais sur 'talking' (panne simulee)
    assert job["states"]["talking"]["model"] == settings.fallback_model()
    for state in ("idle", "thinking", "clicked", "error", "sleeping"):
        assert job["states"][state]["model"] == settings.i2v_model()

    # 5. Compteur de couts alimente
    resp = client.get("/api/cost")
    assert resp.status_code == 200
    cost = resp.json()
    assert cost["spent_usd"] > 0
    assert cost["mascots_completed"] == 1
    assert cost["cap_usd"] == settings.monthly_cap_usd()

    # 6. Export -> zip telechargeable
    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 200, resp.text
    download_url = resp.json()["download_url"]
    assert download_url.endswith(".zip")

    resp = client.get(download_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = archive.namelist()
    assert "mascot/mascot.js" in names
    assert "mascot/manifest.json" in names
    assert "mascot/README.md" in names
    for state in EXPECTED_STATES:
        assert f"mascot/videos/{state}.mp4" in names

    manifest = json.loads(archive.read("mascot/manifest.json"))
    assert manifest["default_state"] == "idle"
    assert manifest["version"] == 1
    assert manifest["generated_at"]
    assert sorted(manifest["states"].keys()) == sorted(EXPECTED_STATES)
    assert manifest["states"]["idle"] == "videos/idle.mp4"
    assert manifest["models"]["talking"] == settings.fallback_model()

    readme = archive.read("mascot/README.md").decode("utf-8")
    assert '<mascot-avatar manifest="./mascot/manifest.json">' in readme
    assert 'play("error")' in readme or "play('error')" in readme
    _no_em_dash(readme)


# ---------------------------------------------------------------------------
# Upload de personnage
# ---------------------------------------------------------------------------
def test_character_from_upload(client):
    files = {"file": ("renard.png", b"\x89PNG-donnees-factices", "image/png")}
    resp = client.post("/api/character/from-upload", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_url"] == "https://fal.media/fake/uploaded.png"
    assert body["character_id"]


def test_character_from_upload_bad_format(client):
    files = {"file": ("renard.txt", b"pas une image", "text/plain")}
    resp = client.post("/api/character/from-upload", files=files)
    assert resp.status_code == 400
    _no_em_dash(resp.json()["detail"])


# ---------------------------------------------------------------------------
# Plafond mensuel -> 429
# ---------------------------------------------------------------------------
def test_cap_exceeded_returns_429(client, monkeypatch):
    monkeypatch.setenv("MASCOTFORGE_MONTHLY_CAP_USD", "0.01")
    resp = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})
    assert resp.status_code == 200
    character_id = resp.json()["character_id"]

    resp = client.post("/api/generate", json={"character_id": character_id})
    assert resp.status_code == 429, resp.text
    detail = resp.json()["detail"]
    assert "Plafond" in detail
    _no_em_dash(detail)


# ---------------------------------------------------------------------------
# FAL_KEY absente -> 503
# ---------------------------------------------------------------------------
def test_no_fal_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)

    resp = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})
    assert resp.status_code == 503
    _no_em_dash(resp.json()["detail"])

    files = {"file": ("x.png", b"\x89PNG", "image/png")}
    resp = client.post("/api/character/from-upload", files=files)
    assert resp.status_code == 503
    _no_em_dash(resp.json()["detail"])

    resp = client.post("/api/generate", json={"character_id": "inexistant"})
    assert resp.status_code == 503
    _no_em_dash(resp.json()["detail"])


# ---------------------------------------------------------------------------
# Cas d'erreur
# ---------------------------------------------------------------------------
def test_generate_unknown_character_404(client):
    resp = client.post("/api/generate", json={"character_id": "nope"})
    assert resp.status_code == 404
    _no_em_dash(resp.json()["detail"])


def test_job_not_found_404(client):
    resp = client.get("/api/jobs/nope")
    assert resp.status_code == 404
    _no_em_dash(resp.json()["detail"])


def test_export_before_done_404(client):
    resp = client.post("/api/character/from-prompt", json={"prompt": "un castor"})
    character_id = resp.json()["character_id"]
    job_id = pipeline_module.create_job(character_id)  # reste "queued", jamais execute

    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 404
    _no_em_dash(resp.json()["detail"])

    resp = client.post("/api/export/job-inexistant")
    assert resp.status_code == 404


def test_export_missing_widget_file_fails_cleanly(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MASCOTFORGE_WIDGET_FILE", str(tmp_path / "absent.js"))
    resp = client.post("/api/character/from-prompt", json={"prompt": "un lynx"})
    character_id = resp.json()["character_id"]
    resp = client.post("/api/generate", json={"character_id": character_id})
    job_id = resp.json()["job_id"]

    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "mascot-avatar.js" in detail
    _no_em_dash(detail)
