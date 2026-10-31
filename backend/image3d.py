"""Image -> personnage 3D Wobnimo.

Un modele qui lit les images (via fal.ai, endpoint openrouter/router/vision)
regarde l'image et ecrit la fiche Wobnimo (CharacterSpec, en JSON) en suivant
le guide du projet Wobnimo (engines/wobnimo/skill/). Le verificateur de Wobnimo
(engines/wobnimo/cli.mjs, lance avec Node) mesure la vraie forme 3D ; ses
erreurs et leurs corrections exactes repartent au modele, jusqu'a
SPEC_MAX_ROUNDS passes. La fiche validee s'affiche dans <wobnimo-mascot> (el.spec).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from backend import cost as cost_module
from backend import fal as fal_module
from backend import settings
from backend.pipeline import public_error

log = logging.getLogger("mascotforge.image3d")
_lock = threading.Lock()

ID_RE = re.compile(r"^[a-f0-9]{12}$")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
CHECK_TIMEOUT_S = 90
INTERRUPTED_ERROR = "Creation interrompue par un redemarrage du serveur. Relance-la."


class Image3DError(RuntimeError):
    """Echec public (le message s'affiche dans le studio)."""


class SpecNotFoundError(LookupError):
    pass


# ---------------------------------------------------------------------------
# Node et le verificateur Wobnimo
# ---------------------------------------------------------------------------
def node_bin() -> str | None:
    return os.environ.get("MASCOTFORGE_NODE") or shutil.which("node")


def checker_path() -> Path:
    return settings.engines_dir() / "wobnimo" / "cli.mjs"


def available() -> bool:
    return bool(node_bin()) and checker_path().is_file()


def check_spec(spec: dict) -> dict:
    """Lance `wobnimo check` sur la fiche. Retourne {"ok", "issues": [...]}.

    Un plantage du verificateur (fiche mal formee) devient une erreur a
    corriger, pour que le modele la voie au tour suivant.
    """
    exe = node_bin()
    if not exe:
        raise Image3DError("Node est introuvable : installe Node 18 ou plus pour creer un personnage 3D.")
    with tempfile.TemporaryDirectory(prefix="mascotforge-spec-") as tmp:
        path = Path(tmp) / "spec.mjs"
        path.write_text("export default " + json.dumps(spec) + ";\n", encoding="utf-8")
        proc = subprocess.run(
            [exe, str(checker_path()), "check", str(path), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=CHECK_TIMEOUT_S,
        )
    try:
        report = json.loads(proc.stdout)
        return {"ok": bool(report.get("ok")), "issues": list(report.get("issues") or [])}
    except (json.JSONDecodeError, AttributeError):
        detail = (proc.stderr or proc.stdout or "sortie vide").strip()[-600:]
        log.warning("verificateur Wobnimo illisible (code %s) : %s", proc.returncode, detail)
        return {"ok": False, "issues": [
            {"level": "error", "where": "spec", "message": f"The checker could not load the spec: {detail}", "fix": ""},
        ]}


def _counts(issues: list[dict]) -> tuple[int, int]:
    errors = sum(1 for i in issues if i.get("level") == "error")
    warnings = sum(1 for i in issues if i.get("level") == "warning")
    return errors, warnings


# ---------------------------------------------------------------------------
# Ce que lit le modele
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def system_prompt() -> str:
    skill = settings.engines_dir() / "wobnimo" / "skill"
    guide = (skill / "SKILL.md").read_text(encoding="utf-8")
    reference = (skill / "spec.md").read_text(encoding="utf-8")
    example = (skill / "volt.json").read_text(encoding="utf-8")
    return (
        "You design mascots for the Wobnimo engine. You look at the reference image and write ONE "
        "CharacterSpec as JSON: plain data only, numbers instead of expressions (no Math.PI, no "
        "functions, no comments).\n\n"
        "Goal: someone who knows the image recognises the character from the front: same silhouette, "
        "same signature feature, same colours and proportions, in the engine's smooth rounded style. "
        "Plan first (silhouette, signature feature, palette), then write the spec.\n\n"
        "You cannot run commands. We run `wobnimo check` on your spec and send you its report; apply "
        "every `fix:` exactly. Skip the guide's steps about the CLI, the preview file and wiring.\n\n"
        "Answer with one ```json block that contains the whole CharacterSpec object, and nothing after it.\n\n"
        f"<guide>\n{guide}\n</guide>\n\n<reference>\n{reference}\n</reference>\n\n"
        f"<example name=\"volt\" note=\"a hand-built robot, as JSON\">\n{example}\n</example>\n"
    )


def first_prompt(spec_id: str) -> str:
    return (
        "Here is the reference image. Design this character as a Wobnimo mascot and write its "
        f'CharacterSpec. Use id "{spec_id}". Give it a short English name and tagline.'
    )


def fix_prompt(spec: dict, issues: list[dict]) -> str:
    report = "\n".join(
        f"{i.get('level')} {i.get('where')}: {i.get('message')}" + (f"\n  fix: {i['fix']}" if i.get("fix") else "")
        for i in issues if i.get("level") in ("error", "warning")
    )
    return (
        "The checker found these problems in your spec. Apply every fix exactly, keep everything "
        "else, and return the full corrected CharacterSpec.\n\n"
        f"Your spec:\n```json\n{json.dumps(spec)}\n```\n\nReport:\n{report}"
    )


def retry_prompt(error: str) -> str:
    return (
        f"Your answer was not a valid JSON object ({error}). Return only the full CharacterSpec "
        "in one ```json block."
    )


def extract_spec(text: str) -> dict:
    """Le JSON du bloc ```json (ou le premier objet du texte). Leve ValueError."""
    match = JSON_BLOCK_RE.search(text)
    raw = match.group(1) if match else text[text.find("{"): text.rfind("}") + 1]
    spec = json.loads(raw)
    if not isinstance(spec, dict) or not isinstance(spec.get("parts"), list):
        raise ValueError("no CharacterSpec object with a parts list")
    return spec


# ---------------------------------------------------------------------------
# Creations (une fiche JSON par creation, dans data/specs/)
# ---------------------------------------------------------------------------
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir() -> Path:
    path = settings.data_dir() / "specs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(spec_id: str) -> Path:
    if not ID_RE.match(spec_id):
        raise SpecNotFoundError(f"Personnage 3D {spec_id!r} introuvable.")
    return _dir() / f"{spec_id}.json"


def get_job(spec_id: str) -> dict:
    path = _path(spec_id)
    if not path.is_file():
        raise SpecNotFoundError(f"Personnage 3D {spec_id!r} introuvable.")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(job: dict) -> None:
    job["updated_at"] = _utcnow()
    path = _path(job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    tmp.replace(path)


def _update(spec_id: str, **fields) -> dict:  # type: ignore[no-untyped-def]
    with _lock:
        job = get_job(spec_id)
        job.update(fields)
        _save(job)
        return job


def create_job(image_path: Path) -> str:
    """Enregistre une creation en file d'attente. L'image est deja copiee dans data/specs/."""
    spec_id = uuid.uuid4().hex[:12]
    with _lock:
        _save({
            "id": spec_id, "status": "queued", "error": None, "name": None, "spec": None,
            "issues": [], "rounds": 0, "cost_usd": 0.0, "model": settings.spec_model(),
            "image_path": str(image_path), "image_url": None, "created_at": _utcnow(),
        })
    return spec_id


def image_path_for(suffix: str) -> Path:
    return _dir() / f"source-{uuid.uuid4().hex[:12]}{suffix}"


def done_spec(spec_id: str) -> dict:
    """La fiche d'une creation terminee. Leve SpecNotFoundError sinon."""
    job = get_job(spec_id)
    if job["status"] != "done" or not job.get("spec"):
        raise SpecNotFoundError(f"Le personnage 3D {spec_id!r} n'est pas pret.")
    return job["spec"]


def recover_interrupted() -> int:
    """Au demarrage : une creation en cours n'a plus de tache, on la passe en echec."""
    count = 0
    with _lock:
        for path in _dir().glob("*.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") in ("queued", "running"):
                job.update(status="failed", error=INTERRUPTED_ERROR)
                _save(job)
                count += 1
    return count


async def run_job(spec_id: str, reserved_usd: float) -> dict:
    """Image -> fiche -> verificateur -> corrections, puis comptabilise le cout reel."""
    spent = 0.0
    try:
        job = _update(spec_id, status="running")
        image_url = await fal_module.upload_character_image(Path(job["image_path"]))
        _update(spec_id, image_url=image_url)
        prompt = first_prompt(spec_id)
        spec: dict | None = None
        issues: list[dict] = []
        for round_no in range(1, settings.SPEC_MAX_ROUNDS + 1):
            text, cost = await fal_module.describe_image(image_url, system_prompt(), prompt)
            spent += cost
            try:
                spec = extract_spec(text)
            except ValueError as exc:
                prompt = retry_prompt(str(exc)[:200])
                _update(spec_id, rounds=round_no, cost_usd=round(spent, 4))
                continue
            spec["id"] = spec_id  # identifiant stable, quel que soit ce qu'ecrit le modele
            report = await asyncio.to_thread(check_spec, spec)
            issues = report["issues"]
            errors, warnings = _counts(issues)
            _update(spec_id, rounds=round_no, cost_usd=round(spent, 4), spec=spec, issues=issues,
                    name=str(spec.get("name") or "Mascotte"))
            if errors == 0 and warnings == 0:
                break
            prompt = fix_prompt(spec, issues)
        errors, _ = _counts(issues)
        if spec is None or errors:
            raise Image3DError(
                "Le personnage 3D n'a pas passe la verification de Wobnimo apres "
                f"{settings.SPEC_MAX_ROUNDS} essais. Relance avec une image plus nette ou plus simple."
            )
        return _update(spec_id, status="done", error=None, cost_usd=round(spent, 4))
    except Exception as exc:
        log.exception("personnage 3D %s : echec", spec_id)
        message = str(exc) if isinstance(exc, Image3DError) else public_error(exc)
        return _update(spec_id, status="failed", error=message, cost_usd=round(spent, 4))
    finally:
        cost_module.release(reserved_usd)
        cost_module.add_spend(round(spent, 4))
