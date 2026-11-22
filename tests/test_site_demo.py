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
    assert page.locator("[data-gallery-state]").count() == 8
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
    assert "Showing the Error state across every live mascot." in page.locator("#messageBar").inner_text()
    assert console_errors == []
    assert page_errors == []


def test_waiting_state_requires_a_visible_human_decision(site_page):
    page, console_errors, page_errors, _ = site_page

    page.locator('[data-gallery-state="waiting-for-approval"]').dispatch_event("click")
    page.wait_for_function(
        "() => window.__mascotforge.getGalleryState() === 'waiting-for-approval'"
    )

    assert page.locator(".demo-console").get_attribute("data-state") == "waiting-for-approval"
    assert page.locator("#galleryStateLabel").inner_text() == "NEEDS YOUR APPROVAL"
    assert page.locator("#galleryStateLabel").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(245, 207, 98)"
    assert page.locator(
        '[data-gallery-state="waiting-for-approval"]'
    ).get_attribute("aria-pressed") == "true"
    assert page.locator("#galleryCode").inner_text() == 'play("waiting-for-approval")'
    assert page.locator("[data-live-state]").all_inner_texts() == [
        "NEEDS YOUR APPROVAL",
        "NEEDS YOUR APPROVAL",
        "NEEDS YOUR APPROVAL",
        "NEEDS YOUR APPROVAL",
    ]
    assert page.evaluate(
        """() => ["mochiDemoMascot", "bunnyMascot", "patchMascot"]
          .every((id) => document.getElementById(id).state === "waiting-for-approval")"""
    )
    assert page.evaluate(
        """() => {
          const orbi = document.getElementById("orbiMascot");
          return !orbi || orbi.getState() === "idle";
        }"""
    )
    page.wait_for_timeout(350)
    assert page.evaluate(
        """() => ["mochiDemoMascot", "bunnyMascot", "patchMascot"]
          .every((id) => document.getElementById(id).shadowRoot
            .querySelector('[data-badge-kind="pause"]'))"""
    )
    assert "ACTION REQUIRED" in page.locator(".gallery-visual").first.evaluate(
        "element => getComputedStyle(element, '::before').content"
    )
    assert console_errors == []
    assert page_errors == []


def test_simulation_pauses_until_the_user_approves(site_page):
    page, console_errors, page_errors, _ = site_page

    page.locator("#simulateButton").dispatch_event("click")
    page.wait_for_function(
        """() => {
          const state = window.__mascotforge.getState();
          return state.simulating && state.agentState === "waiting-for-approval";
        }""",
        timeout=7000,
    )

    assert page.locator("#simulateButton .button-label").inner_text() == "Approve & continue"
    assert page.locator(".forge-stage").get_attribute("data-state") == "waiting-for-approval"
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('.approval-gate')).opacity === '1'"
    )
    assert page.locator(".approval-gate").evaluate(
        "element => getComputedStyle(element).opacity"
    ) == "1"
    assert page.locator("#stageState").inner_text() == "NEEDS YOUR APPROVAL"
    assert "Your approval is required" in page.locator("#messageBar").inner_text()

    page.locator("#simulateButton").dispatch_event("click")
    page.wait_for_function(
        """() => {
          const state = window.__mascotforge.getState();
          return !state.simulating && state.agentState === "done";
        }"""
    )

    assert page.locator("#simulateButton .button-label").inner_text() == "Simulate agent"
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('.approval-gate')).opacity === '0'"
    )
    assert page.locator(".approval-gate").evaluate(
        "element => getComputedStyle(element).opacity"
    ) == "0"
    assert page.locator("#stageState").inner_text() == "DONE"
    assert "completed the task" in page.locator("#messageBar").inner_text()
    assert console_errors == []
    assert page_errors == []


def test_workshop_preview_stays_visible_beside_desktop_controls(site_page):
    page, console_errors, page_errors, _ = site_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.evaluate("() => document.documentElement.style.scrollBehavior = 'auto'")

    layout = page.locator(".workshop-layout")
    preview = page.locator(".workshop-preview")
    controls = page.locator(".workshop-builder")
    layout_box = layout.bounding_box()
    preview_box = preview.bounding_box()
    controls_box = controls.bounding_box()

    assert layout_box is not None
    assert preview_box is not None
    assert controls_box is not None
    assert preview_box["x"] < controls_box["x"]
    assert abs(preview_box["y"] - controls_box["y"]) <= 2

    page.evaluate(
        """() => {
          const layout = document.querySelector(".workshop-layout");
          const layoutTop = layout.getBoundingClientRect().top + window.scrollY;
          window.scrollTo(0, layoutTop + 260);
        }"""
    )
    page.wait_for_timeout(100)
    sticky_top = preview.bounding_box()["y"]
    controls_top = controls.bounding_box()["y"]

    page.evaluate("() => window.scrollBy(0, 420)")
    page.wait_for_timeout(100)

    assert abs(preview.bounding_box()["y"] - sticky_top) <= 2
    assert controls.bounding_box()["y"] < controls_top - 400
    assert console_errors == []
    assert page_errors == []


def test_live_demo_fits_mobile_without_horizontal_scroll(site_page):
    page, console_errors, page_errors, _ = site_page

    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("() => document.documentElement.style.scrollBehavior = 'auto'")

    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth"
    )
    page.evaluate(
        """() => {
          const layout = document.querySelector(".workshop-layout");
          const layoutTop = layout.getBoundingClientRect().top + window.scrollY;
          window.scrollTo(0, layoutTop + 100);
        }"""
    )
    page.wait_for_timeout(100)
    mobile_preview = page.locator(".workshop-preview")
    preview_top = mobile_preview.bounding_box()["y"]
    assert mobile_preview.locator(".forge-stage").bounding_box()["height"] <= 260

    page.evaluate("() => window.scrollBy(0, 240)")
    page.wait_for_timeout(100)
    assert abs(mobile_preview.bounding_box()["y"] - preview_top) <= 2

    buttons = page.locator("[data-gallery-state]")
    assert buttons.count() == 8
    assert all(buttons.nth(index).is_visible() for index in range(8))

    page.locator('[data-gallery-state="done"]').dispatch_event("click")
    page.wait_for_function(
        "() => window.__mascotforge.getGalleryState() === 'done'"
    )
    assert page.locator("#galleryStateLabel").inner_text() == "DONE"
    assert console_errors == []
    assert page_errors == []
