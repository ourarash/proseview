"""Browser tests for a folder with no ``manuscript/`` subfolder.

Without one, the folder opens as plain Markdown until the writer says where
the book is. Named as the whole folder (``manuscript_path: .``), an Obsidian
vault or a flat pile of chapter files is all manuscript: the file browser,
the scene's Analysis numbers and the editor all have to work there, not only
in the ``manuscript/`` layout the other tests use.

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

SCENE = "Chapter 1/01 Café.md"
BODY = "Léa met Jack at the café.<br>\nThen he left.\n\nIt rained.\n"


@pytest.fixture
def vault_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Chapter 1").mkdir(parents=True)
    (root / SCENE).write_text(BODY, encoding="utf-8")
    (root / "Chapter 1" / "02 Night.md").write_text("The night was long.\n", encoding="utf-8")
    (root / ".proseview.yaml").write_text("manuscript_path: .\n", encoding="utf-8")
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
    expect(tree.locator('.file-link[data-path="Chapter 1/01 Café.md"]')).to_be_attached()

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

    folder = tree.locator('.dir-toggle[data-path="Chapter 1"]')
    folder.click(button="right")
    page.locator("#sidebarContextMenu").get_by_role("menuitem", name="Rename").click()
    rename = page.get_by_label("New name for Chapter 1")
    rename.fill("Chapitre Un – Café")
    rename.press("Enter")
    page.wait_for_function("() => !!document.querySelector('.dir-toggle[data-path=\"Chapitre Un – Café\"]')")
    assert (root / "Chapitre Un – Café" / "01 Café.md").is_file()


@pytest.fixture
def server_without_agents(
    tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ProseviewServer]:
    """No codex or claude anywhere on PATH, as on a writer's fresh machine."""
    root = tmp_path / "flat"
    root.mkdir()
    (root / "chapter-01.md").write_text("It was a dark night.\n", encoding="utf-8")
    (root / ".proseview.yaml").write_text("manuscript_path: .\n", encoding="utf-8")
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    server = _start_server(root, empty_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


@pytest.mark.allow_http_errors("/api/discuss/")
@pytest.mark.allow_js_errors("503", "Service Unavailable")
@pytest.mark.parametrize("agent,command", [("codex", "npm install -g @openai/codex"), ("claude", "claude")])
def test_a_tab_whose_agent_is_not_installed_says_how_to_install_it(
    page: Page, server_without_agents: ProseviewServer, agent: str, command: str
):
    page.goto(server_without_agents.url("/#/scene/chapter-01.md"))
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.evaluate("agent => showDiscussAgentTab(agent)", agent)
    state = page.locator("#discussLog .discuss-empty-state")
    expect(state).to_contain_text("is not connected")
    expect(state.locator(".discuss-empty-steps")).to_contain_text(command)
    expect(page.locator("#discussComposerArea")).to_be_hidden()
    expect(page.locator(".discuss-story-action")).to_have_count(0)



@pytest.fixture
def viewer_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    """A folder with no manuscript folder and no configuration."""
    root = tmp_path / "drafts"
    (root / "Book").mkdir(parents=True)
    (root / "Book" / "ch01").mkdir()
    (root / "Book" / "ch01" / "01.md").write_text("It rained all week.\n", encoding="utf-8")
    (root / "ideas.md").write_text("An idea.\n", encoding="utf-8")
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def test_without_a_manuscript_folder_the_folder_opens_as_markdown(page: Page, viewer_server: ProseviewServer):
    page.goto(viewer_server.url("/"))
    setup = page.get_by_role("region", name="This folder is open as Markdown files")
    expect(setup).to_be_visible()
    # The book features wait; nothing pretends there is a book.
    expect(page.locator(".tab-nav")).to_be_hidden()
    expect(page.locator("#exportOpenBtn")).to_be_hidden()

    # Files still open and edit.
    tree = page.get_by_role("tree", name="Repository files")
    tree.locator('.file-link[data-path="ideas.md"]').click()
    expect(page.locator("#filePreviewBody")).to_contain_text("An idea.")
    expect(page.get_by_role("button", name="Edit", exact=True)).to_be_visible()

    # One choice sets the book up.
    page.goto(viewer_server.url("/"))
    page.get_by_role("button", name="Choose manuscript folder…").click()
    chooser = page.get_by_role("dialog", name="Where is the book?")
    chooser.get_by_label("Book/").check()
    chooser.get_by_role("button", name="Use this folder").click()
    expect(page.locator(".tab-nav")).to_be_visible()
    expect(setup).to_have_count(0)
    assert "manuscript_path: Book/" in (viewer_server.root / ".proseview.yaml").read_text(encoding="utf-8")
    assert page.evaluate("paths") == ["ch01/01.md"]
