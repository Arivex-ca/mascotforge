"""Configuration du backend, lue depuis l'environnement.

Les lectures sont dynamiques (fonctions, pas constantes figees a l'import)
pour que les tests puissent surcharger les variables d'environnement.
"""
from __future__ import annotations

import os
from contextvars import ContextVar, Token
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_request_fal_key: ContextVar[str | None] = ContextVar(
    "mascotforge_request_fal_key", default=None
)
_request_openrouter_key: ContextVar[str | None] = ContextVar(
    "mascotforge_request_openrouter_key", default=None
)
_request_vision_provider: ContextVar[str] = ContextVar(
    "mascotforge_request_vision_provider", default="fal"
)


def _clean_key(value: str | None) -> str | None:
    clean = (value or "").strip()
    return clean or None


def bind_request_context(
    fal_key: str | None,
    openrouter_key: str | None,
    vision_provider: str | None,
) -> tuple[Token, Token, Token]:
    """Pose les secrets de la requete courante et retourne les jetons de reset."""
    provider = (vision_provider or "fal").strip().lower()
    if provider not in {"fal", "openrouter"}:
        provider = "fal"
    return (
        _request_fal_key.set(_clean_key(fal_key)),
        _request_openrouter_key.set(_clean_key(openrouter_key)),
        _request_vision_provider.set(provider),
    )


def reset_request_context(tokens: tuple[Token, Token, Token]) -> None:
    _request_fal_key.reset(tokens[0])
    _request_openrouter_key.reset(tokens[1])
    _request_vision_provider.reset(tokens[2])


# ---------------------------------------------------------------------------
# Cle API fal.ai (UNE seule cle pour tout le pipeline)
# ---------------------------------------------------------------------------
def get_fal_key() -> str:
    """Retourne la cle de la requete, puis FAL_KEY en repli local."""
    return _request_fal_key.get() or os.environ.get("FAL_KEY", "").strip()


def get_request_fal_key() -> str:
    """Retourne seulement la cle recue dans X-Fal-Key."""
    return _request_fal_key.get() or ""


def get_openrouter_key() -> str:
    """Retourne la cle OpenRouter de la requete, jamais une valeur persistee."""
    return _request_openrouter_key.get() or ""


def vision_provider() -> str:
    return _request_vision_provider.get()


def fal_key_configured() -> bool:
    """Etat de la cle du serveur uniquement, expose par /api/health."""
    return bool(os.environ.get("FAL_KEY", "").strip())


def fal_key_available() -> bool:
    return bool(get_fal_key())


def openrouter_key_available() -> bool:
    return bool(get_openrouter_key())


# ---------------------------------------------------------------------------
# Model IDs fal.ai (verifies le 2026-10-19, surchargeables par environnement)
# ---------------------------------------------------------------------------
def tti_model() -> str:
    """Text-to-image : personnage (Flux)."""
    return os.environ.get("MASCOTFORGE_TTI_MODEL", "fal-ai/flux/dev")


def i2v_model() -> str:
    """Image-to-video principal : Kling 3.0 standard."""
    return os.environ.get(
        "MASCOTFORGE_I2V_MODEL", "fal-ai/kling-video/v3/standard/image-to-video"
    )


def spec_model() -> str:
    """Image -> personnage 3D : modele OpenRouter qui lit les images.

    Catalogue openrouter.ai/api/v1/models lu le 2026-10-31 : images en entree,
    2 $ par million de jetons en entree, 10 $ en sortie, contexte 1 M.
    """
    return os.environ.get("MASCOTFORGE_SPEC_MODEL", "anthropic/claude-sonnet-5.5")


# Repli si OpenRouter omet usage.cost. Tarifs Claude Sonnet 5.5 verifies le
# 2026-11-01 : 2 $ / M jetons en entree, 10 $ / M jetons en sortie.
SPEC_INPUT_USD_PER_MILLION = 2.0
SPEC_OUTPUT_USD_PER_MILLION = 10.0


SPEC_ENDPOINT = "openrouter/router/vision"  # transport fal.ai ; le cout reel revient dans usage.cost
SPEC_MAX_ROUNDS = 3  # passes modele + verificateur avant d'abandonner
SPEC_VISUAL_ROUNDS = 2  # comparaisons du rendu avec l'image, apres la verification
SPEC_RESERVE_USD = 1.0  # reserve sous le plafond pendant une creation ; le cout reel est compte a la fin


def fallback_model() -> str:
    """Image-to-video de repli.

    NOTE : aucun endpoint fal.ai verifie n'existe pour Runway Gen-4.5
    (Runway expose sa propre API). Le fallback est donc configurable :
    on pourra y brancher Runway plus tard via sa propre cle.
    """
    return os.environ.get(
        "MASCOTFORGE_FALLBACK_MODEL", "fal-ai/kling-video/v3/pro/image-to-video"
    )


# ---------------------------------------------------------------------------
# Tarifs estimes (USD). A VERIFIER sur la page pricing fal.ai avant la prod.
# ---------------------------------------------------------------------------
COST_TTI_PER_IMAGE_USD = 0.025  # fal-ai/flux/dev, par image generee (a verifier)

# Par modele image-to-video, par seconde de video generee, audio coupe
# (fal.py envoie generate_audio=False ; avec audio, Kling 3.0 standard
# passe a 0,126 $/s, page tarif fal.ai lue le 2026-10-30).
I2V_RATES_USD_PER_SECOND = {
    "fal-ai/kling-video/v3/standard/image-to-video": 0.084,  # Kling 3.0 standard, verifie
    "fal-ai/kling-video/v3/pro/image-to-video": 0.140,  # Kling 3.0 pro, estimation
}


def i2v_rate_usd(model: str) -> float:
    """Tarif par seconde pour un modele image-to-video (defaut prudent)."""
    return I2V_RATES_USD_PER_SECOND.get(model, 0.10)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
VIDEO_DURATION_S = 3  # duree discrete Kling ("3" a "15")
LOOK_DURATION_S = 8  # clip du suivi du curseur : la tete regarde dans 4 directions
LOOK_FPS = 12  # images gardees pour le suivi (24 i/s doublerait le poids sans gain visible)
I2V_PARALLELISM = 3  # generations video en parallele, max 3


def sync_jobs() -> bool:
    """Si vrai, /api/generate attend la fin du job (utile pour les tests)."""
    return os.environ.get("MASCOTFORGE_SYNC_JOBS", "") == "1"


def fal_transport() -> str:
    """'sdk' (fal-client), 'rest' (HTTP manuel) ou 'auto' (sdk si dispo)."""
    return os.environ.get("MASCOTFORGE_FAL_TRANSPORT", "auto")


# ---------------------------------------------------------------------------
# Plafond de depenses mensuel
# ---------------------------------------------------------------------------
def monthly_cap_usd() -> float:
    try:
        return float(os.environ.get("MASCOTFORGE_MONTHLY_CAP_USD", "50"))
    except (TypeError, ValueError):
        return 50.0


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
def data_dir() -> Path:
    return Path(os.environ.get("MASCOTFORGE_DATA_DIR", str(PROJECT_ROOT / "data")))


def exports_dir() -> Path:
    return Path(
        os.environ.get("MASCOTFORGE_EXPORTS_DIR", str(PROJECT_ROOT / "exports"))
    )


def studio_dir() -> Path:
    return PROJECT_ROOT / "studio"


def widget_dir() -> Path:
    return PROJECT_ROOT / "widget"


def engines_dir() -> Path:
    """Moteurs open source des mascottes en code (voir engines/README.md)."""
    return PROJECT_ROOT / "engines"


def widget_source_file() -> Path:
    """Fichier source du widget V2 copie dans chaque export."""
    override = os.environ.get("MASCOTFORGE_WIDGET_FILE")
    if override:
        return Path(override)
    return widget_dir() / "mascot-avatar.js"
