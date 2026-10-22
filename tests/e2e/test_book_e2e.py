"""Browser tests for reading the whole book in one scroll.

Opens the book from the dashboard, checks it is every scene in book order
under its chapter headings, that the address follows the scene being read,
and that Edit opens that scene and leaving it comes back to the book at the
scene the writer ended on, with the edit in the text. Back returns to where
the book was opened from. Print layout shows the book as Export lays it out,
at the chapter being read, with words that can be selected, zoom, page
colors and Focus, and Text comes back to the same place in the text.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import re
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
    expect(page.locator("#bookWhere")).to_have_text("I. Down the Rabbit-Hole · Down the Rabbit-Hole")
    expect(page.locator("#bookNavWhere")).to_have_text("I. Down the Rabbit-Hole · scene 1 of 3")
    expect(page.locator("#bookNavPct")).to_have_text("0%")
    # It says what it is, and the file browser steps aside for it.
    expect(page.locator("#bookIntro")).to_contain_text("The whole book as one continuous text")
    assert page.evaluate("document.documentElement.dataset.sidebar") == "closed"
    # The frontmatter stays out of the reading.
    expect(page.locator("#bookBody")).not_to_contain_text("status: drafted")

    # The address follows the scene being read, so a reload reopens there.
    page.mouse.wheel(0, 12000)
    page.wait_for_function(f"() => location.hash.startsWith('#/book/') && !location.hash.endsWith({FIRST.replace('/', '%2F')!r})")
    reading = page.evaluate("bookCurrentScene()")
    page.reload(wait_until="load")
    expect(page.locator("#book-panel")).to_be_visible()
    assert page.evaluate("bookCurrentScene()") == reading

    page.get_by_role("button", name="← Back").click()
    expect(page.locator("#book-panel")).to_be_hidden()
    expect(page.locator("#sceneTable")).to_be_visible()


def test_skip_by_scene_and_chapter_and_pick_a_chapter(page: Page, book_server: ProseviewServer):
    page.goto(book_server.url("/"), wait_until="load")
    page.evaluate("setSidebarOpen(true)")
    page.locator("#bookOpenBtn").click()
    expect(page.locator("#book-panel")).to_be_visible()
    expect(page.locator("#bookIntro")).to_be_visible()
    page.locator(".book-intro-close").click()
    expect(page.locator("#bookIntro")).to_be_hidden()

    page.get_by_role("button", name="Next scene").click()
    assert page.evaluate("bookCurrentScene()") == "ch01/02-down-down-down.md"
    page.keyboard.press("ArrowRight")
    assert page.evaluate("bookCurrentScene()") == "ch01/03-drink-me.md"
    page.get_by_role("button", name="Next chapter").click()
    assert page.evaluate("bookCurrentScene()") == "ch02/01-curiouser-and-curiouser.md"
    page.keyboard.press("ArrowRight")
    # Back goes to the start of this chapter first, then the one before.
    page.keyboard.press("Shift+ArrowLeft")
    assert page.evaluate("bookCurrentScene()") == "ch02/01-curiouser-and-curiouser.md"
    page.get_by_role("button", name="Previous chapter").click()
    assert page.evaluate("bookCurrentScene()") == FIRST

    page.locator("#bookNavWhere").click()
    page.locator("#bookToc").get_by_role("button", name="VII. A Mad Tea-Party").click()
    expect(page.locator("#bookToc")).to_be_hidden()
    assert page.evaluate("bookCurrentScene()").startswith("ch07/01-")
    expect(page.locator("#bookNavWhere")).to_have_text("VII. A Mad Tea-Party · scene 1 of 3")

    # The file browser comes back on the way out, as the writer left it.
    page.get_by_role("button", name="← Back").click()
    assert page.evaluate("document.documentElement.dataset.sidebar") == "open"


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
    expect(page.get_by_role("radio", name="Text")).to_have_attribute("aria-checked", "true")
    # Back goes to the scene the book was opened from, even after reading on.
    page.get_by_role("button", name="Next chapter").click()
    page.get_by_role("button", name="← Back").click()
    page.wait_for_function(f"() => document.documentElement.dataset.view === 'scene' && paths[curIdx] === {scene!r}")


def test_the_book_has_the_reading_appearance_menu(page: Page, book_server: ProseviewServer):
    page.goto(book_server.url("/#/book"), wait_until="load")
    page.get_by_role("button", name="Reading appearance").click()
    menu = page.locator("#bookAppearanceMenu")
    expect(menu).to_be_visible()
    body = page.locator("#bookBody")
    menu.get_by_label("Line width").fill("600")
    menu.get_by_label("Text size").fill("22")
    assert body.evaluate("el => el.getBoundingClientRect().width") == 600
    assert body.evaluate("el => getComputedStyle(el).fontSize") == "22px"
    # The scene view reads with the same settings.
    assert page.evaluate("localStorage.getItem(MODAL_FONT_SIZE_STORAGE_KEY)") == "22"
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()


def test_print_layout_shows_the_book_at_the_chapter_being_read(page: Page, book_server: ProseviewServer):
    scene = "ch03/01-a-queer-looking-party.md"
    page.goto(book_server.url("/#/book/" + scene.replace("/", "%2F")), wait_until="load")
    page.wait_for_function(f"() => bookCurrentScene() === {scene!r}")
    page.locator(".book-intro-close").click()
    reading_at = page.evaluate("scrollY")
    assert reading_at > 0

    pages = page.get_by_role("radio", name="Print layout")
    text = page.get_by_role("radio", name="Text")
    expect(text).to_have_attribute("aria-checked", "true")
    pages.click()
    expect(pages).to_have_attribute("aria-checked", "true")
    expect(text).to_have_attribute("aria-checked", "false")
    expect(page.locator("#bookBody")).to_be_hidden()
    stage = page.locator("#bookPages")
    expect(stage.locator(".pdf-page canvas").first).to_be_visible(timeout=20_000)
    # A printed book: facing pages, flat in the page's own scroll (no box of
    # its own), opened at chapter three's first page.
    status = page.locator("#bookPagesStatus")
    expect(status).to_have_text(re.compile(r"^Pages? \d+(–\d+)? of \d+$"))
    chapter_page = stage.locator(".textLayer", has_text="Caucus").first
    expect(chapter_page).to_be_in_viewport(timeout=10_000)
    expect(page.locator("#bookWhere")).to_have_text("III. A Caucus-Race and a Long Tale · A Queer-Looking Party")
    # The text's chapter and scene moves are there too, and jump in the pages.
    where = page.locator("#bookNavWhere")
    expect(where).to_have_text("III. A Caucus-Race and a Long Tale · scene 1 of 3")
    page.get_by_role("button", name="Next scene").click()
    expect(where).to_have_text("III. A Caucus-Race and a Long Tale · scene 2 of 3")
    assert page.evaluate("bookCurrentScene()") == "ch03/02-the-caucus-race.md"
    page.get_by_role("button", name="Next chapter").click()
    expect(where).to_contain_text("IV.")
    page.get_by_role("button", name="Previous chapter").click()
    expect(where).to_have_text("III. A Caucus-Race and a Long Tale · scene 1 of 3")
    assert stage.evaluate("el => getComputedStyle(el).overflowY") == "hidden"
    assert page.evaluate("document.documentElement.scrollHeight > innerHeight * 3")

    # The words on the page can be selected and copied.
    words = chapter_page.locator("span").filter(has_text=re.compile(r"\w{4,}"))
    first, last = words.nth(2).bounding_box(), words.nth(6).bounding_box()
    page.mouse.move(first["x"] + 2, first["y"] + first["height"] / 2)
    page.mouse.down()
    page.mouse.move(last["x"] + last["width"] - 2, last["y"] + last["height"] / 2, steps=5)
    page.mouse.up()
    selected = page.evaluate("getSelection().toString()")
    assert len(selected.split()) >= 3, selected
    assert page.evaluate("document.getElementById('bookPages').contains(getSelection().anchorNode)")

    before = status.inner_text()
    page.keyboard.press("ArrowRight")
    expect(status).not_to_have_text(before)
    page.keyboard.press("ArrowLeft")
    expect(status).to_have_text(before)

    # One page at a time, and zoomed in: bigger, still selectable words.
    page.get_by_role("button", name="One page").click()
    expect(stage.locator(".pdf-pages-spread").nth(3).locator(".pdf-page")).to_have_count(1)
    expect(status).to_have_text(re.compile(r"^Page \d+ of \d+$"))
    # The wheel scrolls the page, and where you are follows.
    before = status.inner_text()
    page.mouse.move(640, 400)
    page.mouse.wheel(0, 2500)
    expect(status).not_to_have_text(before)
    fitted = stage.locator(".pdf-page canvas").first.bounding_box()["width"]
    page.get_by_role("button", name="Zoom in").click()
    page.wait_for_function(f"() => document.querySelector('#bookPages canvas').getBoundingClientRect().width > {fitted}")
    expect(page.locator(".pdf-pages-zoom")).to_have_text(re.compile(r"^\d+%$"))
    box = page.evaluate("""() => {
        const spans = [...document.querySelectorAll('#bookPages .textLayer span')];
        const seen = spans.map(s => s.getBoundingClientRect())
            .filter((r, i) => r.top > 120 && r.bottom < innerHeight - 80 && r.left > 0 && r.right < innerWidth
                && /\\w{4,}/.test(spans[i].textContent));
        const r = seen[0];
        return {x: r.left + r.width / 2, y: r.top + r.height / 2};
    }""")
    page.mouse.dblclick(box["x"], box["y"])
    assert page.evaluate("getSelection().toString().trim()"), "a zoomed word could not be selected"
    # Fit again, and the choices are remembered for next time.
    page.get_by_role("button", name="Fit the page to the reading column").click()
    expect(page.locator(".pdf-pages-zoom")).to_have_text("Fit")
    assert page.evaluate("JSON.parse(localStorage.getItem('proseview-pdf-pages-book'))") == {"pages": "one"}

    # The pages follow the theme: light paper in a light theme, dark in a
    # dark one, and the Aa menu has only the theme.
    corner = """() => {
        const canvas = document.querySelector('#bookPages canvas');
        const [r, g, b] = canvas.getContext('2d').getImageData(4, 4, 1, 1).data;
        return r + g + b;
    }"""
    page.evaluate("selectTheme('light')")
    page.wait_for_function(f"() => ({corner})() > 700")
    at = page.evaluate("scrollY")
    page.evaluate("selectTheme('dark')")
    page.wait_for_function(f"() => ({corner})() < 120")
    assert page.evaluate("scrollY") == at
    page.get_by_role("button", name="Reading appearance").click()
    expect(page.locator("#bookFontSize")).to_be_hidden()
    expect(page.locator("#bookThemeSelect")).to_be_attached()
    expect(page.locator("#bookAppearanceMenu").get_by_text("Page", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")

    # Focus: the bars step aside, and come back near the edge or with Esc.
    header, nav = page.locator(".book-header"), page.locator("#bookNav")
    page.keyboard.press("f")
    page.mouse.move(600, 400)
    page.wait_for_function("() => document.querySelector('.book-header').getBoundingClientRect().bottom <= 0")
    page.mouse.move(600, 5)
    page.wait_for_function("() => document.querySelector('.book-header').getBoundingClientRect().top >= 0")
    page.mouse.move(600, 400)
    page.keyboard.press("Escape")
    expect(page.locator("#book-panel")).not_to_have_class(re.compile("is-focus"))
    expect(header).to_be_in_viewport()
    expect(nav).to_be_in_viewport()
    # Shift+F is full screen, as in the scene view; Esc leaves it, not the book.
    page.keyboard.press("Shift+F")
    page.wait_for_function("() => !!document.fullscreenElement")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.fullscreenElement")
    expect(page.locator("#book-panel")).to_be_visible()

    # Back to the text, where it was.
    text.click()
    expect(page.locator("#bookBody")).to_be_visible()
    expect(stage).to_be_hidden()
    assert page.evaluate("scrollY") == reading_at
    assert page.evaluate("bookCurrentScene()") == scene


def test_see_in_print_layout_from_a_scene_and_back_to_it(page: Page, book_server: ProseviewServer):
    scene = "ch05/01-advice-from-a-caterpillar.md"
    page.goto(book_server.url("/#/scene/" + scene.replace("/", "%2F")), wait_until="load")
    page.wait_for_selector("#sceneProseHost")
    # Scroll once the scene is tall enough to: on a slow runner the prose was
    # still laying out, the scroll did nothing, and the origin read 0.
    page.wait_for_function(
        """() => { const box = document.querySelector('#sceneModal .modal-content');
                   box.scrollTo({top: 300, behavior: 'instant'});
                   return box.scrollTop >= 300; }"""
    )
    page.locator("#sceneMoreBtn").click()
    expect(page.get_by_role("button", name="Preview as PDF…")).to_have_count(0)
    page.get_by_role("button", name="Print layout", exact=True).click()
    left_at = page.evaluate("_bookOrigin.top")
    assert left_at > 0
    expect(page.get_by_role("radio", name="Print layout")).to_have_attribute("aria-checked", "true")
    stage = page.locator("#bookPages")
    expect(stage.locator(".pdf-page canvas").first).to_be_visible(timeout=20_000)
    expect(page.locator("#bookNavWhere")).to_have_text("V. Advice from a Caterpillar · scene 1 of 3")

    # Back (Esc) returns to the scene it was opened from, scrolled where it was.
    page.keyboard.press("Escape")
    page.wait_for_function(f"() => document.documentElement.dataset.view === 'scene' && paths[curIdx] === {scene!r}")
    page.wait_for_function(f"() => document.querySelector('#sceneModal .modal-content').scrollTop === {left_at}")

    # The dashboard opens the book in the view used last.
    page.get_by_role("button", name="Close scene and return to dashboard").first.click()
    page.locator("#bookOpenBtn").click()
    expect(page.get_by_role("radio", name="Print layout")).to_have_attribute("aria-checked", "true")
    expect(stage.locator(".pdf-page canvas").first).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="← Back").click()
    expect(page.locator("#book-panel")).to_be_hidden()
    expect(page.locator("#sceneTable")).to_be_visible()


def test_the_header_steps_aside_while_reading_on_without_moving_the_text(page: Page, book_server: ProseviewServer):
    page.goto(book_server.url("/#/book"), wait_until="load")
    page.locator(".book-intro-close").click()
    panel, header = page.locator("#book-panel"), page.locator(".book-header")
    height = header.bounding_box()["height"]
    page.mouse.move(640, 400)
    page.mouse.wheel(0, 600)
    expect(panel).to_have_class(re.compile("is-header-hidden"))
    # It keeps its space, so nothing below it moves.
    assert header.bounding_box()["height"] == height
    page.mouse.wheel(0, -200)
    expect(panel).not_to_have_class(re.compile("is-header-hidden"))
    # The pointer at the top edge brings it back too.
    page.mouse.wheel(0, 600)
    expect(panel).to_have_class(re.compile("is-header-hidden"))
    page.mouse.move(640, 20)
    expect(panel).not_to_have_class(re.compile("is-header-hidden"))


def test_print_layout_style_and_size_are_exports_own(page: Page, book_server: ProseviewServer):
    config = book_server.root / ".proseview.yaml"
    before = config.read_text(encoding="utf-8")
    page.goto(book_server.url("/#/book/ch03%2F01-a-queer-looking-party.md"), wait_until="load")
    page.get_by_role("radio", name="Print layout").click()
    stage = page.locator("#bookPages")
    expect(stage.locator(".pdf-page canvas").first).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Reading appearance").click()
    style, kind = page.locator("#bookPrintStyle"), page.locator("#bookPrintFormat")
    # Export's defaults: Classic, the printed book, 5.5 × 8.5 in.
    expect(style).to_have_value("classic")
    expect(kind).to_have_value("pdf-print")
    expect(page.locator("#bookPrintTrim")).to_have_value("5.5x8.5")
    width = stage.locator(".pdf-page").first.evaluate("el => el.getBoundingClientRect().width / el.getBoundingClientRect().height")

    # A new trim lays the book out again, in the same scene, and Export keeps it.
    page.locator("#bookPrintTrim").select_option("6x9")
    page.wait_for_function(f"""() => {{
        const r = document.querySelector('#bookPages .pdf-page').getBoundingClientRect();
        return Math.abs(r.width / r.height - {width}) > 0.01;
    }}""")
    expect(page.locator("#bookNavWhere")).to_contain_text("III. A Caucus-Race")
    assert "trim: 6x9" in config.read_text(encoding="utf-8")

    # Manuscript makes only a shareable PDF, and says so.
    style.select_option("manuscript")
    expect(kind).to_have_value("pdf-share")
    expect(page.locator("#bookPrintNote")).to_have_text("Manuscript makes a shareable PDF only.")
    expect(page.locator("#bookPrintPaper")).to_be_visible()
    _wait_until(lambda: "style: manuscript" in config.read_text(encoding="utf-8"), message="the style was not saved")
    saved = config.read_text(encoding="utf-8")
    assert "format: pdf-share" in saved
    # The rest of the file is as it was.
    assert all(line in saved for line in before.splitlines() if line.strip() and not line.startswith("export"))

    # Export opens with it.
    page.keyboard.press("Escape")
    page.get_by_role("button", name="← Back").click()
    page.evaluate("openExportDialog()")
    page.wait_for_function("() => exportState.details && exportState.details.style === 'manuscript' && exportState.details.format === 'pdf-share'")
