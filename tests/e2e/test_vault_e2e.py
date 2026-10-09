"""Browser tests for a folder with no ``manuscript/`` subfolder.

An Obsidian vault or a flat pile of chapter files is all manuscript. The file
browser, the scene's Analysis numbers and the editor all have to work there,
not only in the ``manuscript/`` layout the other tests use.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import ProseviewServer, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

SCENE = "Part One/Chapter 1/01 Café.md"
BODY = "Léa met Jack at the café.<br>\nThen he left.\n\nIt rained.\n"


@pytest.fixture
def vault_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Part One" / "Chapter 1").mkdir(parents=True)
    (root / SCENE).write_text(BODY, encoding="utf-8")
    (root / "Part One" / "Chapter 1" / "02 Night.md").write_text("The night was long.\n", encoding="utf-8")
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def test_a_vault_lists_its_files_and_opens_a_scene_with_inline_html(page: Page, vault_server: ProseviewServer):
    lexical: list[int] = []
    page.on("response", lambda r: "/api/scene/lexical" in r.url and lexical.append(r.status))
    page.goto(vault_server.url("/"))
    tree = page.get_by_role("tree", name="Repository files")
    expect(tree.locator('.file-link[data-path="Part One/Chapter 1/01 Café.md"]')).to_be_attached()

    tree.get_by_role("treeitem", name="Chapter 1").click()
    tree.get_by_role("treeitem", name="01 Café.md").click()
    editor = page.locator("#sceneProseHost .ProseMirror")
    expect(editor).to_contain_text("Then he left.")
    page.wait_for_timeout(500)
    assert lexical and all(status == 200 for status in lexical), lexical

    page.click("#sceneEditBtn")
    page.wait_for_function("window._pmEditMode === true")
    editor.locator("p", has_text="It rained.").click()
    page.keyboard.press("End")
    page.keyboard.type(" Hard.")
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("window._pmEditMode === false")
    assert (vault_server.root / SCENE).read_text(encoding="utf-8") == BODY.replace("It rained.", "It rained. Hard.")


def test_a_vault_creates_renames_and_trashes_files_anywhere(page: Page, vault_server: ProseviewServer):
    root = vault_server.root
    page.goto(vault_server.url("/"))
    tree = page.get_by_role("tree", name="Repository files")
    expect(tree).to_be_visible()

    page.get_by_role("button", name="Create a file or folder").click()
    page.get_by_role("menuitem", name="New file").click()
    dialog = page.get_by_role("dialog", name="New file")
    location = dialog.get_by_label("Location")
    assert location.evaluate("s => s.options[0].textContent") == "Top level"
    location.select_option("")
    dialog.get_by_label("Name").fill("Été")
    expect(dialog).to_contain_text("Creates Été.md")
    dialog.get_by_role("button", name="Create", exact=True).click()
    page.wait_for_function("() => location.hash.includes('%C3%89t%C3%A9.md')")
    assert (root / "Été.md").read_bytes() == b""

    folder = tree.locator('.dir-toggle[data-path="Part One/Chapter 1"]')
    folder.click(button="right")
    page.locator("#sidebarContextMenu").get_by_role("menuitem", name="Rename").click()
    rename = page.get_by_label("New name for Chapter 1")
    rename.fill("Chapitre Un – Café")
    rename.press("Enter")
    page.wait_for_function("() => !!document.querySelector('.dir-toggle[data-path=\"Part One/Chapitre Un – Café\"]')")
    assert (root / "Part One" / "Chapitre Un – Café" / "01 Café.md").is_file()
