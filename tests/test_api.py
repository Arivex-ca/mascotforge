"""Tests API MascotForge (fal.ai et ffmpeg mockes, aucun appel reseau reel)."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile

from backend import cost as cost_module
from backend import fal as fal_module
from backend import pipeline as pipeline_module
from backend import settings
from backend import states as states_module
from conftest import LOOK_MAP

# Capturee a l'import, avant que la fixture fal_fake ne la remplace.
REAL_GENERATE_STATE_VIDEO = fal_module.generate_state_video

EM_DASH = "\u2014"
AGENT_STATES = ["idle", "thinking", "talking", "error"]
CLIP = round(3 * 0.084, 4)


def _no_em_dash(text: str) -> None:
    assert EM_DASH not in text, f"Em dash interdit dans les textes utilisateur : {text!r}"


def _character(client, prompt: str = "un renard orange") -> str:
    resp = client.post("/api/character/from-prompt", json={"prompt": prompt})
    assert resp.status_code == 200, resp.text
    return resp.json()["character_id"]


def _generate(client, character_id: str, **body):
    return client.post("/api/generate", json={"character_id": character_id, **body})


# ---------------------------------------------------------------------------
# Sante et presets
# ---------------------------------------------------------------------------
def test_health_ok(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "fal_key_configured": True, "ffmpeg_available": True}


def test_health_no_key(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert client.get("/api/health").json()["fal_key_configured"] is False


def test_presets(client):
    body = client.get("/api/presets").json()
    assert body["default"] == "agent"
    assert [s["name"] for s in body["presets"]["agent"]["states"]] == AGENT_STATES
    assert body["cost_per_state_usd"] == CLIP
    assert body["look_cost_usd"] == round(settings.LOOK_DURATION_S * 0.084, 4)
    assert body["max_states"] == states_module.MAX_STATES


# ---------------------------------------------------------------------------
# Cycle complet : prompt -> personnage -> generation -> export
# ---------------------------------------------------------------------------
def test_full_cycle_default_preset_to_export(client, fal_fake):
    character_id = _character(client)

    resp = _generate(client, character_id)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["alpha"] == "stacked"
    assert job["default_state"] == "idle"
    assert list(job["states"]) == AGENT_STATES
    for name, info in job["states"].items():
        assert info["status"] == "done", f"{name}: {info}"
        assert info["video_url"] == f"/videos/{job_id}/{name}.mp4"
        assert info["error"] is None
    assert job["states"]["error"]["loop"] is False
    assert job["cost_usd_estimate"] == round(4 * CLIP, 4)

    # Le fallback a pris le relais sur 'talking' (panne simulee du principal)
    assert job["states"]["talking"]["model"] == settings.fallback_model()
    for name in ("idle", "thinking", "error"):
        assert job["states"][name]["model"] == settings.i2v_model()

    # Cout reel : 3 clips standard + 1 clip pro + l'image du personnage
    expected = round(3 * CLIP + 3 * settings.i2v_rate_usd(settings.fallback_model()), 4)
    assert job["actual_cost_usd"] == expected
    cost = client.get("/api/cost").json()
    assert cost["spent_usd"] == round(expected + settings.COST_TTI_PER_IMAGE_USD, 4)
    assert cost["reserved_usd"] == 0
    assert cost["mascots_completed"] == 1

    # Export -> zip telechargeable, manifest v2
    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 200, resp.text
    resp = client.get(resp.json()["download_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = archive.namelist()
    for expected_file in ("mascot/mascot.js", "mascot/manifest.json", "mascot/README.md"):
        assert expected_file in names
    for name in AGENT_STATES:
        assert f"mascot/videos/{name}.mp4" in names

    manifest = json.loads(archive.read("mascot/manifest.json"))
    assert manifest["version"] == 2
    assert manifest["alpha"] == "stacked"
    assert manifest["default_state"] == "idle"
    assert manifest["states"]["idle"] == {"src": "videos/idle.mp4", "loop": True}
    assert manifest["states"]["error"] == {"src": "videos/error.mp4", "loop": False}
    assert manifest["models"]["talking"] == settings.fallback_model()

    readme = archive.read("mascot/README.md").decode("utf-8")
    assert '<mascot-avatar manifest="./mascot/manifest.json"' in readme
    assert "idle, thinking, talking, error" in readme
    _no_em_dash(readme)


def test_video_request_keeps_pose_and_skips_audio(monkeypatch):
    """Le vrai payload Kling 3.0 : debut = fin = image, audio coupe."""
    sent: dict = {}

    async def fake_submit(model, payload):
        sent.update(payload)
        return {"video": {"url": "https://fal.media/fake/x.mp4"}}

    monkeypatch.setenv("FAL_KEY", "test-key-ne-vaut-rien")
    monkeypatch.setattr(fal_module, "_submit_and_wait", fake_submit)

    url, model = asyncio.run(REAL_GENERATE_STATE_VIDEO("https://img", "waving"))

    assert (url, model) == ("https://fal.media/fake/x.mp4", settings.i2v_model())
    assert sent["start_image_url"] == "https://img"
    assert sent["end_image_url"] == "https://img"
    assert "image_url" not in sent
    assert sent["generate_audio"] is False
    assert sent["duration"] == "3"
    assert "waving" in sent["prompt"]


# ---------------------------------------------------------------------------
# Etats a la demande
# ---------------------------------------------------------------------------
def test_custom_states_any_names(client, fal_fake):
    character_id = _character(client)
    states = [
        {"name": "idle", "prompt": "breathing", "loop": True},
        {"name": "dance", "prompt": "dancing happily", "loop": True},
        {"name": "high-five", "prompt": "raising a hand for a high five", "loop": False},
    ]
    resp = _generate(client, character_id, states=states)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert list(job["states"]) == ["idle", "dance", "high-five"]
    assert job["states"]["high-five"]["loop"] is False
    assert job["cost_usd_estimate"] == round(3 * CLIP, 4)
    assert len(fal_fake.video_calls) == 3

    manifest = client.get(f"/api/jobs/{job_id}/manifest.json").json()
    assert manifest["states"]["dance"] == {"src": f"/videos/{job_id}/dance.mp4", "loop": True}


def test_usage_preset_site(client):
    character_id = _character(client)
    job_id = _generate(client, character_id, usage="site").json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert list(job["states"]) == ["idle", "clicked", "sleeping"]


def test_invalid_states_rejected(client):
    character_id = _character(client)
    cases = [
        [{"name": "Bad Name", "prompt": "x"}],
        [{"name": "idle", "prompt": "a"}, {"name": "idle", "prompt": "b"}],
        [{"name": "idle", "prompt": ""}],
        [{"name": "wave", "prompt": "waving", "loop": False}],
        [],
        [{"name": f"s{i}", "prompt": "x"} for i in range(states_module.MAX_STATES + 1)],
    ]
    for states in cases:
        resp = _generate(client, character_id, states=states)
        assert resp.status_code == 400, (states, resp.text)
        _no_em_dash(resp.json()["detail"])
    resp = _generate(client, character_id, usage="inconnu")
    assert resp.status_code == 400
    assert cost_module.get_status()["reserved_usd"] == 0, "aucune reservation sur un refus"


# ---------------------------------------------------------------------------
# Plafond mensuel
# ---------------------------------------------------------------------------
def test_cap_exceeded_returns_429(client, monkeypatch):
    character_id = _character(client)
    monkeypatch.setenv("MASCOTFORGE_MONTHLY_CAP_USD", "0.5")
    resp = _generate(client, character_id)
    assert resp.status_code == 429, resp.text
    assert "Plafond" in resp.json()["detail"]
    _no_em_dash(resp.json()["detail"])


def test_reservation_blocks_concurrent_jobs(client, monkeypatch):
    """Deux jobs lances avant toute depense ne depassent pas le plafond ensemble."""
    character_id = _character(client)
    one_job = round(4 * CLIP, 4)
    spent = cost_module.get_status()["spent_usd"]
    monkeypatch.setenv("MASCOTFORGE_MONTHLY_CAP_USD", str(spent + one_job * 1.5))

    states = states_module.preset_states("agent")
    pipeline_module.create_job(character_id, states)  # reserve, jamais execute
    try:
        pipeline_module.create_job(character_id, states)
    except pipeline_module.CapExceededError:
        pass
    else:
        raise AssertionError("le second job aurait du etre refuse")
    assert cost_module.get_status()["reserved_usd"] == one_job


def test_character_image_cost_is_counted_and_capped(client, monkeypatch):
    _character(client)
    assert client.get("/api/cost").json()["spent_usd"] == settings.COST_TTI_PER_IMAGE_USD
    monkeypatch.setenv("MASCOTFORGE_MONTHLY_CAP_USD", "0.03")
    resp = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Echecs, relance, robustesse
# ---------------------------------------------------------------------------
def test_failed_state_retry_regenerates_only_that_state(client, fal_fake):
    character_id = _character(client)
    fal_fake.fail_always_when = "pondering"  # thinking echoue sur les deux modeles
    job_id = _generate(client, character_id).json()["job_id"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["states"]["thinking"]["status"] == "failed"
    error = job["states"]["thinking"]["error"]
    assert "HTTP 422" in error
    assert "secrete" not in error, "le detail brut de fal ne sort pas de l'API"
    _no_em_dash(error)
    assert client.post(f"/api/export/{job_id}").status_code == 409

    fal_fake.fail_always_when = None
    calls_before = len(fal_fake.video_calls)
    resp = client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 200, resp.text

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    new_calls = fal_fake.video_calls[calls_before:]
    assert len(new_calls) == 1 and "pondering" in new_calls[0][0]
    assert client.get("/api/cost").json()["mascots_completed"] == 1
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_download_retry_does_not_pay_twice(client, fal_fake):
    character_id = _character(client)
    fal_fake.download_failures = 2  # 2 echecs puis succes : 1 seule generation
    states = [{"name": "idle", "prompt": "breathing", "loop": True}]
    job_id = _generate(client, character_id, states=states).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    assert len(fal_fake.video_calls) == 1


def test_retry_redownloads_paid_clip_without_regenerating(client, fal_fake):
    character_id = _character(client)
    fal_fake.download_failures = pipeline_module.DOWNLOAD_ATTEMPTS
    states = [{"name": "idle", "prompt": "breathing", "loop": True}]
    job_id = _generate(client, character_id, states=states).json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["states"]["idle"]["status"] == "failed"
    assert job["actual_cost_usd"] == CLIP, "le clip genere est compte meme si le telechargement rate"

    client.post(f"/api/jobs/{job_id}/retry")
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    assert len(fal_fake.video_calls) == 1, "aucune nouvelle generation payee"


def test_regenerate_state_pays_one_new_clip(client, fal_fake):
    character_id = _character(client)
    states = [
        {"name": "idle", "prompt": "breathing", "loop": True},
        {"name": "error", "prompt": "shaking head", "loop": False},
    ]
    job_id = _generate(client, character_id, states=states).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
    calls_before = len(fal_fake.video_calls)

    resp = client.post(
        f"/api/jobs/{job_id}/states/error/regenerate", json={"prompt": "sad eyes, shaking head"}
    )
    assert resp.status_code == 200, resp.text
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["states"]["error"]["prompt"] == "sad eyes, shaking head"
    new_calls = fal_fake.video_calls[calls_before:]
    assert len(new_calls) == 1 and "sad eyes" in new_calls[0][0], "seul l'etat demande repart"
    assert job["actual_cost_usd"] == round(3 * CLIP, 4)

    client.post(f"/api/jobs/{job_id}/states/error/regenerate", json={})
    job = client.get(f"/api/jobs/{job_id}").json()
    assert "sad eyes" in fal_fake.video_calls[-1][0], "sans prompt, on garde le dernier"
    assert job["actual_cost_usd"] == round(4 * CLIP, 4)
    cost = client.get("/api/cost").json()
    assert cost["reserved_usd"] == 0
    assert cost["mascots_completed"] == 1, "une regeneration ne compte pas une nouvelle mascotte"


def test_regenerate_state_errors(client):
    character_id = _character(client)
    states = [{"name": "idle", "prompt": "breathing", "loop": True}]
    job_id = _generate(client, character_id, states=states).json()["job_id"]

    resp = client.post(f"/api/jobs/{job_id}/states/dance/regenerate", json={})
    assert resp.status_code == 404
    _no_em_dash(resp.json()["detail"])
    resp = client.post(f"/api/jobs/{job_id}/states/idle/regenerate", json={"prompt": "   "})
    assert resp.status_code == 400
    _no_em_dash(resp.json()["detail"])

    queued_id, _ = pipeline_module.create_job(character_id, states_module.preset_states("site"))
    resp = client.post(f"/api/jobs/{queued_id}/states/idle/regenerate", json={})
    assert resp.status_code == 409
    _no_em_dash(resp.json()["detail"])


def test_look_adds_cursor_tracking_to_a_done_job(client, fal_fake):
    character_id = _character(client)
    states = [{"name": "idle", "prompt": "breathing", "loop": True}]
    job_id = _generate(client, character_id, states=states).json()["job_id"]
    look_cost = round(settings.LOOK_DURATION_S * 0.084, 4)
    assert client.get("/api/presets").json()["look_cost_usd"] == look_cost

    resp = client.post(f"/api/jobs/{job_id}/look", json={})
    assert resp.status_code == 200, resp.text
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["states"]["look"]["kind"] == "look"
    assert fal_fake.durations[-1] == settings.LOOK_DURATION_S
    assert states_module.LOOK_PROMPT in fal_fake.video_calls[-1][0]
    assert job["actual_cost_usd"] == round(CLIP + look_cost, 4)
    assert client.get("/api/cost").json()["mascots_completed"] == 1

    manifest = client.get(f"/api/jobs/{job_id}/manifest.json").json()
    assert list(manifest["states"]) == ["idle"], "look n'est pas un etat jouable"
    assert manifest["look"] == {
        "src": f"/videos/{job_id}/look.mp4", "fps": settings.LOOK_FPS, "map": LOOK_MAP,
    }

    resp = client.get(client.post(f"/api/export/{job_id}").json()["download_url"])
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "mascot/videos/look.mp4" in archive.namelist()
    assert json.loads(archive.read("mascot/manifest.json"))["look"]["src"] == "videos/look.mp4"
    readme = archive.read("mascot/README.md").decode("utf-8")
    assert "Suivi du curseur" in readme and "idle" in readme
    _no_em_dash(readme)

    # Refaire le suivi : un seul nouveau clip de 8 s, avec la nouvelle description
    client.post(f"/api/jobs/{job_id}/look", json={"prompt": "the head looks around"})
    assert len(fal_fake.video_calls) == 3 and "looks around" in fal_fake.video_calls[-1][0]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["actual_cost_usd"] == round(CLIP + 2 * look_cost, 4)
    assert client.get("/api/cost").json()["reserved_usd"] == 0


def test_look_name_is_reserved(client):
    character_id = _character(client)
    resp = _generate(client, character_id, states=[{"name": "look", "prompt": "x", "loop": True}])
    assert resp.status_code == 400
    _no_em_dash(resp.json()["detail"])


def test_restart_marks_interrupted_jobs_failed(client):
    character_id = _character(client)
    job_id, _ = pipeline_module.create_job(character_id, states_module.preset_states("site"))
    assert cost_module.get_status()["reserved_usd"] > 0

    assert pipeline_module.recover_interrupted_jobs() == 1
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["states"]["idle"]["error"] == pipeline_module.INTERRUPTED_ERROR
    assert cost_module.get_status()["reserved_usd"] == 0


# ---------------------------------------------------------------------------
# Upload de personnage
# ---------------------------------------------------------------------------
def test_character_from_upload(client):
    files = {"file": ("renard.png", b"\x89PNG-donnees-factices", "image/png")}
    resp = client.post("/api/character/from-upload", files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["image_url"] == "https://fal.media/fake/uploaded.png"


def test_character_from_upload_bad_format(client):
    files = {"file": ("renard.txt", b"pas une image", "text/plain")}
    resp = client.post("/api/character/from-upload", files=files)
    assert resp.status_code == 400
    _no_em_dash(resp.json()["detail"])


def test_character_from_upload_too_large(client):
    big = b"\x89PNG" + b"0" * (10 * 1024 * 1024)
    resp = client.post("/api/character/from-upload", files={"file": ("big.png", big, "image/png")})
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# FAL_KEY absente -> 503, cas d'erreur
# ---------------------------------------------------------------------------
def test_no_fal_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    resp = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})
    assert resp.status_code == 503
    _no_em_dash(resp.json()["detail"])
    files = {"file": ("x.png", b"\x89PNG", "image/png")}
    assert client.post("/api/character/from-upload", files=files).status_code == 503
    assert _generate(client, "inexistant").status_code == 503


def test_generate_unknown_character_404(client):
    resp = _generate(client, "nope")
    assert resp.status_code == 404
    _no_em_dash(resp.json()["detail"])


def test_job_not_found_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/manifest.json").status_code == 404
    assert client.post("/api/jobs/nope/retry").status_code == 404


def test_export_before_done_409(client):
    character_id = _character(client, "un castor")
    job_id, _ = pipeline_module.create_job(character_id, states_module.preset_states("agent"))
    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 409
    _no_em_dash(resp.json()["detail"])
    assert client.post("/api/export/job-inexistant").status_code == 404


def test_export_missing_widget_file_fails_cleanly(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MASCOTFORGE_WIDGET_FILE", str(tmp_path / "absent.js"))
    character_id = _character(client, "un lynx")
    job_id = _generate(client, character_id).json()["job_id"]
    resp = client.post(f"/api/export/{job_id}")
    assert resp.status_code == 500
    assert "mascot-avatar.js" in resp.json()["detail"]
    _no_em_dash(resp.json()["detail"])
