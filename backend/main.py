"""MascotForge : API FastAPI (personnages, generation, export, couts)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import alpha
from backend import cost as cost_module
from backend import engines as engines_module
from backend import image3d
from backend import exporter, fal as fal_module
from backend import pipeline, settings
from backend import states as states_module
from backend.models import (
    CharacterFromPromptRequest,
    CharacterResponse,
    CostResponse,
    EngineExportRequest,
    ExportResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    JobResponse,
    PresetsResponse,
    RegenerateRequest,
    StateInfo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mascotforge.api")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Les taches de fond doivent rester referencees, sinon le ramasse-miettes
# peut les supprimer en cours de route (doc asyncio.create_task).
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    for directory in (
        settings.data_dir(),
        settings.data_dir() / "characters",
        settings.data_dir() / "videos",
        settings.exports_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    interrupted = pipeline.recover_interrupted_jobs() + image3d.recover_interrupted()
    if interrupted:
        log.warning("%s job(s) interrompu(s) par le redemarrage, passes en echec", interrupted)
    if not alpha.available():
        log.warning("ffmpeg absent : les clips resteront opaques (pas de detourage)")
    yield


app = FastAPI(title="MascotForge", version="0.3.0", lifespan=lifespan)


def _no_fal_key_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "FAL_KEY n'est pas configuree : cette operation necessite fal.ai. "
            "Ajoutez la variable d'environnement FAL_KEY puis reessayez."
        ),
    )


def _start(coro) -> None:  # type: ignore[no-untyped-def]
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _job_to_response(job: dict) -> JobResponse:
    return JobResponse(
        job_id=job["job_id"],
        character_id=job["character_id"],
        status=job["status"],
        default_state=job["default_state"],
        alpha=job.get("alpha"),
        states={
            state: StateInfo(
                status=info["status"],
                prompt=info["prompt"],
                loop=info["loop"],
                video_url=info.get("video_url"),
                model=info.get("model"),
                error=info.get("error"),
                kind=info.get("kind"),
            )
            for state, info in job["states"].items()
        },
        cost_usd_estimate=job["cost_usd_estimate"],
        actual_cost_usd=job.get("actual_cost_usd", 0.0),
    )


def _get_job_or_404(job_id: str) -> dict:
    try:
        return pipeline.get_job(job_id)
    except pipeline.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job introuvable.")


# ---------------------------------------------------------------------------
# Sante et presets
# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse)
def api_health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        fal_key_configured=settings.fal_key_configured(),
        ffmpeg_available=alpha.available(),
    )


@app.get("/api/presets", response_model=PresetsResponse)
def api_presets() -> PresetsResponse:
    return PresetsResponse(
        default=states_module.DEFAULT_PRESET,
        presets=states_module.PRESETS,
        cost_per_state_usd=pipeline.clip_cost_usd(settings.i2v_model()),
        look_cost_usd=pipeline.clip_cost_usd(settings.i2v_model(), settings.LOOK_DURATION_S),
        max_states=states_module.MAX_STATES,
    )


# ---------------------------------------------------------------------------
# Personnages
# ---------------------------------------------------------------------------
@app.post("/api/character/from-prompt", response_model=CharacterResponse)
async def api_character_from_prompt(body: CharacterFromPromptRequest) -> CharacterResponse:
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    price = settings.COST_TTI_PER_IMAGE_USD
    if not cost_module.reserve(price):
        raise HTTPException(status_code=429, detail=pipeline.cap_message(price))
    try:
        image_url = await fal_module.generate_character_image(
            fal_module.CHARACTER_PROMPT_PREFIX + body.prompt.strip()
        )
    except fal_module.FalNotConfiguredError:
        raise _no_fal_key_error()
    except fal_module.FalApiError as exc:
        log.warning("generation d'image echouee : %r", exc)
        raise HTTPException(status_code=502, detail="La generation d'image a echoue sur fal.ai.")
    finally:
        cost_module.release(price)
    cost_module.add_spend(price)
    character_id = pipeline.save_character(image_url)
    # Copie locale de l'image (optionnelle : on continue meme si ca echoue)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
        local = settings.data_dir() / "characters" / f"{character_id}.png"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(resp.content)
    except Exception:
        log.info("copie locale de l'image %s impossible", character_id)
    return CharacterResponse(character_id=character_id, image_url=image_url)


@app.post("/api/character/from-upload", response_model=CharacterResponse)
async def api_character_from_upload(file: UploadFile = File(...)) -> CharacterResponse:
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Format de fichier refuse : envoyez un PNG, JPG ou WEBP.",
        )
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier envoye est vide.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image trop lourde : 10 Mo maximum.")
    character_id = uuid.uuid4().hex[:12]
    dest = settings.data_dir() / "characters" / f"{character_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    to_send = dest
    if alpha.available():
        # Un PNG detoure passe sur fond vert : le detourage final le retirera.
        to_send = dest.with_name(f"{character_id}.green.png")
        try:
            await asyncio.to_thread(alpha.put_on_green, dest, to_send)
        except alpha.AlphaError:
            log.warning("image %s illisible par ffmpeg", character_id, exc_info=True)
            raise HTTPException(status_code=400, detail="Image illisible : envoyez un PNG, JPG ou WEBP valide.")
    try:
        image_url = await fal_module.upload_character_image(to_send)
    except fal_module.FalNotConfiguredError:
        raise _no_fal_key_error()
    except fal_module.FalApiError as exc:
        log.warning("upload fal echoue : %r", exc)
        raise HTTPException(status_code=502, detail="L'envoi de l'image vers fal.ai a echoue.")
    pipeline.save_character(image_url, local_path=str(to_send), character_id=character_id)
    return CharacterResponse(character_id=character_id, image_url=image_url)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@app.post("/api/generate", response_model=GenerateResponse)
async def api_generate(body: GenerateRequest) -> GenerateResponse:
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        if body.states is not None:
            requested = [s.model_dump() for s in body.states]
        else:
            requested = states_module.preset_states(body.usage or states_module.DEFAULT_PRESET)
        job_id, reserved = pipeline.create_job(body.character_id, requested)
    except pipeline.CharacterNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Personnage introuvable : verifiez le character_id.",
        )
    except states_module.InvalidStatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pipeline.CapExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if settings.sync_jobs():
        await pipeline.run_job(job_id, reserved_usd=reserved)
    else:
        _start(pipeline.run_job(job_id, reserved_usd=reserved))
    return GenerateResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def api_get_job(job_id: str) -> JobResponse:
    return _job_to_response(_get_job_or_404(job_id))


@app.post("/api/jobs/{job_id}/retry", response_model=GenerateResponse)
async def api_retry_job(job_id: str) -> GenerateResponse:
    _get_job_or_404(job_id)
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        names, reserved = pipeline.prepare_retry(job_id)
    except pipeline.NothingToRetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pipeline.CapExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if settings.sync_jobs():
        await pipeline.run_job(job_id, only=names, reserved_usd=reserved)
    else:
        _start(pipeline.run_job(job_id, only=names, reserved_usd=reserved))
    return GenerateResponse(job_id=job_id)


@app.post("/api/jobs/{job_id}/states/{state}/regenerate", response_model=GenerateResponse)
async def api_regenerate_state(job_id: str, state: str, body: RegenerateRequest) -> GenerateResponse:
    """Nouveau clip pour un seul etat, avec sa description actuelle ou une nouvelle."""
    job = _get_job_or_404(job_id)
    if state not in job["states"]:
        raise HTTPException(status_code=404, detail=f"L'etat {state!r} n'existe pas dans ce job.")
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        reserved = pipeline.prepare_regenerate(job_id, state, body.prompt)
    except pipeline.NothingToRetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except states_module.InvalidStatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pipeline.CapExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if settings.sync_jobs():
        await pipeline.run_job(job_id, only=[state], reserved_usd=reserved)
    else:
        _start(pipeline.run_job(job_id, only=[state], reserved_usd=reserved))
    return GenerateResponse(job_id=job_id)


@app.post("/api/jobs/{job_id}/look", response_model=GenerateResponse)
async def api_add_look(job_id: str, body: RegenerateRequest) -> GenerateResponse:
    """Ajoute (ou refait) le suivi du curseur d'une mascotte."""
    _get_job_or_404(job_id)
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        reserved = pipeline.prepare_look(job_id, body.prompt)
    except pipeline.NothingToRetryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except states_module.InvalidStatesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pipeline.CapExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    only = [states_module.LOOK_STATE]
    if settings.sync_jobs():
        await pipeline.run_job(job_id, only=only, reserved_usd=reserved)
    else:
        _start(pipeline.run_job(job_id, only=only, reserved_usd=reserved))
    return GenerateResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}/manifest.json")
def api_job_manifest(job_id: str):  # type: ignore[no-untyped-def]
    """Manifest du widget pour l'apercu du studio (clips servis par /videos)."""
    job = _get_job_or_404(job_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    return exporter.build_manifest(job, lambda s: f"/videos/{job_id}/{s}.mp4", generated_at)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@app.post("/api/export/{job_id}", response_model=ExportResponse)
def api_export(job_id: str) -> ExportResponse:
    job = _get_job_or_404(job_id)
    if job["status"] != "done":
        raise HTTPException(
            status_code=409,
            detail=(
                "Export impossible : le job n'est pas termine "
                f"(statut actuel : {job['status']}). Attendez la fin de la generation."
            ),
        )
    try:
        result = exporter.build_export(job)
    except exporter.ExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return ExportResponse(**result)


# ---------------------------------------------------------------------------
# Mascottes en code (moteurs open source, gratuites, sans fal.ai)
# ---------------------------------------------------------------------------
@app.get("/api/engines")
def api_engines() -> dict:
    return engines_module.public_catalog()


@app.post("/api/engines/3d/from-image")
async def api_spec_from_image(file: UploadFile = File(...)) -> dict:
    """Cree un personnage 3D Wobnimo d'apres une image. Suivi : GET /api/engines/3d/specs/{id}."""
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    if not image3d.available():
        raise HTTPException(
            status_code=503,
            detail="Node est introuvable : installe Node 18 ou plus pour creer un personnage 3D.",
        )
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Format de fichier refuse : envoyez un PNG, JPG ou WEBP.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier envoye est vide.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image trop lourde : 10 Mo maximum.")
    reserve = settings.SPEC_RESERVE_USD
    if not cost_module.reserve(reserve):
        raise HTTPException(status_code=429, detail=pipeline.cap_message(reserve))
    source = image3d.image_path_for(ext)
    source.write_bytes(content)
    spec_id = image3d.create_job(source)
    if settings.sync_jobs():
        await image3d.run_job(spec_id, reserve)
    else:
        _start(image3d.run_job(spec_id, reserve))
    return {"spec_id": spec_id}


@app.get("/api/engines/3d/specs/{spec_id}")
def api_spec_status(spec_id: str) -> dict:
    try:
        job = image3d.get_job(spec_id)
    except image3d.SpecNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    warnings = [i for i in job.get("issues", []) if i.get("level") == "warning"]
    return {
        "spec_id": job["id"], "status": job["status"], "error": job.get("error"),
        "name": job.get("name"), "rounds": job.get("rounds", 0),
        "visual_rounds": job.get("visual_rounds", 0),
        "warnings": len(warnings), "cost_usd": job.get("cost_usd", 0.0), "model": job.get("model"),
    }


@app.get("/api/engines/{engine}/manifest.json")
def api_engine_manifest(engine: str, request: Request):  # type: ignore[no-untyped-def]
    """Manifest d'apercu : les reglages arrivent en parametres de requete."""
    try:
        spec = engines_module.get_engine(engine)
        return engines_module.build_manifest(
            engine, dict(request.query_params), f"/engines/{spec['script']}", f"apercu-{engine}"
        )
    except engines_module.InvalidEngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/engines/{engine}/export", response_model=ExportResponse)
def api_engine_export(engine: str, body: EngineExportRequest) -> ExportResponse:
    try:
        result = exporter.build_engine_export(engine, body.config)
    except engines_module.InvalidEngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except exporter.ExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return ExportResponse(**result)


@app.get("/api/exports/{filename}")
def api_download_export(filename: str):  # type: ignore[no-untyped-def]
    safe = Path(filename).name
    if safe != filename or not safe.endswith(".zip"):
        raise HTTPException(status_code=404, detail="Export introuvable.")
    path = settings.exports_dir() / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export introuvable.")
    return FileResponse(path, media_type="application/zip", filename=safe)


# ---------------------------------------------------------------------------
# Videos generees (fichiers locaux)
# ---------------------------------------------------------------------------
@app.get("/videos/{job_id}/{filename}")
def serve_video(job_id: str, filename: str):  # type: ignore[no-untyped-def]
    safe = Path(filename).name
    if safe != filename or not safe.endswith(".mp4"):
        raise HTTPException(status_code=404, detail="Video introuvable.")
    path = settings.data_dir() / "videos" / Path(job_id).name / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video introuvable.")
    return FileResponse(path, media_type="video/mp4")


# ---------------------------------------------------------------------------
# Couts
# ---------------------------------------------------------------------------
@app.get("/api/cost", response_model=CostResponse)
def api_cost() -> CostResponse:
    return CostResponse(**cost_module.get_status())


# ---------------------------------------------------------------------------
# Studio et widget (fichiers statiques, si presents)
# ---------------------------------------------------------------------------
@app.get("/")
def root():  # type: ignore[no-untyped-def]
    index = settings.studio_dir() / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    return JSONResponse(
        status_code=404,
        content={"detail": "Studio non disponible : ajoutez studio/index.html au projet."},
    )


if settings.widget_dir().is_dir():
    app.mount("/widget", StaticFiles(directory=settings.widget_dir(), html=True), name="widget")

if settings.engines_dir().is_dir():
    app.mount("/engines", StaticFiles(directory=settings.engines_dir()), name="engines")

if settings.studio_dir().is_dir():
    # Sert index.html + ses assets (style.css, studio.js) : sans ce montage,
    # la route "/" ci-dessus ne servait que le HTML et le studio arrivait
    # sans CSS ni JS (404 sur les chemins relatifs).
    # Les routes /api/* et /widget definies plus haut restent prioritaires.
    app.mount("/", StaticFiles(directory=settings.studio_dir(), html=True), name="studio")
