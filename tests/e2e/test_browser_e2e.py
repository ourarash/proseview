"""End-to-end tests that drive Proseview in a real browser.

These cover the surface that only exists once the page's JavaScript runs: the
ProseMirror editor, the selection menu, highlight passes, deep links, the
terminal, and the AI proposal bridge arriving over SSE.

Opt-in -- excluded from the default ``pytest`` run by the ``e2e_browser`` marker.

    pip install -e ".[e2e]"
    python -m playwright install chromium
    pytest -m e2e_browser

ProseMirror is imported from esm.sh at fixed versions. Rather than hit the
network on every run, requests are served from ``tests/e2e/_esm_cache/`` and
populated on first miss. To refresh after changing the pins in
``index.html.j2``, delete that directory and run the suite once with network
access.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Browser, Page, Route, sync_playwright  # noqa: E402

from .conftest import (
    AGENT_MARKER,
    ANNOTATED_SCENE_REL,
    LARGE_SCENE_REL,
    NESTED_MANUSCRIPT_NOTE,
    SCENE_REL,
    STORY_SCENES,
    ProseviewServer,
)

pytestmark = pytest.mark.e2e_browser

ESM_CACHE = Path(__file__).parent / "_esm_cache"
#: Maps cache filenames back to their esm.sh URLs, so a human can see which
#: pinned modules are vendored here.
ESM_INDEX = ESM_CACHE / "index.json"


# ── browser plumbing ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        instance = pw.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


def _install_esm_cache(page: Page) -> None:
    """Serve esm.sh from disk, populating the cache on first miss.

    Set ``PROSEVIEW_ESM_OFFLINE=1`` to make a miss fatal instead of fetching --
    useful in CI, where a silent network fallback would hide a stale cache.
    """
    ESM_CACHE.mkdir(parents=True, exist_ok=True)
    offline = os.environ.get("PROSEVIEW_ESM_OFFLINE") == "1"

    def handler(route: Route) -> None:
        url = route.request.url
        cached = ESM_CACHE / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.js"
        if cached.exists():
            route.fulfill(
                status=200,
                body=cached.read_bytes(),
                headers={"content-type": "application/javascript"},
            )
            return
        if offline:
            raise AssertionError(
                f"esm cache miss for {url} with PROSEVIEW_ESM_OFFLINE=1.\n"
                "The pinned ProseMirror versions in index.html.j2 changed; "
                "re-run without that variable to repopulate tests/e2e/_esm_cache/."
            )
        fetched = route.fetch()
        body = fetched.body()
        cached.write_bytes(body)
        index = json.loads(ESM_INDEX.read_text()) if ESM_INDEX.exists() else {}
        index[cached.name] = url
        ESM_INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        route.fulfill(
            status=fetched.status,
            body=body,
            headers={"content-type": "application/javascript"},
        )

    page.route("https://esm.sh/**", handler)


#: Console noise that is not a JavaScript fault. A 409 from the save conflict
#: guard and an aborted request from a deliberate ``location.reload()`` both
#: log here, and both are the app working as designed.
_CONSOLE_NOISE = (
    "Failed to load resource",
    "net::ERR_ABORTED",
    "net::ERR_EMPTY_RESPONSE",
)


@pytest.fixture
def page(browser: Browser, request: pytest.FixtureRequest) -> Iterator[Page]:
    """A page wired to the esm cache that fails the test on any JS error.

    A test may declare known-buggy output with
    ``@pytest.mark.allow_js_errors("substring")`` -- used to keep a regression
    documented rather than silently tolerated everywhere.
    """
    marker = request.node.get_closest_marker("allow_js_errors")
    allowed = tuple(marker.args) if marker else ()

    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    pg = context.new_page()
    _install_esm_cache(pg)

    errors: list[str] = []

    def record(text: str) -> None:
        if any(noise in text for noise in _CONSOLE_NOISE):
            return
        if any(ok in text for ok in allowed):
            return
        errors.append(text)

    pg.on("pageerror", lambda exc: record(str(exc)))
    pg.on("console", lambda msg: record(msg.text) if msg.type == "error" else None)

    try:
        yield pg
    finally:
        context.close()

    assert not errors, "uncaught JavaScript errors:\n" + "\n".join(errors)


# ── page helpers ────────────────────────────────────────────────────────────


def _wait_until(predicate: Callable[[], bool], timeout: float = 10.0, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(message or f"condition not met within {timeout}s")


def open_dashboard(page: Page, server: ProseviewServer) -> None:
    # `networkidle` never fires: the page holds the /events SSE stream open.
    page.goto(server.base_url, wait_until="load")
    page.wait_for_selector("#sceneTable tbody tr")
    page.wait_for_function("() => !!window._PM")


def open_scene(page: Page, server: ProseviewServer, rel: str = SCENE_REL) -> None:
    page.goto(f"{server.base_url}#/scene/{rel}", wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.wait_for_selector("#sceneProseHost .ProseMirror")


def open_scene_appearance(page: Page) -> None:
    if not page.locator("#sceneAppearanceMenu").is_visible():
        page.locator("#sceneAppearanceBtn").focus()
        page.keyboard.press("Enter")
    page.wait_for_selector("#sceneAppearanceMenu", state="visible")


def enter_edit_mode(page: Page) -> None:
    page.click("#sceneEditBtn")
    page.wait_for_function("() => window._pmEditMode === true")


def append_to_paragraph(page: Page, needle: str, text: str) -> None:
    """Put the caret at the end of the paragraph containing *needle* and type."""
    page.evaluate(
        """(needle) => {
            const host = document.querySelector('#sceneProseHost .ProseMirror');
            const para = Array.from(host.querySelectorAll('p'))
                .find(p => p.textContent.includes(needle));
            if (!para) throw new Error('paragraph not found: ' + needle);
            para.scrollIntoView();
            const range = document.createRange();
            range.selectNodeContents(para);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }""",
        needle,
    )
    page.keyboard.type(text)


def save_scene(page: Page) -> None:
    page.keyboard.press("ControlOrMeta+s")


def wait_for_discuss_answer(page: Page, text: str = "Fake answer") -> None:
    page.wait_for_function(
        "needle => document.querySelector('#discussLog').innerText.includes(needle)",
        arg=text,
        timeout=10_000,
    )


def select_prose(page: Page, needle: str, *, block: str = "start") -> str:
    """Select *needle* in the rendered prose and raise the selection pill.

    The pill is bound to ``mouseup`` on ``#modalBody``, so a synthetic Range has
    to be followed by that event for the UI to react. ``block`` lets placement
    tests exercise selections near both vertical viewport edges.
    """
    selected = page.evaluate(
        """({needle, block}) => {
            const host = document.getElementById('sceneProseHost');
            const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
            let node = null, idx = -1;
            while ((node = walker.nextNode())) {
                idx = node.data.indexOf(needle);
                if (idx >= 0) break;
            }
            if (!node) throw new Error('text not found in prose: ' + needle);
            if (node.parentElement) {
                node.parentElement.scrollIntoView({ block });
            }
            const range = document.createRange();
            range.setStart(node, idx);
            range.setEnd(node, idx + needle.length);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            const rect = range.getBoundingClientRect();
            document.getElementById('modalBody').dispatchEvent(new MouseEvent('mouseup', {
                bubbles: true, clientX: rect.left, clientY: rect.bottom,
            }));
            return sel.toString();
        }""",
        {"needle": needle, "block": block},
    )
    page.wait_for_selector("#selectionPill", state="visible")
    page.wait_for_function("needle => currentSelectionText.includes(needle)", arg=needle)
    return selected


def assert_fully_inside_viewport(page: Page, selector: str) -> None:
    """Assert that a rendered control is completely reachable in the viewport."""
    box = page.locator(selector).bounding_box()
    viewport = page.viewport_size
    assert box and viewport, f"{selector} does not have a rendered box"
    assert box["x"] >= 0, f"{selector} extends past the left viewport edge: {box}"
    assert box["y"] >= 0, f"{selector} extends past the top viewport edge: {box}"
    assert box["x"] + box["width"] <= viewport["width"], (
        f"{selector} extends past the right viewport edge: {box}"
    )
    assert box["y"] + box["height"] <= viewport["height"], (
        f"{selector} extends past the bottom viewport edge: {box}"
    )


def test_discuss_scene_streams_safe_document_aware_conversation(page: Page, server: ProseviewServer):
    open_scene(page, server)
    selected = select_prose(page, "ledger")
    assert selected == "ledger"
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert SCENE_REL in page.locator("#discussContext").inner_text()
    assert "Selection · 1 words" in page.locator("#discussSelectionChip").inner_text()

    page.fill("#discussInput", "Explain this scene")
    page.evaluate("sendDiscussQuestion(); sendDiscussQuestion()")
    wait_for_discuss_answer(page, "<script>hostile()</script>")
    panel_text = page.locator("#discussPanel").inner_text()
    assert "What Codex is doing" in panel_text
    assert "Read context" in panel_text
    assert "commandExecution" in panel_text
    assert "PRIVATE RAW REASONING" not in panel_text
    assert "<script>hostile()</script>" in panel_text
    assert page.locator("#discussLog script").count() == 0
    link = page.locator("#discussLog a", has_text="link")
    assert link.get_attribute("href") == "https://example.test"
    assert page.locator("#discussLog a", has_text="unsafe").count() == 0
    assert page.locator(".discuss-message.user").count() == 1

    page.evaluate("_discussEventSource.close(); setDiscussConnection('Reconnecting', ''); connectDiscussEvents()")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')", timeout=15_000)

    page.locator("#sceneModal .nav-btn").nth(1).click()
    page.wait_for_function("previous => !document.querySelector('#discussContext').innerText.includes(previous)", arg=SCENE_REL)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    page.press("body", "Escape")
    page.wait_for_selector("#discussPanel", state="hidden")
    assert page.evaluate("document.activeElement === document.querySelector('#sceneModal .discuss-open-btn')")


def test_discuss_canon_refactor_audits_then_hands_off_and_verifies_without_silent_writes(
    page: Page, server: ProseviewServer
):
    before = server.scene_path().read_bytes()
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    trace = page.get_by_role("button", name=re.compile("Trace a canon change"))
    assert trace.is_visible()
    assert page.locator("#discussHistoryClear").is_hidden()
    page.fill("#discussInput", "Mira grew up in Chicago, not Boston.")
    trace.click()
    assert page.locator("#discussSend").inner_text() == "Scan"
    assert "Read-only scan" in page.locator("#discussTaskMode").inner_text()
    assert page.locator(".discuss-story-action").count() == 0
    assert page.locator("#discussInput").input_value() == "Mira grew up in Chicago, not Boston."

    page.get_by_role("button", name="Change action").click()
    assert page.get_by_role("button", name=re.compile("Trace a canon change")).is_visible()
    assert page.locator("#discussSend").inner_text() == "Send"
    assert page.locator("#discussInput").input_value() == "Mira grew up in Chicago, not Boston."
    page.get_by_role("button", name=re.compile("Trace a canon change")).click()
    assert page.locator(".discuss-story-action").count() == 0
    page.fill("#discussInput", "Rena changed the safe code this spring.")
    page.locator("#discussSend").click()

    page.wait_for_selector(".discuss-refactor-finding", state="visible")
    assert page.locator("#discussHistoryClear").inner_text() == "Clear results"
    assert page.locator("#discussHistoryClear").is_visible()
    report = page.locator(".discuss-task", has_text="Trace a canon change")
    assert "Read-only scan complete" in report.inner_text()
    assert "manuscript/ch01/01-opening.md#L18" in report.inner_text()
    assert server.scene_path().read_bytes() == before

    report.get_by_role("button", name="Mark intentional").click()
    page.get_by_role("button", name="Mark unresolved").wait_for(state="visible")
    assert server.scene_path().read_bytes() == before

    report.get_by_role("button", name="Review proposed edit").click()
    page.wait_for_selector("#aiProposalPanel", state="visible")
    assert "This sentence preserves the old safe-code history." in page.locator("#aiProposalPanel").inner_text()
    assert server.scene_path().read_bytes() == before

    page.locator("#aiProposalPanel").get_by_role("button", name=re.compile("Dismiss|Close")).click()
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'dismissed'"
    )
    report.get_by_role("button", name="Review proposed edit").click()
    page.get_by_role("button", name="Use this version").wait_for(state="visible")
    page.get_by_role("button", name="Use this version").click()
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'applied'"
    )
    assert server.scene_path().read_bytes() == before
    page.get_by_role("button", name="Undo").click()
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'proposal'"
    )
    assert server.scene_path().read_bytes() == before
    page.get_by_role("button", name="Reject").click()
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'rejected'"
    )
    report.get_by_role("button", name="Verify after edits").click()
    page.wait_for_function(
        "() => [...document.querySelectorAll('.discuss-task-heading strong')]"
        ".some(node => node.innerText === 'Verify a canon change')"
    )
    page.wait_for_function(
        "() => [...document.querySelectorAll('.discuss-task')]"
        ".some(node => node.innerText.includes('Verify a canon change') && node.innerText.includes('Read-only scan complete'))"
    )
    assert server.scene_path().read_bytes() == before


def test_discuss_canon_refactor_marks_a_proposal_resolved_only_after_scene_save(
    page: Page, server: ProseviewServer
):
    before = server.scene_path().read_bytes()
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.get_by_role("button", name=re.compile("Trace a canon change")).click()
    page.fill("#discussInput", "Rena changed the safe code this spring.")
    page.locator("#discussSend").click()
    page.wait_for_selector(".discuss-refactor-finding", state="visible")
    page.get_by_role("button", name="Review proposed edit").click()
    page.get_by_role("button", name="Use this version").wait_for(state="visible")
    page.get_by_role("button", name="Use this version").click()
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'applied'"
    )
    assert server.scene_path().read_bytes() == before

    page.get_by_role("button", name="Save scene").click()
    _wait_until(lambda: server.scene_path().read_bytes() != before)
    page.wait_for_function(
        "() => document.querySelector('.discuss-refactor-finding')?.dataset.decision === 'resolved'"
    )


def test_discuss_scene_continuity_starts_without_an_optional_focus(
    page: Page, server: ProseviewServer
):
    before = server.scene_path().read_bytes()
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    page.get_by_role("button", name=re.compile("Check this scene's continuity")).click()

    assert page.get_by_text("Ready to scan this scene", exact=True).is_visible()
    assert "optional focus" in page.locator("#discussLog").inner_text().lower()
    assert page.locator("#discussInput").input_value() == ""
    page.locator("#discussSend").click()

    page.wait_for_function(
        "() => [...document.querySelectorAll('.discuss-task-status')]"
        ".some(node => ['Ready', 'Failed'].includes(node.innerText))"
    )
    report = page.locator(".discuss-task", has_text="Check this scene's continuity")
    assert "Read-only scan complete" in report.inner_text()
    assert report.locator(".discuss-refactor-finding").is_visible()
    assert server.scene_path().read_bytes() == before


def test_discuss_scene_continuity_bounds_large_repository_context(
    page: Page, server: ProseviewServer
):
    plans = server.root / "plans"
    plans.mkdir(exist_ok=True)
    for index in range(4):
        (plans / f"large-continuity-context-{index}.md").write_text(
            f"# Large continuity context {index}\n\n" + ("A configured story fact.\n" * 15_000),
            encoding="utf-8",
        )
    before = server.scene_path().read_bytes()
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.get_by_role("button", name=re.compile("Check this scene's continuity")).click()
    page.locator("#discussSend").click()

    page.wait_for_function(
        "() => [...document.querySelectorAll('.discuss-task-status')]"
        ".some(node => ['Ready', 'Failed'].includes(node.innerText))"
    )
    report = page.locator(".discuss-task", has_text="Check this scene's continuity")
    assert "Read-only scan complete" in report.inner_text()
    assert report.locator(".discuss-refactor-finding").is_visible()
    assert "Codex input limit" in report.inner_text()
    assert "files were omitted" in report.inner_text()
    assert "Input exceeds the maximum length" not in page.locator("#discussPanel").inner_text()
    assert server.scene_path().read_bytes() == before


def test_discuss_scene_continuity_reports_that_a_scan_is_starting_and_recovers_on_failure(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.get_by_role("button", name=re.compile("Check this scene's continuity")).click()
    page.evaluate(
        """
        () => {
            window.__discussOriginalFetch = window.fetch;
            window.fetch = function(input, options) {
                if (String(input).includes('/questions')) {
                    return new Promise(function(resolve) {
                        window.__resolveDiscussQuestion = function() {
                            resolve(new Response(JSON.stringify({error: 'Continuity scan could not start.'}), {
                                status: 503,
                                headers: {'Content-Type': 'application/json'}
                            }));
                        };
                    });
                }
                return window.__discussOriginalFetch(input, options);
            };
        }
        """
    )

    page.locator("#discussSend").click()

    assert page.get_by_text("Starting continuity scan…", exact=True).is_visible()
    assert page.locator("#discussSend").is_disabled()
    assert page.locator("#discussSend").inner_text() == "Starting…"
    page.evaluate(
        """
        () => {
            window.fetch = window.__discussOriginalFetch;
            window.__resolveDiscussQuestion();
        }
        """
    )
    page.wait_for_function(
        "() => !document.getElementById('discussSend').disabled "
        "&& document.getElementById('discussSend').innerText === 'Scan'"
    )
    assert page.get_by_text("Ready to scan this scene", exact=True).is_visible()
    assert page.get_by_text("Continuity scan could not start.", exact=True).is_visible()


def test_discuss_send_times_out_and_recovers_from_a_stalled_request(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "Why is the opening quiet?")
    page.evaluate(
        """
        () => {
            window._discussRequestTimeoutMs = 100;
            window.__discussOriginalFetch = window.fetch;
            window.fetch = function(input, options) {
                if (!String(input).includes('/questions')) {
                    return window.__discussOriginalFetch(input, options);
                }
                return new Promise(function(_resolve, reject) {
                    options.signal.addEventListener('abort', function() {
                        reject(new DOMException('The operation was aborted.', 'AbortError'));
                    }, {once: true});
                });
            };
        }
        """
    )

    page.locator("#discussSend").click()

    assert page.locator("#discussSend").is_disabled()
    assert page.locator("#discussSend").inner_text() == "Sending…"
    assert page.locator("#discussSend").evaluate("node => getComputedStyle(node).cursor") != "wait"
    page.wait_for_function(
        "() => !document.getElementById('discussSend').disabled "
        "&& document.getElementById('discussSend').innerText === 'Send'",
        timeout=2_000,
    )
    assert page.get_by_text(
        "Request timed out. Check the connection and try again.", exact=True
    ).is_visible()
    assert page.locator("#discussInput").input_value() == "Why is the opening quiet?"


def test_discuss_open_times_out_with_an_operable_retry(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.evaluate(
        """
        () => {
            window._discussRequestTimeoutMs = 100;
            window.__discussOriginalFetch = window.fetch;
            window.__stallDiscussOpen = true;
            window.fetch = function(input, options) {
                if (!window.__stallDiscussOpen || !String(input).includes('/conversations/open')) {
                    return window.__discussOriginalFetch(input, options);
                }
                window.__stallDiscussOpen = false;
                return new Promise(function(_resolve, reject) {
                    options.signal.addEventListener('abort', function() {
                        reject(new DOMException('The operation was aborted.', 'AbortError'));
                    }, {once: true});
                });
            };
        }
        """
    )

    page.locator("#sceneModal .discuss-open-btn").click()

    page.wait_for_function(
        "() => !document.getElementById('discussSend').disabled "
        "&& document.getElementById('discussSend').innerText === 'Try again'",
        timeout=2_000,
    )
    assert page.locator("#discussConnection").inner_text().startswith("Unavailable")
    assert page.get_by_text(
        "Request timed out. Check the connection and try again.", exact=True
    ).is_visible()
    page.locator("#discussSend").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert page.locator("#discussSend").inner_text() == "Send"
    assert not page.locator("#discussSend").is_disabled()


def test_discuss_detects_a_server_restart_and_recovers_by_reload(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    draft = "What do you think about this scene?"
    page.fill("#discussInput", draft)

    server.restart()

    page.wait_for_function(
        "() => document.getElementById('discussConnection').innerText.startsWith('Reload required')",
        timeout=15_000,
    )
    assert page.get_by_text(
        "Proseview restarted. Reload this page to reconnect.", exact=True
    ).is_visible()
    assert page.locator("#discussSend").is_disabled()
    assert page.locator("#discussInput").input_value() == draft

    page.get_by_role("button", name="Reload page").click()
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert page.locator("#discussInput").input_value() == draft


def test_discuss_repository_action_selected_state_reflows_at_dark_200_percent_zoom(
    page: Page, server: ProseviewServer
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.evaluate("document.body.style.zoom = '2'")

    trace = page.get_by_role("button", name=re.compile("Trace a canon change"))
    trace.click()

    assert page.locator(".discuss-story-action").count() == 0
    change_action = page.get_by_role("button", name="Change action")
    assert change_action.is_visible()
    assert page.locator("#discussSend").inner_text() == "Scan"
    assert page.evaluate("document.activeElement === document.getElementById('discussInput')")
    assert_fully_inside_viewport(page, "#discussTaskMode")
    assert_fully_inside_viewport(page, "#discussInput")
    assert_fully_inside_viewport(page, "#discussSend")
    change_action.focus()
    assert change_action.evaluate("button => document.activeElement === button")
    change_action.press("Enter")
    assert page.get_by_role("button", name=re.compile("Trace a canon change")).is_visible()
    assert page.evaluate("document.activeElement === document.getElementById('discussInput')")


def test_discuss_decodes_restored_assistant_prose_after_server_restart(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "Describe Patel's setting")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page, "Patel's note")

    server.restart()
    page.context.new_cdp_session(page).send("Network.setCacheDisabled", {"cacheDisabled": True})
    page.goto("about:blank")
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    wait_for_discuss_answer(page, "Patel's note")

    assistant = page.locator(".discuss-message.assistant")
    assert "Patel's note" in assistant.inner_text()
    assert "&#39;" not in assistant.inner_text()
    assert assistant.locator("code").inner_text() == "&amp;"
    assert assistant.locator("script").count() == 0
    assert assistant.locator("a", has_text="link").get_attribute("href") == "https://example.test"
    assert assistant.locator("a", has_text="unsafe").count() == 0


def test_discuss_repository_links_open_inside_prosview_and_target_source_line(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "SHOW_FILE_LINKS")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page, "current scene")

    assistant = page.locator(".discuss-message.assistant").last
    current = assistant.get_by_role("link", name="current scene")
    assert current.get_attribute("href").endswith("#/scene/ch01%2F01-opening.md")
    assert current.get_attribute("target") is None
    assert current.get_attribute("title") == "Open in Prosview at line 18"
    assert assistant.get_by_role("link", name="another scene").get_attribute("href").endswith(
        "#/scene/ch01%2F02-walk.md"
    )
    assert assistant.get_by_role("link", name="repository file").get_attribute("href").endswith(
        "#/file/scripts%2Fcheck_continuity.py"
    )
    assert assistant.locator("a", has_text="outside repository").count() == 0
    assert assistant.locator("a", has_text="unsafe").count() == 0
    external = assistant.get_by_role("link", name="external")
    assert external.get_attribute("href") == "https://example.test/reference"
    assert external.get_attribute("target") == "_blank"

    current.click()
    assert page.evaluate("decodeURIComponent(location.hash)") == f"#/scene/{SCENE_REL}"
    target = page.locator("#sceneProseHost .para-flash")
    target.wait_for(state="visible")
    assert target.get_attribute("data-line") == "18"

    assistant.get_by_role("link", name="repository file").click()
    page.wait_for_function(
        "() => document.getElementById('filePreviewTitle').innerText === 'scripts/check_continuity.py'"
    )
    assert page.evaluate("decodeURIComponent(location.hash)") == "#/file/scripts/check_continuity.py"


def test_discuss_repository_link_preserves_unsaved_scene_edits(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "SHOW_FILE_LINKS")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page, "another scene")

    page.click("#sceneEditBtn")
    page.evaluate(
        """() => {
            _pmView.dispatch(_pmView.state.tr.insertText('Unsaved local note. ', 1));
            setPmDirty(true);
        }"""
    )
    page.locator(".discuss-message.assistant").last.get_by_role("link", name="another scene").click()

    assert page.evaluate("decodeURIComponent(location.hash)") == f"#/scene/{SCENE_REL}"
    assert "Unsaved local note." in _editor_text(page)
    assert "Save or cancel your scene edits before opening another file." in page.locator("#discussLog").inner_text()


def test_discuss_current_file_is_default_removable_context(
    page: Page,
    server: ProseviewServer,
    fake_home: Path,
):
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    context_button = page.locator("#discussContextButton")
    assert context_button.get_attribute("aria-label") == "Add files and more"
    assert "+ Context" not in page.locator("#discussComposerArea").inner_text()
    page.locator("#discussInput").press("@")
    page.wait_for_selector("#discussContextPicker", state="visible")
    assert page.locator("#discussContextOptions").get_attribute("role") == "listbox"
    assert not page.locator("#discussContextPicker").evaluate("node => node.matches(':modal')")
    assert context_button.get_attribute("aria-expanded") == "true"
    page.locator("#discussInput").press("Escape")
    page.wait_for_selector("#discussContextPicker", state="hidden")
    assert context_button.get_attribute("aria-expanded") == "false"
    assert page.locator("#discussPanel").is_visible()

    page.fill("#discussInput", "Compare ")
    page.locator("#discussInput").press_sequentially("@02-walk")
    page.wait_for_selector("#discussContextPicker", state="visible")
    assert "manuscript/ch01/02-walk.md" in page.locator("#discussContextOptions").inner_text()
    page.locator("#discussInput").press("Enter")
    page.wait_for_selector("#discussContextPicker", state="hidden")
    assert page.locator("#discussInput").input_value() == "Compare "
    assert "manuscript/ch01/02-walk.md" in page.locator("#discussContext").inner_text()
    page.locator("#discussInput").press_sequentially("@check_continuity")
    page.wait_for_selector("#discussContextPicker", state="visible")
    assert "scripts/check_continuity.py" in page.locator("#discussContextOptions").inner_text()
    page.locator("#discussInput").press("Enter")
    assert "scripts/check_continuity.py" in page.locator("#discussContext").inner_text()
    current_chip = page.locator("#discussContext .discuss-chip-current")
    assert SCENE_REL in current_chip.inner_text()

    current_chip.get_by_role("button", name=f"Remove current document {SCENE_REL}").click()
    assert SCENE_REL not in page.locator("#discussContext").inner_text()

    question = "Compare BROWSER OMIT CURRENT DOCUMENT SENTINEL"
    page.fill("#discussInput", question)
    page.locator("#discussSend").click()
    wait_for_discuss_answer(page, "<script>hostile()</script>")

    records = [json.loads(line) for line in (fake_home / "fake-codex-received.jsonl").read_text(encoding="utf-8").splitlines()]
    prompt = next(
        record["params"]["input"][0]["text"]
        for record in reversed(records)
        if question in json.dumps(record)
    )
    assert "Opening Ledger" not in prompt
    assert "manuscript/ch01/02-walk.md" in prompt
    assert "def check_continuity" in prompt
    assert question in prompt


def test_discuss_approval_file_navigation_and_shared_terminal_dock(page: Page, server: ProseviewServer):
    page.goto(f"{server.base_url}#/file/plans/book-plan.md", wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#file-preview-panel", state="visible")
    page.click("#file-preview-panel .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert "plans/book-plan.md" in page.locator("#discussContext").inner_text()

    page.get_by_role("button", name="Add files and more").click()
    page.wait_for_selector("#discussContextPicker", state="visible")
    page.locator("#discussInput").press_sequentially("plans")
    page.locator("#discussContextOptions [data-path='plans']").click()
    assert "plans" in page.locator("#discussContext").inner_text()

    page.fill("#discussInput", "REQUEST_APPROVAL")
    page.press("#discussInput", "Enter")
    page.wait_for_selector(".discuss-approval button", state="visible")
    assert page.evaluate("document.activeElement === document.querySelector('.discuss-approval button')")
    page.keyboard.press("Enter")
    wait_for_discuss_answer(page, "Approval resolved")
    assert "resolved" in page.locator(".discuss-approval").inner_text().lower()

    page.fill("#discussInput", "REQUEST_APPROVAL again")
    page.press("#discussInput", "Enter")
    page.locator(".discuss-approval button", has_text="Decline").wait_for(state="visible")
    page.locator(".discuss-approval button", has_text="Decline").click()
    page.wait_for_function("() => document.querySelector('#discussLog').innerText.includes('Approval resolved: decline')")

    page.click("#discussPanel .utility-tab:text-is('Terminal')")
    page.wait_for_selector("#terminalPanel", state="visible")
    page.wait_for_function("() => document.getElementById('terminalPanel').classList.contains('dock-right')")
    page.wait_for_selector(".terminal-tab-mount .xterm", timeout=20_000)
    page.click(".terminal-tab-mount .xterm-screen")
    _wait_until(lambda: any(ch in _terminal_text(page) for ch in ("$", "%", "#")), timeout=25)
    run_in_terminal(page, "echo discuss-terminal-alive", "discuss-terminal-alive")
    page.click("#terminalPanel button:text-is('Discuss')")
    page.wait_for_selector("#discussPanel", state="visible")
    assert "Approval resolved" in page.locator("#discussLog").inner_text()
    page.click("#discussPanel .utility-tab:text-is('Terminal')")
    assert "discuss-terminal-alive" in _terminal_text(page)


def test_discuss_responsive_dark_zoom_and_keyboard_flow(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 1400, "height": 1000})
    open_scene(page, server)
    button = page.locator("#sceneModal .discuss-open-btn")
    button.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    box = page.locator("#discussPanel").bounding_box()
    assert box and box["x"] + box["width"] <= 1401

    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    page.set_viewport_size({"width": 1024, "height": 768})
    page.evaluate("document.body.style.zoom = '2'")
    page.wait_for_timeout(100)
    box = page.locator("#discussPanel").bounding_box()
    assert box and box["x"] >= 0 and box["width"] <= 1024
    assert page.locator("#discussInput").is_visible()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.locator("#discussInput").press("@")
    page.wait_for_selector("#discussContextPicker", state="visible")
    menu_box = page.locator("#discussContextPicker").bounding_box()
    assert menu_box
    assert menu_box["x"] >= 0 and menu_box["x"] + menu_box["width"] <= 1024
    assert menu_box["y"] >= 0 and menu_box["y"] + menu_box["height"] <= 768
    page.locator("#discussInput").press("Escape")
    assert page.locator("#discussPanel").is_visible()

    page.evaluate("document.body.style.zoom = '1'")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(100)
    phone_box = page.locator("#discussPanel").bounding_box()
    assert phone_box and phone_box["x"] == 0 and phone_box["width"] <= 390
    page.fill("#discussInput", "")
    page.get_by_role("button", name="Add files and more").click()
    page.wait_for_selector("#discussContextPicker", state="visible")
    phone_menu_box = page.locator("#discussContextPicker").bounding_box()
    assert phone_menu_box and phone_menu_box["x"] >= 0 and phone_menu_box["x"] + phone_menu_box["width"] <= 390
    page.locator("#discussInput").press("Escape")

    page.keyboard.press("Escape")
    page.wait_for_selector("#discussPanel", state="hidden")
    assert page.evaluate("document.activeElement === document.querySelector('#sceneModal .discuss-open-btn')")


def test_discuss_queues_stops_and_continues(page: Page, server: ProseviewServer):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "HOLD_FOR_STOP")
    page.press("#discussInput", "Enter")
    page.wait_for_selector("#discussStop", state="visible")

    page.fill("#discussInput", "Continue after the stopped turn")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('#discussLog').innerText.includes('item queued')")

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelectorAll('.discuss-message.user').length === 2")
    page.wait_for_selector("#discussStop", state="visible")
    page.click("#discussStop")
    wait_for_discuss_answer(page, "Fake answer")
    assert page.locator(".discuss-message.user").count() == 2
    page.wait_for_selector("#discussStop", state="hidden")


def test_discuss_stop_recovers_when_codex_unloads_thread(page: Page, server: ProseviewServer):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "HOLD_UNLOAD_ON_STOP")
    page.press("#discussInput", "Enter")
    page.wait_for_selector("#discussStop", state="visible")

    page.fill("#discussInput", "Continue in a fresh conversation")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('#discussLog').innerText.includes('item queued')")
    page.click("#discussStop")

    wait_for_discuss_answer(page, "Fake answer")
    page.wait_for_selector("#discussStop", state="hidden")
    connection = page.locator("#discussConnection").inner_text()
    assert connection == "Live"
    assert "thread not loaded" not in connection


def test_discuss_pending_queue_item_can_be_removed(page: Page, server: ProseviewServer):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "HOLD_FOR_STOP")
    page.press("#discussInput", "Enter")
    page.wait_for_selector("#discussStop", state="visible")
    page.fill("#discussInput", "Remove this queued request")
    page.press("#discussInput", "Enter")
    remove = page.get_by_role("button", name="Remove Question from queue")
    remove.wait_for(state="visible")
    remove.click()
    page.wait_for_function("() => !document.querySelector('.discuss-queue-remove')")
    assert page.locator(".discuss-message.user").count() == 1
    page.click("#discussStop")
    page.wait_for_selector("#discussStop", state="hidden")


def test_active_codex_turn_explains_new_conversation_and_has_explicit_stop(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "HOLD_FOR_STOP")
    page.press("#discussInput", "Enter")

    stop = page.get_by_role("button", name="Stop Codex")
    stop.wait_for(state="visible")
    assert page.locator("#discussNewConversation").is_disabled()
    hint = page.locator("#discussNewConversationHint")
    assert hint.is_visible()
    assert "Stop Codex before starting a new conversation" in hint.inner_text()

    stopping = page.evaluate(
        """() => new Promise(resolve => {
            const button = document.getElementById('discussStop');
            const observer = new MutationObserver(() => {
                if (button.textContent === 'Stopping…') {
                    observer.disconnect();
                    resolve(button.textContent);
                }
            });
            observer.observe(button, {childList: true, subtree: true});
            button.click();
        })"""
    )
    assert stopping == "Stopping…"
    page.wait_for_selector("#discussStop", state="hidden")
    page.wait_for_function("() => !document.getElementById('discussNewConversation').disabled")
    assert hint.is_hidden()


def test_discuss_refresh_recovers_missing_thread_and_new_conversation_is_explicit(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "FORGET_THREAD_AFTER_TURN")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page)

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    panel_text = page.locator("#discussPanel").inner_text()
    assert "next question will start a new conversation" in panel_text.lower()
    assert "thread not found" not in panel_text.lower()

    page.fill("#discussInput", "Continue after refresh")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('.discuss-message.assistant').length === 2")
    page.wait_for_function("() => !document.getElementById('discussNewConversation').disabled")
    assert page.locator("#discussConnection").inner_text().startswith("Live")

    new_button = page.locator("#discussNewConversation")
    new_button.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#discussNewConversationDialog", state="visible")
    assert page.evaluate("document.activeElement === document.getElementById('discussNewConversationCancel')")
    assert "reopen the current conversation later from History" in page.locator("#discussNewConversationDialog").inner_text()
    page.keyboard.press("Escape")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")
    page.wait_for_selector("#discussPanel", state="visible")
    assert page.evaluate("document.activeElement === document.getElementById('discussNewConversation')")

    page.keyboard.press("Enter")
    page.click("#discussNewConversationConfirm")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")
    page.wait_for_function("() => document.querySelectorAll('#discussLog .discuss-message').length === 0")
    assert "Ask about what you are reading" in page.locator("#discussLog").inner_text()
    assert page.evaluate("document.activeElement === document.getElementById('discussInput')")

    page.fill("#discussInput", "A fresh browser conversation")
    page.press("#discussInput", "Enter")
    page.wait_for_function(
        "() => document.querySelectorAll('.discuss-message.user').length === 1 && "
        "document.querySelector('#discussLog').innerText.includes('Fake answer')"
    )
    assert page.locator(".discuss-message.user").count() == 1


def test_conversation_history_reopens_a_previous_thread(page: Page, server: ProseviewServer):
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "Why is the opening quiet?")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page)

    page.click("#discussNewConversation")
    page.click("#discussNewConversationConfirm")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")
    page.fill("#discussInput", "What changes in the second conversation?")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page)

    page.click("#discussHistory")
    page.wait_for_selector("#discussHistoryDialog", state="visible")
    previous = page.locator(".discuss-history-row").filter(has_text="Why is the opening quiet?")
    previous.wait_for(state="visible")
    assert previous.count() == 1
    assert "Saved conversation" in previous.inner_text()
    previous.get_by_role("button", name="Open").click()
    page.wait_for_selector("#discussHistoryDialog", state="hidden")
    page.wait_for_function("() => document.querySelector('#discussLog').innerText.includes('Why is the opening quiet?')")
    assert "What changes in the second conversation?" not in page.locator("#discussLog").inner_text()

    page.fill("#discussInput", "Continue this earlier thought")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('.discuss-message.user').length === 2")
    page.wait_for_function("() => document.querySelectorAll('.discuss-message.assistant').length === 2")

    page.click("#discussHistory")
    current = page.locator(".discuss-history-row").filter(has_text="Why is the opening quiet?")
    current.wait_for(state="visible")
    current.locator("summary").click()
    current.get_by_role("button", name="Rename").click()
    current.locator("input").fill("Opening rhythm")
    current.get_by_role("button", name="Save").click()
    renamed = page.locator(".discuss-history-row").filter(has_text="Opening rhythm")
    renamed.wait_for(state="visible")
    renamed.locator("summary").click()
    with page.expect_download() as download_info:
        renamed.get_by_role("button", name="Export JSON").click()
    exported = Path(download_info.value.path()).read_text(encoding="utf-8")
    assert '"title": "Opening rhythm"' in exported
    assert "BEGIN UNTRUSTED DOCUMENT" not in exported
    assert "RAW SECRET" not in exported

    page.click("#discussHistoryClose")
    page.click("#discussNewConversation")
    page.click("#discussNewConversationConfirm")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")
    page.click("#discussHistory")
    saved = page.locator(".discuss-history-row").filter(has_text="Opening rhythm")
    saved.wait_for(state="visible")
    saved.locator("summary").click()
    page.once("dialog", lambda dialog: dialog.accept())
    saved.get_by_role("button", name="Remove from history").click()
    saved.wait_for(state="detached")


def test_new_conversation_dialog_announces_pending_and_recovers_from_failure(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.click("#discussNewConversation")
    page.wait_for_selector("#discussNewConversationDialog", state="visible")
    page.evaluate(
        """() => {
            const originalFetch = window.fetch.bind(window);
            window.fetch = function(...args) {
                if (String(args[0]).endsWith('/new')) {
                    return new Promise((resolve, reject) => {
                        window.__releaseConversationReset = () => {
                            window.fetch = originalFetch;
                            originalFetch(...args).then(resolve, reject);
                        };
                    });
                }
                return originalFetch(...args);
            };
        }"""
    )

    pending = page.evaluate(
        """() => new Promise(resolve => {
            const dialog = document.getElementById('discussNewConversationDialog');
            const button = document.getElementById('discussNewConversationConfirm');
            const observer = new MutationObserver(() => {
                if (button.textContent === 'Starting…') {
                    observer.disconnect();
                    resolve({
                        label: button.textContent,
                        disabled: button.disabled,
                        busy: dialog.getAttribute('aria-busy'),
                        announcement: document.getElementById('discussAnnouncement').textContent,
                    });
                }
            });
            observer.observe(button, {childList: true, subtree: true});
            button.click();
        })"""
    )
    assert pending == {
        "label": "Starting…",
        "disabled": True,
        "busy": "true",
        "announcement": "Starting a new conversation",
    }
    page.keyboard.press("Escape")
    assert page.locator("#discussNewConversationDialog").is_visible()
    slow_status = page.locator("#discussNewConversationStatus")
    slow_status.wait_for(state="visible", timeout=3_000)
    assert "Still starting" in slow_status.inner_text()
    page.evaluate("window.__releaseConversationReset()")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")

    page.click("#discussNewConversation")
    page.wait_for_selector("#discussNewConversationDialog", state="visible")
    page.route(
        "**/api/discuss/conversations/*/new",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body='{"error":"The local reset could not finish safely."}',
        ),
    )
    page.click("#discussNewConversationConfirm")
    error = page.locator("#discussNewConversationError")
    error.wait_for(state="visible")
    assert "could not finish safely" in error.inner_text()
    retry = page.get_by_role("button", name="Try again")
    assert retry.is_enabled()
    assert retry.evaluate("button => document.activeElement === button")
    assert page.locator("#discussNewConversationDialog").get_attribute("aria-busy") == "false"


def test_new_conversation_dialog_remains_operable_at_dark_200_percent_zoom(
    page: Page, server: ProseviewServer
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.evaluate("document.body.style.zoom = '2'")
    page.click("#discussNewConversation")
    page.wait_for_selector("#discussNewConversationDialog", state="visible")

    assert_fully_inside_viewport(page, "#discussNewConversationDialog")
    assert page.get_by_role("button", name="Keep conversation").is_visible()
    assert page.get_by_role("button", name="Start new conversation").is_visible()
    page.keyboard.press("Escape")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")


def open_selection_menu(page: Page, needle: str) -> None:
    select_prose(page, needle)
    page.click("#selectionPillBtn")
    page.wait_for_selector("#selectionPillMenu", state="visible")


def _editor_text(page: Page) -> str:
    return page.locator("#sceneProseHost .ProseMirror").inner_text()


def frontmatter(text: str) -> str:
    match = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    assert match, "scene file lost its frontmatter block"
    return match.group(0)


def paragraphs(text: str) -> list[str]:
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    return [p.strip() for p in body.split("\n\n") if p.strip()]


# ── dashboard, navigation, preferences ──────────────────────────────────────


def test_dashboard_renders_the_scene_table_and_charts(page: Page, server: ProseviewServer):
    open_dashboard(page, server)

    assert page.locator("#sceneTable tbody tr").count() >= 6
    table = page.locator("#sceneTable").inner_text()
    assert SCENE_REL in table
    assert LARGE_SCENE_REL in table
    assert "10,069" in table, "word counts are not rendered in the scene table"

    # Charts are Chart.js canvases; a non-zero box means they actually laid out.
    for chart_id in ("presenceChart", "rhythmChart", "locationChart", "lexicalScatterChart"):
        box = page.locator(f"#{chart_id}").bounding_box()
        assert box and box["width"] > 0, f"{chart_id} did not render"


def test_deep_link_opens_a_scene_and_back_returns_to_the_dashboard(page: Page, server: ProseviewServer):
    open_dashboard(page, server)
    # `openSceneModal` is bound to the path span inside the row, not the <tr>.
    page.click(f"#sceneTable tr.scene-row span:text-is('{SCENE_REL}')")
    page.wait_for_selector("#sceneModal", state="visible")
    # The router percent-encodes the path segment, so compare decoded.
    assert page.evaluate("decodeURIComponent(location.hash)") == f"#/scene/{SCENE_REL}"

    page.go_back()
    page.wait_for_selector("#sceneModal", state="hidden")

    # And the URL alone is enough to restore the view.
    open_scene(page, server)
    assert SCENE_REL in page.locator("#modalTitle").inner_text()


def test_tab_routes_survive_navigation(page: Page, server: ProseviewServer):
    open_dashboard(page, server)
    page.click(".tab-nav button[data-tab='todos']")
    assert page.evaluate("location.hash") == "#/tab/todos"

    page.reload(wait_until="load")
    page.wait_for_selector("#tab-todos.active")
    assert page.locator("#tab-todos").is_visible()


def test_todo_and_note_tabs_list_scene_annotations(page: Page, server: ProseviewServer):
    open_dashboard(page, server)

    page.click(".tab-nav button[data-tab='todos']")
    page.wait_for_selector("#tab-todos.active")
    assert "Tighten this opening beat" in page.locator("#tab-todos").inner_text()

    page.click(".tab-nav button[data-tab='notes']")
    page.wait_for_selector("#tab-notes.active")
    assert "Patel should not know about the safe yet" in page.locator("#notesTabContent").inner_text()


def test_scene_table_sorts_by_column(page: Page, server: ProseviewServer):
    open_dashboard(page, server)
    first_column = "#sceneTable tbody tr td:first-child"

    before = page.locator(first_column).all_inner_texts()
    page.click("#sceneTable thead th:first-child")
    after = page.locator(first_column).all_inner_texts()

    assert sorted(before) == sorted(after), "sorting must not add or drop rows"
    assert before != after, "clicking the header did not reorder the table"


def test_theme_choice_survives_a_reload(page: Page, server: ProseviewServer):
    """Theme is written to localStorage and re-applied on load."""
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    _wait_until(lambda: page.evaluate("document.documentElement.dataset.theme") == "dark")

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")

    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.locator("#modalThemeSelect").input_value() == "dark"


def test_scene_toolbar_is_compact_and_exposes_grouped_actions(page: Page, server: ProseviewServer):
    open_scene(page, server)

    header = page.locator("#sceneModal .modal-header")
    box = header.bounding_box()
    assert box and box["height"] <= 52
    assert page.locator("#modalTitle").bounding_box()["width"] > 0
    assert page.get_by_role("button", name="Discuss").is_visible()
    assert page.get_by_role("button", name="Edit scene").is_visible()

    page.locator("#sceneAppearanceBtn").click()
    appearance = page.locator("#sceneAppearanceMenu")
    assert appearance.is_visible()
    assert page.locator("#modalFontSize").is_visible()
    assert page.locator("#modalFontSelect").is_visible()
    assert page.locator("#modalThemeSelect").is_visible()
    assert page.locator("#modalLineNumbersBtn").is_visible()

    page.locator("#sceneMoreBtn").click()
    more = page.locator("#sceneMoreMenu")
    assert more.is_visible()
    assert page.locator("#modalRefreshBtn").is_visible()
    assert page.locator("#modalEditorBtn").is_visible()
    assert page.locator("#agentMenuSceneBtn").is_visible()
    assert more.get_by_role("button", name="Open shell").is_visible()
    page.keyboard.press("Escape")
    assert more.is_hidden()
    assert page.evaluate("document.activeElement.id") == "sceneMoreBtn"


def test_scene_toolbar_visibility_mode_persists_and_has_keyboard_recovery(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    header = page.locator("#sceneModal .modal-header")

    page.locator("#sceneAppearanceBtn").click()
    page.locator("input[name='sceneToolbarMode'][value='hidden']").check()
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'true'"
    )
    assert page.evaluate("localStorage.getItem('proseview-scene-toolbar-mode')") == "hidden"

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'true'"
    )
    stats_box = page.locator("#modalStats").bounding_box()
    assert stats_box and stats_box["y"] <= 2

    reveal_box = page.locator("#sceneToolbarReveal").bounding_box()
    assert reveal_box
    page.mouse.move(
        reveal_box["x"] + reveal_box["width"] / 2,
        reveal_box["y"] + reveal_box["height"] / 2,
    )
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'false'"
    )
    page.mouse.move(500, 500)
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'true'"
    )

    page.locator("#sceneToolbarReveal").focus()
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'false'"
    )
    assert page.evaluate("document.activeElement.id") == "sceneToolbarReveal"
    assert header.get_attribute("data-toolbar-mode") == "hidden"


def test_scene_toolbar_auto_hides_on_scroll_and_reveals_on_reverse_scroll(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server, LARGE_SCENE_REL)
    scroller = page.locator("#sceneModal .modal-content")
    # Route scroll restoration retries for 260ms while the editor settles.
    page.wait_for_timeout(350)
    scroller.hover(position={"x": 400, "y": 500})
    page.mouse.wheel(0, 1400)
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'true'"
    )

    page.mouse.wheel(0, -500)
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'false'"
    )


def test_scene_toolbar_auto_mode_does_not_move_with_reduced_motion(
    page: Page,
    server: ProseviewServer,
):
    page.emulate_media(reduced_motion="reduce")
    open_scene(page, server, LARGE_SCENE_REL)
    scroller = page.locator("#sceneModal .modal-content")
    page.wait_for_timeout(350)
    scroller.evaluate(
        "node => { node.style.scrollBehavior = 'auto'; "
        "node.scrollTop = node.scrollHeight - node.clientHeight; "
        "node.dispatchEvent(new Event('scroll')); }"
    )

    assert page.locator("#sceneModal .modal-header").get_attribute("data-toolbar-hidden") == "false"


def test_focus_layout_uses_the_toolbar_visibility_state(page: Page, server: ProseviewServer):
    open_scene(page, server)

    page.keyboard.press("f")
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'true'"
    )
    assert page.locator("#modalStats").is_hidden()
    assert page.locator("#modalFocusBtn").get_attribute("aria-pressed") == "true"

    page.keyboard.press("f")
    page.wait_for_function(
        "() => document.querySelector('#sceneModal .modal-header').dataset.toolbarHidden === 'false'"
    )
    assert page.locator("#modalStats").is_visible()
    assert page.locator("#modalFocusBtn").get_attribute("aria-pressed") == "false"


def test_scene_toolbar_mode_change_invalidates_temporary_hide_timer(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    page.evaluate("setSceneToolbarMode('hidden'); revealSceneToolbar(true)")
    page.locator("#sceneAppearanceBtn").focus()
    page.keyboard.press("Enter")
    page.locator("input[name='sceneToolbarMode'][value='pinned']").check()
    page.locator("#sceneProseHost .ProseMirror").focus()
    page.wait_for_timeout(2000)

    header = page.locator("#sceneModal .modal-header")
    assert header.get_attribute("data-toolbar-mode") == "pinned"
    assert header.get_attribute("data-toolbar-hidden") == "false"


def test_scene_toolbar_stays_single_row_with_dock_and_at_two_hundred_percent_zoom(
    page: Page,
    server: ProseviewServer,
):
    page.set_viewport_size({"width": 1400, "height": 800})
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_selector("#discussPanel", state="visible")

    header = page.locator("#sceneModal .modal-header")
    box = header.bounding_box()
    assert box and box["height"] <= 52
    assert page.locator("#modalTitle").bounding_box()["width"] > 0

    page.evaluate("document.body.style.zoom = '2'")
    page.wait_for_function("() => document.documentElement.dataset.cssZoom === 'true'")
    box = header.bounding_box()
    assert box and box["height"] <= 104
    assert page.evaluate(
        "() => { const h = document.querySelector('#sceneModal .modal-header'); "
        "return h.scrollWidth <= h.clientWidth; }"
    )
    for selector in ("#sceneMoreBtn", "#sceneAppearanceBtn", "#sceneEditBtn"):
        action = page.locator(selector).bounding_box()
        assert action
        assert action["x"] >= 0 and action["x"] + action["width"] <= 1400

    for trigger, menu in (
        ("#sceneAppearanceBtn", "#sceneAppearanceMenu"),
        ("#sceneMoreBtn", "#sceneMoreMenu"),
    ):
        page.locator(trigger).click()
        menu_box = page.locator(menu).bounding_box()
        assert menu_box
        assert menu_box["x"] >= 0
        assert menu_box["x"] + menu_box["width"] <= 1400
        assert menu_box["y"] >= 0
        assert menu_box["y"] + menu_box["height"] <= 800
        page.keyboard.press("Escape")


def test_scene_toolbar_actions_remain_clickable_beside_compact_dock(
    page: Page,
    server: ProseviewServer,
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, server)
    page.locator("#sceneModal .discuss-open-btn").click()
    page.wait_for_selector("#discussPanel", state="visible")

    header = page.locator("#sceneModal .modal-header")
    assert header.bounding_box()["height"] <= 52
    assert page.evaluate(
        "() => { const h = document.querySelector('#sceneModal .modal-header'); "
        "return h.scrollWidth <= h.clientWidth; }"
    )
    page.locator("#sceneAppearanceBtn").click()
    assert page.locator("#sceneAppearanceMenu").is_visible()


def test_switching_theme_does_not_raise(page: Page, server: ProseviewServer):
    """Re-theming the charts must not throw.

    Regression guard: this used to recurse to a stack overflow because the
    theme was written through Chart.js's resolved options proxy rather than the
    raw config. Charts must still repaint, so assert both.
    """
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    open_scene(page, server)
    open_scene_appearance(page)
    for theme in ("dark", "docsify", "hopscotch", "light"):
        page.select_option("#modalThemeSelect", theme)
        _wait_until(lambda t=theme: page.evaluate("document.documentElement.dataset.theme") == t)

    assert not errors, f"switching theme raised: {errors}"

    # Charts live behind the modal, so close it before checking they repainted
    # rather than being torn down by the re-theme.
    page.click("#sceneModal .modal-close")
    page.wait_for_selector("#sceneModal", state="hidden")
    box = page.locator("#presenceChart").bounding_box()
    assert box and box["width"] > 0, "charts did not survive the theme switch"


@pytest.mark.parametrize("font", ["reader", "literary", "inter", "georgia", "baskerville", "sans", "mono"])
def test_every_font_choice_survives_a_reload(page: Page, server: ProseviewServer, font: str):
    """All seven fonts, because the boot allow-list once knew only four.

    Inter, Georgia, and Baskerville were accepted by the picker, written to
    localStorage, then silently rejected on load and reset to Reader.
    """
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalFontSelect", font)
    _wait_until(lambda: page.evaluate("document.documentElement.dataset.font") == font)

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")

    assert page.evaluate("document.documentElement.dataset.font") == font
    assert page.locator("#modalFontSelect").input_value() == font


#: Every editorial pass, and the CSS class its marks carry. Mirrors
#: ``PASS_CLASSES`` in ``00-state.js``; a rename there should fail these tests.
PASS_CLASSES = {
    "passive_voice": "hl-passive",
    "filter_verbs": "hl-filter",
    "crutch_words": "hl-crutch",
    "hyperbole": "hl-hyperbole",
    "lyrical": "hl-lyrical",
    "sensory": "hl-sensory",
    "comedy_beats": "hl-comedy",
    "repeats": "hl-repeat",
    "first_person": "hl-first-person",
}


def _scene_with_hits(server: ProseviewServer, pass_name: str) -> str:
    """Pick the scene where *pass_name* fires hardest.

    Chosen from the server's own highlight payload rather than hard-coded, so
    the test follows the fixture instead of silently going vacuous when the
    prose changes.
    """
    highlights = server.get_json("/data.json")["highlightsByPath"]

    def hits(entry: dict) -> int:
        value = entry["highlights"].get(pass_name, 0)
        return len(value) if hasattr(value, "__len__") else int(value or 0)

    best = max(highlights.items(), key=lambda kv: hits(kv[1]))
    assert hits(best[1]) > 0, f"no fixture scene exercises the {pass_name} pass"
    return best[0]


@pytest.mark.parametrize("pass_name", list(PASS_CLASSES))
def test_every_highlight_pass_marks_the_prose(page: Page, shared_server: ProseviewServer, pass_name: str):
    """All nine passes, each on a scene that actually triggers it."""
    css = PASS_CLASSES[pass_name]
    scene = _scene_with_hits(shared_server, pass_name)

    open_scene(page, shared_server, scene)
    marks = page.locator(f"#sceneProseHost .{css}")
    assert marks.count() == 0, f"{pass_name} marks rendered before the pass was enabled"

    toggle = page.locator(f"#tag-{pass_name}")
    toggle.wait_for(state="visible")
    toggle.click()

    _wait_until(
        lambda: "alert-tag-active" in (toggle.get_attribute("class") or ""),
        message=f"{pass_name} chip did not activate",
    )
    # The chip lighting up is not the feature; the marks are.
    _wait_until(
        lambda: marks.count() > 0,
        message=f"{pass_name} enabled but no .{css} marks rendered in {scene}",
    )


def test_highlight_pass_choice_persists_across_a_reload(page: Page, shared_server: ProseviewServer):
    open_scene(page, shared_server)
    page.click("#tag-repeats")
    _wait_until(lambda: page.locator("#sceneProseHost .hl-repeat").count() > 0)

    page.reload(wait_until="load")
    page.wait_for_selector("#sceneProseHost .ProseMirror")

    assert "alert-tag-active" in (page.locator("#tag-repeats").get_attribute("class") or "")
    _wait_until(
        lambda: page.locator("#sceneProseHost .hl-repeat").count() > 0,
        message="pass was remembered but its marks were not re-rendered",
    )


def test_clear_all_turns_every_active_pass_off(page: Page, shared_server: ProseviewServer):
    open_scene(page, shared_server)
    page.click("#tag-repeats")
    page.click("#tag-sensory")
    _wait_until(lambda: page.locator("#sceneProseHost .hl-repeat").count() > 0)

    # #tag-all reads "All" when everything is off and "Clear" once any pass is on.
    assert page.locator("#tag-all").inner_text().strip() == "Clear"
    page.click("#tag-all")

    _wait_until(
        lambda: page.locator("#sceneProseHost .hl-repeat").count() == 0
        and page.locator("#sceneProseHost .hl-sensory").count() == 0,
        message="Clear did not remove the rendered marks",
    )


def test_repo_tree_previews_a_non_manuscript_file(page: Page, server: ProseviewServer):
    page.goto(f"{server.base_url}#/file/plans/book-plan.md", wait_until="load")
    page.wait_for_selector("#file-preview-panel", state="visible")

    assert "book-plan.md" in page.locator("#filePreviewTitle").inner_text()
    assert page.locator("#filePreviewBody").inner_text().strip()


# ── editor round-trip fidelity ──────────────────────────────────────────────


def test_typing_saves_the_edit_and_preserves_everything_else(page: Page, server: ProseviewServer):
    path = server.scene_path()
    before = path.read_text(encoding="utf-8")

    open_scene(page, server)
    enter_edit_mode(page)
    append_to_paragraph(page, "The loft smelled of cold coffee", " The kettle ticked.")
    save_scene(page)

    _wait_until(lambda: "The kettle ticked." in path.read_text(encoding="utf-8"),
                message="Mod-S did not reach the file")
    after = path.read_text(encoding="utf-8")

    # Frontmatter is rebuilt server-side from the live file; a serializer that
    # round-trips the whole document could silently reformat it.
    assert frontmatter(after) == frontmatter(before)
    # Every paragraph the user did not touch must come back byte-identical.
    untouched = [p for p in paragraphs(before) if "The loft smelled of cold coffee" not in p]
    after_paras = paragraphs(after)
    for para in untouched:
        assert para in after_paras, f"paragraph was rewritten by the save:\n{para}"


def test_saving_preserves_inline_todo_and_note_annotations(page: Page, server: ProseviewServer):
    path = server.scene_path(ANNOTATED_SCENE_REL)
    before = path.read_text(encoding="utf-8")

    open_scene(page, server, ANNOTATED_SCENE_REL)
    enter_edit_mode(page)
    append_to_paragraph(page, "Patel arrived with the ledger", " He did not sit.")
    save_scene(page)

    _wait_until(lambda: "He did not sit." in path.read_text(encoding="utf-8"))
    after = path.read_text(encoding="utf-8")

    # Annotations are atom nodes in ProseMirror. If the round trip degraded them
    # they would come back as escaped text or vanish entirely.
    assert "<!-- TODO: Tighten this opening beat -->" in after
    assert "<!-- NOTE[continuity]: Patel should not know about the safe yet -->" in after
    assert after.count("<!--") == before.count("<!--")
    assert "&lt;!--" not in after, "annotation was HTML-escaped on save"
    assert frontmatter(after) == frontmatter(before)


def test_emphasis_survives_a_save_without_reformatting(page: Page, server: ProseviewServer):
    path = server.scene_path(ANNOTATED_SCENE_REL)

    open_scene(page, server, ANNOTATED_SCENE_REL)
    enter_edit_mode(page)
    append_to_paragraph(page, "Patel arrived with the ledger", " Noted.")
    save_scene(page)

    _wait_until(lambda: "Noted." in path.read_text(encoding="utf-8"))
    assert "*quiet*" in path.read_text(encoding="utf-8"), "emphasis marker was rewritten"


def test_undo_before_saving_leaves_the_file_untouched(page: Page, server: ProseviewServer):
    path = server.scene_path()
    before = path.read_text(encoding="utf-8")

    open_scene(page, server)
    enter_edit_mode(page)
    append_to_paragraph(page, "The loft smelled of cold coffee", " Typed then regretted.")
    page.keyboard.press("ControlOrMeta+z")
    page.wait_for_function(
        "() => !document.querySelector('#sceneProseHost .ProseMirror').textContent"
        ".includes('Typed then regretted')"
    )
    save_scene(page)
    page.wait_for_timeout(1000)

    assert path.read_text(encoding="utf-8") == before


def test_editing_a_large_scene_leaves_untouched_prose_intact(page: Page, server: ProseviewServer):
    """~10k words through the editor.

    A serializer that reflows or normalises on save would show up here as
    hundreds of rewritten paragraphs rather than the one that was edited.
    """
    path = server.scene_path(LARGE_SCENE_REL)
    before = path.read_text(encoding="utf-8")
    before_paras = paragraphs(before)

    open_scene(page, server, LARGE_SCENE_REL)
    enter_edit_mode(page)
    append_to_paragraph(page, before_paras[1][:40], " EDITED-MARKER.")
    save_scene(page)

    _wait_until(lambda: "EDITED-MARKER." in path.read_text(encoding="utf-8"), timeout=20,
                message="large-scene save never landed")
    after_paras = paragraphs(path.read_text(encoding="utf-8"))

    assert len(after_paras) == len(before_paras)
    rewritten = [
        p for p in before_paras
        if p not in after_paras and "EDITED-MARKER." not in p and p != before_paras[1]
    ]
    assert not rewritten, f"{len(rewritten)} untouched paragraphs were rewritten on save"


def test_conflicting_save_is_refused_in_the_browser(page: Page, server: ProseviewServer):
    """Someone edits the file in vim while the editor is open."""
    path = server.scene_path()
    open_scene(page, server)
    enter_edit_mode(page)

    path.write_text(path.read_text(encoding="utf-8") + "\nChanged underneath.\n", encoding="utf-8")
    on_disk = path.read_text(encoding="utf-8")

    append_to_paragraph(page, "The loft smelled of cold coffee", " Browser wins?")
    save_scene(page)
    page.wait_for_timeout(1500)

    assert path.read_text(encoding="utf-8") == on_disk
    assert "Browser wins?" not in on_disk


# ── repo-wide search ────────────────────────────────────────────────────────
#
# `_runSearch` scans five categories -- FILES, SCENES, PROSE, TODOS, NOTES --
# with a two-character minimum and a 30-result cap. Results render into
# #searchResults, which stays `hidden` until a query qualifies.


def search_for(page: Page, query: str) -> None:
    box = page.locator("#searchBox")
    if box.is_hidden():
        page.get_by_role("button", name="Search files").first.click()
    box.fill(query)


def search_rows(page: Page):
    return page.locator("#searchResults .search-row")


def search_groups(page: Page) -> list[str]:
    """Displayed group labels, upper-cased.

    The headings read "Files" / "Scenes" / "In prose" / "TODOs" / "Notes" and
    are upper-cased by CSS, so normalise rather than depend on which form a
    given text-extraction path returns.
    """
    labels = page.locator("#searchResults .search-group-label").all_inner_texts()
    return [t.strip().upper() for t in labels]


def test_dashboard_search_is_large_and_inline(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)

    box = page.locator("#searchBox")
    palette = page.locator("#searchPalette")
    assert box.is_visible()
    assert palette.is_hidden()
    bounds = box.bounding_box()
    assert bounds and bounds["width"] >= 300

    box.fill("Rena")
    page.wait_for_selector("#searchResults .search-row")
    assert palette.is_hidden(), "dashboard search should not open a second modal"


def test_scene_has_an_explicit_return_to_dashboard(page: Page, shared_server: ProseviewServer):
    open_scene(page, shared_server)

    back = page.get_by_role("button", name="Close scene and return to dashboard").first
    assert back.is_visible()
    assert "Dashboard" in back.inner_text()
    back.click()

    page.wait_for_selector("#sceneModal", state="hidden")
    assert page.evaluate("document.documentElement.dataset.view || ''") == ""
    assert page.locator("#tab-overview").is_visible()


def test_scene_search_modal_has_pointer_close(page: Page, shared_server: ProseviewServer):
    open_scene(page, shared_server)
    page.locator("#sceneModal button[aria-label='Search files']").click()

    palette = page.locator("#searchPalette")
    palette.wait_for(state="visible")
    close = page.get_by_role("button", name="Close search")
    assert close.is_visible()
    close.click()

    palette.wait_for(state="hidden")
    assert page.locator("#sceneModal").is_visible()


def test_search_needs_two_characters_before_it_offers_anything(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    panel = page.locator("#searchResults")

    search_for(page, "R")
    page.wait_for_timeout(400)
    assert panel.is_hidden(), "a single character should not open the results panel"

    search_for(page, "Rena")
    panel.wait_for(state="visible")
    assert search_rows(page).count() > 0


def test_search_finds_a_scene_by_path_and_opens_it(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "01-opening")

    page.wait_for_selector("#searchResults .search-row")
    assert "FILES" in search_groups(page)
    assert SCENE_REL in page.locator("#searchResults").inner_text()

    page.keyboard.press("Enter")
    page.wait_for_selector("#sceneModal", state="visible")
    assert SCENE_REL in page.locator("#modalTitle").inner_text()


def test_search_finds_prose_and_jumps_into_the_scene(page: Page, shared_server: ProseviewServer):
    """A phrase that appears only in the prose, not in any path or annotation."""
    open_dashboard(page, shared_server)
    search_for(page, "slow algebra")

    page.wait_for_selector("#searchResults .search-row")
    assert "IN PROSE" in search_groups(page)

    page.keyboard.press("Enter")
    page.wait_for_selector("#sceneModal", state="visible")
    _wait_until(lambda: "slow algebra" in _editor_text(page),
                message="activating a prose hit did not open the right scene")


def test_search_finds_todos(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "Tighten this opening")

    page.wait_for_selector("#searchResults .search-row")
    assert "TODOS" in search_groups(page)
    assert ANNOTATED_SCENE_REL in page.locator("#searchResults").inner_text()


def test_search_finds_tagged_notes(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "should not know about the safe")

    page.wait_for_selector("#searchResults .search-row")
    assert "NOTES" in search_groups(page)
    # The tag rides along in the result row, so a writer can tell why it matched.
    assert "[continuity]" in page.locator("#searchResults").inner_text()


def test_search_finds_non_scene_repo_files(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "book-plan")

    page.wait_for_selector("#searchResults .search-row")
    assert "plans/book-plan.md" in page.locator("#searchResults").inner_text()

    page.keyboard.press("Enter")
    page.wait_for_selector("#file-preview-panel", state="visible")
    assert "book-plan.md" in page.locator("#filePreviewTitle").inner_text()


def test_search_opens_manuscript_files_outside_the_scene_index(
    page: Page,
    shared_server: ProseviewServer,
):
    """Manuscript Markdown nested below a chapter dir is not a scene.

    It used to be flagged as one, which routed the click to a scene the
    client had no entry for and left the result dead.
    """
    open_dashboard(page, shared_server)
    search_for(page, "reader-pass-notes")

    page.wait_for_selector("#searchResults .search-row")
    assert NESTED_MANUSCRIPT_NOTE in page.locator("#searchResults").inner_text()

    page.keyboard.press("Enter")
    page.wait_for_selector("#file-preview-panel", state="visible")
    page.wait_for_function(
        "path => document.getElementById('filePreviewTitle').innerText === path",
        arg=NESTED_MANUSCRIPT_NOTE,
    )
    # The title is set before the body is fetched, so wait on the body itself.
    page.wait_for_function(
        "() => document.getElementById('filePreviewBody')"
        ".innerText.includes('safe reveal lands too early')"
    )


def test_opening_a_file_reveals_and_highlights_it_in_the_sidebar(
    page: Page,
    shared_server: ProseviewServer,
):
    """Opening from search points the sidebar at the file, VS Code style:
    ancestor folders expand, the row is highlighted and scrolled into view."""
    open_dashboard(page, shared_server)
    # Collapse everything first, so an expanded ancestor proves the reveal.
    page.evaluate(
        "() => document.querySelectorAll('#sidebarTree li')"
        ".forEach(li => li.classList.remove('expanded'))"
    )

    search_for(page, "reader-pass-notes")
    page.wait_for_selector("#searchResults .search-row")
    page.keyboard.press("Enter")
    page.wait_for_selector("#file-preview-panel", state="visible")

    active = page.locator("#sidebarTree .file-link.active")
    active.wait_for(state="visible")
    assert active.get_attribute("data-path") == NESTED_MANUSCRIPT_NOTE
    # Every folder on the way down is open, so the row is actually on screen.
    expanded = page.evaluate(
        "() => [...document.querySelectorAll('#sidebarTree li.expanded > .dir-toggle')]"
        ".map(el => el.textContent)"
    )
    assert {"manuscript", "ch01", "review"} <= set(expanded)

    # A scene reveals the same way, matched on its scene path. Typing and
    # pressing Enter without pause also lands inside the search debounce, so
    # this doubles as a guard that activation uses the query on screen rather
    # than the previous keystroke's results.
    search_for(page, "02-walk")
    page.wait_for_selector("#searchResults .search-row")
    page.keyboard.press("Enter")
    page.wait_for_selector("#sceneModal", state="visible")
    scene_active = page.locator("#sidebarTree .file-link.active")
    scene_active.wait_for(state="visible")
    assert scene_active.get_attribute("data-path") == "manuscript/ch01/02-walk.md"



@pytest.mark.parametrize("start_view", ["scene", "file"])
def test_global_search_opens_unconfigured_file_from_every_reader_view(
    page: Page,
    shared_server: ProseviewServer,
    start_view: str,
):
    if start_view == "scene":
        open_scene(page, shared_server)
    else:
        page.goto(f"{shared_server.base_url}#/file/plans/book-plan.md", wait_until="load")
        page.wait_for_selector("#file-preview-panel", state="visible")

    page.keyboard.press("ControlOrMeta+k")

    palette = page.locator("#searchPalette")
    box = page.locator("#searchBox")
    palette.wait_for(state="visible")
    assert box.is_visible()
    assert page.evaluate("document.activeElement === document.getElementById('searchBox')")
    assert box.evaluate("node => node.getClientRects().length > 0")

    box.fill("check_continuity")
    page.wait_for_selector("#searchResults .search-row")
    assert "scripts/check_continuity.py" in page.locator("#searchResults").inner_text()
    page.keyboard.press("Enter")

    page.wait_for_selector("#file-preview-panel", state="visible")
    page.wait_for_function("() => document.getElementById('filePreviewTitle').innerText === 'scripts/check_continuity.py'")
    page.wait_for_function("() => document.getElementById('filePreviewBody').innerText.includes('def check_continuity')")
    assert "def check_continuity" in page.locator("#filePreviewBody").inner_text()

    page.go_back(wait_until="load")
    if start_view == "scene":
        page.wait_for_selector("#sceneModal", state="visible")
    else:
        page.wait_for_function("() => document.getElementById('filePreviewTitle').innerText === 'plans/book-plan.md'")
    page.go_forward(wait_until="load")
    page.wait_for_function("() => document.getElementById('filePreviewTitle').innerText === 'scripts/check_continuity.py'")

    page.keyboard.press("ControlOrMeta+k")
    palette.wait_for(state="visible")
    assert box.input_value() == "check_continuity"
    assert "scripts/check_continuity.py" in page.locator("#searchResults").inner_text()
    page.keyboard.press("Escape")
    palette.wait_for(state="hidden")


def test_global_search_has_visible_pointer_entry_and_lazy_deep_link(page: Page, shared_server: ProseviewServer):
    page.goto(f"{shared_server.base_url}#/file/scripts/check_continuity.py", wait_until="load")
    page.wait_for_selector("#file-preview-panel", state="visible")
    page.wait_for_function("() => document.getElementById('filePreviewTitle').innerText === 'scripts/check_continuity.py'")
    page.wait_for_function("() => document.getElementById('filePreviewBody').innerText.includes('def check_continuity')")
    assert "def check_continuity" in page.locator("#filePreviewBody").inner_text()

    search_button = page.locator("#file-preview-panel").get_by_role("button", name="Search files")
    assert search_button.is_visible()
    page.select_option("#filePreviewThemeSelect", "dark")
    page.set_viewport_size({"width": 1024, "height": 768})
    page.evaluate("document.body.style.zoom = '2'")
    search_button.click()
    page.wait_for_selector("#searchPalette", state="visible")
    assert page.evaluate("document.activeElement === document.getElementById('searchBox')")
    palette_box = page.locator("#searchMenu").bounding_box()
    assert palette_box
    assert palette_box["x"] >= 0 and palette_box["x"] + palette_box["width"] <= 1024
    assert palette_box["y"] >= 0 and palette_box["y"] + palette_box["height"] <= 768
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement === document.querySelector('#file-preview-panel button[aria-label=\"Search files\"]')")


def test_search_does_not_navigate_away_from_an_unsaved_scene(page: Page, server: ProseviewServer):
    before = _stage_unsaved_edit(page, server)
    page.keyboard.press("ControlOrMeta+k")
    page.locator("#searchBox").fill("check_continuity")
    page.wait_for_selector("#searchResults .search-row")

    page.keyboard.press("Enter")

    assert page.locator("#searchPalette").is_visible()
    assert page.locator("#searchNavigationWarning").is_visible()
    assert "Save or cancel" in page.locator("#searchNavigationWarning").inner_text()
    assert page.evaluate("document.documentElement.dataset.view") == "scene"
    assert TYPED.strip() in _editor_text(page)
    assert server.scene_path().read_text(encoding="utf-8") == before
    page.keyboard.press("Escape")
    page.wait_for_selector("#searchPalette", state="hidden")
    assert page.evaluate("document.activeElement.classList.contains('ProseMirror')")
    assert page.locator(DIALOG).count() == 0
    assert TYPED.strip() in _editor_text(page)


def test_scene_search_pointer_entry_reflows_at_two_hundred_percent_zoom(
    page: Page,
    shared_server: ProseviewServer,
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, shared_server)
    page.evaluate("document.body.style.zoom = '2'")
    page.wait_for_function("() => document.documentElement.dataset.cssZoom === 'true'")

    trigger = page.locator("#sceneModal button[aria-label='Search files']")
    box = trigger.bounding_box()
    assert box
    assert box["x"] >= 0 and box["x"] + box["width"] <= 1024
    assert box["y"] >= 0 and box["y"] + box["height"] <= 768
    trigger.click()
    page.wait_for_selector("#searchPalette", state="visible")


def test_scene_search_pointer_entry_reflows_for_compact_css_viewport(
    page: Page,
    shared_server: ProseviewServer,
):
    page.set_viewport_size({"width": 512, "height": 500})
    open_scene(page, shared_server)

    trigger = page.locator("#sceneModal button[aria-label='Search files']")
    box = trigger.bounding_box()
    assert box
    assert box["x"] >= 0 and box["x"] + box["width"] <= 512
    assert box["y"] >= 0 and box["y"] + box["height"] <= 500
    trigger.click()
    page.wait_for_selector("#searchPalette", state="visible")


def test_lazy_markdown_preview_treats_hostile_html_and_links_as_text(
    page: Page,
    shared_server: ProseviewServer,
):
    page.goto(f"{shared_server.base_url}#/file/scripts/hostile-preview.md", wait_until="load")
    page.wait_for_function(
        "() => document.getElementById('filePreviewTitle').innerText === 'scripts/hostile-preview.md'"
    )
    page.wait_for_function("() => document.getElementById('filePreviewBody').innerText.includes('<img src=x')")

    body = page.locator("#filePreviewBody")
    assert "<img src=x" in body.inner_text()
    assert body.locator("img").count() == 0
    assert body.locator("a").count() == 0
    assert page.evaluate("window.__previewPwned === true") is False


def test_hidden_repository_deep_link_never_displays_its_contents(
    page: Page,
    shared_server: ProseviewServer,
):
    page.goto(f"{shared_server.base_url}#/file/.private/token.txt", wait_until="load")
    page.wait_for_function("() => document.getElementById('filePreviewMeta').innerText === 'Preview unavailable'")

    assert "fixture secret" not in page.locator("#filePreviewBody").inner_text()


def test_newer_lazy_preview_wins_when_an_older_request_finishes_late(
    page: Page,
    shared_server: ProseviewServer,
):
    def delay_first_preview(route):
        if "check_continuity.py" in route.request.url:
            time.sleep(0.25)
        route.continue_()

    page.route("**/repo-file?*", delay_first_preview)
    open_dashboard(page, shared_server)
    page.evaluate(
        """() => {
            previewRepoFile('scripts/check_continuity.py');
            previewRepoFile('scripts/hostile-preview.md');
        }"""
    )

    page.wait_for_function(
        "() => document.getElementById('filePreviewBody').innerText.includes('Safe heading')"
    )
    page.wait_for_timeout(400)
    assert page.locator("#filePreviewTitle").inner_text() == "scripts/hostile-preview.md"
    assert "def check_continuity" not in page.locator("#filePreviewBody").inner_text()


def test_arrow_keys_move_the_search_cursor(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "Rena")
    page.wait_for_selector("#searchResults .search-row")
    assert search_rows(page).count() > 1

    def active_index() -> int:
        classes = [r.get_attribute("class") or "" for r in search_rows(page).all()]
        return next((i for i, c in enumerate(classes) if "active" in c), -1)

    first = active_index()
    page.keyboard.press("ArrowDown")
    _wait_until(lambda: active_index() != first, message="ArrowDown did not move the cursor")
    moved = active_index()

    page.keyboard.press("ArrowUp")
    _wait_until(lambda: active_index() != moved, message="ArrowUp did not move the cursor back")


def test_escape_closes_the_search_panel(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "Rena")
    page.wait_for_selector("#searchResults", state="visible")

    page.keyboard.press("Escape")

    page.wait_for_selector("#searchResults", state="hidden")


@pytest.mark.parametrize("query", ["the", "a ", "e", "Rena", ".md"])
def test_search_never_exceeds_the_result_cap(page: Page, shared_server: ProseviewServer, query: str):
    """SEARCH_RESULT_CAP bounds the dropdown however broad the query.

    This asserts the invariant, not the overflow banner: prose hits are deduped
    to one row per scene, so a six-scene fixture cannot actually reach 30 rows.
    A test for the "+N more hits hidden" label would need a repo an order of
    magnitude larger and could never fail here.
    """
    open_dashboard(page, shared_server)
    search_for(page, query)
    page.wait_for_timeout(500)

    assert search_rows(page).count() <= 30, f"{query!r} returned more rows than the cap"


def test_search_reports_when_nothing_matches(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    search_for(page, "zzzznotinthisrepo")

    page.wait_for_selector("#searchResults .search-empty")
    assert search_rows(page).count() == 0
    assert "No matches" in page.locator("#searchResults").inner_text()


# ── unsaved-changes guard ───────────────────────────────────────────────────
#
# The highest-consequence path in the app. A save that breaks fails loudly; a
# discard guard that breaks throws away a writer's prose with no error and no
# way to get it back. Esc is wired at capture phase in 60-selection.js and
# routes through tryEscapeEditMode() in 50-discard-confirm.js.


DIALOG = ".unsaved-dialog-overlay"
TYPED = " An unsaved sentence."


def _dialog(page: Page):
    return page.locator(DIALOG)


def _stage_unsaved_edit(page: Page, server: ProseviewServer) -> str:
    """Enter edit mode, type, and return the file's untouched contents."""
    before = server.scene_path().read_text(encoding="utf-8")
    open_scene(page, server)
    enter_edit_mode(page)
    append_to_paragraph(page, "The loft smelled of cold coffee", TYPED)
    _wait_until(lambda: TYPED.strip() in _editor_text(page))
    return before


def test_escape_with_no_unsaved_edits_leaves_edit_mode_silently(page: Page, server: ProseviewServer):
    before = server.scene_path().read_text(encoding="utf-8")
    open_scene(page, server)
    enter_edit_mode(page)

    page.keyboard.press("Escape")

    page.wait_for_function("() => window._pmEditMode === false")
    assert _dialog(page).count() == 0, "guard prompted despite there being nothing to lose"
    assert server.scene_path().read_text(encoding="utf-8") == before


def test_escape_with_unsaved_edits_prompts_instead_of_discarding(page: Page, server: ProseviewServer):
    before = _stage_unsaved_edit(page, server)

    page.keyboard.press("Escape")

    page.wait_for_selector(DIALOG, state="visible")
    # Nothing may be lost or written while the writer is still deciding.
    assert TYPED.strip() in _editor_text(page)
    assert server.scene_path().read_text(encoding="utf-8") == before


def test_discarding_drops_the_edit_and_never_writes_the_file(page: Page, server: ProseviewServer):
    before = _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    page.click(".unsaved-dialog-discard")

    page.wait_for_selector(DIALOG, state="detached")
    _wait_until(lambda: TYPED.strip() not in _editor_text(page),
                message="discard left the edit in the editor")
    page.wait_for_function("() => window._pmEditMode === false")
    assert server.scene_path().read_text(encoding="utf-8") == before


def test_saving_from_the_guard_persists_the_edit(page: Page, server: ProseviewServer):
    path = server.scene_path()
    _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    page.click(".unsaved-dialog-save")

    _wait_until(lambda: TYPED.strip() in path.read_text(encoding="utf-8"),
                message="Save in the guard did not reach the file")
    assert frontmatter(path.read_text(encoding="utf-8"))


def test_cancelling_the_guard_keeps_the_editor_open_and_dirty(page: Page, server: ProseviewServer):
    before = _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    page.click(".unsaved-dialog-cancel")

    page.wait_for_selector(DIALOG, state="detached")
    assert page.evaluate("window._pmEditMode") is True, "cancel dropped out of edit mode"
    assert TYPED.strip() in _editor_text(page)
    assert server.scene_path().read_text(encoding="utf-8") == before


def test_escape_inside_the_guard_dismisses_it_without_discarding(page: Page, server: ProseviewServer):
    """Esc opened the guard; Esc again must not be read as 'yes, throw it away'."""
    before = _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    page.keyboard.press("Escape")

    page.wait_for_selector(DIALOG, state="detached")
    assert TYPED.strip() in _editor_text(page), "second Esc discarded the edit"
    assert page.evaluate("window._pmEditMode") is True
    assert server.scene_path().read_text(encoding="utf-8") == before


def test_enter_inside_the_guard_saves(page: Page, server: ProseviewServer):
    path = server.scene_path()
    _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    page.keyboard.press("Enter")

    _wait_until(lambda: TYPED.strip() in path.read_text(encoding="utf-8"),
                message="Enter did not take the guard's default action")


def test_clicking_the_backdrop_dismisses_the_guard_without_discarding(page: Page, server: ProseviewServer):
    before = _stage_unsaved_edit(page, server)
    page.keyboard.press("Escape")
    page.wait_for_selector(DIALOG, state="visible")

    # Corner of the overlay, well clear of the centred dialog box.
    _dialog(page).click(position={"x": 5, "y": 5})

    page.wait_for_selector(DIALOG, state="detached")
    assert TYPED.strip() in _editor_text(page), "a stray backdrop click discarded the edit"
    assert server.scene_path().read_text(encoding="utf-8") == before


# ── inline annotation editing ───────────────────────────────────────────────
#
# TODO/NOTE comments render as atom nodes with their own node view. Clicking one
# in read mode enters edit mode with autoSave on, so Save and Resolve write
# straight through to the file.


TODO_BODY = "Tighten this opening beat"
NOTE_BODY = "Patel should not know about the safe yet"


def open_annotated_scene(page: Page, server: ProseviewServer) -> Path:
    open_scene(page, server, ANNOTATED_SCENE_REL)
    page.wait_for_selector(".pm-annotation")
    return server.scene_path(ANNOTATED_SCENE_REL)


def wait_for_annotation_editor(page: Page):
    """Wait until the annotation's box is not just present but focused.

    The node view focuses the field and selects its contents from a
    ``setTimeout(..., 0)``. Typing before that lands appends instead of
    replacing, so waiting on the element alone is a race.
    """
    page.wait_for_selector(".pm-annotation-editing .pm-annotation-edit-text")
    page.wait_for_function(
        "() => document.activeElement"
        " && document.activeElement.classList.contains('pm-annotation-edit-text')"
    )
    return page.locator(".pm-annotation-editing .pm-annotation-edit-text")


def click_annotation(page: Page, body: str):
    marker = page.locator(f".pm-annotation:has-text('{body}')")
    marker.wait_for(state="visible")
    marker.click()
    return wait_for_annotation_editor(page)


def test_annotations_render_as_markers_not_raw_comments(page: Page, server: ProseviewServer):
    open_annotated_scene(page, server)

    assert page.locator(".pm-annotation-todo").count() == 1
    assert page.locator(".pm-annotation-note").count() == 1
    assert TODO_BODY in page.locator(".pm-annotation-todo").inner_text()
    # The raw comment syntax must never be visible to the writer.
    assert "<!--" not in _editor_text(page)


def test_clicking_a_todo_opens_it_for_editing_and_enters_edit_mode(page: Page, server: ProseviewServer):
    open_annotated_scene(page, server)
    assert page.evaluate("window._pmEditMode") is not True

    editable = click_annotation(page, TODO_BODY)

    assert editable.inner_text().strip() == TODO_BODY
    assert page.evaluate("window._pmEditMode") is True, "editing an annotation did not enter edit mode"
    assert page.locator(".pm-annotation-save").is_visible()


def test_editing_a_todo_inline_writes_it_back_to_the_file(page: Page, server: ProseviewServer):
    path = open_annotated_scene(page, server)
    click_annotation(page, TODO_BODY)

    # The node view selects the existing body on focus, so typing replaces it.
    page.keyboard.type("Cut the opening beat entirely")
    page.click(".pm-annotation-save")

    _wait_until(lambda: "Cut the opening beat entirely" in path.read_text(encoding="utf-8"),
                message="inline TODO edit never reached the file")
    after = path.read_text(encoding="utf-8")
    assert "<!-- TODO: Cut the opening beat entirely -->" in after
    assert TODO_BODY not in after
    # The neighbouring note and the frontmatter must be untouched.
    assert f"<!-- NOTE[continuity]: {NOTE_BODY} -->" in after


def test_editing_a_note_inline_preserves_its_tag(page: Page, server: ProseviewServer):
    path = open_annotated_scene(page, server)
    click_annotation(page, NOTE_BODY)

    page.keyboard.type("Patel learns about the safe in chapter three")
    page.click(".pm-annotation-save")

    # Wait on a phrase that appears nowhere else -- "chapter three" is already
    # in this scene's frontmatter `todos:`, so it would match before the save.
    _wait_until(lambda: "Patel learns about the safe" in path.read_text(encoding="utf-8"),
                message="inline note edit never reached the file")
    after = path.read_text(encoding="utf-8")
    assert "<!-- NOTE[continuity]: Patel learns about the safe in chapter three -->" in after
    assert "NOTE[note]" not in after, "the tag was reset to the default on save"


def test_resolving_a_todo_removes_it_from_the_file(page: Page, server: ProseviewServer):
    path = open_annotated_scene(page, server)
    before = path.read_text(encoding="utf-8")
    click_annotation(page, TODO_BODY)

    # Labelled "Resolve" for TODOs and "Delete" for notes; same control.
    page.click(".pm-annotation-delete")

    _wait_until(lambda: "<!-- TODO:" not in path.read_text(encoding="utf-8"),
                message="resolving the TODO did not remove it from the file")
    after = path.read_text(encoding="utf-8")
    assert f"<!-- NOTE[continuity]: {NOTE_BODY} -->" in after
    assert "Patel arrived with the ledger" in after, "resolving an annotation ate the prose"
    assert frontmatter(after) == frontmatter(before)


def test_cancelling_an_inline_annotation_edit_leaves_the_file_untouched(page: Page, server: ProseviewServer):
    path = open_annotated_scene(page, server)
    before = path.read_text(encoding="utf-8")
    click_annotation(page, TODO_BODY)

    page.keyboard.type("This should never be written")
    page.click(".pm-annotation-cancel")

    page.wait_for_selector(".pm-annotation-editing", state="detached")
    page.wait_for_timeout(1000)
    assert path.read_text(encoding="utf-8") == before
    assert TODO_BODY in page.locator(".pm-annotation-todo").inner_text()


def test_insert_affordance_adds_a_new_todo_to_a_paragraph(page: Page, server: ProseviewServer):
    """Hovering a paragraph in edit mode offers a TODO insertion point."""
    path = open_annotated_scene(page, server)
    enter_edit_mode(page)

    page.hover("#sceneProseHost .ProseMirror p")
    affordance = page.locator("#pmInsertAffordance")
    affordance.wait_for(state="visible")
    affordance.click()

    wait_for_annotation_editor(page)
    page.keyboard.type("Added from the gutter affordance")
    page.click(".pm-annotation-save")

    # Inserting does not autosave -- the affordance path leaves the writer in
    # control, so the edit only lands once they save the scene.
    page.wait_for_timeout(500)
    assert "Added from the gutter affordance" not in path.read_text(encoding="utf-8")

    # Mod-S is a ProseMirror keymap binding, so the editor needs focus back --
    # rendering the annotation read-only left it on the body.
    page.click("#sceneProseHost .ProseMirror p")
    save_scene(page)
    _wait_until(lambda: "Added from the gutter affordance" in path.read_text(encoding="utf-8"),
                message="the inserted TODO never reached the file")
    assert "<!-- TODO: Added from the gutter affordance -->" in path.read_text(encoding="utf-8")


# ── selection menu ──────────────────────────────────────────────────────────


def test_selection_pill_exposes_every_action(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    menu = page.locator("#selectionPillMenu")
    for control in ("selectionEditorBtn", "selectionTodoBtn", "selectionNoteBtn",
                    "selectionCodexBtn", "selectionSkillsBtn"):
        assert menu.locator(f"#{control}").is_visible(), f"{control} missing from the pill"


def test_selection_menu_has_keyboard_semantics_and_restores_focus(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    select_prose(page, "the slow algebra")

    trigger = page.locator("#selectionPillBtn")
    menu = page.locator("#selectionPillMenu")
    assert trigger.get_attribute("aria-label") == "Work with selected text"
    assert trigger.get_attribute("aria-haspopup") == "menu"
    assert trigger.get_attribute("aria-controls") == "selectionPillMenu"
    assert trigger.get_attribute("aria-expanded") == "false"
    assert menu.get_attribute("role") == "menu"

    page.keyboard.press("ControlOrMeta+k")

    menu.wait_for(state="visible")
    assert page.locator("#searchPalette").is_hidden()
    assert trigger.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement === document.getElementById('selectionRewriteBtn')")
    assert page.locator("#selectionRewriteBtn").get_attribute("aria-controls") == "selectionRewriteMenu"
    assert page.locator("#selectionRewriteBtn").get_attribute("aria-expanded") == "false"
    page.keyboard.press("ArrowRight")
    assert page.locator("#selectionRewriteBtn").get_attribute("aria-expanded") == "true"
    assert page.locator("#selectionRewriteMenu").is_visible()
    page.keyboard.press("ArrowLeft")
    assert page.locator("#selectionRewriteBtn").get_attribute("aria-expanded") == "false"
    assert page.evaluate("document.activeElement === document.getElementById('selectionRewriteBtn')")

    for _ in range(4):
        page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement === document.getElementById('selectionTodoBtn')")
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement === document.getElementById('selectionTodoText')")

    page.keyboard.press("Escape")
    assert menu.is_visible()
    assert page.locator("#selectionTodoForm").is_hidden()
    assert page.evaluate("document.activeElement === document.getElementById('selectionTodoBtn')")

    page.keyboard.press("Escape")
    menu.wait_for(state="hidden")
    assert trigger.is_visible()
    assert trigger.get_attribute("aria-expanded") == "false"
    assert page.evaluate("document.activeElement === document.getElementById('selectionPillBtn')")


def test_selection_skills_open_managed_searchable_surface(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.locator("#selectionSkillsBtn").click()
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelectorAll('#discussSkillsPicker .discuss-skill').length >= 2")
    assert "Tighten Prose" in page.locator("#discussSkillsPicker").inner_text()
    page.locator("#discussSkillsPicker .discuss-skill").first.click()
    page.fill("#discussInput", "Review this selected passage")
    page.click("#discussSend")
    wait_for_discuss_answer(page)

    received = (server.env["HOME"] and Path(server.env["HOME"]) / "fake-codex-received.jsonl").read_text(encoding="utf-8")
    assert '"type": "skill"' in received


def test_selection_shortcut_falls_back_to_search_after_selection_is_cleared(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    select_prose(page, "the slow algebra")
    page.keyboard.press("ControlOrMeta+k")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    page.locator("#sceneProseHost .ProseMirror p").first.click()
    assert page.evaluate("window.getSelection().isCollapsed")
    assert page.locator("#selectionPill").is_hidden()

    page.keyboard.press("ControlOrMeta+k")

    page.wait_for_selector("#searchPalette", state="visible")
    assert page.locator("#selectionPillMenu").is_hidden()
    assert page.evaluate("document.activeElement === document.getElementById('searchBox')")


def test_selection_pill_reanchors_with_the_scene_scroll_container(
    page: Page,
    server: ProseviewServer,
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, server)
    page.evaluate(
        "document.querySelector('#sceneModal .modal-content').style.scrollBehavior = 'auto'"
    )
    select_prose(page, "the slow algebra", block="center")
    page.wait_for_timeout(50)

    before = page.evaluate(
        """() => ({
            anchorTop: currentSelectionRange.getBoundingClientRect().top,
            pillTop: document.getElementById('selectionPillBtn').getBoundingClientRect().top,
        })"""
    )
    page.evaluate(
        """() => {
            const scroller = document.querySelector('#sceneModal .modal-content');
            scroller.scrollTop += 40;
        }"""
    )
    page.wait_for_function(
        "before => Math.abs(currentSelectionRange.getBoundingClientRect().top - before) > 20",
        arg=before["anchorTop"],
    )
    page.wait_for_timeout(50)
    after = page.evaluate(
        """() => ({
            anchorTop: currentSelectionRange.getBoundingClientRect().top,
            pillTop: document.getElementById('selectionPillBtn').getBoundingClientRect().top,
        })"""
    )

    anchor_delta = after["anchorTop"] - before["anchorTop"]
    pill_delta = after["pillTop"] - before["pillTop"]
    assert abs(anchor_delta - pill_delta) < 2
    assert_fully_inside_viewport(page, "#selectionPillBtn")


def test_selection_form_is_a_separate_accessible_surface(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.locator("#selectionTodoBtn").click()

    assert page.locator("#selectionPillMenu").is_hidden()
    form = page.locator("#selectionTodoForm")
    assert form.is_visible()
    assert form.get_attribute("role") == "dialog"
    assert form.get_attribute("aria-label") == "Add TODO to selected text"
    assert page.locator("#selectionPillBtn").get_attribute("aria-expanded") == "false"
    assert page.locator("#selectionPill [role='menuitem']:visible").count() == 0

    page.keyboard.press("Escape")
    assert form.is_hidden()
    assert page.locator("#selectionPillMenu").is_visible()
    assert page.locator("#selectionPillMenu").get_attribute("role") == "menu"
    assert page.evaluate("document.activeElement === document.getElementById('selectionTodoBtn')")


def test_selection_menu_tab_dismisses_to_a_page_control(
    page: Page,
    server: ProseviewServer,
):
    open_scene(page, server)
    select_prose(page, "the slow algebra")
    page.keyboard.press("ControlOrMeta+k")
    assert page.evaluate("document.activeElement === document.getElementById('selectionRewriteBtn')")

    page.keyboard.press("Tab")
    assert page.locator("#selectionPillMenu").is_hidden()
    assert page.evaluate(
        "document.activeElement !== document.body && !document.getElementById('selectionPill').contains(document.activeElement)"
    )


@pytest.mark.parametrize(
    ("opener_id", "form_id", "first_id", "last_id"),
    [
        ("selectionTodoBtn", "selectionTodoForm", "selectionTodoText", "selectionTodoCancel"),
        ("selectionNoteBtn", "selectionNoteForm", "selectionNoteTag", "selectionNoteCancel"),
    ],
)
def test_selection_dialogs_trap_tab_focus(
    page: Page,
    server: ProseviewServer,
    opener_id: str,
    form_id: str,
    first_id: str,
    last_id: str,
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")
    page.locator(f"#{opener_id}").click()
    assert page.locator(f"#{form_id}").is_visible()

    page.locator(f"#{first_id}").focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate(
        "lastId => document.activeElement === document.getElementById(lastId)",
        last_id,
    )

    page.keyboard.press("Tab")
    assert page.evaluate(
        "firstId => document.activeElement === document.getElementById(firstId)",
        first_id,
    )
    assert page.locator(f"#{form_id}").is_visible()


@pytest.mark.parametrize("dirty", [False, True])
def test_selection_escape_precedes_edit_mode_escape(
    page: Page,
    server: ProseviewServer,
    dirty: bool,
):
    open_scene(page, server)
    enter_edit_mode(page)
    if dirty:
        append_to_paragraph(page, "The loft smelled of cold coffee", TYPED)
        assert TYPED.strip() in _editor_text(page)
    select_prose(page, "the slow algebra")
    page.keyboard.press("ControlOrMeta+k")
    page.locator("#selectionTodoBtn").click()
    assert page.locator("#selectionTodoForm").is_visible()

    page.keyboard.press("Escape")
    assert page.locator("#selectionTodoForm").is_hidden()
    assert page.locator("#selectionPillMenu").is_visible()
    assert page.evaluate("window._pmEditMode === true")
    assert page.locator(DIALOG).count() == 0

    page.keyboard.press("Escape")
    assert page.locator("#selectionPillMenu").is_hidden()
    assert page.locator("#selectionPillBtn").is_visible()
    assert page.evaluate("window._pmEditMode === true")
    assert page.locator(DIALOG).count() == 0

    page.keyboard.press("Escape")
    assert page.locator("#selectionPill").is_hidden()
    assert page.evaluate("window._pmEditMode === true")
    assert page.locator(DIALOG).count() == 0

    page.keyboard.press("Escape")
    if dirty:
        page.wait_for_selector(DIALOG, state="visible")
        assert page.evaluate("window._pmEditMode === true")
    else:
        page.wait_for_function("() => window._pmEditMode === false")
        assert page.locator(DIALOG).count() == 0


@pytest.mark.parametrize(
    ("width", "height", "zoom", "theme"),
    [(1400, 1000, 1, "light"), (1024, 768, 2, "dark")],
)
def test_selection_menu_and_managed_dock_stay_inside_the_visual_viewport(
    page: Page,
    server: ProseviewServer,
    width: int,
    height: int,
    zoom: int,
    theme: str,
):
    page.set_viewport_size({"width": width, "height": height})
    open_scene(page, server)
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", theme)
    page.evaluate("zoom => { document.body.style.zoom = String(zoom); }", zoom)
    if zoom > 1:
        page.wait_for_function("() => document.documentElement.dataset.cssZoom === 'true'")

    select_prose(page, "the slow algebra", block="end")
    assert_fully_inside_viewport(page, "#selectionPillBtn")

    page.locator("#selectionPillBtn").click()
    page.wait_for_selector("#selectionPillMenu", state="visible")
    assert_fully_inside_viewport(page, "#selectionPillMenu")

    page.locator("#selectionCodexBtn").click()
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.activeElement === document.getElementById('discussInput')")
    assert page.locator("#selectionPillMenu").is_hidden()
    assert_fully_inside_viewport(page, "#discussPanel")
    assert_fully_inside_viewport(page, "#discussInput")
    assert_fully_inside_viewport(page, "#discussSend")


def test_selection_add_todo_writes_the_comment_to_the_file(page: Page, server: ProseviewServer):
    path = server.scene_path()
    open_scene(page, server)
    open_selection_menu(page, "It is sticking again")

    page.click("#selectionTodoBtn")
    page.fill("#selectionTodoText", "Sharpen Lowe's entrance")
    page.click("#selectionTodoCopy")

    _wait_until(lambda: "<!-- TODO: Sharpen Lowe's entrance -->" in path.read_text(encoding="utf-8"),
                message="TODO from the selection menu never reached the file")

    text = path.read_text(encoding="utf-8")
    assert text.index("<!-- TODO:") < text.index("It is sticking again")


def test_selection_add_note_writes_a_tagged_comment(page: Page, server: ProseviewServer):
    path = server.scene_path()
    open_scene(page, server)
    open_selection_menu(page, "It is not the safe")

    page.click("#selectionNoteBtn")
    page.fill("#selectionNoteText", "Safe brand must match chapter three")
    page.select_option("#selectionNoteTag", "continuity")
    page.click("#selectionNoteCopy")

    _wait_until(
        lambda: "<!-- NOTE[continuity]: Safe brand must match chapter three -->"
        in path.read_text(encoding="utf-8"),
        message="tagged note never reached the file",
    )


def test_managed_skills_come_from_app_server(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.click("#selectionSkillsBtn")
    page.wait_for_function("() => document.querySelectorAll('#discussSkillsPicker .discuss-skill').length >= 2")
    listed = page.locator("#discussSkillsPicker").inner_text()

    assert "Continuity Check" in listed
    assert "Tighten Prose" in listed


# ── agents and terminal ─────────────────────────────────────────────────────


def _terminal_text(page: Page) -> str:
    """Read the visible xterm buffer.

    xterm renders into ``.xterm-rows``, so ``inner_text`` on the panel works --
    but only for rows currently on screen, which is all these tests need.
    """
    return page.locator("#terminalPanel").inner_text()


def open_shell_terminal(page: Page) -> None:
    """Open a shell tab, focus xterm, and wait until the shell can take input.

    Two separate races here. The click is needed because keystrokes otherwise
    go to the document and never reach the PTY. The prompt wait is needed
    because the ``$ Shell`` button spawns a *login interactive* shell: until it
    has finished starting up and drawn a prompt, anything typed is swallowed
    and the test hangs waiting for output that will never come.
    """
    page.click("#sceneMoreBtn")
    page.get_by_role("button", name="Open shell").click()
    page.wait_for_selector("#terminalPanel", state="visible")
    page.wait_for_selector(".terminal-tab-mount .xterm", timeout=20_000)
    page.click(".terminal-tab-mount .xterm-screen")
    _wait_until(
        lambda: any(ch in _terminal_text(page) for ch in ("$", "%", "#")),
        timeout=25,
        message="shell never drew a prompt",
    )


def run_in_terminal(page: Page, command: str, marker: str, attempts: int = 4) -> None:
    """Type *command* into the focused terminal until *marker* comes back.

    xterm wires its ``onData`` handler to ``/terminal-input`` a beat after the
    element appears, so the first keystrokes are occasionally dropped on the
    floor with no error. Retrying is what a user does when nothing echoes, and
    it makes the test deterministic; re-running an ``echo`` is harmless.
    """
    for _ in range(attempts):
        page.keyboard.type(command + "\n")
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if marker in _terminal_text(page):
                return
            time.sleep(0.15)
    raise AssertionError(f"{marker!r} never appeared after {attempts} attempts")


def test_shell_terminal_opens_and_runs_a_command(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_shell_terminal(page)

    run_in_terminal(page, "echo proseview-browser-marker", "proseview-browser-marker")


@pytest.mark.parametrize(("label", "agent"), [("Codex", "codex"), ("Claude", "claude"), ("Gemini", "gemini")])
def test_scene_agent_menu_launches_the_agent(page: Page, server: ProseviewServer, label: str, agent: str):
    """The agent menu spawns the agent's own binary in a terminal tab.

    A stub on PATH stands in for the real tool and announces itself, so this
    proves the click reaches an actual process.
    """
    open_scene(page, server)
    page.click("#sceneMoreBtn")
    page.click("#agentMenuSceneBtn")
    page.wait_for_selector("#agentMenuScene", state="visible")
    page.click(f"#agentMenuScene button:has-text('{label}')")

    page.wait_for_selector("#terminalPanel", state="visible")
    _wait_until(lambda: f"{AGENT_MARKER} {agent}" in _terminal_text(page), timeout=25,
                message=f"{agent} stub never announced itself")

    sessions = server.get_json("/terminal-list")["sessions"]
    assert any(s["type"] == agent for s in sessions)


def _terminal_flat(page: Page) -> str:
    """Terminal text with runs of whitespace collapsed.

    xterm hard-wraps at the column width and each visual row is its own DOM
    node, so a long prompt is split across lines. Collapsing whitespace lets a
    test match the prompt as the user wrote it.
    """
    return " ".join(_terminal_text(page).split())


def test_ask_about_selection_is_normal_chat_and_keeps_context_for_followups(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    path = server.scene_path()
    before = path.read_bytes()
    open_scene(page, server)
    open_selection_menu(page, quote)

    assert page.locator("#selectionCodexBtn").inner_text() == "Ask about selection"
    page.click("#selectionCodexBtn")
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert quote in page.locator("#discussSelectionChip").inner_text()
    assert SCENE_REL in page.locator("#discussContext").inner_text()
    assert page.locator("#discussInput").get_attribute("placeholder") == "Ask anything about this selection…"
    assert page.locator("#discussSend").inner_text() == "Send"

    page.fill("#discussInput", "Explain how this image affects the voice")
    page.click("#discussSend")
    wait_for_discuss_answer(page)
    assert quote in page.locator("#discussSelectionChip").inner_text()
    assert page.locator(".discuss-task").count() == 0
    assert page.locator(".ai-proposal-panel:visible").count() == 0

    page.fill("#discussInput", "What does it reveal about the narrator?")
    page.click("#discussSend")
    page.wait_for_function("() => document.querySelectorAll('.discuss-message.assistant').length === 2")
    assert quote in page.locator("#discussSelectionChip").inner_text()

    records = [
        json.loads(line)
        for line in (server.home / "fake-codex-received.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    questions = ("Explain how this image affects the voice", "What does it reveal about the narrator?")
    prompts = [
        record["params"]["input"][0]["text"]
        for record in records
        if record["params"].get("input")
        and any(question in record["params"]["input"][0]["text"] for question in questions)
    ]
    assert len(prompts) == 2
    assert all(f"BEGIN USER SELECTION\n{quote}\nEND USER SELECTION" in prompt for prompt in prompts)

    page.locator("#discussSelectionChip button").click()
    assert page.locator("#discussSelectionChip").is_hidden()
    assert page.locator("#discussInput").get_attribute("placeholder") == "Ask about this document…"
    assert path.read_bytes() == before


def test_selection_dock_close_returns_focus_to_visible_selection_trigger(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")
    page.click("#selectionCodexBtn")
    page.wait_for_selector("#discussPanel", state="visible")
    assert page.locator("#selectionPillBtn").is_visible()
    page.click(".discuss-close")
    assert page.evaluate("document.activeElement === document.getElementById('selectionPillBtn')")


def test_unsent_selection_instruction_survives_panel_close_and_reload(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)

    page.click("#selectionCodexBtn")
    page.fill("#discussInput", "Make the waiting feel more ominous")
    page.click(".discuss-close")
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    assert page.input_value("#discussInput") == "Make the waiting feel more ominous"
    page.reload()
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    assert page.input_value("#discussInput") == "Make the waiting feel more ominous"


def test_selection_quick_flow_never_offers_auto_approve(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.click("#selectionCodexBtn")
    page.wait_for_selector("#discussPanel", state="visible")
    assert page.locator("text=Auto-approve changes").count() == 0
    assert page.locator("#selectionCodexAutoApprove").count() == 0


def test_new_conversation_clears_configured_selection_action_mode(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra of yesterday's receipts")
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='custom_rewrite']")
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert "Custom rewrite" in page.locator("#discussTaskMode").inner_text()
    page.fill("#discussInput", "Make the diction more formal")

    page.click("#discussNewConversation")
    page.wait_for_selector("#discussNewConversationDialog", state="visible")
    page.click("#discussNewConversationConfirm")
    page.wait_for_selector("#discussNewConversationDialog", state="hidden")

    assert page.locator("#discussTaskMode").is_hidden()
    assert page.locator("#discussSelectionChip").is_hidden()
    page.fill("#discussInput", "Fresh question after reset")
    page.press("#discussInput", "Enter")
    page.wait_for_function(
        "() => document.querySelector('.discuss-message.user')?.textContent.includes('Fresh question after reset')"
    )


def test_managed_rewrite_auto_opens_review_exposes_suggestions_and_applies_only_to_draft(
    page: Page, server: ProseviewServer
):
    path = server.scene_path()
    before = path.read_text(encoding="utf-8")
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")

    page.wait_for_selector(".ai-proposal-panel", state="visible", timeout=15_000)
    page.wait_for_function("() => document.activeElement === document.getElementById('aiProposalPanel')")
    task = page.locator(".discuss-task").first
    assert "Tighten" in task.inner_text()
    assert "2 suggestions" in task.inner_text()
    suggestions = task.locator(".discuss-alternatives")
    suggestions.locator("summary").click()
    assert "Rena pressed her thumb against the envelope seam." in suggestions.inner_text()
    assert "Uses a direct physical action." in suggestions.inner_text()
    assert "Rena held the sealed envelope to the window." in suggestions.inner_text()
    assert path.read_text(encoding="utf-8") == before

    panel = page.locator(".ai-proposal-panel")
    assert panel.get_attribute("role") == "dialog"
    assert panel.get_attribute("aria-modal") == "false"
    assert panel.get_attribute("aria-labelledby") == "aiProposalTitle"
    assert "PROPOSED · 1 OF 2" in panel.inner_text()
    assert "Use this version" in panel.inner_text()
    assert "Stage change" not in panel.inner_text()
    panel.get_by_role("button", name="Use this version").click()
    _wait_until(lambda: "Rena pressed her thumb" in _editor_text(page))
    assert path.read_text(encoding="utf-8") == before
    assert "Applied to draft · Not saved" in panel.inner_text()
    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Applied · Not saved'")
    assert "used suggestion 1" in task.inner_text().lower()
    assert "Rena pressed her thumb against the envelope seam." in task.inner_text()

    panel.get_by_role("button", name="Undo").click()
    _wait_until(lambda: quote in _editor_text(page))
    assert "Rena pressed her thumb" not in _editor_text(page)
    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'")


def test_managed_selection_action_restores_as_a_card_after_server_restart(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Reviewing'",
        timeout=15_000,
    )

    server.restart()
    # Force a fresh document so the restarted server's per-process mutation
    # token is not satisfied from the browser cache.
    page.context.new_cdp_session(page).send("Network.setCacheDisabled", {"cacheDisabled": True})
    page.goto("about:blank")
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_timeout(1_000)
    connection = page.locator("#discussConnection").inner_text()
    assert connection.startswith("Live"), connection
    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'",
        timeout=15_000,
    )

    task = page.locator(".discuss-task")
    assert task.count() == 1
    assert "Tighten" in task.inner_text()
    assert "Restored from Codex history" in task.inner_text()
    assert "2 suggestions" in task.inner_text()
    restored_suggestions = task.locator(".discuss-alternatives")
    restored_suggestions.locator("summary").click()
    assert "Rena pressed her thumb against the envelope seam." in restored_suggestions.inner_text()
    assert "Rena held the sealed envelope to the window." in restored_suggestions.inner_text()
    assert "&quot;" not in page.locator("#discussLog").inner_text()
    assert '"kind":"alternatives"' not in page.locator("#discussLog").inner_text()
    task.get_by_role("button", name="Review changes").click()
    page.wait_for_selector(".ai-proposal-panel", state="visible")
    assert quote in page.locator(".ai-proposal-panel").inner_text()


def test_same_server_reload_does_not_auto_review_replayed_rewrite_history(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Reviewing'",
        timeout=15_000,
    )

    proposal_requests: list[str] = []
    page.on(
        "request",
        lambda request: proposal_requests.append(request.url)
        if request.url.endswith("/proposal")
        else None,
    )
    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.wait_for_selector("#sceneModal", state="visible")
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.wait_for_timeout(1_000)

    assert proposal_requests == []
    assert page.locator(".ai-proposal-panel:visible").count() == 0, page.evaluate(
        """() => ({
            reviewed: Object.keys(_discussAutoReviewedTasks),
            pendingRequests: Object.keys(_discussAutoReviewRequests),
            taskStatus: document.querySelector('.discuss-task-status')?.textContent,
            panelText: document.querySelector('#aiProposalPanel')?.textContent
        })"""
    )
    task = page.locator(".discuss-task").first
    assert "Reviewing" in task.locator(".discuss-task-status").inner_text()
    task.get_by_role("button", name="Review changes").click()
    page.wait_for_selector(".ai-proposal-panel", state="visible")


def test_legacy_selection_history_restores_as_a_safe_historical_card(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='custom_rewrite']")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "SIMULATE_LEGACY_HISTORY")
    page.press("#discussInput", "Enter")
    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Reviewing'",
        timeout=15_000,
    )

    server.restart()
    page.context.new_cdp_session(page).send("Network.setCacheDisabled", {"cacheDisabled": True})
    page.goto("about:blank")
    open_scene(page, server)
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Restored'",
        timeout=15_000,
    )

    task = page.locator(".discuss-task")
    assert task.count() == 1
    assert "Custom rewrite" in task.inner_text()
    assert "Historical result · reselect the passage to use it safely" in task.inner_text()
    assert "2 suggestions" in task.inner_text()
    assert "Instruction · SIMULATE_LEGACY_HISTORY" in task.inner_text()
    assert task.get_by_role("button", name="Review changes").count() == 0
    assert "&quot;" not in page.locator("#discussLog").inner_text()
    assert '"kind":"alternatives"' not in page.locator("#discussLog").inner_text()


def test_managed_apply_tracks_target_after_unrelated_unsaved_insert(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.wait_for_selector(".pm-ai-proposal-highlight", state="visible")
    page.evaluate(
        """() => {
            if (!_pmEditMode) toggleSceneEdit();
            _pmView.dispatch(_pmView.state.tr.insertText('Local preface. ', 1));
            setPmDirty(true);
        }"""
    )
    page.get_by_role("button", name="Use this version").click()
    _wait_until(lambda: "Rena pressed her thumb" in _editor_text(page))
    assert "Local preface." in _editor_text(page)
    assert quote not in _editor_text(page)


def test_selection_action_started_from_dirty_editor_uses_live_target(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    page.click("#sceneEditBtn")
    page.evaluate(
        """() => {
            _pmView.dispatch(_pmView.state.tr.insertText('Local preface. ', 1));
            setPmDirty(true);
        }"""
    )
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.wait_for_selector(".pm-ai-proposal-highlight", state="visible")
    page.get_by_role("button", name="Use this version").click()
    _wait_until(lambda: "Rena pressed her thumb" in _editor_text(page))
    assert "Local preface." in _editor_text(page)
    assert quote not in _editor_text(page)


def test_applied_managed_task_becomes_saved_only_after_normal_scene_save(
    page: Page, server: ProseviewServer
):
    path = server.scene_path()
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.get_by_role("button", name="Use this version").wait_for(state="visible", timeout=15_000)
    page.get_by_role("button", name="Use this version").click()
    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Applied · Not saved'")
    assert "Rena pressed her thumb" not in path.read_text(encoding="utf-8")
    page.get_by_role("button", name="Save scene").click()
    _wait_until(lambda: "Rena pressed her thumb" in path.read_text(encoding="utf-8"))
    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Saved'")
    saved_task = page.locator(".discuss-task").first
    assert "used suggestion 1" in saved_task.inner_text().lower()
    assert "Rena pressed her thumb against the envelope seam." in saved_task.inner_text()
    assert "saved to manuscript" in saved_task.inner_text().lower()


def test_one_scene_save_marks_every_applied_managed_task_saved(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra of yesterday's receipts")
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.get_by_role("button", name="Use this version").wait_for(state="visible", timeout=15_000)
    page.get_by_role("button", name="Use this version").click()
    page.locator("#aiProposalPanel").get_by_role("button", name="Close", exact=True).click()

    open_selection_menu(page, "dial turned with a dry clatter")
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='clarify']")
    page.get_by_role("button", name="Use this version").wait_for(state="visible", timeout=15_000)
    page.get_by_role("button", name="Use this version").click()
    page.wait_for_function(
        "() => document.querySelectorAll('.discuss-task-status.status-applied').length === 2"
    )
    page.get_by_role("button", name="Save scene").click()
    page.wait_for_function(
        "() => document.querySelectorAll('.discuss-task-status.status-saved').length === 2"
    )


def test_proposal_review_fits_beside_dock_at_200_percent_zoom(
    page: Page, server: ProseviewServer
):
    page.set_viewport_size({"width": 1024, "height": 768})
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra of yesterday's receipts")
    page.click("#selectionRewriteBtn")
    page.click("[data-selection-action='tighten']")
    page.wait_for_selector("#aiProposalPanel", state="visible")
    open_scene_appearance(page)
    page.select_option("#modalThemeSelect", "dark")
    page.evaluate("document.body.style.zoom = '2'")
    page.wait_for_timeout(150)
    assert_fully_inside_viewport(page, "#aiProposalPanel")
    assert page.locator("#discussPanel").bounding_box() is None


def test_managed_critique_is_evidence_linked_and_can_transition_to_a_revision(
    page: Page, server: ProseviewServer
):
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionCritiqueBtn")
    page.click("[data-selection-action='quick_critique']")

    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'", timeout=15_000)
    task = page.locator(".discuss-task").first
    assert "The passage delays its strongest image" in task.inner_text()
    assert quote in task.inner_text()
    assert page.locator(".ai-proposal-panel:visible").count() == 0

    task.get_by_role("button", name="Propose a revision").click()
    assert "Rephrase selection" in page.locator("#discussTaskMode").inner_text()
    assert "Address the critique" in page.input_value("#discussInput")


def test_quick_critique_queues_while_another_tab_restores_history(
    page: Page, server: ProseviewServer
):
    """A slow thread/read must not hold the queue endpoint past its deadline."""
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "Prime this conversation")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page)

    other = page.context.new_page()
    _install_esm_cache(other)
    try:
        with server.hold_codex_request("thread/read") as restore_reached:
            open_scene(other, server)
            other.click("#sceneModal .discuss-open-btn")
            _wait_until(
                restore_reached.exists,
                message="the second tab never began restoring Codex history",
            )

            # Keep this shorter than the held restore. Before the lock fix, the
            # browser aborts this POST and renders the same timeout users saw.
            page.evaluate("window._discussRequestTimeoutMs = 500")
            open_selection_menu(page, quote)
            page.click("#selectionCritiqueBtn")
            page.click("[data-selection-action='quick_critique']")
            page.wait_for_selector(".discuss-task", state="visible", timeout=1_500)
            assert page.locator("#discussError", has_text="Request timed out").count() == 0
    finally:
        other.close()

    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'",
        timeout=15_000,
    )


def test_quick_critique_queues_before_a_slow_codex_turn_starts(
    page: Page, server: ProseviewServer
):
    """Queue acknowledgement is independent of Codex accepting the turn."""
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)

    with server.hold_codex_request("turn/start") as turn_start_reached:
        page.evaluate("window._discussRequestTimeoutMs = 500")
        open_selection_menu(page, quote)
        page.click("#selectionCritiqueBtn")
        page.click("[data-selection-action='quick_critique']")
        _wait_until(
            turn_start_reached.exists,
            message="Quick Critique never reached the Codex turn boundary",
        )
        page.wait_for_selector(".discuss-task", state="visible", timeout=1_500)
        assert page.locator("#discussError", has_text="Request timed out").count() == 0
        assert page.locator(".discuss-task-status").inner_text() in {"Queued", "Running"}

    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'",
        timeout=15_000,
    )


def test_quick_critique_runs_immediately_after_restart_with_retained_history(
    page: Page, server: ProseviewServer
):
    """A fresh process must retain history without delaying the next action."""
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "Prime retained history")
    page.press("#discussInput", "Enter")
    wait_for_discuss_answer(page)

    server.restart()
    page.context.new_cdp_session(page).send("Network.setCacheDisabled", {"cacheDisabled": True})
    page.goto("about:blank")
    open_scene(page, server)
    open_selection_menu(page, quote)
    page.click("#selectionCritiqueBtn")
    page.click("[data-selection-action='quick_critique']")

    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'",
        timeout=15_000,
    )
    assert page.locator("#discussConnection").inner_text().startswith("Live")
    assert page.locator("#discussError").count() == 0
    assert "Fake answer" in page.locator("#discussLog").inner_text()


def test_quick_critique_queues_while_an_active_turn_is_stopping(
    page: Page, server: ProseviewServer
):
    """Stopping one request must not make the next managed action disappear."""
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.fill("#discussInput", "HOLD_FOR_STOP")
    page.press("#discussInput", "Enter")
    page.wait_for_selector("#discussStop", state="visible")

    with server.hold_codex_request("turn/interrupt") as interrupt_reached:
        page.click("#discussStop")
        _wait_until(
            interrupt_reached.exists,
            message="the stop request never reached Codex",
        )
        assert page.locator("#discussStop").inner_text() == "Stopping…"
        page.evaluate("window._discussRequestTimeoutMs = 500")
        open_selection_menu(page, quote)
        page.click("#selectionCritiqueBtn")
        page.click("[data-selection-action='quick_critique']")
        page.wait_for_selector(".discuss-task", state="visible", timeout=1_500)
        assert page.locator("#discussError", has_text="Request timed out").count() == 0

    page.wait_for_function(
        "() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'",
        timeout=15_000,
    )
    page.wait_for_selector("#discussStop", state="hidden")


def test_failed_critique_retry_shows_the_bad_citation_and_groups_attempts(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_selection_menu(page, "dial turned with a dry clatter")
    page.click("#selectionCritiqueBtn")
    page.click("[data-selection-action='quick_critique']")

    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Failed'", timeout=15_000)
    task = page.locator(".discuss-task")
    assert task.count() == 1
    assert "a pressure gauge that was never selected" in task.inner_text()
    task.get_by_role("button", name="Try again").click()

    page.wait_for_function(
        "() => document.querySelector('.discuss-task')?.querySelector('.discuss-task-status')?.textContent === 'Failed'"
        " && document.querySelector('.discuss-attempts summary')?.textContent.includes('previous attempt')",
        timeout=15_000,
    )
    assert page.locator(".discuss-task").count() == 1
    attempts = page.locator(".discuss-attempts")
    assert "1 previous attempt" in attempts.locator("summary").inner_text()
    attempts.locator("summary").click()
    assert "Attempt 1 · failed" in attempts.inner_text()


def test_selection_assistance_history_can_be_cleared_without_clearing_conversation(
    page: Page, server: ProseviewServer
):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra of yesterday's receipts")
    page.click("#selectionCritiqueBtn")
    page.click("[data-selection-action='quick_critique']")
    page.wait_for_function("() => document.querySelector('.discuss-task-status')?.textContent === 'Ready'", timeout=15_000)
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#discussHistoryClear")
    page.wait_for_function("() => document.querySelectorAll('.discuss-task').length === 0")
    assert page.locator("#discussPanel").is_visible()


def test_terminal_survives_a_page_reload(page: Page, server: ProseviewServer):
    """A reload must reattach live sessions rather than orphan running agents."""
    open_scene(page, server)
    open_shell_terminal(page)
    run_in_terminal(page, "echo before-reload", "before-reload")

    before = {s["id"] for s in server.get_json("/terminal-list")["sessions"]}
    assert before

    page.reload(wait_until="load")
    page.wait_for_selector("#terminalPanel", state="visible")
    page.wait_for_selector(".terminal-tab-mount .xterm")

    after = {s["id"] for s in server.get_json("/terminal-list")["sessions"]}
    assert before <= after, "reload killed a live terminal session"
    _wait_until(lambda: "before-reload" in _terminal_text(page), timeout=20,
                message="scrollback was not replayed after reload")


# ── AI proposal bridge ──────────────────────────────────────────────────────


QUOTE = "the slow algebra of yesterday's receipts"
REPLACEMENT = "the arithmetic of yesterday's receipts"


def _raise_proposal(page: Page, server: ProseviewServer) -> None:
    server.cli(
        "propose", "--root", str(server.root), "--file", SCENE_REL,
        "--quote", QUOTE, "--message", "Too ornate for a cold open",
        "--option", REPLACEMENT,
    )
    # Pushed over SSE: the panel and the inline decoration appear without a
    # reload. (Playwright timeouts are milliseconds.)
    page.wait_for_selector(".ai-proposal-panel", timeout=20_000)
    page.wait_for_selector(".pm-ai-proposal-highlight", timeout=20_000)


def test_proposal_from_the_cli_is_highlighted_in_the_open_scene(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _raise_proposal(page, server)

    assert QUOTE in page.locator(".pm-ai-proposal-highlight").inner_text()
    assert "Too ornate for a cold open" in page.locator(".ai-proposal-panel").inner_text()


def test_using_a_proposal_applies_the_edit_without_writing_the_file(page: Page, server: ProseviewServer):
    """Accepting is not committing.

    The edit lands in the editor and the file is left alone until the writer
    confirms -- the guarantee that nothing rewrites prose behind their back.
    """
    path = server.scene_path()
    before = path.read_text(encoding="utf-8")

    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Use this version')")

    _wait_until(lambda: REPLACEMENT in _editor_text(page),
                message="the replacement never appeared in the editor")
    page.wait_for_timeout(1500)
    assert path.read_text(encoding="utf-8") == before, "accepting wrote to disk without confirmation"


def test_undo_restores_the_original_passage(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Use this version')")
    _wait_until(lambda: REPLACEMENT in _editor_text(page))

    page.click("button:has-text('Undo')")
    _wait_until(lambda: QUOTE in _editor_text(page),
                message="undo did not restore the original passage")
    assert REPLACEMENT not in _editor_text(page)


def test_proposal_undo_restores_original_inline_emphasis(page: Page, server: ProseviewServer):
    path = open_annotated_scene(page, server)
    original = path.read_text(encoding="utf-8")
    server.cli(
        "propose", "--root", str(server.root), "--file", ANNOTATED_SCENE_REL,
        "--quote", "shop stayed quiet", "--message", "Test marked selection", "--option", "shop fell silent",
    )
    page.wait_for_selector(".ai-proposal-panel", timeout=20_000)
    page.wait_for_selector(".pm-ai-proposal-highlight", timeout=20_000)
    page.click(".ai-proposal-panel button:has-text('Use this version')")
    _wait_until(lambda: "shop fell silent" in _editor_text(page))
    page.click("button:has-text('Undo')")
    _wait_until(lambda: page.locator("#sceneProseHost em", has_text="quiet").count() == 1)
    assert path.read_text(encoding="utf-8") == original


def test_applied_proposal_requires_normal_save_to_reach_disk(page: Page, server: ProseviewServer):
    """The bridge applies locally; only the editor's normal Save writes the file."""
    path = server.scene_path()
    original = path.read_text(encoding="utf-8")

    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Use this version')")
    _wait_until(lambda: REPLACEMENT in _editor_text(page))

    page.click("button:has-text('Close')")
    page.wait_for_timeout(500)
    assert path.read_text(encoding="utf-8") == original
    page.click("#sceneProseHost .ProseMirror")
    save_scene(page)
    _wait_until(lambda: REPLACEMENT in path.read_text(encoding="utf-8"), timeout=20,
                message="normal Save did not persist the applied proposal")

    after = path.read_text(encoding="utf-8")
    assert QUOTE not in after
    assert frontmatter(after) == frontmatter(original)


def test_timeline_tab_shows_shape_threads_and_chronology(page: Page, shared_server: ProseviewServer):
    """The three story layers render from frontmatter, and the chronology view
    names the scene that is read out of the order it happens."""
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    # Layer 1 is always available: one segment and one bar per scene.
    scenes = page.evaluate("() => storyModel.scenes.length")
    assert scenes > 0
    assert page.locator(".story-seg").count() == scenes
    assert page.locator(".story-barwrap").count() == scenes

    # Layer 2: one lane per thread the fixture seeds.
    lanes = page.locator(".story-lane-row")
    lanes.first.wait_for(state="visible")
    lane_text = page.locator("#timelineContent").inner_text().lower()
    assert "present" in lane_text and "recollection" in lane_text

    # Layer 3: the seeded flashback happens first but is read last.
    assert "reading order vs story order" in lane_text
    assert page.locator(".story-svg").count() == 1
    assert "read far from where they happen" in lane_text
    assert "flashback" in lane_text


def test_timeline_scene_click_opens_the_scene(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    first = page.locator(".story-barwrap[data-scene]").first
    expected = page.evaluate("() => storyModel.scenes[+document.querySelector('.story-barwrap[data-scene]').dataset.scene].path")
    first.click()

    page.wait_for_selector("#sceneModal", state="visible")
    assert expected in page.locator("#modalTitle").inner_text()


def test_timeline_says_what_is_missing_rather_than_guessing(page: Page, shared_server: ProseviewServer):
    """A manuscript with no story fields still gets the shape view, and the
    other two layers name the field they would need instead of guessing."""
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    # Re-render against a model with no thread or day data, which is what an
    # untagged manuscript produces (proseview/story.py decides that; this
    # asserts what the renderer does with it).
    page.evaluate("""() => {
        storyModel.threads = [];
        storyModel.has_threads = false;
        storyModel.has_chronology = false;
        _timelineBuilt = false;
        buildTimelineTab();
    }""")

    text = page.locator("#timelineContent").inner_text().lower()
    assert "proportion of the book" in text, "the shape layer must survive with no story fields"
    assert "no storylines yet" in text
    assert "thread" in text, "the empty state names the field to add"
    assert "no chronology yet" in text
    assert page.locator(".story-lane-row").count() == 0
    assert page.locator(".story-svg").count() == 0
    # Still navigable: the shape layer keeps its per-scene marks.
    assert page.locator(".story-barwrap").count() > 0


def test_timeline_hover_shows_a_scene_card(page: Page, shared_server: ProseviewServer):
    """Hovering a scene mark shows its title, metadata, and what happens in it."""
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    card = page.locator("#storyCard")
    assert card.count() == 0, "the card is created on first hover, not up front"

    page.locator(".story-barwrap[data-scene]").first.hover()
    page.wait_for_selector("#storyCard.on")

    text = card.inner_text()
    expected = page.evaluate(
        "() => storyModel.scenes[+document.querySelector('.story-barwrap[data-scene]').dataset.scene]")
    assert expected["title"] in text
    assert "words" in text
    if expected["blurb"]:
        assert expected["blurb"][:40] in text

    # It goes away again, and never covers what it describes.
    page.locator("#timelineContent .story-h").first.hover()
    page.wait_for_function("() => !document.getElementById('storyCard').classList.contains('on')")


def test_timeline_hover_card_reaches_the_chronology_blocks(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector(".story-svg")

    page.locator(".story-node[data-scene]").first.hover()
    page.wait_for_selector("#storyCard.on")
    assert page.locator("#storyCard").inner_text().strip() != ""


def test_timeline_shows_untagged_scenes_as_their_own_lane(page: Page, shared_server: ProseviewServer):
    """Untagged scenes are a state, not a gap.

    Drawn only as holes in the real lanes they read as a rendering fault, so
    they get a lane of their own that says how many and which.
    """
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    untagged = page.evaluate("() => storyModel.scenes.filter(s => !s.thread).length")
    assert untagged > 0, "the fixture must have some untagged scenes for this to mean anything"

    row = page.locator(".story-lane-untagged")
    row.wait_for(state="visible")
    assert str(untagged) in row.inner_text()
    assert storyModel_field(page) in row.inner_text()
    # Its marks are real scenes: hoverable and clickable like any other.
    assert page.locator(".story-lane-untagged .story-slot.none[data-scene]").count() == untagged

    page.locator(".story-lane-untagged .story-slot.none[data-scene]").first.hover()
    page.wait_for_selector("#storyCard.on")


def storyModel_field(page: Page) -> str:
    return page.evaluate("() => storyModel.thread_field")


def test_timeline_hides_the_untagged_lane_when_everything_is_tagged(page: Page, shared_server: ProseviewServer):
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    page.evaluate("""() => {
        storyModel.scenes.forEach(s => { s.thread = s.thread || 'present'; });
        _timelineBuilt = false;
        buildTimelineTab();
    }""")

    assert page.locator(".story-lane-untagged").count() == 0
    assert "every scene belongs to a storyline" in page.locator("#timelineContent").inner_text().lower()


def test_scene_card_shows_the_story_fields_when_present(page: Page, shared_server: ProseviewServer):
    """A scene's storyline and day belong on the scene card, not only in the
    Timeline, and are labelled with the keys this repo actually uses."""
    rel, thread, day = STORY_SCENES[0]
    open_scene(page, shared_server, rel.split("manuscript/")[-1] if "manuscript/" in rel else rel)

    card = page.locator(".scene-card").inner_text().lower()
    assert thread in card
    assert str(day) in card
    assert page.evaluate("() => storyModel.thread_field") in card
    assert page.evaluate("() => storyModel.day_field") in card


def test_scene_card_omits_story_rows_when_the_scene_has_none(page: Page, shared_server: ProseviewServer):
    """A manuscript that does not use these fields sees no row at all, rather
    than a line of 'Unknown' for something it never opted into."""
    open_scene(page, shared_server, SCENE_REL)

    card = page.locator(".scene-card").inner_text().lower()
    thread_field = page.evaluate("() => storyModel.thread_field")
    assert thread_field not in card
    # The rows that were always there are untouched.
    assert "pov" in card and "when" in card and "goal" in card


def test_timeline_names_a_bare_chapter_number(page: Page, shared_server: ProseviewServer):
    """A frontmatter `chapter: 2` renders as "Chapter 2", while a value that
    already names itself is left alone."""
    open_dashboard(page, shared_server)
    page.click('.tab-nav button[data-tab="timeline"]')
    page.wait_for_selector("#tab-timeline.active")

    labels = page.evaluate(
        "() => ['2', 2, 'ch00-prolog', 'Chapter 3', ''].map(v => _storyChapterLabel(v))")

    assert labels == ["Chapter 2", "Chapter 2", "ch00-prolog", "Chapter 3", ""]
