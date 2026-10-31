"""Schemas pydantic de l'API MascotForge."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterFromPromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)


class CharacterResponse(BaseModel):
    character_id: str
    image_url: str


class StateSpec(BaseModel):
    name: str
    prompt: str
    loop: bool = True


class GenerateRequest(BaseModel):
    character_id: str
    usage: str | None = None  # preset (agent, site, complet) si states est absent
    states: list[StateSpec] | None = None


class GenerateResponse(BaseModel):
    job_id: str


class RegenerateRequest(BaseModel):
    prompt: str | None = None  # nouvelle description ; absente : on garde l'ancienne


class StateInfo(BaseModel):
    status: str  # queued | running | done | failed
    prompt: str
    loop: bool
    video_url: str | None = None
    model: str | None = None
    error: str | None = None
    kind: str | None = None  # "look" : clip du suivi du curseur, pas un etat jouable


class JobResponse(BaseModel):
    job_id: str
    character_id: str
    status: str  # queued | running | done | failed
    default_state: str
    alpha: str | None  # "stacked" quand tous les clips sont detoures
    states: dict[str, StateInfo]
    cost_usd_estimate: float
    actual_cost_usd: float


class ExportResponse(BaseModel):
    filename: str
    download_url: str


class CostResponse(BaseModel):
    month: str
    spent_usd: float
    reserved_usd: float
    cap_usd: float
    mascots_completed: int


class HealthResponse(BaseModel):
    ok: bool
    fal_key_configured: bool
    ffmpeg_available: bool


class PresetsResponse(BaseModel):
    default: str
    presets: dict[str, dict]
    cost_per_state_usd: float
    look_cost_usd: float  # clip du suivi du curseur (plus long qu'un etat)
    max_states: int
