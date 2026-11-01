"""Client fal.ai : upload d'image, text-to-image, image-to-video.

Transport principal : le package ``fal-client`` (upload + file d'attente geres).
Repli : appels REST manuels vers queue.fal.run (``MASCOTFORGE_FAL_TRANSPORT=rest``,
ou automatiquement si fal-client n'est pas installe).

Toutes les fonctions publiques sont ``async`` et mockables par les tests
(monkeypatch de ce module). Aucune video reelle n'est generee sans FAL_KEY.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from backend import settings


class FalNotConfiguredError(RuntimeError):
    """Levee quand FAL_KEY est absente (l'API repond 503)."""


class FalApiError(RuntimeError):
    """Levee quand l'appel fal.ai echoue (l'API repond 502)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Prompts (anglais). Le fond vert uni sert au detourage (backend/alpha.py).
# ---------------------------------------------------------------------------
CHARACTER_PROMPT_PREFIX = (
    "Mascot character, full body, centered, facing the viewer, "
    "on a solid pure bright green (#00FF00) chroma key background, "
    "no shadow, no ground, no text, no other objects. Character: "
)

_MOTION_PREFIX = (
    "The exact same character as in the image, same art style, colors and "
    "proportions. "
)
_MOTION_SUFFIX = (
    ". Static camera. Any facial expression described is clearly visible in the "
    "middle of the clip. The character starts and ends in the exact pose and "
    "expression of the image. The plain green background stays unchanged."
)
VIDEO_NEGATIVE_PROMPT = (
    "camera movement, zoom, background change, shadow, new objects, text, "
    "blur, distort, low quality"
)


def build_motion_prompt(motion: str) -> str:
    """Encadre le mouvement d'un etat pour garder personnage, style et fond."""
    return _MOTION_PREFIX + motion.strip().rstrip(".") + _MOTION_SUFFIX


# ---------------------------------------------------------------------------
# Bas niveau
# ---------------------------------------------------------------------------
def _require_key() -> str:
    key = settings.get_fal_key()
    if not key:
        raise FalNotConfiguredError(
            "Colle ta cle fal.ai dans Reglages."
        )
    return key


def _sdk() -> Any | None:
    try:
        import fal_client  # type: ignore[import-not-found]

        return fal_client
    except ImportError:
        return None


def _http_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(**kwargs)


def _use_rest() -> bool:
    transport = settings.fal_transport()
    if transport == "rest":
        return True
    if transport == "sdk":
        return False
    return _sdk() is None  # auto : REST seulement si fal-client manque


async def _sdk_submit_and_wait(
    model: str, arguments: dict[str, Any], timeout_s: int = 900
) -> dict[str, Any]:
    sdk = _sdk()
    if sdk is None:
        raise FalApiError("Le package fal-client n'est pas installe.")
    key = _require_key()

    def _run() -> dict[str, Any]:
        client = sdk.SyncClient(key=key)
        handler = client.submit(model, arguments=arguments)
        return handler.get()

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout_s)
    except asyncio.TimeoutError as exc:
        raise FalApiError(
            f"Delai depasse ({timeout_s}s) pour le modele {model}."
        ) from exc
    except FalApiError:
        raise
    except Exception:  # erreur remontee par fal-client, detail potentiellement sensible
        raise FalApiError(f"Erreur fal.ai sur le modele {model}.") from None


async def _rest_submit_and_wait(
    model: str, payload: dict[str, Any], timeout_s: int = 900
) -> dict[str, Any]:
    """Soumission manuelle via l'API REST queue.fal.run (sans fal-client).

    Format impose par la doc fal.ai : le corps POST est l'input du modele
    tel quel (pas d'enveloppe {"input": ...}), et les URLs de statut /
    reponse sont celles retournees par la soumission (base proprietaire +
    app seulement ; le chemin complet du modele retournerait 405).
    """
    key = _require_key()
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    base = f"https://queue.fal.run/{model}"
    async with _http_client(timeout=60) as client:
        resp = await client.post(base, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise FalApiError(
                f"Soumission fal.ai refusee ({resp.status_code}).",
                status_code=resp.status_code,
            )
        submit = resp.json()
        request_id = submit.get("request_id")
        if not request_id:
            raise FalApiError("Reponse fal.ai inattendue : request_id manquant.")
        app_base = "/".join(model.split("/")[:2])  # proprietaire + app
        status_url = submit.get("status_url") or (
            f"https://queue.fal.run/{app_base}/requests/{request_id}/status"
        )
        response_url = submit.get("response_url") or (
            f"https://queue.fal.run/{app_base}/requests/{request_id}"
        )
        elapsed = 0
        while elapsed < timeout_s:
            status_resp = await client.get(status_url, headers=headers)
            status_resp.raise_for_status()
            status = status_resp.json().get("status")
            if status == "COMPLETED":
                break
            if status == "FAILED":
                raise FalApiError(
                    f"Le job fal.ai {request_id} a echoue (modele {model})."
                )
            await asyncio.sleep(3)
            elapsed += 3
        else:
            raise FalApiError(
                f"Delai depasse ({timeout_s}s) pour le modele {model}."
            )
        out = await client.get(response_url, headers=headers)
        out.raise_for_status()
        return out.json()


async def _submit_and_wait(
    model: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if _use_rest():
        return await _rest_submit_and_wait(model, payload)
    return await _sdk_submit_and_wait(model, payload)


async def test_key() -> bool:
    """Valide gratuitement la cle via le jeton de stockage lu dans fal-client 1.0.3."""
    key = _require_key()
    url = "https://rest.fal.ai/storage/auth/token?storage_type=fal-cdn-v3"
    headers = {
        "Authorization": f"Key {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with _http_client(timeout=30) as client:
            response = await client.post(url, headers=headers, json={})
    except httpx.HTTPError:
        raise FalApiError("Impossible de joindre fal.ai pour tester la cle.") from None
    if response.status_code in {401, 403}:
        return False
    if response.status_code >= 400:
        raise FalApiError("fal.ai n'a pas pu tester la cle.", status_code=response.status_code)
    return True


# ---------------------------------------------------------------------------
# API publique (mockable)
# ---------------------------------------------------------------------------
async def describe_image(
    image_urls: list[str], system_prompt: str, prompt: str, model: str | None = None
) -> tuple[str, float]:
    """Fait lire des images a un modele de langage. Retourne (texte, cout reel en USD)."""
    _require_key()
    payload = {
        "model": model or settings.spec_model(),
        "prompt": prompt,
        "system_prompt": system_prompt,
        "image_urls": list(image_urls),
        "temperature": 0.3,
        "max_tokens": 16000,
        # Les modeles qui raisonnent (claude-sonnet-5.5) refusent l'appel si le
        # raisonnement est coupe ("Reasoning is mandatory", constate le 2026-10-31).
        "reasoning": True,
    }
    result = await _submit_and_wait(settings.SPEC_ENDPOINT, payload)
    try:
        return str(result["output"]), float((result.get("usage") or {}).get("cost") or 0.0)
    except (KeyError, TypeError, ValueError) as exc:
        raise FalApiError("Reponse du modele vision inattendue : texte introuvable.") from exc


async def upload_character_image(path: Path) -> str:
    """Envoie une image personnage vers le stockage fal.ai, retourne son URL publique."""
    _require_key()
    if _use_rest():
        # L'ancien endpoint rest.alpha.fal.ai/storage est obsolete (le
        # stockage actuel passe par un jeton rest.fal.ai + v3.fal.media,
        # gere par le SDK). En transport REST, on passe l'image en data URI :
        # les modeles fal.ai l'acceptent directement comme image_url.
        import base64
        import mimetypes

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{encoded}"
    sdk = _sdk()
    if sdk is None:  # pragma: no cover - ne devrait pas arriver ici
        raise FalApiError("Le package fal-client n'est pas installe.")
    key = _require_key()
    try:
        client = sdk.SyncClient(key=key)
        return await asyncio.to_thread(client.upload_file, str(path))
    except Exception:
        raise FalApiError("Echec de l'upload vers fal.ai.") from None


async def generate_character_image(prompt: str) -> str:
    """Genere l'image du personnage (Flux), retourne l'URL publique de l'image."""
    _require_key()
    payload = {
        "prompt": prompt,
        "image_size": "square_hd",
    }
    result = await _submit_and_wait(settings.tti_model(), payload)
    try:
        return result["images"][0]["url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FalApiError(
            "Reponse text-to-image inattendue : URL d'image introuvable."
        ) from exc


async def generate_state_video(
    image_url: str, motion: str, model: str | None = None, duration_s: int | None = None
) -> tuple[str, str]:
    """Genere le clip video d'un etat. Retourne (url_video, modele_utilise).

    Debut et fin sur la meme image : les clips bouclent sans saut et le
    widget passe d'un etat a l'autre sur cette pose commune.
    """
    _require_key()
    chosen = model or settings.i2v_model()
    payload = {
        "start_image_url": image_url,
        "end_image_url": image_url,
        "prompt": build_motion_prompt(motion),
        "negative_prompt": VIDEO_NEGATIVE_PROMPT,
        "duration": str(duration_s or settings.VIDEO_DURATION_S),  # Kling : "3".."15"
        "generate_audio": False,  # le widget est muet ; l'audio coute 50 % de plus
    }
    result = await _submit_and_wait(chosen, payload)
    try:
        return result["video"]["url"], chosen
    except (KeyError, TypeError) as exc:
        raise FalApiError(
            "Reponse image-to-video inattendue : URL de video introuvable."
        ) from exc
