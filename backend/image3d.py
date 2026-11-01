"""Image -> personnage 3D Wobnimo.

Un modele qui lit les images (via fal.ai ou OpenRouter direct)
regarde l'image et ecrit la fiche Wobnimo (CharacterSpec, en JSON) en suivant
le guide du projet Wobnimo (engines/wobnimo/skill/). Le verificateur de Wobnimo
(engines/wobnimo/dist/cli.js, lance avec Node) mesure la vraie forme 3D ; ses
erreurs et leurs corrections exactes repartent au modele, jusqu'a
SPEC_MAX_ROUNDS passes. Le verificateur ne juge pas la ressemblance : le
serveur fait donc le rendu de la fiche et le modele le compare a l'image,
jusqu'a SPEC_VISUAL_ROUNDS fois. La fiche s'affiche dans <wobnimo-mascot> (el.spec).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
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
from backend import openrouter
from backend import settings
from backend.pipeline import public_error

log = logging.getLogger("mascotforge.image3d")
_lock = threading.Lock()

ID_RE = re.compile(r"^[a-f0-9]{12}$")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
CHECK_TIMEOUT_S = 90
RENDER_TIMEOUT_S = 180
RENDER_SIZE = 200  # cote de chaque vue sur la planche envoyee au modele
INTERRUPTED_ERROR = "Creation interrompue par un redemarrage du serveur. Relance-la."


class Image3DError(RuntimeError):
    """Echec public (le message s'affiche dans le studio)."""


class SpecNotFoundError(LookupError):
    pass


class AgentSpecValidationError(ValueError):
    """Fiche ecrite par un agent qui contient encore des erreurs."""

    def __init__(self, issues: list[dict]) -> None:
        super().__init__("La fiche Wobnimo contient encore des erreurs.")
        self.issues = issues


# ---------------------------------------------------------------------------
# Node et le verificateur Wobnimo
# ---------------------------------------------------------------------------
def node_bin() -> str | None:
    return os.environ.get("MASCOTFORGE_NODE") or shutil.which("node")


def checker_path() -> Path:
    return settings.engines_dir() / "wobnimo" / "dist" / "cli.js"


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


class RenderError(RuntimeError):
    """Rendu impossible (pas de navigateur, delai depasse) : la comparaison est sautee."""


def render_sheet(spec: dict, out: Path) -> Path:
    """Planche de rendu Wobnimo (vues et etats) avec `wobnimo preview`, qui ouvre
    Chrome ou Edge sans fenetre. MASCOTFORGE_BROWSER donne son chemin s'il n'est
    pas trouve tout seul. Leve RenderError."""
    exe = node_bin()
    if not exe:
        raise RenderError("Node est introuvable.")
    env = dict(os.environ)
    if os.environ.get("MASCOTFORGE_BROWSER"):
        env["WOBNIMO_BROWSER"] = os.environ["MASCOTFORGE_BROWSER"]
    with tempfile.TemporaryDirectory(prefix="mascotforge-rendu-") as tmp:
        path = Path(tmp) / "spec.mjs"
        path.write_text("export default " + json.dumps(spec) + ";\n", encoding="utf-8")
        try:
            proc = subprocess.run(
                [exe, str(checker_path()), "preview", str(path), "--out", str(out), "--size", str(RENDER_SIZE)],
                capture_output=True, text=True, encoding="utf-8", timeout=RENDER_TIMEOUT_S, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"rendu plus long que {RENDER_TIMEOUT_S} s") from exc
    if proc.returncode != 0 or not out.is_file():
        raise RenderError((proc.stderr or proc.stdout or "").strip()[-300:] or f"code {proc.returncode}")
    return out


def wobnimo_id(spec_id: str) -> str:
    """L'identifiant donne a Wobnimo : il doit commencer par une lettre, nos numeros non."""
    return f"img-{spec_id}"


def _counts(issues: list[dict]) -> tuple[int, int]:
    errors = sum(1 for i in issues if i.get("level") == "error")
    warnings = sum(1 for i in issues if i.get("level") == "warning")
    return errors, warnings


def _agent_spec(spec: dict, spec_id: str) -> dict:
    """Copie une fiche JSON et remplace son identifiant par celui du serveur."""
    normalized = json.loads(json.dumps(spec))
    normalized["id"] = wobnimo_id(spec_id)
    return normalized


# ---------------------------------------------------------------------------
# Ce que lit le modele
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def agent_guide() -> str:
    """Guide autonome donne aux agents qui ecrivent eux-memes une fiche."""
    skill = settings.engines_dir() / "wobnimo" / "skill"
    guide = (skill / "SKILL.md").read_text(encoding="utf-8")
    reference = (skill / "spec.md").read_text(encoding="utf-8")
    example = (skill / "volt.json").read_text(encoding="utf-8")
    return (
        "# Creer gratuitement une fiche Wobnimo dans MascotForge\n\n"
        "Boucle obligatoire : regarde l'image de reference, lis ce guide, ecris une fiche, "
        "lance le check, affiche la planche, compare sa vue de face a l'image, corrige, puis "
        "enregistre ou exporte. Recommence le check et la preview apres chaque correction.\n\n"
        "Regles propres a MascotForge :\n"
        "- Le serveur impose l'identifiant final. La valeur `id` envoyee est ignoree.\n"
        "- La fiche est un objet JSON pur. Aucun code, commentaire, fonction ou expression.\n"
        "- La fiche doit contenir une liste `parts`.\n"
        "- La planche place la vue de face au repos en haut a gauche. C'est la vue principale "
        "a comparer a l'image de reference.\n"
        "- Le moteur dessine lui-meme les yeux et la bouche de l'ecran LED. Ne tente pas de "
        "reproduire leurs formes dans les pieces de la fiche.\n"
        "- Le check mesure la geometrie, mais pas la ressemblance. La comparaison visuelle de "
        "la preview reste indispensable.\n\n"
        f"<wobnimo-skill>\n{guide}\n</wobnimo-skill>\n\n"
        f"<wobnimo-spec-reference>\n{reference}\n</wobnimo-spec-reference>\n\n"
        f"<volt-example>\n{example}\n</volt-example>\n"
    )


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


def visual_prompt(spec: dict) -> str:
    return (
        "Image 1 is the reference. Image 2 is a render of your current spec: the top-left picture is "
        "the front view in idle; the others show the three-quarter, side and back views, a face "
        "close-up and the other states.\n\n"
        "Compare the front view with the reference: silhouette, proportions (head size and shape "
        "against the body), colours, and features that are missing, extra or misplaced. A coloured "
        "reflection or glow on a white surface is not the colour of that surface. The engine draws "
        "the LED screen face itself: ignore the shapes of its eyes and mouth.\n\n"
        "If the front view already matches the reference well, reply with exactly OK. Otherwise list "
        "the differences in a few short lines, then return the full corrected CharacterSpec in one "
        "```json block, changing only what brings it closer to the reference.\n\n"
        f"Your current spec:\n```json\n{json.dumps(spec)}\n```"
    )


def matches_reference(text: str) -> bool:
    """Le modele a repondu OK, sans fiche corrigee."""
    return text.strip().upper().startswith("OK") and not JSON_BLOCK_RE.search(text)


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
            "issues": [], "rounds": 0, "visual_rounds": 0, "cost_usd": 0.0,
            "cost_estimated": False, "model": settings.spec_model(),
            "image_path": str(image_path), "image_url": None, "created_at": _utcnow(),
        })
    return spec_id


def check_agent_spec(spec: dict, spec_id: str = "agent-draft") -> dict:
    """Verifie une fiche d'agent avec un identifiant controle par le serveur."""
    return check_spec(_agent_spec(spec, spec_id))


def render_agent_sheet(spec: dict) -> bytes:
    """Rend la planche d'une fiche d'agent et renvoie son PNG."""
    with tempfile.TemporaryDirectory(prefix="mascotforge-agent-rendu-") as tmp:
        out = Path(tmp) / "planche.png"
        render_sheet(_agent_spec(spec, "agent-draft"), out)
        return out.read_bytes()


def create_agent_spec(spec: dict) -> dict:
    """Verifie et conserve gratuitement une fiche ecrite par un agent."""
    spec_id = uuid.uuid4().hex[:12]
    normalized = _agent_spec(spec, spec_id)
    report = check_spec(normalized)
    issues = report["issues"]
    errors, _warnings = _counts(issues)
    if errors:
        raise AgentSpecValidationError(issues)
    job = {
        "id": spec_id,
        "source": "agent",
        "status": "done",
        "error": None,
        "name": str(normalized.get("name") or "Mascotte"),
        "spec": normalized,
        "issues": issues,
        "rounds": 0,
        "visual_rounds": 0,
        "cost_usd": 0.0,
        "cost_estimated": False,
        "model": None,
        "image_path": None,
        "image_url": None,
        "created_at": _utcnow(),
    }
    with _lock:
        _save(job)
    return job


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


def _data_url(path: Path) -> str:
    """Encode une image locale sans l'envoyer vers un stockage tiers."""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def _ask(
    spec_id: str,
    image_urls: list[str],
    prompt: str,
    spent: float,
    cost_estimated: bool,
) -> tuple[str, float, bool]:
    """Un appel au modele ; le cout reel s'ajoute au total de la creation."""
    if settings.vision_provider() == "openrouter":
        text, cost, call_estimated = await openrouter.describe_image(
            image_urls, system_prompt(), prompt
        )
    else:
        text, cost = await fal_module.describe_image(image_urls, system_prompt(), prompt)
        call_estimated = False
    spent += cost
    cost_estimated = cost_estimated or call_estimated
    _update(
        spec_id,
        cost_usd=round(spent, 4),
        cost_estimated=cost_estimated,
    )
    return text, spent, cost_estimated


async def _until_checked(
    spec_id: str,
    image_urls: list[str],
    text: str,
    calls_left: int,
    spent: float,
    cost_estimated: bool,
) -> tuple[dict | None, list[dict], float, int, bool]:
    """Lit la fiche de `text` et la verifie ; tant qu'il reste des problemes et des
    appels, renvoie le rapport au modele. Retourne (fiche ou None, rapport, cout, appels faits)."""
    spec: dict | None = None
    issues: list[dict] = []
    calls = 0
    while True:
        try:
            spec = extract_spec(text)
        except ValueError as exc:
            spec, issues = None, []
            prompt = retry_prompt(str(exc)[:200])
        else:
            spec["id"] = wobnimo_id(spec_id)  # identifiant stable, quel que soit ce qu'ecrit le modele
            issues = (await asyncio.to_thread(check_spec, spec))["issues"]
            if _counts(issues) == (0, 0):
                return spec, issues, spent, calls, cost_estimated
            prompt = fix_prompt(spec, issues)
        if calls >= calls_left:
            return spec, issues, spent, calls, cost_estimated
        text, spent, cost_estimated = await _ask(
            spec_id, image_urls, prompt, spent, cost_estimated
        )
        calls += 1


async def run_job(spec_id: str, reserved_usd: float) -> dict:
    """Image -> fiche -> verificateur -> comparaison du rendu avec l'image, puis cout reel."""
    spent = 0.0
    cost_estimated = False
    try:
        job = _update(spec_id, status="running")
        source = Path(job["image_path"])
        if settings.vision_provider() == "openrouter":
            image_url = _data_url(source)
        else:
            image_url = await fal_module.upload_character_image(source)
            _update(spec_id, image_url=image_url)

        # 1. Le modele ecrit la fiche ; le verificateur la corrige jusqu'a ce qu'elle tienne.
        text, spent, cost_estimated = await _ask(
            spec_id,
            [image_url],
            first_prompt(wobnimo_id(spec_id)),
            spent,
            cost_estimated,
        )
        spec, issues, spent, calls, cost_estimated = await _until_checked(
            spec_id,
            [image_url],
            text,
            settings.SPEC_MAX_ROUNDS - 1,
            spent,
            cost_estimated,
        )
        _update(spec_id, rounds=1 + calls, spec=spec, issues=issues,
                name=str((spec or {}).get("name") or "Mascotte"))
        if spec is None or _counts(issues)[0]:
            raise Image3DError(
                "Le personnage 3D n'a pas passe la verification de Wobnimo apres "
                f"{settings.SPEC_MAX_ROUNDS} essais. Relance avec une image plus nette ou plus simple."
            )

        # 2. Le modele voit le rendu de sa fiche a cote de l'image et corrige la ressemblance.
        visual = 0
        while visual < settings.SPEC_VISUAL_ROUNDS:
            try:
                sheet = await asyncio.to_thread(render_sheet, spec, _dir() / f"{spec_id}-rendu-{visual + 1}.png")
                if settings.vision_provider() == "openrouter":
                    render_url = _data_url(sheet)
                else:
                    render_url = await fal_module.upload_character_image(sheet)
            except RenderError as exc:
                log.warning("personnage 3D %s : comparaison sautee, rendu impossible (%s)", spec_id, exc)
                break
            visual += 1
            text, spent, cost_estimated = await _ask(
                spec_id,
                [image_url, render_url],
                visual_prompt(spec),
                spent,
                cost_estimated,
            )
            _update(spec_id, visual_rounds=visual)
            if matches_reference(text):
                break
            candidate, candidate_issues, spent, _, cost_estimated = await _until_checked(
                spec_id, [image_url], text, 1, spent, cost_estimated
            )
            if candidate is None or _counts(candidate_issues)[0]:
                log.warning("personnage 3D %s : correction visuelle refusee, fiche precedente gardee", spec_id)
                break
            spec, issues = candidate, candidate_issues
            _update(spec_id, spec=spec, issues=issues, name=str(spec.get("name") or "Mascotte"))

        return _update(
            spec_id,
            status="done",
            error=None,
            spec=spec,
            issues=issues,
            cost_usd=round(spent, 4),
            cost_estimated=cost_estimated,
        )
    except Exception as exc:
        log.exception("personnage 3D %s : echec", spec_id)
        message = str(exc) if isinstance(exc, Image3DError) else public_error(exc)
        return _update(
            spec_id,
            status="failed",
            error=message,
            cost_usd=round(spent, 4),
            cost_estimated=cost_estimated,
        )
    finally:
        cost_module.release(reserved_usd)
        cost_module.add_spend(round(spent, 4))
