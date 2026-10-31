"""Orchestration des jobs de generation MascotForge.

Un job = un clip video par etat demande, generes en parallele (max 3).
Si un etat echoue sur le modele principal, on retente avec le modele fallback.
Chaque clip passe ensuite au detourage (backend/alpha.py) quand ffmpeg est la.
Le modele qui a produit chaque clip est journalise dans le job.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend import alpha
from backend import cost as cost_module
from backend import fal as fal_module
from backend import settings
from backend import states as states_module

log = logging.getLogger("mascotforge.pipeline")

DOWNLOAD_ATTEMPTS = 3
INTERRUPTED_ERROR = (
    "Generation interrompue par un redemarrage du serveur. "
    "Relance les etats en echec."
)


class JobNotFoundError(Exception):
    pass


class CharacterNotFoundError(Exception):
    pass


class CapExceededError(Exception):
    pass


class NothingToRetryError(Exception):
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
def clip_cost_usd(model: str, duration_s: int | None = None) -> float:
    return round((duration_s or settings.VIDEO_DURATION_S) * settings.i2v_rate_usd(model), 4)


def estimate_job_cost_usd(n_states: int) -> float:
    """Cout estime de n clips sur le modele principal."""
    return round(n_states * clip_cost_usd(settings.i2v_model()), 4)


def cap_message(estimate: float) -> str:
    status = cost_module.get_status()
    return (
        "Plafond mensuel atteint : "
        f"{status['spent_usd']} $ depenses et {status['reserved_usd']} $ reserves "
        f"sur {status['cap_usd']} $ autorises pour {status['month']} "
        f"(estimation : {estimate} $). "
        "Relevez MASCOTFORGE_MONTHLY_CAP_USD ou attendez le mois prochain."
    )


def create_job(character_id: str, requested_states: list[dict]) -> tuple[str, float]:
    """Cree un job en file d'attente et reserve son cout. Retourne (job_id, reserve).

    Leve CharacterNotFoundError, states.InvalidStatesError ou CapExceededError.
    """
    get_character(character_id)
    clean = states_module.validate_states(requested_states)
    estimate = estimate_job_cost_usd(len(clean))
    if not cost_module.reserve(estimate):
        raise CapExceededError(cap_message(estimate))
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "character_id": character_id,
        "status": "queued",
        "default_state": states_module.default_state(clean),
        "alpha": None,
        "states": {
            s["name"]: {
                "status": "queued",
                "prompt": s["prompt"],
                "loop": s["loop"],
                "video_url": None,
                "source_url": None,
                "model": None,
                "error": None,
                "alpha": False,
                "cost_usd": 0.0,
            }
            for s in clean
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
    return job_id, estimate


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


def prepare_retry(job_id: str) -> tuple[list[str], float]:
    """Remet en file les etats en echec et reserve leur cout. Retourne (etats, reserve).

    Un etat dont le clip brut est deja telecharge ne repasse que par le
    detourage : il ne coute rien de plus.
    """
    job = get_job(job_id)
    if job["status"] in ("queued", "running"):
        raise NothingToRetryError("Le job tourne encore : attends la fin avant de relancer.")
    failed = [name for name, info in job["states"].items() if info["status"] != "done"]
    if not failed:
        raise NothingToRetryError("Aucun etat en echec a relancer.")
    to_generate = [n for n in failed if not _raw_path(job_id, n).is_file()]
    estimate = estimate_job_cost_usd(len(to_generate))
    if estimate and not cost_module.reserve(estimate):
        raise CapExceededError(cap_message(estimate))
    for name in failed:
        _update_state(job_id, name, status="queued", error=None)
    _update_job(job_id, status="queued")
    return failed, estimate


def prepare_regenerate(job_id: str, state: str, prompt: str | None = None) -> float:
    """Remet un etat en file pour un nouveau clip, paye. Retourne la reserve.

    Le nouveau prompt, s'il est fourni, remplace l'ancien. Leve
    NothingToRetryError, states.InvalidStatesError ou CapExceededError.
    """
    job = get_job(job_id)
    if job["status"] in ("queued", "running"):
        raise NothingToRetryError("Le job tourne encore : attends la fin avant de regenerer.")
    if state not in job["states"]:
        raise states_module.InvalidStatesError(f"L'etat {state!r} n'existe pas dans ce job.")
    fields: dict = {"status": "queued", "error": None, "source_url": None}
    if prompt is not None:
        fields["prompt"] = states_module.clean_prompt(state, prompt)
    estimate = clip_cost_usd(settings.i2v_model(), job["states"][state].get("duration_s"))
    if not cost_module.reserve(estimate):
        raise CapExceededError(cap_message(estimate))
    _raw_path(job_id, state).unlink(missing_ok=True)  # sinon on reprendrait l'ancien clip
    _update_state(job_id, state, **fields)
    _update_job(
        job_id, status="queued",
        completed_once=job.get("completed_once", False) or job["status"] == "done",
    )
    return estimate


def prepare_look(job_id: str, prompt: str | None = None) -> float:
    """Ajoute (ou refait) le clip du suivi du curseur. Retourne la reserve.

    Le clip dure LOOK_DURATION_S et n'est pas un etat jouable : le widget en
    affiche l'image qui regarde vers le curseur.
    """
    job = get_job(job_id)
    name = states_module.LOOK_STATE
    if name in job["states"]:
        return prepare_regenerate(job_id, name, prompt)
    if job["status"] in ("queued", "running"):
        raise NothingToRetryError("Le job tourne encore : attends la fin avant d'ajouter le suivi.")
    clean = states_module.clean_prompt(name, prompt if prompt is not None else states_module.LOOK_PROMPT)
    estimate = clip_cost_usd(settings.i2v_model(), settings.LOOK_DURATION_S)
    if not cost_module.reserve(estimate):
        raise CapExceededError(cap_message(estimate))
    with _lock:
        jobs = _read_json(_jobs_path(), {})
        current = jobs[job_id]
        current["states"][name] = {
            "status": "queued", "prompt": clean, "loop": False,
            "kind": "look", "duration_s": settings.LOOK_DURATION_S, "look_map": None,
            "video_url": None, "source_url": None, "model": None, "error": None,
            "alpha": False, "cost_usd": 0.0,
        }
        current["completed_once"] = current.get("completed_once", False) or current["status"] == "done"
        current["status"] = "queued"
        current["updated_at"] = _utcnow()
        _write_json(_jobs_path(), jobs)
    return estimate


def recover_interrupted_jobs() -> int:
    """Au demarrage : un job queued/running n'a plus de tache, on le passe en echec."""
    cost_module.reset_reservations()
    count = 0
    with _lock:
        jobs = _read_json(_jobs_path(), {})
        for job in jobs.values():
            if job.get("status") not in ("queued", "running"):
                continue
            count += 1
            job["status"] = "failed"
            for info in job["states"].values():
                if info["status"] in ("queued", "running"):
                    info["status"] = "failed"
                    info["error"] = INTERRUPTED_ERROR
            job["updated_at"] = _utcnow()
        if count:
            _write_json(_jobs_path(), jobs)
    return count


# ---------------------------------------------------------------------------
# Generation d'un etat
# ---------------------------------------------------------------------------
def _videos_dir(job_id: str) -> Path:
    return settings.data_dir() / "videos" / job_id


def _raw_path(job_id: str, state: str) -> Path:
    return _videos_dir(job_id) / f"{state}.raw.mp4"


def public_error(exc: Exception) -> str:
    """Message montre a l'utilisateur ; le detail technique reste dans les logs."""
    if isinstance(exc, fal_module.FalNotConfiguredError):
        return "FAL_KEY n'est pas configuree."
    if isinstance(exc, fal_module.FalApiError):
        code = f" (HTTP {exc.status_code})" if exc.status_code else ""
        return f"fal.ai a refuse ou rate la generation{code}. Detail dans les logs du serveur."
    if isinstance(exc, alpha.AlphaError):
        return "Le detourage du clip a echoue. Detail dans les logs du serveur."
    if isinstance(exc, httpx.HTTPError):
        return "Le telechargement du clip a echoue."
    return "Erreur interne. Detail dans les logs du serveur."


async def _download_video(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)


async def _download_with_retries(url: str, dest: Path) -> None:
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            await _download_video(url, dest)
            return
        except httpx.HTTPError:
            dest.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            await asyncio.sleep(attempt)


async def _generate_with_fallback(
    job_id: str, state: str, image_url: str, motion: str, duration_s: int | None = None
) -> str:
    """Genere le clip (principal puis fallback). Retourne l'URL fal du clip."""
    primary = settings.i2v_model()
    fallback = settings.fallback_model()
    models = [primary] + ([fallback] if fallback != primary else [])
    last_exc: Exception | None = None
    for model in models:
        try:
            video_url, used_model = await fal_module.generate_state_video(
                image_url, motion, model=model, duration_s=duration_s
            )
        except Exception as exc:  # on journalise, puis on tente le fallback
            last_exc = exc
            log.warning("job %s etat %s : echec sur %s : %r", job_id, state, model, exc)
            continue
        # Le clip est facture des qu'il existe, meme si la suite echoue.
        spent = get_job(job_id)["states"][state]["cost_usd"] + clip_cost_usd(used_model, duration_s)
        _update_state(
            job_id, state, model=used_model, source_url=video_url, cost_usd=round(spent, 4)
        )
        return video_url
    assert last_exc is not None
    raise last_exc


async def _generate_one_state(
    job_id: str, state: str, image_url: str, sem: asyncio.Semaphore
) -> None:
    async with sem:
        _update_state(job_id, state, status="running", error=None)
        info = get_job(job_id)["states"][state]
        raw = _raw_path(job_id, state)
        final = _videos_dir(job_id) / f"{state}.mp4"
        try:
            if not raw.is_file():
                downloaded = False
                if info.get("source_url"):  # clip deja paye : on le retelecharge
                    try:
                        await _download_with_retries(info["source_url"], raw)
                        downloaded = True
                    except httpx.HTTPError:
                        log.warning("job %s etat %s : URL fal expiree, on regenere", job_id, state)
                if not downloaded:
                    url = await _generate_with_fallback(
                        job_id, state, image_url, info["prompt"], info.get("duration_s")
                    )
                    await _download_with_retries(url, raw)
            extra: dict = {}
            if info.get("kind") == "look":
                if not alpha.available():
                    raise alpha.AlphaError("Le suivi du curseur demande ffmpeg pour analyser le clip.")
                # Une image cle par image : le widget saute a n'importe laquelle.
                await asyncio.to_thread(
                    alpha.to_stacked_alpha, raw, final, fps=settings.LOOK_FPS, all_intra=True
                )
                extra["look_map"] = await asyncio.to_thread(alpha.head_offsets, final)
                stacked = True
            elif alpha.available():
                await asyncio.to_thread(alpha.to_stacked_alpha, raw, final)
                stacked = True
            else:
                shutil.copyfile(raw, final)
                stacked = False
            _update_state(
                job_id, state, status="done", error=None, alpha=stacked,
                video_url=f"/videos/{job_id}/{state}.mp4", **extra,
            )
        except Exception as exc:
            log.exception("job %s etat %s : echec", job_id, state)
            _update_state(job_id, state, status="failed", error=public_error(exc))


async def run_job(job_id: str, only: list[str] | None = None, reserved_usd: float = 0.0) -> dict:
    """Genere les clips demandes (tous par defaut), puis comptabilise le cout reel."""
    before = get_job(job_id)
    was_done = before["status"] == "done" or before.get("completed_once", False)
    spent_before = before.get("actual_cost_usd", 0.0)
    try:
        character = get_character(before["character_id"])
        names = only or list(before["states"])
        _update_job(job_id, status="running")
        sem = asyncio.Semaphore(settings.I2V_PARALLELISM)
        await asyncio.gather(
            *(_generate_one_state(job_id, name, character["image_url"], sem) for name in names)
        )
    except Exception:
        log.exception("job %s : echec inattendu", job_id)
    finally:
        job = get_job(job_id)
        states = job["states"].values()
        final_status = "done" if all(s["status"] == "done" for s in states) else "failed"
        actual = round(sum(s.get("cost_usd", 0.0) for s in states), 4)
        alpha_mode = "stacked" if final_status == "done" and all(s.get("alpha") for s in states) else None
        _update_job(
            job_id, status=final_status, actual_cost_usd=actual, alpha=alpha_mode,
            completed_once=was_done or final_status == "done",
        )
        cost_module.release(reserved_usd)
        cost_module.add_spend(
            round(actual - spent_before, 4),
            mascots_completed=1 if final_status == "done" and not was_done else 0,
        )
    return get_job(job_id)
