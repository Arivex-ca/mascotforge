"""MascotForge V2 : API FastAPI (personnages, generation, export, couts)."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import cost as cost_module
from backend import exporter, fal as fal_module
from backend import pipeline, settings
from backend.models import (
    CharacterFromPromptRequest,
    CharacterResponse,
    CostResponse,
    ExportResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    JobResponse,
    StateInfo,
)

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    for directory in (
        settings.data_dir(),
        settings.data_dir() / "characters",
        settings.data_dir() / "videos",
        settings.exports_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="MascotForge V2", version="0.1.0", lifespan=lifespan)


def _no_fal_key_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "FAL_KEY n'est pas configuree : cette operation necessite fal.ai. "
            "Ajoutez la variable d'environnement FAL_KEY puis reessayez."
        ),
    )


def _job_to_response(job: dict) -> JobResponse:
    return JobResponse(
        job_id=job["job_id"],
        character_id=job["character_id"],
        status=job["status"],
        states={
            state: StateInfo(
                status=info["status"],
                video_url=info.get("video_url"),
                model=info.get("model"),
                error=info.get("error"),
            )
            for state, info in job["states"].items()
        },
        cost_usd_estimate=job["cost_usd_estimate"],
    )


# ---------------------------------------------------------------------------
# Sante
# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse)
def api_health() -> HealthResponse:
    return HealthResponse(ok=True, fal_key_configured=settings.fal_key_configured())


# ---------------------------------------------------------------------------
# Personnages
# ---------------------------------------------------------------------------
@app.post("/api/character/from-prompt", response_model=CharacterResponse)
async def api_character_from_prompt(body: CharacterFromPromptRequest) -> CharacterResponse:
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        image_url = await fal_module.generate_character_image(
            fal_module.CHARACTER_PROMPT_PREFIX + body.prompt.strip()
        )
    except fal_module.FalNotConfiguredError:
        raise _no_fal_key_error()
    except fal_module.FalApiError as exc:
        raise HTTPException(
            status_code=502, detail=f"La generation d'image a echoue : {exc}"
        )
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
        pass
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
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier envoye est vide.")
    character_id = uuid.uuid4().hex[:12]
    dest = settings.data_dir() / "characters" / f"{character_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    try:
        image_url = await fal_module.upload_character_image(dest)
    except fal_module.FalNotConfiguredError:
        raise _no_fal_key_error()
    except fal_module.FalApiError as exc:
        raise HTTPException(
            status_code=502, detail=f"L'envoi de l'image vers fal.ai a echoue : {exc}"
        )
    pipeline.save_character(image_url, local_path=str(dest), character_id=character_id)
    return CharacterResponse(character_id=character_id, image_url=image_url)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@app.post("/api/generate", response_model=GenerateResponse)
async def api_generate(body: GenerateRequest) -> GenerateResponse:
    if not settings.fal_key_configured():
        raise _no_fal_key_error()
    try:
        job_id = pipeline.create_job(body.character_id)
    except pipeline.CharacterNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Personnage introuvable : verifiez le character_id.",
        )
    except pipeline.CapExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if settings.sync_jobs():
        await pipeline.run_job(job_id)
    else:
        asyncio.create_task(pipeline.run_job(job_id))
    return GenerateResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def api_get_job(job_id: str) -> JobResponse:
    try:
        job = pipeline.get_job(job_id)
    except pipeline.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    return _job_to_response(job)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@app.post("/api/export/{job_id}", response_model=ExportResponse)
def api_export(job_id: str) -> ExportResponse:
    try:
        job = pipeline.get_job(job_id)
    except pipeline.JobNotFoundError:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    if job["status"] != "done":
        raise HTTPException(
            status_code=404,
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

if settings.studio_dir().is_dir():
    # Sert index.html + ses assets (style.css, studio.js) : sans ce montage,
    # la route "/" ci-dessus ne servait que le HTML et le studio arrivait
    # sans CSS ni JS (404 sur les chemins relatifs).
    # Les routes /api/* et /widget definies plus haut restent prioritaires.
    app.mount("/", StaticFiles(directory=settings.studio_dir(), html=True), name="studio")
