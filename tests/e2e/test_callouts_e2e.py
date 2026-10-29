"""Browser tests for callouts (``> [!letter] Title``) in the scene view.

A callout reads as a framed box with its title and its type's colour for the
current theme, apart from the TODO and note comments beside it; in edit mode
its type and title can be changed, the toolbar makes one, and a save writes
the Markdown back with only the edited lines changed.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import REPO_ROOT, ProseviewServer, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"
SCENE_REL = "ch01%2F04-letter.md"
BODY = """She found the letter folded inside the atlas.

> [!letter] A letter, undated
> Mara, if you are reading this,
> the boat has gone without me.
>
> — T.

<!-- TODO: check the boat's name -->

> Every harbour keeps one ghost.

> [!NOTE]
> An untitled box.

Her phone buzzed twice on the table.
"""
SCENE = "---\ntitle: The Letter\n---\n\n" + BODY
COLOURS = """
callouts:
  letter:
    background:
      graphite-light: "#f7f1e6"
      graphite-dark: "#2e2a24"
"""


@pytest.fixture
def callout_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    with (root / ".proseview.yaml").open("a", encoding="utf-8") as config:
        config.write(COLOURS)
    (root / "manuscript" / "ch01" / "04-letter.md").write_text(SCENE, encoding="utf-8")
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def _open(page: Page, server: ProseviewServer, theme: str = "graphite-light") -> None:
    page.goto(server.url(f"/#/scene/{SCENE_REL}"), wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.evaluate("(theme) => selectTheme(theme)", theme)
    page.wait_for_selector("#sceneProseHost .ProseMirror .pv-callout")


def _scene(server: ProseviewServer) -> Path:
    return server.root / "manuscript" / "ch01" / "04-letter.md"


@pytest.mark.parametrize(("theme", "colour", "note"), [
    ("graphite-light", "rgb(247, 241, 230)", "rgb(242, 242, 240)"),
    ("graphite-dark", "rgb(46, 42, 36)", "rgb(34, 43, 48)"),
])
def test_a_callout_reads_as_a_box_in_its_themes_colour(
    page: Page, callout_server: ProseviewServer, theme: str, colour: str, note: str,
):
    _open(page, callout_server, theme)
    prose = page.locator("#sceneProseHost .ProseMirror")
    letter = prose.locator('.pv-callout[data-callout="letter"]')
    expect(letter.locator(".pv-callout-title")).to_have_text("A letter, undated")
    expect(letter).to_contain_text("Mara, if you are reading this, the boat has gone without me.")
    assert letter.evaluate("el => getComputedStyle(el).backgroundColor") == colour
    # GitHub's types bring the theme's own colour, with nothing in the config.
    untitled = prose.locator('.pv-callout[data-callout="note"]')
    assert untitled.evaluate("el => getComputedStyle(el).backgroundColor") == note
    # No title: nothing printed for the type, and the title line takes no room.
    expect(untitled.locator(".pv-callout-title")).to_be_hidden()
    expect(untitled.locator(".pv-callout-type")).to_be_hidden()
    expect(untitled.locator("p:not(.pv-callout-title)")).to_have_text("An untitled box.")
    # The quotation and the TODO are still themselves, not boxes.
    expect(prose.locator("blockquote p")).to_have_text("Every harbour keeps one ghost.")
    expect(prose.locator(".pm-annotation-todo")).to_have_count(1)
    assert "[!" not in prose.inner_text()


def test_editing_a_callout_saves_only_the_changed_lines(page: Page, callout_server: ProseviewServer):
    _open(page, callout_server)
    page.click("#sceneEditBtn")
    page.wait_for_function("() => window._pmEditMode === true")
    prose = page.locator("#sceneProseHost .ProseMirror")
    letter = prose.locator('.pv-callout[data-callout="letter"]')

    letter.locator("p", has_text="— T.").click()
    page.keyboard.press("End")
    page.keyboard.type(" Burn this.")
    kind = letter.get_by_label("Callout type")
    expect(kind).to_have_value("letter")
    # Focused, the field empties so the browser offers every type, not
    # just those matching "letter"; leaving it empty keeps the type.
    kind.focus()
    expect(kind).to_have_value("")
    expect(kind).to_have_attribute("placeholder", "letter")
    assert page.locator("#calloutTypeOptions option").evaluate_all("els => els.map(e => e.value)") == [
        "note", "tip", "important", "warning", "caution", "letter",
    ]
    kind.blur()
    expect(kind).to_have_value("letter")
    kind.fill("note-to-self")
    kind.press("Enter")
    expect(prose.locator('.pv-callout[data-callout="note-to-self"]')).to_have_count(1)
    page.keyboard.press("ControlOrMeta+s")

    page.wait_for_function("() => window._pmEditMode === false")
    assert _scene(callout_server).read_text(encoding="utf-8") == SCENE.replace(
        "[!letter]", "[!note-to-self]").replace("> — T.", "> — T. Burn this.")


def test_the_toolbar_wraps_a_paragraph_in_a_callout_with_a_title(page: Page, callout_server: ProseviewServer):
    _open(page, callout_server)
    page.click("#sceneEditBtn")
    page.wait_for_function("() => window._pmEditMode === true")
    prose = page.locator("#sceneProseHost .ProseMirror")

    prose.locator("p", has_text="Her phone buzzed").click()
    page.get_by_role("button", name="Callout", exact=True).click()
    box = prose.locator(".pv-callout").last
    expect(box.locator(".pv-callout-title")).to_have_class("pv-callout-title is-empty")
    page.keyboard.type("Jonah, 11:42 pm")
    page.keyboard.press("ControlOrMeta+s")

    page.wait_for_function("() => window._pmEditMode === false")
    assert _scene(callout_server).read_text(encoding="utf-8") == SCENE.replace(
        "Her phone buzzed twice on the table.\n", "> [!note] Jonah, 11:42 pm\n> Her phone buzzed twice on the table.\n")
