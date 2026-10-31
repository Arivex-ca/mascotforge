"""Preuves visuelles du widget <mascot-avatar> dans un vrai Chromium.

Lance un Chromium headless (executable en cache, deja present sur la machine),
sert widget/ en HTTP local, puis verifie les transitions d'etats :
  - getState() pour chaque transition
  - les evenements statechange / sleep / wake
  - zero erreur JS console
  - captures d'ecran dans tests/screenshots/

IMPORTANT : pendant la phase de transitions, sleep-after est monte a 3600 s
(via setAttribute, ce qui rearme le minuteur) pour que le minuteur de sommeil
de 2 s ne vienne pas parasiter le retour automatique des etats one-shot
(clicked / error, clips de 2 s). Le test de sommeil utilise ensuite la vraie
valeur sleep-after="2" demandee par la page de test.

Aucune generation IA : seuls les placeholders MP4 locaux sont lus.
"""
from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WIDGET_DIR = PROJECT_ROOT / "widget"
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"

SHELL = Path.home() / ".cache/ms-playwright/chromium_headless_shell-1248" / \
    "chrome-headless-shell-linux64" / "chrome-headless-shell"

TEST_PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Test mascot-avatar</title>
<style>mascot-avatar { width: 320px; height: 320px; }</style>
</head><body>
<mascot-avatar id="avatar" manifest="manifest.exemple.json" sleep-after="2"></mascot-avatar>
<script src="mascot-avatar.js"></script>
<script>
  window.__avatar = document.getElementById("avatar");
  window.__events = [];
  window.__errors = [];
  for (const name of ["statechange", "sleep", "wake"]) {
    window.__avatar.addEventListener(name, (ev) => {
      window.__events.push({ name, detail: ev.detail || null });
    });
  }
  window.__avatar.ready().then(() => { window.__ready = true; });
  window.addEventListener("error", (ev) => {
    window.__errors.push("window.onerror: " + ev.message);
  });
  window.addEventListener("unhandledrejection", (ev) => {
    window.__errors.push("unhandledrejection: " + (ev.reason && ev.reason.message));
  });
</script>
</body></html>
"""


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/_test-page.html":
            body = TEST_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):  # silencieux
        pass


@pytest.fixture(scope="module")
def page_and_server():
    """Serveur HTTP local sur widget/ + page Playwright ouverte."""
    from playwright.sync_api import sync_playwright

    if not SHELL.is_file():
        pytest.skip(f"headless shell introuvable : {SHELL}")

    handler = functools.partial(_Handler, directory=str(WIDGET_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(executable_path=str(SHELL))
    context = browser.new_context(viewport={"width": 800, "height": 600})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    try:
        page.goto(f"http://127.0.0.1:{port}/_test-page.html")
        page.wait_for_function("() => window.__ready === true", timeout=10000)
        yield page, console_errors, page_errors
    finally:
        browser.close()
        playwright.stop()
        server.shutdown()
        thread.join(timeout=5)


def _state(page) -> str:
    return page.evaluate("() => window.__avatar.getState()")


def _wait_state(page, state: str, timeout: int = 10000):
    page.wait_for_function(
        f"() => window.__avatar.getState() === '{state}'", timeout=timeout
    )


def _events(page):
    return page.evaluate("() => window.__events")


def _shot(page, name: str):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / name
    page.screenshot(path=str(path))
    assert path.is_file() and path.stat().st_size > 0
    return path


def _assert_no_js_errors(page, console_errors, page_errors):
    in_page = page.evaluate("() => window.__errors")
    assert console_errors == [], f"erreurs console: {console_errors}"
    assert page_errors == [], f"pageerror: {page_errors}"
    assert in_page == [], f"erreurs JS in-page: {in_page}"


def test_01_idle_initial(page_and_server):
    page, console_errors, page_errors = page_and_server
    assert _state(page) == "idle"
    _shot(page, "01-idle.png")
    _assert_no_js_errors(page, console_errors, page_errors)
    # Isolation : le minuteur de sommeil de 2 s ne doit pas parasiter les
    # transitions one-shot (clips de 2 s). On le remonte, puis on le
    # redescendra pour le test de sommeil.
    page.evaluate("() => window.__avatar.setAttribute('sleep-after', '3600')")


def test_02_click_then_auto_back_to_idle(page_and_server):
    page, console_errors, page_errors = page_and_server
    before = len(_events(page))
    page.click("mascot-avatar")
    _wait_state(page, "clicked")
    _shot(page, "02-clicked.png")
    _wait_state(page, "idle", timeout=15000)
    _shot(page, "03-back-idle.png")
    new_events = _events(page)[before:]
    kinds = [(e["name"], (e["detail"] or {}).get("from"),
             (e["detail"] or {}).get("to")) for e in new_events]
    assert ("statechange", "idle", "clicked") in kinds, kinds
    assert ("statechange", "clicked", "idle") in kinds, kinds
    _assert_no_js_errors(page, console_errors, page_errors)


def test_03_play_talking_then_error(page_and_server):
    page, console_errors, page_errors = page_and_server
    before = len(_events(page))
    page.evaluate("() => window.__avatar.play('talking')")
    _wait_state(page, "talking")
    _shot(page, "04-talking.png")
    page.evaluate("() => window.__avatar.play('error')")
    _wait_state(page, "error")
    _shot(page, "05-error.png")
    new_events = _events(page)[before:]
    kinds = [(e["name"], (e["detail"] or {}).get("to")) for e in new_events]
    assert ("statechange", "talking") in kinds, kinds
    assert ("statechange", "error") in kinds, kinds
    _assert_no_js_errors(page, console_errors, page_errors)


def test_04_sleep_after_inactivity_then_wake_on_click(page_and_server):
    page, console_errors, page_errors = page_and_server
    # error (one-shot) doit revenir a idle tout seul avant le test de sommeil
    _wait_state(page, "idle", timeout=15000)
    before = len(_events(page))
    # On remet la vraie valeur sleep-after="2" : rearme le minuteur a 2 s.
    page.evaluate("() => window.__avatar.setAttribute('sleep-after', '2')")
    _wait_state(page, "sleeping", timeout=10000)
    _shot(page, "06-sleeping.png")
    # Clic : pointerdown reveille (sleeping -> idle + evenement wake),
    # puis le clic joue l'etat clicked qui revient a idle.
    page.click("mascot-avatar")
    page.wait_for_function(
        "() => window.__events.some(e => e.name === 'wake')", timeout=10000
    )
    _wait_state(page, "idle", timeout=15000)
    _shot(page, "07-wake-idle.png")
    new_events = _events(page)[before:]
    names = [e["name"] for e in new_events]
    assert "sleep" in names, names
    assert "wake" in names, names
    sleep_to = [e for e in new_events
                if e["name"] == "statechange" and (e["detail"] or {}).get("to") == "sleeping"]
    assert sleep_to, names
    _assert_no_js_errors(page, console_errors, page_errors)
