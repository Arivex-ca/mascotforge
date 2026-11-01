"""CLI agent : API simulee, exports gratuits et confirmations payantes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import image3d
from mascotforge import cli
from mascotforge.client import MascotForgeClient, MascotForgeError
from conftest import ARIVEX_SPEC_TEXT


def _api(test_client) -> MascotForgeClient:  # type: ignore[no-untyped-def]
    return MascotForgeClient(base_url="http://testserver", http_client=test_client)


def test_styles_json_lists_engines_presets_and_prices(client, capsys):
    result = cli.main(["styles", "--json"], client=_api(client))
    assert result == 0
    body = json.loads(capsys.readouterr().out)
    assert set(body["engines"]) == {"blob", "3d"}
    assert set(body["presets"]["presets"]) == {"agent", "site", "complet"}
    assert body["presets"]["cost_per_state_usd"] > 0


@pytest.mark.parametrize(
    ("engine", "setting", "engine_file"),
    [
        ("blob", "shape=cloud", "agent-mascot.js"),
        ("3d", "character=volt", "wobnimo.js"),
    ],
)
def test_code_exports_both_engines(client, tmp_path, engine, setting, engine_file):
    out = tmp_path / engine
    result = cli.main(
        ["code", "--engine", engine, "--set", setting, "--out", str(out)],
        client=_api(client),
    )
    assert result == 0
    assert (out / "mascot" / "manifest.json").is_file()
    assert (out / "mascot" / "mascot.js").is_file()
    assert (out / "mascot" / "engines" / engine_file).is_file()


def test_free_spec_workflow_checks_previews_saves_and_exports(
    client, fal_fake, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(image3d, "check_spec", lambda _spec: {"ok": True, "issues": []})

    def render(_spec, out: Path) -> Path:
        out.write_bytes(b"\x89PNG\r\n\x1a\nplanche-factice")
        return out

    monkeypatch.setattr(image3d, "render_sheet", render)
    spec_file = tmp_path / "arivex.json"
    spec_file.write_text(ARIVEX_SPEC_TEXT, encoding="utf-8")
    guide_file = tmp_path / "guide.md"
    sheet = tmp_path / "planche.png"
    out = tmp_path / "export-spec"
    api = _api(client)

    assert cli.main(["spec", "guide", "--out", str(guide_file)], client=api) == 0
    capsys.readouterr()
    assert "Wobnimo" in guide_file.read_text(encoding="utf-8")

    assert cli.main(["spec", "check", str(spec_file), "--json"], client=api) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["ok"] and checked["issues"] == []

    assert cli.main(
        ["spec", "preview", str(spec_file), "--out", str(sheet), "--json"], client=api
    ) == 0
    previewed = json.loads(capsys.readouterr().out)
    assert previewed["bytes"] == sheet.stat().st_size
    assert sheet.read_bytes().startswith(b"\x89PNG")

    assert cli.main(["spec", "save", str(spec_file), "--json"], client=api) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["spec_id"] and saved["name"] == "Arivex"

    assert cli.main(
        ["spec", "export", str(spec_file), "--out", str(out), "--json"], client=api
    ) == 0
    exported = json.loads(capsys.readouterr().out)
    manifest = json.loads((out / "mascot" / "manifest.json").read_text(encoding="utf-8"))
    assert exported["spec_id"] and manifest["engine_spec"]["name"] == "Arivex"
    assert fal_fake.vision_prompts == []


def test_paid_commands_stop_before_creation_without_yes(client, fal_fake, tmp_path, capsys):
    image = tmp_path / "robot.png"
    image.write_bytes(b"\x89PNG-factice")

    result = cli.main(
        ["video", "--image", str(image), "--out", str(tmp_path / "video")],
        client=_api(client),
    )
    video_output = capsys.readouterr().out
    assert result != 0 and "Prix estime" in video_output and "--yes" in video_output
    assert fal_fake.video_calls == []

    result = cli.main(
        ["image3d", str(image), "--out", str(tmp_path / "image3d")],
        client=_api(client),
    )
    image3d_output = capsys.readouterr().out
    assert result != 0 and "0,15" in image3d_output and "0,60" in image3d_output
    assert fal_fake.vision_prompts == []


def test_video_with_yes_uses_fake_server_and_exports(client, fal_fake, tmp_path, capsys):
    image = tmp_path / "robot.png"
    image.write_bytes(b"\x89PNG-factice")
    out = tmp_path / "video"

    result = cli.main(
        [
            "video", "--image", str(image), "--usage", "agent",
            "--yes", "--out", str(out), "--json",
        ],
        client=_api(client),
    )

    assert result == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] and body["creation"] == "video"
    assert len(fal_fake.video_calls) == 5, "4 etats, dont talking relance sur le modele de secours"
    assert (out / "mascot" / "manifest.json").is_file()
    assert (out / "mascot" / "videos" / "idle.mp4").is_file()


def test_image3d_with_yes_uses_fake_server_and_exports(
    client, fal_fake, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(image3d, "available", lambda: True)
    monkeypatch.setattr(image3d, "check_spec", lambda _spec: {"ok": True, "issues": []})

    def render(_spec, out: Path) -> Path:
        out.write_bytes(b"\x89PNG-rendu-factice")
        return out

    monkeypatch.setattr(image3d, "render_sheet", render)
    image = tmp_path / "robot.png"
    image.write_bytes(b"\x89PNG-factice")
    out = tmp_path / "image3d"

    result = cli.main(
        ["image3d", str(image), "--yes", "--out", str(out), "--json"],
        client=_api(client),
    )

    assert result == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] and body["creation"] == "image3d"
    assert fal_fake.vision_images == [1, 2]
    assert (out / "mascot" / "manifest.json").is_file()
    assert (out / "mascot" / "engines" / "wobnimo.js").is_file()


def test_status_export_and_cost_commands(client, fal_fake, tmp_path, capsys):
    image = tmp_path / "robot.png"
    image.write_bytes(b"\x89PNG-factice")
    api = _api(client)
    started = api.start_video("site", image=image)

    assert cli.main(["status", started["job_id"], "--json"], client=api) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["type"] == "video" and status["status"] == "done"

    out = tmp_path / "export"
    assert cli.main(["export", started["job_id"], "--out", str(out)], client=api) == 0
    capsys.readouterr()
    assert (out / "mascot" / "manifest.json").is_file()

    assert cli.main(["cost", "--json"], client=api) == 0
    cost = json.loads(capsys.readouterr().out)
    assert cost["spent_usd"] > 0 and cost["reserved_usd"] == 0


def test_server_url_rejects_secrets():
    with pytest.raises(MascotForgeError, match="secret"):
        MascotForgeClient("https://user:secret@example.test?token=secret")
