"""Browser tests for reading the whole book in one scroll.

Opens the book from the dashboard, checks it is every scene in book order
under its chapter headings, that the address follows the scene being read,
and that Edit opens that scene and leaving it comes back to the book at the
scene the writer ended on, with the edit in the text.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import REPO_ROOT, ProseviewServer, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"
FIRST = "ch01/01-down-the-rabbit-hole.md"


@pytest.fixture
def book_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def _wait_until(predicate, timeout: float = 10.0, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(message or f"condition not met within {timeout}s")


def test_the_book_is_every_scene_in_order_under_its_chapters(page: Page, book_server: ProseviewServer):
    page.goto(book_server.url("/"), wait_until="load")
    page.locator("#bookOpenBtn").click()

    expect(page.locator("#book-panel")).to_be_visible()
    order = page.evaluate("paths")
    assert page.locator(".book-scene").evaluate_all("els => els.map(e => e.dataset.path)") == order
    headings = page.locator(".book-chapter-title")
    expect(headings).to_have_count(12)
    expect(headings.first).to_have_text("I. Down the Rabbit-Hole")
    expect(page.locator("#bookWhere")).to_contain_text("I. Down the Rabbit-Hole · Down the Rabbit-Hole · 0%")
    # The frontmatter stays out of the reading.
    expect(page.locator("#bookBody")).not_to_contain_text("status: drafted")

    # The address follows the scene being read, so a reload reopens there.
    page.mouse.wheel(0, 12000)
    page.wait_for_function(f"() => location.hash.startsWith('#/book/') && !location.hash.endsWith({FIRST.replace('/', '%2F')!r})")
    reading = page.evaluate("bookCurrentScene()")
    page.reload(wait_until="load")
    expect(page.locator("#book-panel")).to_be_visible()
    assert page.evaluate("bookCurrentScene()") == reading

    page.get_by_role("button", name="← Overview").click()
    expect(page.locator("#book-panel")).to_be_hidden()
    expect(page.locator("#sceneTable")).to_be_visible()


def test_edit_from_the_book_and_come_back_to_the_same_scene(page: Page, book_server: ProseviewServer):
    scene = "ch02/01-curiouser-and-curiouser.md"
    path = book_server.root / "manuscript" / scene
    page.goto(book_server.url("/#/book/" + scene.replace("/", "%2F")), wait_until="load")
    page.wait_for_function("() => !!window._PM")
    expect(page.locator("#bookWhere")).to_contain_text("Curiouser and Curiouser")

    page.keyboard.press("e")
    page.wait_for_function("() => window._pmEditMode === true")
    assert page.evaluate("paths[curIdx]") == scene
    page.evaluate(
        """() => {
            const para = document.querySelector('#sceneProseHost .ProseMirror p');
            const range = document.createRange();
            range.selectNodeContents(para);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }"""
    )
    page.keyboard.type(" The kettle ticked.")
    page.keyboard.press("ControlOrMeta+s")
    _wait_until(lambda: "The kettle ticked." in path.read_text(encoding="utf-8"), message="the save did not reach the file")
    page.wait_for_function("() => window._pmEditMode === false")

    page.get_by_role("button", name="Close scene and return to dashboard").first.click()
    expect(page.locator("#book-panel")).to_be_visible()
    page.wait_for_function(f"() => bookCurrentScene() === {scene!r}")
    expect(page.locator(f'.book-scene[data-path="{scene}"]')).to_contain_text("The kettle ticked.")


def test_read_the_book_from_a_scene(page: Page, book_server: ProseviewServer):
    scene = "ch03/01-a-queer-looking-party.md"
    page.goto(book_server.url("/#/scene/" + scene.replace("/", "%2F")), wait_until="load")
    page.locator("#sceneMoreBtn").click()
    page.locator("#modalReadBookBtn").click()
    expect(page.locator("#book-panel")).to_be_visible()
    page.wait_for_function(f"() => bookCurrentScene() === {scene!r}")
    # Leaving the book from here goes to the dashboard, not back to the scene.
    page.get_by_role("button", name="← Overview").click()
    expect(page.locator("#sceneTable")).to_be_visible()
