"""Schemas pydantic de l'API MascotForge V2."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterFromPromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)


class CharacterResponse(BaseModel):
    character_id: str
    image_url: str


class GenerateRequest(BaseModel):
    character_id: str


class GenerateResponse(BaseModel):
    job_id: str


class StateInfo(BaseModel):
    status: str  # queued | running | done | failed
    video_url: str | None = None
    model: str | None = None
    error: str | None = None


class JobResponse(BaseModel):
    job_id: str
    character_id: str
    status: str  # queued | running | done | failed
    states: dict[str, StateInfo]
    cost_usd_estimate: float


class ExportResponse(BaseModel):
    filename: str
    download_url: str


class CostResponse(BaseModel):
    month: str
    spent_usd: float
    cap_usd: float
    mascots_completed: int


class HealthResponse(BaseModel):
    ok: bool
    fal_key_configured: bool
