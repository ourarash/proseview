"""Browser tests for moving the floating edit bar and the ··· selection pill.

The bar can be dragged by any part of it, not only the status dot. A press
that barely moves stays a click, so its buttons still work, and the place it
was left is used again the next time edit mode opens.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import enter_edit_mode, open_scene, select_prose  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def _drag(page: Page, selector: str, dx: float, dy: float) -> None:
    box = page.locator(selector).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx / 2, y + dy / 2, steps=4)
    page.mouse.move(x + dx, y + dy, steps=4)
    page.mouse.up()


def test_edit_bar_drags_from_a_button_without_pressing_it(page: Page, server: ProseviewServer):
    open_scene(page, server)
    enter_edit_mode(page)
    before = page.locator("#sceneEditBar").bounding_box()

    # Dragging from the Cancel button moves the bar and does not cancel.
    _drag(page, ".scene-edit-cancel", -200, -150)
    after = page.locator("#sceneEditBar").bounding_box()
    assert abs(after["x"] - (before["x"] - 200)) < 3
    assert abs(after["y"] - (before["y"] - 150)) < 3
    assert page.evaluate("window._pmEditMode") is True

    # A plain click on the same button still cancels.
    page.locator(".scene-edit-cancel").click()
    page.wait_for_function("() => !window._pmEditMode")

    # Next time edit mode opens, the bar is where it was left.
    enter_edit_mode(page)
    again = page.locator("#sceneEditBar").bounding_box()
    assert abs(again["x"] - after["x"]) < 3
    assert abs(again["y"] - after["y"]) < 3


def test_edit_bar_position_survives_a_reload_and_stays_on_screen(page: Page, server: ProseviewServer):
    open_scene(page, server)
    page.evaluate(
        "localStorage.setItem('proseview-edit-bar-pos', JSON.stringify({left: 99999, top: 99999}))"
    )
    page.reload()
    open_scene(page, server)
    enter_edit_mode(page)
    box = page.locator("#sceneEditBar").bounding_box()
    view = page.viewport_size
    assert box["x"] + box["width"] <= view["width"] + 1
    assert box["y"] + box["height"] <= view["height"] + 1

    # A click on Bold still formats, the drag listener lets it through.
    page.locator(".scene-edit-format-btn[aria-label='Bold']").click()
    assert page.evaluate("window._pmEditMode") is True


def _select_word(page: Page, word: str) -> dict:
    """Select *word* in the editor with the mouse, as a writer would."""
    box = page.evaluate(
        """(word) => {
            const host = document.querySelector('#sceneProseHost .ProseMirror');
            const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const i = node.textContent.indexOf(word);
                if (i < 0) continue;
                node.parentElement.scrollIntoView({block: 'center'});
                const range = document.createRange();
                range.setStart(node, i);
                range.setEnd(node, i + word.length);
                const r = range.getBoundingClientRect();
                return {x0: r.left + 1, x1: r.right - 1, y: r.top + r.height / 2, top: r.top, bottom: r.bottom};
            }
            throw new Error('word not found: ' + word);
        }""",
        word,
    )
    page.mouse.move(box["x0"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x1"], box["y"], steps=5)
    page.mouse.up()
    return box


def test_edit_bar_sits_above_a_selection_and_goes_back(page: Page, server: ProseviewServer):
    open_scene(page, server)
    enter_edit_mode(page)
    home = page.locator("#sceneEditBar").bounding_box()
    word = page.evaluate(
        "() => document.querySelector('#sceneProseHost .ProseMirror p').textContent.trim().split(/\\s+/)[1]"
    )

    word_box = _select_word(page, word)
    page.wait_for_timeout(100)
    bar = page.locator("#sceneEditBar").bounding_box()
    assert bar["y"] + bar["height"] <= word_box["top"]
    assert 15 < word_box["top"] - (bar["y"] + bar["height"]) < 30
    centre = (word_box["x0"] + word_box["x1"]) / 2
    assert abs(bar["x"] + bar["width"] / 2 - centre) < 3

    # Bold works from there and the bar stays with the selection.
    page.locator(".scene-edit-format-btn[aria-label='Bold']").click()
    assert page.locator("#sceneProseHost .ProseMirror strong").count() >= 1

    # Clearing the selection puts the bar back where it was.
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(100)
    back = page.locator("#sceneEditBar").bounding_box()
    assert abs(back["y"] - home["y"]) < 3
    assert abs(back["x"] - home["x"]) < 3


def test_selection_pill_drags_from_its_button_and_still_opens(page: Page, server: ProseviewServer):
    open_scene(page, server)
    needle = page.evaluate(
        "() => document.querySelector('#sceneProseHost .ProseMirror p').textContent.trim().split(/\\s+/).slice(1, 3).join(' ')"
    )
    select_prose(page, needle)
    page.wait_for_selector("#selectionPillBtn", state="visible")
    before = page.locator("#selectionPillBtn").bounding_box()

    # Dragging by the ··· button moves the pill and leaves the menu shut.
    _drag(page, "#selectionPillBtn", 120, 80)
    after = page.locator("#selectionPillBtn").bounding_box()
    assert abs(after["x"] - (before["x"] + 120)) < 3
    assert abs(after["y"] - (before["y"] + 80)) < 3
    assert page.locator("#selectionPillMenu").is_hidden()

    # A plain click still opens the menu.
    page.click("#selectionPillBtn")
    page.wait_for_selector("#selectionPillMenu", state="visible")
