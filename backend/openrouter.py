"""Client OpenRouter direct pour la lecture d'images."""
from __future__ import annotations

from typing import Any

import httpx

from backend import settings

OPENROUTER_API = "https://openrouter.ai/api/v1"


class OpenRouterNotConfiguredError(RuntimeError):
    pass


class OpenRouterApiError(RuntimeError):
    pass


def _http_client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(**kwargs)


def _require_key() -> str:
    key = settings.get_openrouter_key()
    if not key:
        raise OpenRouterNotConfiguredError("Colle ta cle OpenRouter dans Reglages.")
    return key


async def test_key() -> bool:
    key = _require_key()
    try:
        async with _http_client(timeout=30) as client:
            response = await client.get(
                f"{OPENROUTER_API}/key",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError:
        raise OpenRouterApiError("Impossible de joindre OpenRouter pour tester la cle.") from None
    if response.status_code in {401, 403}:
        return False
    if response.status_code >= 400:
        raise OpenRouterApiError("OpenRouter n'a pas pu tester la cle.")
    return True


def _cost(usage: dict[str, Any]) -> tuple[float, bool]:
    real = usage.get("cost")
    if isinstance(real, (int, float)):
        return round(float(real), 6), False
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    try:
        estimate = (
            float(prompt_tokens) * settings.SPEC_INPUT_USD_PER_MILLION
            + float(completion_tokens) * settings.SPEC_OUTPUT_USD_PER_MILLION
        ) / 1_000_000
    except (TypeError, ValueError):
        estimate = 0.0
    return round(estimate, 6), True


async def describe_image(
    image_urls: list[str], system_prompt: str, prompt: str, model: str | None = None
) -> tuple[str, float, bool]:
    key = _require_key()
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": image_url}}
        for image_url in image_urls
    )
    payload = {
        "model": model or settings.spec_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "temperature": 0.3,
        "max_tokens": 16000,
        "reasoning": {"enabled": True},
    }
    try:
        async with _http_client(timeout=900) as client:
            response = await client.post(
                f"{OPENROUTER_API}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError:
        raise OpenRouterApiError("L'appel au modele vision OpenRouter a echoue.") from None
    if response.status_code in {401, 403}:
        raise OpenRouterNotConfiguredError("La cle OpenRouter a ete refusee.")
    if response.status_code >= 400:
        raise OpenRouterApiError(
            f"Le modele vision OpenRouter a refuse la requete ({response.status_code})."
        )
    try:
        result = response.json()
        text = result["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text:
            raise TypeError
        cost, estimated = _cost(result.get("usage") or {})
        return text, cost, estimated
    except (KeyError, IndexError, TypeError, ValueError):
        raise OpenRouterApiError("Reponse du modele vision OpenRouter inattendue.") from None
