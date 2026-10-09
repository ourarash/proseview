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
