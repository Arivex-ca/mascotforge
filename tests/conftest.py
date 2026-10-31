"""Fixtures communes : fal.ai mocke, repertoires isoles, jobs synchrones."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import fal as fal_module  # noqa: E402
from backend import pipeline as pipeline_module  # noqa: E402
from backend import settings  # noqa: E402


async def fake_generate_character_image(prompt: str) -> str:
    assert prompt.startswith(fal_module.CHARACTER_PROMPT_PREFIX)
    assert "square_hd" not in prompt  # le prompt, pas les arguments
    return "https://fal.media/fake/character.png"


async def fake_upload_character_image(path: Path) -> str:
    assert path.is_file()
    return "https://fal.media/fake/uploaded.png"


async def fake_generate_state_video(
    image_url: str, state: str, model: str | None = None
) -> tuple[str, str]:
    """Le modele principal echoue une fois sur 'talking' pour tester le fallback."""
    chosen = model or settings.i2v_model()
    if state == "talking" and chosen == settings.i2v_model():
        raise RuntimeError("panne simulee du modele principal")
    return f"https://fal.media/fake/{state}.mp4", chosen


async def fake_download_video(url: str, dest: Path) -> None:
    assert url.startswith("https://fal.media/fake/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"FAKE-MP4:" + url.encode())


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client de test : fal.ai mocke, donnees isolees, jobs executes en ligne."""
    data_dir = tmp_path / "data"
    exports_dir = tmp_path / "exports"
    monkeypatch.setenv("MASCOTFORGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MASCOTFORGE_EXPORTS_DIR", str(exports_dir))
    monkeypatch.setenv("MASCOTFORGE_SYNC_JOBS", "1")
    monkeypatch.setenv("FAL_KEY", "test-key-ne-vaut-rien")
    widget_file = tmp_path / "mascot-avatar.js"
    widget_file.write_text(
        "// widget de test\nclass MascotAvatar extends HTMLElement {}",
        encoding="utf-8",
    )
    monkeypatch.setenv("MASCOTFORGE_WIDGET_FILE", str(widget_file))

    monkeypatch.setattr(
        fal_module, "generate_character_image", fake_generate_character_image
    )
    monkeypatch.setattr(
        fal_module, "upload_character_image", fake_upload_character_image
    )
    monkeypatch.setattr(
        fal_module, "generate_state_video", fake_generate_state_video
    )
    monkeypatch.setattr(pipeline_module, "_download_video", fake_download_video)

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
