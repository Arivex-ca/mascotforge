from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "studio" / "index.html").read_text(encoding="utf-8")
STUDIO_JS = (ROOT / "studio" / "studio.js").read_text(encoding="utf-8")
STYLE = (ROOT / "studio" / "style.css").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_agent_panel_documents_cli_and_mcp_configuration():
    expected = (
        "python -m mascotforge styles",
        "python -m mascotforge code",
        "python -m mascotforge blob guide",
        "python -m mascotforge blob check",
        "python -m mascotforge blob preview",
        "python -m mascotforge blob export",
        "python -m mascotforge spec guide",
        "python -m mascotforge spec check",
        "python -m mascotforge spec preview",
        "python -m mascotforge spec export",
        "python -m mascotforge image3d",
        "python -m mascotforge video",
        "python -m mascotforge mcp",
        "MASCOTFORGE_URL",
        "X-Fal-Key",
        "X-OpenRouter-Key",
        "Claude Desktop",
        "Cursor",
        "Codex CLI et application",
        "config.toml",
        "[mcp_servers.mascotforge]",
        "cwd = 'C:\\Users\\Darius\\Desktop\\text-to-mascot'",
    )

    assert 'id="btn-agents"' in INDEX
    assert 'id="panneau-agents"' in INDEX
    for text in expected:
        assert text in INDEX


def test_prices_are_absent_before_a_paid_launch():
    accueil_et_choix = INDEX.split('<section id="ecran-accueil"', 1)[1].split(
        '<section id="ecran-personnalisation"', 1
    )[0]

    assert "$" not in accueil_et_choix
    assert "gratuit" not in accueil_et_choix.lower()
    assert "Nécessite une clé API" in accueil_et_choix
    assert 'id="ouvrir-reglages-capacite"' in accueil_et_choix
    assert "Environ 0,15 à 0,60" not in INDEX
    assert 'id="btn-creer-3d"' in INDEX
    assert "Créer en 3D, environ 0,15 à 0,60" in INDEX


def test_video_estimate_is_computed_on_launch_button():
    assert '"Générer les " + etatsEdites.length + " états, environ "' in STUDIO_JS
    assert "etatsEdites.length * presets.cost_per_state_usd" in STUDIO_JS
    assert '"Sans clé API et instantané"' in STUDIO_JS


def test_mobile_header_and_progression_wrap_without_page_overflow():
    narrow_header = STYLE.split("@media (max-width: 430px)", 1)[1].split(
        "@media (max-width: 390px)", 1
    )[0]
    mobile = STYLE.split("@media (max-width: 640px)", 1)[1].split(
        "@media (max-width: 430px)", 1
    )[0]

    assert ".barre-haut { flex-wrap: wrap; padding-inline: 2px; }" in narrow_header
    assert ".actions-entete { width: 100%; justify-content: flex-end; }" in narrow_header
    assert (
        ".progression { justify-content: flex-start; flex-wrap: wrap; "
        "overflow-x: visible; }"
    ) in mobile


def test_readme_documents_codex_skill_and_future_studio_captures():
    assert "[mcp_servers.mascotforge]" in README
    assert "Codex CLI et application" in README
    assert "python -m mascotforge skill" in README
    assert ".claude/skills/mascotforge/" in README
    assert ".agents/skills/mascotforge/" in README
    for name in (
        "studio-accueil.png",
        "studio-choix.png",
        "studio-final.png",
        "studio-reglages.png",
        "studio-agents.png",
    ):
        assert f"docs/media/{name}" in README
