"""Browser tests for the phone layout that ``proseview --remote`` serves.

Runs the demo book in an emulated Android phone (Pixel 7: touch, narrow) and
checks:

- the home shows Continue reading and the chapters, not the scene table
- a tap on a paragraph only marks it and shows the + TODO / Note pill; the
  pill opens the sheet, and Add puts the TODO above that paragraph on disk,
  including a paragraph that opens with Markdown formatting
- Quick edit saved without changes leaves a scene and a note byte for byte
- a Quick edit draft survives a reload and is still checked against the
  file's original mtime, so a change made on the Mac meanwhile raises the
  conflict sheet instead of being overwritten
- with the connection gone, Save keeps the text and shows the "Mac asleep"
  banner; Retry reconnects without a reload and the draft keeps its mtime
- Ask opens the chat with only the Codex, Claude and Agy tabs, and Return
  in the chat box adds a line instead of sending

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Browser, Page, expect  # noqa: E402

from .conftest import REPO_ROOT, ProseviewServer, _install_esm_cache, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"
SCENE = "ch01/01-down-the-rabbit-hole.md"
NOTE = "story-bible/characters/alice.md"
FORMATTED = "*Later,* she counted the boats again, twice."


@pytest.fixture
def book_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    scene = root / "manuscript" / SCENE
    scene.write_text(scene.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + FORMATTED + "\n", encoding="utf-8")
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


#: Playwright's "Pixel 7", written out: the browser fixture already owns
#: the Playwright instance, so its device list is not reachable here.
PIXEL_7 = {
    "viewport": {"width": 412, "height": 839},
    "device_scale_factor": 2.625,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"),
}


@pytest.fixture
def phone(browser: Browser, request: pytest.FixtureRequest) -> Iterator[Page]:
    marker = request.node.get_closest_marker("allow_js_errors")
    allowed = tuple(marker.args) if marker else ()
    context = browser.new_context(**PIXEL_7, service_workers="block")
    page = context.new_page()
    _install_esm_cache(page)
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)) if not any(a in str(exc) for a in allowed) else None)
    try:
        yield page
    finally:
        context.close()
    assert not errors, "uncaught JavaScript errors:\n" + "\n".join(errors)


def open_home(page: Page, server: ProseviewServer) -> None:
    page.goto(server.url("/"))
    expect(page.locator("html")).to_have_class("pv-phone")
    expect(page.locator("#phoneHome")).to_be_visible()


def open_scene(page: Page, rel: str = SCENE) -> None:
    page.evaluate("p => openSceneModal(p)", rel)
    expect(page.locator("#pvSceneBar")).to_be_visible()
    expect(page.locator("#sceneProseHost p").first).to_be_visible()


def test_home_shows_continue_reading_and_chapters_not_the_table(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    expect(phone.locator(".pv-continue")).to_contain_text("Down the Rabbit-Hole")
    expect(phone.locator(".pv-chapter").first).to_contain_text("Down the Rabbit-Hole")
    expect(phone.locator("#sceneTable")).to_be_hidden()
    expect(phone.locator(".tab-nav")).to_be_hidden()
    phone.locator(".pv-chapter").nth(1).locator("summary").tap()
    phone.locator(".pv-chapter").nth(1).locator(".pv-row").first.tap()
    expect(phone.locator("html")).to_have_attribute("data-view", "scene")
    expect(phone.locator("#pvReadBtn")).to_be_visible()


def test_a_tap_marks_a_paragraph_and_the_pill_adds_a_todo_above_it(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    open_scene(phone)
    paragraph = phone.locator("#sceneProseHost p", has_text="she counted the boats again")
    paragraph.scroll_into_view_if_needed()
    paragraph.tap()
    expect(paragraph).to_have_class("pv-tapped")
    expect(phone.locator("#pvNoteSheet")).to_have_count(0)  # nothing opens on a tap
    phone.locator("#pvNotePill").tap()
    expect(phone.locator("#pvNoteSheet")).to_be_visible()
    expect(phone.locator("#pvNoteQuote")).to_contain_text("Later, she counted")
    phone.locator("#pvNoteText").fill("Which boats?")
    phone.locator("#pvNoteAdd").tap()
    expect(phone.locator("#pvNoteSheet")).to_be_hidden()
    lines = (book_server.root / "manuscript" / SCENE).read_text(encoding="utf-8").splitlines()
    assert lines[lines.index(FORMATTED) - 2] == "<!-- TODO: Which boats? -->"


def test_quick_edit_saved_unchanged_leaves_scene_and_note_byte_for_byte(phone: Page, book_server: ProseviewServer):
    scene = book_server.root / "manuscript" / SCENE
    note = book_server.root / NOTE
    note.write_bytes(b"---\nname: Alice\n---\n# Alice\n\nNo blank line after the frontmatter.\n")
    before = scene.read_bytes(), note.read_bytes()
    open_home(phone, book_server)
    open_scene(phone)
    phone.locator("#pvEditBtn").tap()
    phone.wait_for_function("document.getElementById('pvEditText').value.length > 100")
    phone.locator("#pvEditSave").tap()
    expect(phone.locator("#pvEditSheet")).to_be_hidden()
    phone.goto(book_server.url("/#/file/" + NOTE.replace("/", "%2F")))
    expect(phone.locator("#pvEditBtn")).to_be_visible()
    phone.locator("#pvEditBtn").tap()
    expect(phone.locator("#pvEditText")).to_have_value("# Alice\n\nNo blank line after the frontmatter.\n")
    phone.locator("#pvEditSave").tap()
    expect(phone.locator("#pvEditSheet")).to_be_hidden()
    assert (scene.read_bytes(), note.read_bytes()) == before


def test_a_draft_survives_a_reload_and_conflicts_with_a_change_on_the_mac(phone: Page, book_server: ProseviewServer):
    scene = book_server.root / "manuscript" / SCENE
    open_home(phone, book_server)
    open_scene(phone)
    phone.locator("#pvEditBtn").tap()
    phone.wait_for_function("document.getElementById('pvEditText').value.length > 100")
    phone.locator("#pvEditText").press("End")
    phone.locator("#pvEditText").type(" Written on the phone.")
    expect(phone.locator("#pvEditStatus")).to_have_text("Draft saved on this phone")

    # Edited on the Mac meanwhile.
    time.sleep(0.05)
    scene.write_text(scene.read_text(encoding="utf-8") + "\nWritten on the Mac.\n", encoding="utf-8")
    os.utime(scene, (time.time() + 5, time.time() + 5))

    phone.reload()
    open_scene(phone)
    phone.locator("#pvEditBtn").tap()
    expect(phone.locator("#pvEditStatus")).to_have_text("Your unsaved draft is back.")
    assert phone.locator("#pvEditText").input_value().endswith(" Written on the phone.")
    phone.locator("#pvEditSave").tap()
    expect(phone.locator("#pvConflictSheet")).to_be_visible()
    assert "Written on the Mac." in scene.read_text(encoding="utf-8")
    phone.get_by_role("button", name="Keep mine").tap()
    expect(phone.locator("#pvEditSheet")).to_be_hidden()
    text = scene.read_text(encoding="utf-8")
    assert "Written on the phone." in text and "Written on the Mac." not in text


@pytest.mark.allow_js_errors("Failed to fetch")
def test_offline_keeps_the_text_and_retry_reconnects_without_a_reload(phone: Page, book_server: ProseviewServer):
    scene = book_server.root / "manuscript" / SCENE
    open_home(phone, book_server)
    open_scene(phone)
    phone.locator("#pvEditBtn").tap()
    phone.wait_for_function("document.getElementById('pvEditText').value.length > 100")
    phone.locator("#pvEditText").press("End")
    phone.locator("#pvEditText").type(" Offline words.")
    baseline = phone.evaluate("pvPhone.state.edit.mtime")
    phone.evaluate("window.__notReloaded = true")

    phone.context.set_offline(True)
    phone.locator("#pvEditSave").tap()
    expect(phone.locator("#pvOfflineBanner")).to_be_visible()
    expect(phone.locator("#pvEditStatus")).to_contain_text("kept on this phone")
    assert phone.locator("#pvEditText").input_value().endswith(" Offline words.")
    assert "Offline words." not in scene.read_text(encoding="utf-8")

    phone.context.set_offline(False)
    phone.locator("#pvOfflineRetry").tap()
    expect(phone.locator("#pvOfflineBanner")).to_be_hidden()
    assert phone.evaluate("window.__notReloaded") is True
    assert phone.locator("#pvEditText").input_value().endswith(" Offline words.")
    assert phone.evaluate("pvPhone.state.edit.mtime") == baseline
    stored = phone.evaluate(
        "JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.startsWith('proseview-phone-draft:'))))"
    )
    assert stored["mtime"] == baseline
    phone.locator("#pvEditSave").tap()
    expect(phone.locator("#pvEditSheet")).to_be_hidden()
    assert "Offline words." in scene.read_text(encoding="utf-8")


def test_ask_opens_the_chat_with_the_agent_tabs_and_return_adds_a_line(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    open_scene(phone)
    phone.locator("#pvAskBtn").tap()
    expect(phone.locator("#discussPanel")).to_be_visible()
    for tab in ("Codex", "Claude", "Agy"):
        expect(phone.locator(f"#utilityTab{tab}")).to_be_visible()
    for tab in ("Analysis", "History", "Beats", "Group"):
        expect(phone.locator(f"#utilityTab{tab}")).to_be_hidden()
    expect(phone.locator("#pvSceneBar")).to_be_hidden()
    box = phone.locator("#discussInput")
    assert box.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 16
    box.fill("First line")
    box.press("Enter")
    box.type("second line")
    assert box.input_value() == "First line\nsecond line"
    assert json.loads(phone.evaluate("JSON.stringify(document.querySelectorAll('#discussLog .discuss-message-user').length)")) == 0


def test_the_home_lists_every_todo_and_opens_its_scene_at_it(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    todos = phone.locator(".pv-todos")
    expect(todos).to_be_visible()
    todos.locator("summary").tap()
    row = todos.locator(".pv-todo-row", has_text="riddle stays unanswered")
    expect(row).to_contain_text("A Mad Tea-Party")
    row.tap()
    expect(phone.locator("html")).to_have_attribute("data-view", "scene")
    expect(phone.locator("#sceneProseHost .pm-annotation-todo", has_text="riddle stays unanswered")).to_be_in_viewport()


def test_cover_hides_the_book_and_a_double_tap_uncovers_it(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    phone.locator("#pvCoverTop").tap()
    expect(phone.locator("#privacyScreen")).to_be_visible()
    screen = phone.locator("#privacyScreen")
    screen.tap(position={"x": 200, "y": 400})
    screen.tap(position={"x": 200, "y": 400})
    expect(screen).to_be_hidden()
    expect(phone.locator("#phoneHome")).to_be_visible()


def test_read_the_book_and_settings_are_trimmed_for_the_phone(phone: Page, book_server: ProseviewServer):
    open_home(phone, book_server)
    phone.locator("#phoneHome").get_by_role("button", name="Read the book").tap()
    expect(phone.locator("#bookWhere")).to_be_visible()
    for hidden in ("#bookViewSwitch", "#bookTitle", "#phoneHome"):
        expect(phone.locator(hidden)).to_be_hidden()
    box = phone.locator("#bookNav .book-nav-btn").first.bounding_box()
    assert box and box["height"] >= 44 and box["width"] >= 44
    phone.locator("#bookBackBtn").tap()
    phone.evaluate("openSettings()")
    expect(phone.locator("#settingsTabGeneral")).to_be_visible()
    expect(phone.locator("#settingsTabAppearance")).to_be_visible()
    for tab in ("Suggestions", "Group", "Beatmap", "Sceneimage", "Discuss"):
        expect(phone.locator(f"#settingsTab{tab}")).to_be_hidden()


def test_read_the_book_hides_todo_and_note_comments(phone: Page, book_server: ProseviewServer):
    scene = book_server.root / "manuscript" / SCENE
    scene.write_text(
        scene.read_text(encoding="utf-8") + "\n<!-- NOTE: hugging the paragraph -->\nRight under the note.\n",
        encoding="utf-8",
    )
    open_home(phone, book_server)
    phone.locator("#phoneHome").get_by_role("button", name="Read the book").tap()
    expect(phone.locator("#bookBody")).to_contain_text("Right under the note.")
    text = phone.locator("#bookBody").inner_text()
    assert "<!--" not in text and "hugging the paragraph" not in text
