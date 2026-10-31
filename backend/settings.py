"""Configuration du backend, lue depuis l'environnement.

Les lectures sont dynamiques (fonctions, pas constantes figees a l'import)
pour que les tests puissent surcharger les variables d'environnement.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Cle API fal.ai (UNE seule cle pour tout le pipeline)
# ---------------------------------------------------------------------------
def get_fal_key() -> str:
    """Retourne FAL_KEY, ou une chaine vide si elle est absente."""
    return os.environ.get("FAL_KEY", "").strip()


def fal_key_configured() -> bool:
    return bool(get_fal_key())


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
    """Image -> personnage 3D : modele OpenRouter qui lit les images, appele via fal.ai.

    Catalogue openrouter.ai/api/v1/models lu le 2026-10-31 : images en entree,
    2 $ par million de jetons en entree, 10 $ en sortie, contexte 1 M.
    """
    return os.environ.get("MASCOTFORGE_SPEC_MODEL", "anthropic/claude-sonnet-5.5")


SPEC_ENDPOINT = "openrouter/router/vision"  # endpoint fal.ai ; le cout reel revient dans usage.cost
SPEC_MAX_ROUNDS = 3  # passes modele + verificateur avant d'abandonner
SPEC_RESERVE_USD = 0.5  # reserve sous le plafond pendant une creation ; le cout reel est compte a la fin


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
