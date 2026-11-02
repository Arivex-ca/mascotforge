from __future__ import annotations

import json
from pathlib import Path

from mascotforge import cli


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "mascotforge" / "SKILL.md"


def test_mascotforge_skill_is_actionable_and_safe():
    text = SOURCE.read_text(encoding="utf-8")

    assert text.startswith("---\nname: mascotforge\ndescription:")
    assert "mascotte" in text.lower()
    assert "avatar animé" in text.lower()
    assert "donner un visage à mon agent" in text.lower()
    assert "python -m mascotforge spec guide" in text
    assert "python -m mascotforge blob guide" in text
    assert "mascotforge_spec_preview" in text
    assert "mascotforge_image3d_start" in text
    assert "mascotforge_video_start" in text
    assert "accord explicite" in text
    assert "jamais" in text.lower() and "URL" in text
    for state in ("idle", "thinking", "talking", "error"):
        assert state in text


def test_skill_command_installs_both_agent_formats_in_current_directory(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    result = cli.main(["skill", "--json"])

    assert result == 0
    body = json.loads(capsys.readouterr().out)
    assert body["kind"] == "skill" and body["installed"] == 2
    source = SOURCE.read_bytes()
    assert (tmp_path / ".claude" / "skills" / "mascotforge" / "SKILL.md").read_bytes() == source
    assert (tmp_path / ".agents" / "skills" / "mascotforge" / "SKILL.md").read_bytes() == source


def test_skill_command_refuses_modified_file_until_force(tmp_path, capsys):
    project = tmp_path / "projet"
    project.mkdir()
    arguments = ["skill", "--dir", str(project), "--json"]
    assert cli.main(arguments) == 0
    capsys.readouterr()

    claude_skill = project / ".claude" / "skills" / "mascotforge" / "SKILL.md"
    agents_skill = project / ".agents" / "skills" / "mascotforge" / "SKILL.md"
    claude_skill.write_text("contenu local modifié\n", encoding="utf-8")
    agents_before = agents_skill.read_bytes()

    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    error = captured.out + captured.err
    assert "modifié" in error and "--force" in error
    assert claude_skill.read_text(encoding="utf-8") == "contenu local modifié\n"
    assert agents_skill.read_bytes() == agents_before

    assert cli.main([*arguments, "--force"]) == 0
    capsys.readouterr()
    assert claude_skill.read_bytes() == SOURCE.read_bytes()
    assert agents_skill.read_bytes() == SOURCE.read_bytes()
