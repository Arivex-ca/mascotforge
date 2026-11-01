"""Cles par requete : isolation, validation gratuite et absence de fuite."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

import httpx

from backend import fal as fal_module
from backend import image3d
from backend import openrouter
from backend import pipeline as pipeline_module
from backend import settings
from backend.main import app
from conftest import ARIVEX_SPEC_TEXT


def test_header_key_overrides_environment_and_fake_fal_sees_it(client, fal_fake):
    response = client.post(
        "/api/character/from-prompt",
        headers={"X-Fal-Key": "fal-cle-navigateur"},
        json={"prompt": "un hibou"},
    )

    assert response.status_code == 200, response.text
    assert fal_fake.fal_keys == ["fal-cle-navigateur"]


def test_environment_key_is_the_fallback(client, fal_fake):
    response = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})

    assert response.status_code == 200, response.text
    assert fal_fake.fal_keys == ["test-key-ne-vaut-rien"]


def test_paid_route_without_any_key_returns_clear_503(client, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)

    response = client.post("/api/character/from-prompt", json={"prompt": "un hibou"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Colle ta cle fal.ai dans Reglages."}


def test_key_never_appears_in_responses_logs_or_data(client, fal_fake, caplog):
    secret = "fal-secret-a-ne-jamais-ecrire"
    caplog.set_level(logging.DEBUG)
    headers = {"X-Fal-Key": secret}

    character = client.post(
        "/api/character/from-prompt", headers=headers, json={"prompt": "un renard"}
    )
    generated = client.post(
        "/api/generate",
        headers=headers,
        json={"character_id": character.json()["character_id"], "usage": "site"},
    )
    job = client.get(f"/api/jobs/{generated.json()['job_id']}")

    bodies = character.text + generated.text + job.text
    assert secret not in bodies
    assert secret not in caplog.text
    data_root = Path(os.environ["MASCOTFORGE_DATA_DIR"])
    for path in data_root.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path


def test_two_concurrent_requests_keep_their_own_keys(client, monkeypatch):
    seen: list[tuple[str, str]] = []
    both_started = asyncio.Event()
    started = 0
    lock = asyncio.Lock()

    async def fake_generate(_prompt: str) -> str:
        nonlocal started
        before = settings.get_fal_key()
        async with lock:
            started += 1
            if started == 2:
                both_started.set()
        await both_started.wait()
        await asyncio.sleep(0)
        seen.append((before, settings.get_fal_key()))
        return "data:image/png;base64,eA=="

    monkeypatch.setattr(fal_module, "generate_character_image", fake_generate)

    async def send(key: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as browser:
            return await browser.post(
                "/api/character/from-prompt",
                headers={"X-Fal-Key": key},
                json={"prompt": key},
            )

    async def run() -> list[httpx.Response]:
        return await asyncio.gather(send("cle-a"), send("cle-b"))

    responses = asyncio.run(run())
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(seen) == [("cle-a", "cle-a"), ("cle-b", "cle-b")]


def test_background_task_keeps_request_key(client, fal_fake, monkeypatch):
    character = client.post("/api/character/from-prompt", json={"prompt": "un robot"})
    monkeypatch.setenv("MASCOTFORGE_SYNC_JOBS", "0")
    captured: list[str] = []
    finished = threading.Event()

    async def fake_run_job(_job_id: str, **_kwargs: object) -> dict:
        await asyncio.sleep(0.02)
        captured.append(settings.get_fal_key())
        finished.set()
        return {}

    monkeypatch.setattr(pipeline_module, "run_job", fake_run_job)
    response = client.post(
        "/api/generate",
        headers={"X-Fal-Key": "cle-tache-fond"},
        json={"character_id": character.json()["character_id"], "usage": "site"},
    )

    assert response.status_code == 200, response.text
    assert finished.wait(1)
    assert captured == ["cle-tache-fond"]


def test_keys_test_uses_the_header_for_each_provider(client, monkeypatch):
    seen: list[tuple[str, str]] = []

    async def fal_ok() -> bool:
        seen.append(("fal", settings.get_fal_key()))
        return True

    async def openrouter_ok() -> bool:
        seen.append(("openrouter", settings.get_openrouter_key()))
        return True

    monkeypatch.setattr(fal_module, "test_key", fal_ok)
    monkeypatch.setattr(openrouter, "test_key", openrouter_ok)

    fal_response = client.post(
        "/api/keys/test", headers={"X-Fal-Key": "fal-test"}, json={"provider": "fal"}
    )
    openrouter_response = client.post(
        "/api/keys/test",
        headers={"X-OpenRouter-Key": "or-test"},
        json={"provider": "openrouter"},
    )

    assert fal_response.json() == {"ok": True, "message": "Cle fal.ai valide."}
    assert openrouter_response.json() == {"ok": True, "message": "Cle OpenRouter valide."}
    assert seen == [("fal", "fal-test"), ("openrouter", "or-test")]


def test_fal_key_test_does_not_fall_back_to_the_server_key(client, monkeypatch):
    called = False

    async def should_not_run() -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(fal_module, "test_key", should_not_run)
    response = client.post("/api/keys/test", json={"provider": "fal"})

    assert response.json() == {
        "ok": False,
        "message": "Colle ta cle fal.ai dans Reglages.",
    }
    assert called is False


def test_fal_key_test_uses_the_free_storage_token_call(monkeypatch):
    secret = "fal-validation-gratuite"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "token": "jeton-cdn",
                "token_type": "Bearer",
                "base_url": "https://v3.fal.media",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )

    monkeypatch.setattr(
        fal_module,
        "_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    tokens = settings.bind_request_context(secret, None, "fal")
    try:
        assert asyncio.run(fal_module.test_key()) is True
    finally:
        settings.reset_request_context(tokens)

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "https://rest.fal.ai/storage/auth/token?storage_type=fal-cdn-v3"
    assert requests[0].headers["Authorization"] == f"Key {secret}"


def test_fal_sdk_receives_explicit_key_without_touching_environment(monkeypatch, tmp_path):
    seen: list[str] = []

    class Handler:
        def get(self) -> dict:
            return {"images": [{"url": "https://fal.media/image.png"}]}

    class Client:
        def __init__(self, key: str) -> None:
            seen.append(key)

        def submit(self, _model: str, arguments: dict) -> Handler:
            assert arguments["prompt"] == "robot"
            return Handler()

        def upload_file(self, path: str) -> str:
            assert Path(path).is_file()
            return "https://fal.media/upload.png"

    class FakeSdk:
        SyncClient = Client

    image = tmp_path / "robot.png"
    image.write_bytes(b"png")
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(fal_module, "_sdk", lambda: FakeSdk)
    monkeypatch.setattr(settings, "fal_transport", lambda: "sdk")
    tokens = settings.bind_request_context("cle-sdk-explicite", None, "fal")
    try:
        result = asyncio.run(fal_module._sdk_submit_and_wait("fal-ai/test", {"prompt": "robot"}))
        uploaded = asyncio.run(fal_module.upload_character_image(image))
    finally:
        settings.reset_request_context(tokens)

    assert result["images"][0]["url"].endswith("image.png")
    assert uploaded.endswith("upload.png")
    assert seen == ["cle-sdk-explicite", "cle-sdk-explicite"]
    assert "FAL_KEY" not in os.environ


def test_openrouter_chat_uses_data_urls_reasoning_and_real_cost(monkeypatch):
    secret = "openrouter-secret"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.1234},
            },
        )

    monkeypatch.setattr(
        openrouter,
        "_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    tokens = settings.bind_request_context(None, secret, "openrouter")
    try:
        text, cost, estimated = asyncio.run(
            openrouter.describe_image(
                ["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"],
                "Systeme",
                "Compare",
            )
        )
    finally:
        settings.reset_request_context(tokens)

    assert (text, cost, estimated) == ("OK", 0.1234, False)
    request = requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {secret}"
    payload = json.loads(request.content)
    assert payload["model"] == settings.spec_model()
    assert payload["reasoning"] == {"enabled": True}
    image_parts = [part for part in payload["messages"][1]["content"] if part["type"] == "image_url"]
    assert [part["image_url"]["url"] for part in image_parts] == [
        "data:image/png;base64,AAAA",
        "data:image/png;base64,BBBB",
    ]


def test_openrouter_cost_is_estimated_from_usage_when_real_cost_is_missing(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            },
        )

    monkeypatch.setattr(
        openrouter,
        "_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    tokens = settings.bind_request_context(None, "or-key", "openrouter")
    try:
        _text, cost, estimated = asyncio.run(
            openrouter.describe_image(["data:image/png;base64,AAAA"], "Systeme", "Dessine")
        )
    finally:
        settings.reset_request_context(tokens)

    assert cost == 0.003
    assert estimated is True


def test_image3d_openrouter_path_never_uploads_to_fal(
    client, fal_fake, monkeypatch
):
    calls: list[dict] = []

    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(
        image3d,
        "check_spec",
        lambda _spec: {"ok": True, "issues": []},
    )

    def fake_render(_spec: dict, out: Path) -> Path:
        out.write_bytes(b"\x89PNG-rendu-factice")
        return out

    monkeypatch.setattr(image3d, "render_sheet", fake_render)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        content = f"```json\n{ARIVEX_SPEC_TEXT}\n```" if len(calls) == 1 else "OK"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"cost": 0.05, "prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    monkeypatch.setattr(
        openrouter,
        "_http_client",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = client.post(
        "/api/engines/3d/from-image",
        headers={
            "X-OpenRouter-Key": "or-image-3d",
            "X-Vision-Provider": "openrouter",
        },
        files={"file": ("robot.png", b"\x89PNG-donnees", "image/png")},
    )

    assert response.status_code == 200, response.text
    job = client.get(f"/api/engines/3d/specs/{response.json()['spec_id']}").json()
    assert job["status"] == "done"
    assert job["cost_usd"] == 0.1
    assert job["cost_estimated"] is False
    assert fal_fake.upload_keys == []
    for payload in calls:
        parts = payload["messages"][1]["content"]
        urls = [part["image_url"]["url"] for part in parts if part["type"] == "image_url"]
        assert urls and all(url.startswith("data:image/png;base64,") for url in urls)
