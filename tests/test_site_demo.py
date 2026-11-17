"""Browser checks for the synchronized homepage demonstration."""
from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright absent (pip install playwright)")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = PROJECT_ROOT / "site"
SHELL = (
    Path.home()
    / ".cache/ms-playwright/chromium_headless_shell-1248"
    / "chrome-headless-shell-linux64"
    / "chrome-headless-shell"
)


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site_page():
    from playwright.sync_api import sync_playwright

    handler = functools.partial(_Handler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        executable_path=str(SHELL) if SHELL.is_file() else None
    )
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    external_requests: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "request",
        lambda request: external_requests.append(request.url)
        if not request.url.startswith(f"http://127.0.0.1:{port}/")
        else None,
    )

    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_function(
            "() => document.documentElement.dataset.ready === 'true'",
            timeout=15000,
        )
        yield page, console_errors, page_errors, external_requests
    finally:
        browser.close()
        playwright.stop()
        server.shutdown()
        thread.join(timeout=5)


def test_live_demo_starts_synchronized(site_page):
    page, console_errors, page_errors, external_requests = site_page

    assert page.locator("#gallery-title").inner_text() == "One state. Four live faces."
    assert page.locator("[data-gallery-state]").count() == 7
    assert page.evaluate("() => window.__mascotforge.getGalleryState()") == "thinking"
    assert page.locator("#galleryStateLabel").inner_text() == "THINKING"
    assert page.locator('[data-gallery-state="thinking"]').get_attribute("aria-pressed") == "true"
    assert page.evaluate(
        """() => ["mochiDemoMascot", "bunnyMascot", "patchMascot"]
          .every((id) => document.getElementById(id).state === "thinking")"""
    )
    assert console_errors == []
    assert page_errors == []
    assert external_requests == []


def test_state_button_updates_every_live_mascot(site_page):
    page, console_errors, page_errors, _ = site_page

    page.locator('[data-gallery-state="error"]').dispatch_event("click")
    page.wait_for_function(
        "() => window.__mascotforge.getGalleryState() === 'error'"
    )
    page.wait_for_function(
        """() => {
          const orbi = document.getElementById("orbiMascot");
          return !orbi || orbi.getState() === "error";
        }"""
    )

    assert page.locator("#galleryStateLabel").inner_text() == "ERROR"
    assert page.locator('[data-gallery-state="error"]').get_attribute("aria-pressed") == "true"
    assert page.locator('[data-gallery-state="thinking"]').get_attribute("aria-pressed") == "false"
    assert page.evaluate(
        """() => ["mochiDemoMascot", "bunnyMascot", "patchMascot"]
          .every((id) => document.getElementById(id).state === "error")"""
    )
    assert page.locator("[data-live-state]").all_inner_texts() == [
        "ERROR",
        "ERROR",
        "ERROR",
        "ERROR",
    ]
    assert "Showing Error across every live mascot." in page.locator("#messageBar").inner_text()
    assert console_errors == []
    assert page_errors == []


def test_live_demo_fits_mobile_without_horizontal_scroll(site_page):
    page, console_errors, page_errors, _ = site_page

    page.set_viewport_size({"width": 390, "height": 844})

    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth"
    )
    buttons = page.locator("[data-gallery-state]")
    assert buttons.count() == 7
    assert all(buttons.nth(index).is_visible() for index in range(7))

    page.locator('[data-gallery-state="done"]').dispatch_event("click")
    page.wait_for_function(
        "() => window.__mascotforge.getGalleryState() === 'done'"
    )
    assert page.locator("#galleryStateLabel").inner_text() == "DONE"
    assert console_errors == []
    assert page_errors == []
