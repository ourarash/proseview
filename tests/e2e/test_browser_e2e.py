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
    SCENE_REL,
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


def select_prose(page: Page, needle: str) -> str:
    """Select *needle* in the rendered prose and raise the selection pill.

    The pill is bound to ``mouseup`` on ``#modalBody``, so a synthetic Range has
    to be followed by that event for the UI to react. The passage is scrolled
    near the top of the viewport first: the pill is positioned at the selection
    and its menu is tall, so a selection low on the page puts the menu items
    off-screen and Playwright refuses to click them.
    """
    selected = page.evaluate(
        """(needle) => {
            const host = document.getElementById('sceneProseHost');
            const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
            let node = null, idx = -1;
            while ((node = walker.nextNode())) {
                idx = node.data.indexOf(needle);
                if (idx >= 0) break;
            }
            if (!node) throw new Error('text not found in prose: ' + needle);
            if (node.parentElement) {
                node.parentElement.scrollIntoView({ block: 'start' });
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
        needle,
    )
    page.wait_for_selector("#selectionPill", state="visible")
    return selected


def test_discuss_scene_streams_safe_document_aware_conversation(page: Page, server: ProseviewServer):
    open_scene(page, server)
    selected = select_prose(page, "ledger")
    assert selected == "ledger"
    page.evaluate("openDiscuss(document.querySelector('#sceneModal .discuss-open-btn'))")
    page.wait_for_selector("#discussPanel", state="visible")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert SCENE_REL in page.locator("#discussContext").inner_text()
    assert "Selected text: ledger" in page.locator("#discussSelectionChip").inner_text()

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
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Reconnecting')")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')", timeout=15_000)

    page.locator("#sceneModal .nav-btn").nth(1).click()
    page.wait_for_function("previous => !document.querySelector('#discussContext').innerText.includes(previous)", arg=SCENE_REL)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    page.press("body", "Escape")
    page.wait_for_selector("#discussPanel", state="hidden")
    assert page.evaluate("document.activeElement === document.querySelector('#sceneModal .discuss-open-btn')")


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
    page.wait_for_function("() => document.querySelector('#discussLog').innerText.includes('question queued')")

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
    assert "remains in your Codex history" in page.locator("#discussNewConversationDialog").inner_text()
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
    page.select_option("#modalThemeSelect", "dark")
    _wait_until(lambda: page.evaluate("document.documentElement.dataset.theme") == "dark")

    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")

    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.locator("#modalThemeSelect").input_value() == "dark"


def test_switching_theme_does_not_raise(page: Page, server: ProseviewServer):
    """Re-theming the charts must not throw.

    Regression guard: this used to recurse to a stack overflow because the
    theme was written through Chart.js's resolved options proxy rather than the
    raw config. Charts must still repaint, so assert both.
    """
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    open_scene(page, server)
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
    box.click()
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


def test_skills_submenu_lists_the_repo_snippet_skills(page: Page, server: ProseviewServer):
    """Skills come from ``skills/*/SKILL.md``, read at render time.

    The selection menu deliberately lists only ``snippet-`` type skills, so
    ``tighten-prose`` must stay out of it. ``snippet-continuity`` carries an
    ``agents/openai.yaml``, so seeing its *display* name rather than its
    directory name proves that file was parsed.
    """
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.click("#selectionSkillsBtn")
    page.wait_for_selector("#selectionSkillsMenu", state="visible")
    listed = page.locator("#selectionSkillsMenu").inner_text()

    assert "Continuity Check" in listed, "display_name from agents/openai.yaml was not used"
    assert "snippet-sensory" in listed, "snippet skill without openai.yaml is missing"
    assert "tighten-prose" not in listed, "non-snippet skill leaked into the selection menu"


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
    page.click("#sceneModal button:has-text('$ Shell')")
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


def test_running_a_selection_in_codex_sends_the_passage(page: Page, server: ProseviewServer):
    """The whole prompt reaches the agent's stdin, not just the instruction.

    The selection menu composes ``Run <instruction> on "<selection>" in @<path>``
    and types it into the PTY -- it is never passed as argv. All three parts
    matter: an agent that receives the instruction but loses the passage or the
    file reference is being handed a task it cannot do.
    """
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)

    page.click("#selectionCodexBtn")
    page.fill("#selectionCodexInstruction", "Tighten this passage")
    page.click("#selectionCodexRun")

    page.wait_for_selector("#terminalPanel", state="visible")
    _wait_until(lambda: f"{AGENT_MARKER} codex" in _terminal_text(page), timeout=25,
                message="Run in Codex did not launch the agent")
    _wait_until(lambda: "Tighten this passage" in _terminal_flat(page), timeout=25,
                message="instruction never reached the agent process")

    delivered = _terminal_flat(page)
    assert quote in delivered, "the selected passage was dropped from the prompt"
    assert f"@{SCENE_REL}" in delivered, "the scene reference was dropped from the prompt"
    # The stub echoes stdin, so seeing it prefixed proves it arrived as input.
    assert f"STDIN:Run Tighten this passage on" in delivered


def test_running_a_selection_without_an_instruction_still_sends_the_passage(
    page: Page, server: ProseviewServer
):
    """With no instruction the menu falls back to a review prompt."""
    quote = "the slow algebra of yesterday's receipts"
    open_scene(page, server)
    open_selection_menu(page, quote)

    page.click("#selectionCodexBtn")
    page.click("#selectionCodexRun")

    page.wait_for_selector("#terminalPanel", state="visible")
    _wait_until(lambda: f'STDIN:Review "{quote}"' in _terminal_flat(page), timeout=25,
                message="the no-instruction fallback prompt never reached the agent")


def test_auto_approve_launches_codex_with_full_auto(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_selection_menu(page, "the slow algebra")

    page.click("#selectionCodexBtn")
    page.fill("#selectionCodexInstruction", "Polish it")
    page.check("#selectionCodexAutoApprove")
    page.click("#selectionCodexRun")

    page.wait_for_selector("#terminalPanel", state="visible")
    _wait_until(lambda: "argv:--full-auto" in _terminal_text(page), timeout=25,
                message="--full-auto was not passed to the agent")


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


def test_accepting_a_proposal_stages_the_edit_without_writing_the_file(page: Page, server: ProseviewServer):
    """Accepting is not committing.

    The edit lands in the editor and the file is left alone until the writer
    confirms -- the guarantee that nothing rewrites prose behind their back.
    """
    path = server.scene_path()
    before = path.read_text(encoding="utf-8")

    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Accept selected')")

    _wait_until(lambda: REPLACEMENT in _editor_text(page),
                message="the replacement never appeared in the editor")
    page.wait_for_timeout(1500)
    assert path.read_text(encoding="utf-8") == before, "accepting wrote to disk without confirmation"


def test_undo_restores_the_original_passage(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Accept selected')")
    _wait_until(lambda: REPLACEMENT in _editor_text(page))

    page.click("button:has-text('Undo')")
    _wait_until(lambda: QUOTE in _editor_text(page),
                message="undo did not restore the original passage")
    assert REPLACEMENT not in _editor_text(page)


def test_done_commits_the_accepted_proposal_to_disk(page: Page, server: ProseviewServer):
    """The end of the bridge: CLI -> SSE -> decoration -> accept -> Done -> file."""
    path = server.scene_path()
    original = path.read_text(encoding="utf-8")

    open_scene(page, server)
    _raise_proposal(page, server)
    page.click(".ai-proposal-panel button:has-text('Accept selected')")
    _wait_until(lambda: REPLACEMENT in _editor_text(page))

    page.click("button:has-text('Done')")
    _wait_until(lambda: REPLACEMENT in path.read_text(encoding="utf-8"), timeout=20,
                message="Done did not persist the accepted proposal")

    after = path.read_text(encoding="utf-8")
    assert QUOTE not in after
    assert frontmatter(after) == frontmatter(original)
