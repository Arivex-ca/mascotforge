"""Fixtures communes : fal.ai et ffmpeg mockes, repertoires isoles, jobs synchrones."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import alpha as alpha_module  # noqa: E402
from backend import fal as fal_module  # noqa: E402
from backend import pipeline as pipeline_module  # noqa: E402
from backend import settings  # noqa: E402


LOOK_MAP = [[0.0, 0.0], [-1.0, 0.0], [1.0, 0.0], [0.0, -1.0], [0.0, 1.0]]  # carte simulee
ARIVEX_SPEC_TEXT = (Path(__file__).parent / "fixtures" / "arivex-spec.json").read_text(encoding="utf-8")
VISION_COST = 0.04  # cout simule d'un appel au modele vision


class FakeFal:
    """fal.ai simule. Les tests reglent les pannes et lisent les appels."""

    def __init__(self) -> None:
        self.video_calls: list[tuple[str, str]] = []  # (mouvement, modele)
        self.durations: list[int | None] = []  # duree demandee pour chaque clip
        self.vision_prompts: list[str] = []  # messages envoyes au modele vision
        self.vision_images: list[int] = []  # nombre d'images de chaque appel
        self.vision_answers: list[str] = []  # reponses imposees, dans l'ordre (sinon voir describe_image)
        self.fail_primary_when: str | None = "talking"  # panne du principal si le mouvement contient ce mot
        self.fail_always_when: str | None = None  # panne de tous les modeles
        self.download_failures = 0  # nombre de telechargements a faire echouer

    async def describe_image(
        self, image_urls: list[str], system_prompt: str, prompt: str, model: str | None = None
    ) -> tuple[str, float]:
        assert all(url.startswith("https://fal.media/fake/") for url in image_urls)
        assert "Wobnimo" in system_prompt
        self.vision_prompts.append(prompt)
        self.vision_images.append(len(image_urls))
        if self.vision_answers:
            return self.vision_answers.pop(0), VISION_COST
        # Par defaut : la fiche du robot pour une ecriture, OK pour une comparaison (2 images).
        return ("OK" if len(image_urls) > 1 else f"```json\n{ARIVEX_SPEC_TEXT}\n```"), VISION_COST

    async def generate_character_image(self, prompt: str) -> str:
        assert prompt.startswith(fal_module.CHARACTER_PROMPT_PREFIX)
        return "https://fal.media/fake/character.png"

    async def upload_character_image(self, path: Path) -> str:
        assert path.is_file()
        return "https://fal.media/fake/uploaded.png"

    async def generate_state_video(
        self, image_url: str, motion: str, model: str | None = None, duration_s: int | None = None
    ) -> tuple[str, str]:
        chosen = model or settings.i2v_model()
        self.video_calls.append((motion, chosen))
        self.durations.append(duration_s)
        if self.fail_always_when and self.fail_always_when in motion:
            raise fal_module.FalApiError("panne simulee secrete", status_code=422)
        if self.fail_primary_when and self.fail_primary_when in motion and chosen == settings.i2v_model():
            raise RuntimeError("panne simulee du modele principal")
        slug = abs(hash(motion)) % 10_000
        return f"https://fal.media/fake/{slug}.mp4", chosen

    async def download_video(self, url: str, dest: Path) -> None:
        import httpx

        assert url.startswith("https://fal.media/fake/")
        if self.download_failures > 0:
            self.download_failures -= 1
            raise httpx.ConnectError("telechargement simule en echec")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE-MP4:" + url.encode())


@pytest.fixture
def fal_fake(monkeypatch) -> FakeFal:
    fake = FakeFal()
    monkeypatch.setattr(fal_module, "generate_character_image", fake.generate_character_image)
    monkeypatch.setattr(fal_module, "upload_character_image", fake.upload_character_image)
    monkeypatch.setattr(fal_module, "generate_state_video", fake.generate_state_video)
    monkeypatch.setattr(fal_module, "describe_image", fake.describe_image)
    monkeypatch.setattr(pipeline_module, "_download_video", fake.download_video)
    # ffmpeg simule : les vrais filtres sont couverts par tests/test_alpha.py
    monkeypatch.setattr(alpha_module, "available", lambda: True)
    monkeypatch.setattr(alpha_module, "to_stacked_alpha", lambda src, dest, **_opts: shutil.copyfile(src, dest))
    monkeypatch.setattr(alpha_module, "head_offsets", lambda path: LOOK_MAP)
    monkeypatch.setattr(alpha_module, "put_on_green", lambda src, dest: shutil.copyfile(src, dest))
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, fal_fake):
    """Client de test : fal.ai mocke, donnees isolees, jobs executes en ligne."""
    monkeypatch.setenv("MASCOTFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MASCOTFORGE_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("MASCOTFORGE_SYNC_JOBS", "1")
    monkeypatch.setenv("FAL_KEY", "test-key-ne-vaut-rien")
    monkeypatch.setenv("MASCOTFORGE_MONTHLY_CAP_USD", "50")
    widget_file = tmp_path / "mascot-avatar.js"
    widget_file.write_text(
        "// widget de test\nclass MascotAvatar extends HTMLElement {}",
        encoding="utf-8",
    )
    monkeypatch.setenv("MASCOTFORGE_WIDGET_FILE", str(widget_file))

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
