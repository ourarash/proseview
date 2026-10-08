"""Browser tests for editing story-bible and other notes in the file view.

Opens the page straight at a note's address (the dashboard renders it while
the page is still loading, which once stopped the page's script), edits a
character sheet in the rich editor and a note with a table as plain text,
saves both, and checks the files on disk.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import REPO_ROOT, ProseviewServer, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"


@pytest.fixture
def notes_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    (root / "story-bible" / "relationships.md").write_text(
        "---\ntitle: Who knows whom\n---\n\n# Relationships\n\n| Who | Knows |\n| --- | --- |\n| Alice | the Cat |\n",
        encoding="utf-8",
    )
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def test_edit_a_character_sheet_and_save_it(page: Page, notes_server: ProseviewServer):
    sheet = notes_server.root / "story-bible" / "characters" / "alice.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fcharacters%2Falice.md"))
    edit = page.get_by_role("button", name="Edit", exact=True)
    expect(edit).to_be_visible()
    # The rest of the page still works after rendering a file during load.
    expect(page.locator("#exportOpenBtn")).to_be_attached()

    edit.click()
    editor = page.locator(".file-edit-host .ProseMirror")
    expect(editor).to_be_visible()
    editor.locator("p").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" She keeps a diary.")
    expect(page.locator("#fileEditStatus")).to_have_text("Unsaved changes")
    page.get_by_role("button", name="Save", exact=True).click()

    expect(page.locator("#fileEditBar")).to_be_hidden()
    expect(page.locator("#filePreviewBody")).to_contain_text("She keeps a diary.")
    text = sheet.read_text(encoding="utf-8")
    assert text.startswith("---\nname: Alice\nrole: protagonist\n---\n") and "She keeps a diary." in text


def test_a_note_with_a_table_is_edited_as_plain_markdown(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "relationships.md"
    page.goto(notes_server.url("/#/file/story-bible%2Frelationships.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    expect(page.locator(".file-edit-note")).to_contain_text("because it has a table")
    source = page.get_by_label("Markdown of story-bible/relationships.md")
    source.fill(source.input_value() + "| Alice | the Hatter |\n")
    source.press("ControlOrMeta+s")

    expect(page.locator("#fileEditBar")).to_be_hidden()
    assert note.read_text(encoding="utf-8") == (
        "---\ntitle: Who knows whom\n---\n\n# Relationships\n\n| Who | Knows |\n| --- | --- |\n"
        "| Alice | the Cat |\n| Alice | the Hatter |\n"
    )


@pytest.mark.allow_js_errors("409")
def test_a_note_changed_elsewhere_is_not_overwritten(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "relationships.md"
    page.goto(notes_server.url("/#/file/story-bible%2Frelationships.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    source = page.get_by_label("Markdown of story-bible/relationships.md")
    expect(source).to_be_visible()  # the editor has read the file
    note.write_text(note.read_text(encoding="utf-8") + "\nEdited elsewhere.\n", encoding="utf-8")
    later = note.stat().st_mtime + 5
    os.utime(note, (later, later))

    source.fill("mine")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#fileEditStatus")).to_have_text("This file changed on disk since you opened it.")
    assert "Edited elsewhere." in note.read_text(encoding="utf-8")
    page.get_by_role("button", name="Discard mine and reload").click()
    expect(page.locator("#filePreviewBody")).to_contain_text("Edited elsewhere.")


def test_e_opens_the_editor_on_a_note_and_on_a_scene(page: Page, notes_server: ProseviewServer):
    page.goto(notes_server.url("/#/file/story-bible%2Fcharacters%2Falice.md"))
    expect(page.get_by_role("button", name="Edit", exact=True)).to_be_visible()
    page.locator("#filePreviewBody").click()
    page.keyboard.press("e")
    editor = page.locator(".file-edit-host .ProseMirror")
    expect(editor).to_be_visible()
    # Typing an "e" in the editor is just a letter.
    editor.locator("p").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" e")
    expect(editor).to_contain_text(" e")
    page.once("dialog", lambda dialog: dialog.accept())
    page.keyboard.press("Escape")
    expect(page.locator("#fileEditBar")).to_be_hidden()

    page.goto(notes_server.url("/#/scene/ch01%2F01-down-the-rabbit-hole.md"))
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.locator("#sceneProseHost").click()
    page.keyboard.press("e")
    page.wait_for_function("window._pmEditMode === true")
