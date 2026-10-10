"""Browser tests for editing story-bible and other notes in the file view.

Opens the page straight at a note's address (the dashboard renders it while
the page is still loading, which once stopped the page's script), edits a
character sheet in the rich editor and a note with a table as plain text,
saves both, and checks the files on disk.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import base64
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

#: A 1x1 PNG.
PIXEL_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

#: Obsidian-style Markdown the editor has no syntax for. A save must leave it
#: as written rather than escape or reformat it.
VAULT_BODY = """Jack met [[Jack Mercer]] at the docks.

> [!note] Continuity
> He limps on the left side.

![[map-of-the-harbor]]

- rope
- _salt_

It was ==important==, and _meant_.
"""
VAULT_SCENE = "---\ntitle: The Vault\n---\n\n" + VAULT_BODY
#: A table inside a quote has no block of its own, so the note opens as text.
QUOTED_TABLE = "# Quoted\n\n> | Who | Knows |\n> | --- | --- |\n> | Alice | the Cat |\n"


@pytest.fixture
def notes_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    (root / "story-bible" / "relationships.md").write_text(
        "---\ntitle: Who knows whom\n---\n\n# Relationships\n\n| Who | Knows |\n| --- | --- |\n| Alice | the Cat |\n",
        encoding="utf-8",
    )
    (root / "story-bible" / "quoted.md").write_text(QUOTED_TABLE, encoding="utf-8")
    (root / "manuscript" / "ch01" / "04-vault.md").write_text(VAULT_SCENE, encoding="utf-8")
    (root / "story-bible" / "vault.md").write_text("---\ntitle: Vault\n---\n\n" + VAULT_BODY, encoding="utf-8")
    chapter = root / "manuscript" / "ch01"
    (chapter / "map.png").write_bytes(base64.b64decode(PIXEL_PNG))
    (chapter / "loose-notes.txt").write_text("Check the tide tables.\n", encoding="utf-8")
    (root / "story-bible" / "harbor.md").write_text(
        '# Harbor\n\n<img src="/repo-asset/manuscript/ch01/map.png" alt="The harbor map">\n', encoding="utf-8",
    )
    (chapter / "draft.docx").write_bytes(b"PK\x03\x04\x14\x00\xff\xfe\x00\x00")
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


def test_a_note_with_a_table_keeps_the_table_and_edits_the_rest(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "relationships.md"
    page.goto(notes_server.url("/#/file/story-bible%2Frelationships.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    editor = page.locator(".file-edit-host .ProseMirror")
    expect(editor.locator(".pm-raw-block table")).to_contain_text("the Cat")
    editor.locator("h1").click()
    page.keyboard.press("End")
    page.keyboard.type(" so far")
    page.keyboard.press("ControlOrMeta+s")

    expect(page.locator("#fileEditBar")).to_be_hidden()
    assert note.read_text(encoding="utf-8") == (
        "---\ntitle: Who knows whom\n---\n\n# Relationships so far\n\n| Who | Knows |\n| --- | --- |\n"
        "| Alice | the Cat |\n"
    )


def test_a_note_with_a_table_in_a_quote_is_edited_as_plain_markdown(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "quoted.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fquoted.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    expect(page.locator(".file-edit-note")).to_contain_text("because it has a table inside a list or quote")
    source = page.get_by_label("Markdown of story-bible/quoted.md")
    source.fill(source.input_value() + "> | Alice | the Hatter |\n")
    source.press("ControlOrMeta+s")

    expect(page.locator("#fileEditBar")).to_be_hidden()
    assert note.read_text(encoding="utf-8") == QUOTED_TABLE + "> | Alice | the Hatter |\n"


@pytest.mark.allow_js_errors("409")
def test_a_note_changed_elsewhere_is_not_overwritten(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "quoted.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fquoted.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    source = page.get_by_label("Markdown of story-bible/quoted.md")
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


def _type_at_end_of(page: Page, host: str, needle: str, text: str) -> None:
    page.locator(host + " p", has_text=needle).click()
    page.keyboard.press("End")
    page.keyboard.type(text)


def test_saving_a_scene_leaves_untouched_vault_markdown_as_written(page: Page, notes_server: ProseviewServer):
    scene = notes_server.root / "manuscript" / "ch01" / "04-vault.md"
    page.goto(notes_server.url("/#/scene/ch01%2F04-vault.md"))
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.click("#sceneEditBtn")
    page.wait_for_function("window._pmEditMode === true")

    # A change typed and taken back still saves: the file must not move.
    _type_at_end_of(page, "#sceneProseHost", "It was", "x")
    page.keyboard.press("Backspace")
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("window._pmEditMode === false")
    assert scene.read_text(encoding="utf-8") == VAULT_SCENE

    # A fresh page, so the save's own reload cannot land mid-edit.
    page.reload()
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.click("#sceneEditBtn")
    page.wait_for_function("window._pmEditMode === true")
    _type_at_end_of(page, "#sceneProseHost", "It was", " Truly.")
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("window._pmEditMode === false")
    assert scene.read_text(encoding="utf-8") == VAULT_SCENE.replace(
        "It was ==important==, and _meant_.", "It was ==important==, and *meant*. Truly.")


def test_saving_a_note_leaves_untouched_vault_markdown_as_written(page: Page, notes_server: ProseviewServer):
    note = notes_server.root / "story-bible" / "vault.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fvault.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    expect(page.locator(".file-edit-host .ProseMirror")).to_be_visible()
    _type_at_end_of(page, ".file-edit-host", "Jack met", " He waved.")
    page.get_by_role("button", name="Save", exact=True).click()

    expect(page.locator("#fileEditBar")).to_be_hidden()
    assert note.read_text(encoding="utf-8") == "---\ntitle: Vault\n---\n\n" + VAULT_BODY.replace(
        "Jack met [[Jack Mercer]] at the docks.", "Jack met \\[\\[Jack Mercer\\]\\] at the docks. He waved.")


def test_images_and_other_files_beside_the_scenes_can_be_opened(page: Page, notes_server: ProseviewServer):
    page.goto(notes_server.url("/#/file/manuscript%2Fch01%2Fmap.png"))
    image = page.locator("#filePreviewBody .repo-image img")
    expect(image).to_be_visible()
    page.wait_for_function("() => document.querySelector('#filePreviewBody .repo-image img').naturalWidth === 1")

    page.goto(notes_server.url("/#/file/manuscript%2Fch01%2Floose-notes.txt"))
    expect(page.locator("#filePreviewBody pre")).to_have_text("Check the tide tables.\n")
    expect(page.get_by_role("button", name="Edit", exact=True)).to_be_hidden()

    page.goto(notes_server.url("/#/file/manuscript%2Fch01%2Fdraft.docx"))
    expect(page.locator("#filePreviewBody .repo-warn")).to_contain_text("cannot open draft.docx")
    # E on a file that cannot be edited says so, quietly.
    page.locator("#filePreviewBody").click()
    page.keyboard.press("e")
    expect(page.locator("#sidebarFileToast")).to_have_text("Only Markdown files can be edited in Proseview.")
    expect(page.locator("#fileEditBar")).to_be_hidden()

    # They are listed beside the scenes, and none of them became a scene.
    page.goto(notes_server.url("/"))
    tree = page.get_by_role("tree", name="Repository files")
    expect(tree.locator('.file-link[data-path="manuscript/ch01/map.png"]')).to_be_attached()
    assert page.evaluate("Object.keys(meta).every(p => p.endsWith('.md'))")


def test_cmd_s_closes_a_note_and_e_picks_up_where_it_stopped(page: Page, notes_server: ProseviewServer):
    sheet = notes_server.root / "story-bible" / "characters" / "alice.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fcharacters%2Falice.md"))
    page.get_by_role("button", name="Edit", exact=True).click()
    editor = page.locator(".file-edit-host .ProseMirror")
    editor.locator("p").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" She is seven.")
    page.keyboard.press("ControlOrMeta+s")
    expect(page.locator("#fileEditBar")).to_be_hidden()

    page.locator("#filePreviewBody").click()
    page.keyboard.press("e")
    expect(editor).to_be_visible()
    page.keyboard.type(" And a half.")
    page.keyboard.press("ControlOrMeta+s")
    expect(page.locator("#fileEditBar")).to_be_hidden()
    # The paragraph keeps its wrapping, so the words may break across lines.
    assert "She is seven. And a half." in " ".join(sheet.read_text(encoding="utf-8").split())


def test_an_image_written_as_a_repo_asset_url_shows_in_the_file_view(page: Page, notes_server: ProseviewServer):
    """The URL was prefixed a second time, /repo-asset/repo-asset/..., and 404ed."""
    page.goto(notes_server.url("/#/file/story-bible%2Fharbor.md"))
    image = page.locator("#filePreviewBody img[alt='The harbor map']")
    expect(image).to_have_attribute("src", "/repo-asset/manuscript/ch01/map.png")
    page.wait_for_function("() => document.querySelector(\"#filePreviewBody img[alt='The harbor map']\").naturalWidth === 1")


SCENE_ONE = "ch01/01-down-the-rabbit-hole.md"


@pytest.mark.allow_http_errors("/save-scene")
@pytest.mark.allow_js_errors("400")
def test_a_scene_shows_its_frontmatter_and_edits_it(page: Page, notes_server: ProseviewServer):
    scene = notes_server.root / "manuscript" / SCENE_ONE
    before = scene.read_text(encoding="utf-8")
    page.goto(notes_server.url("/#/scene/ch01%2F01-down-the-rabbit-hole.md"))
    block = page.locator("#sceneFrontmatter .fm-block")
    expect(block).to_contain_text("title: Down the Rabbit-Hole")
    expect(block.locator(".fm-key").first).to_have_text("title")

    page.click("#sceneEditBtn")
    page.wait_for_function("window._pmEditMode === true")
    box = page.get_by_label("Frontmatter (YAML)")
    # Not YAML: nothing is written, and the box says where.
    box.fill(box.input_value() + "\ncast: [Alice, the Rabbit")
    page.keyboard.press("ControlOrMeta+s")
    expect(page.locator("#sceneFrontmatter .fm-error")).to_contain_text("not valid YAML")
    assert scene.read_text(encoding="utf-8") == before

    box.fill(box.input_value().replace("status: drafted", "status: revised").replace("\ncast: [Alice, the Rabbit", ""))
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("window._pmEditMode === false")
    after = scene.read_text(encoding="utf-8")
    assert after == before.replace("status: drafted", "status: revised")


def test_a_files_frontmatter_shows_as_yaml_and_edits(page: Page, notes_server: ProseviewServer):
    sheet = notes_server.root / "story-bible" / "characters" / "alice.md"
    page.goto(notes_server.url("/#/file/story-bible%2Fcharacters%2Falice.md"))
    expect(page.locator("#filePreviewBody .fm-block")).to_contain_text("role: protagonist")
    # The closing --- no longer turns the frontmatter into a heading.
    expect(page.locator("#filePreviewBody h2", has_text="name:")).to_have_count(0)

    page.get_by_role("button", name="Edit", exact=True).click()
    box = page.get_by_label("Frontmatter (YAML)")
    box.fill(box.input_value().replace("role: protagonist", "role: heroine"))
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#fileEditBar")).to_be_hidden()
    assert sheet.read_text(encoding="utf-8").startswith("---\nname: Alice\nrole: heroine\n---\n")
    expect(page.locator("#filePreviewBody .fm-block")).to_contain_text("role: heroine")
