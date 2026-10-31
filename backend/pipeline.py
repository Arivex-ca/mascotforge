"""Orchestration des jobs de generation MascotForge V2.

Un job = 6 clips video (un par etat), generes en parallele (max 3).
Si un etat echoue sur le modele principal, on retente avec le modele fallback.
Le modele qui a produit chaque clip est journalise dans le job.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend import cost as cost_module
from backend import fal as fal_module
from backend import settings

STATES: list[str] = ["idle", "talking", "thinking", "clicked", "error", "sleeping"]


class JobNotFoundError(Exception):
    pass


class CharacterNotFoundError(Exception):
    pass


class CapExceededError(Exception):
    pass


_lock = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_path() -> Path:
    return settings.data_dir() / "jobs.json"


def _characters_path() -> Path:
    return settings.data_dir() / "characters.json"


def _read_json(path: Path, default):  # type: ignore[no-untyped-def]
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Personnages
# ---------------------------------------------------------------------------
def save_character(
    image_url: str, local_path: str | None = None, character_id: str | None = None
) -> str:
    """Enregistre un personnage, retourne son character_id."""
    cid = character_id or uuid.uuid4().hex[:12]
    with _lock:
        chars = _read_json(_characters_path(), {})
        chars[cid] = {
            "character_id": cid,
            "image_url": image_url,
            "local_path": local_path,
            "created_at": _utcnow(),
        }
        _write_json(_characters_path(), chars)
    return cid


def get_character(character_id: str) -> dict:
    chars = _read_json(_characters_path(), {})
    if character_id not in chars:
        raise CharacterNotFoundError(
            f"Personnage {character_id!r} introuvable."
        )
    return chars[character_id]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def estimate_job_cost_usd() -> float:
    """Cout estime d'un job complet (6 clips sur le modele principal)."""
    per_clip = settings.VIDEO_DURATION_S * settings.i2v_rate_usd(settings.i2v_model())
    return round(len(STATES) * per_clip, 4)


def create_job(character_id: str) -> str:
    """Cree un job en file d'attente. Leve CapExceededError si le plafond est atteint."""
    get_character(character_id)  # leve CharacterNotFoundError si inconnu
    estimate = estimate_job_cost_usd()
    if not cost_module.can_afford(estimate):
        status = cost_module.get_status()
        raise CapExceededError(
            "Plafond mensuel atteint : "
            f"{status['spent_usd']} $ depenses sur {status['cap_usd']} $ autorises "
            f"pour {status['month']} (estimation du job : {estimate} $). "
            "Relevez MASCOTFORGE_MONTHLY_CAP_USD ou attendez le mois prochain."
        )
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "character_id": character_id,
        "status": "queued",
        "states": {
            state: {
                "status": "queued",
                "video_url": None,
                "model": None,
                "error": None,
                "cost_usd": 0.0,
            }
            for state in STATES
        },
        "cost_usd_estimate": estimate,
        "actual_cost_usd": 0.0,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    with _lock:
        jobs = _read_json(_jobs_path(), {})
        jobs[job_id] = job
        _write_json(_jobs_path(), jobs)
    return job_id


def get_job(job_id: str) -> dict:
    jobs = _read_json(_jobs_path(), {})
    if job_id not in jobs:
        raise JobNotFoundError(f"Job {job_id!r} introuvable.")
    return jobs[job_id]


def _update_job(job_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
    with _lock:
        jobs = _read_json(_jobs_path(), {})
        if job_id not in jobs:
            raise JobNotFoundError(f"Job {job_id!r} introuvable.")
        jobs[job_id].update(fields)
        jobs[job_id]["updated_at"] = _utcnow()
        _write_json(_jobs_path(), jobs)


def _update_state(job_id: str, state: str, **fields) -> None:  # type: ignore[no-untyped-def]
    with _lock:
        jobs = _read_json(_jobs_path(), {})
        if job_id not in jobs:
            raise JobNotFoundError(f"Job {job_id!r} introuvable.")
        jobs[job_id]["states"][state].update(fields)
        jobs[job_id]["updated_at"] = _utcnow()
        _write_json(_jobs_path(), jobs)


async def _download_video(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)


async def _generate_one_state(
    job_id: str, state: str, image_url: str, sem: asyncio.Semaphore
) -> None:
    async with sem:
        _update_state(job_id, state, status="running")
        primary = settings.i2v_model()
        fallback = settings.fallback_model()
        models = [primary] + ([fallback] if fallback != primary else [])
        last_error: str | None = None
        for model in models:
            try:
                video_url, used_model = await fal_module.generate_state_video(
                    image_url, state, model=model
                )
                dest = settings.data_dir() / "videos" / job_id / f"{state}.mp4"
                await _download_video(video_url, dest)
                clip_cost = round(
                    settings.VIDEO_DURATION_S * settings.i2v_rate_usd(used_model), 4
                )
                _update_state(
                    job_id,
                    state,
                    status="done",
                    video_url=f"/videos/{job_id}/{state}.mp4",
                    model=used_model,
                    error=None,
                    cost_usd=clip_cost,
                )
                return
            except Exception as exc:  # on journalise, puis on tente le fallback
                last_error = f"{type(exc).__name__} : {exc}"
        _update_state(job_id, state, status="failed", error=last_error)


async def run_job(job_id: str) -> dict:
    """Execute un job : genere les 6 clips, journalise les modeles, comptabilise le cout."""
    job = get_job(job_id)
    character = get_character(job["character_id"])
    image_url = character["image_url"]
    _update_job(job_id, status="running")
    sem = asyncio.Semaphore(settings.I2V_PARALLELISM)
    await asyncio.gather(
        *(_generate_one_state(job_id, state, image_url, sem) for state in STATES)
    )
    job = get_job(job_id)
    failed = [s for s in STATES if job["states"][s]["status"] != "done"]
    final_status = "done" if not failed else "failed"
    actual = round(sum(job["states"][s].get("cost_usd", 0.0) for s in STATES), 4)
    _update_job(job_id, status=final_status, actual_cost_usd=actual)
    cost_module.add_spend(actual, mascots_completed=1 if final_status == "done" else 0)
    return get_job(job_id)
