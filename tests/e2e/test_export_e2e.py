"""Browser tests for the Export dialog, on a copy of the demo book.

Clicks through the three steps the way a writer would: open Export from the
top bar, pick one chapter, keep the Classic style, fill in the book details,
check the preview, export, and read the finished screen. The exported file is
then checked on disk, and the fixture itself is checked to be untouched.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from proseview.epub_check import structural_problems  # noqa: E402

from .conftest import REPO_ROOT, ProseviewServer, _start_server, _stop_server  # noqa: E402

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"


@pytest.fixture
def demo_book_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    (root / ".git").mkdir()  # enough for the exports/ .gitignore entry
    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


def test_export_one_chapter_from_the_dashboard(page: Page, demo_book_server: ProseviewServer):
    fixture_config = (DEMO / ".proseview.yaml").read_bytes()
    root = demo_book_server.root
    page.goto(demo_book_server.url("/"))

    page.get_by_role("button", name="Export").first.click()
    dialog = page.locator("#exportDialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#exportTotals")).to_contain_text("The whole book: 12 chapters, 39 scenes")

    # Step 1: one chapter, from the "First three chapters" quick pick.
    dialog.get_by_role("button", name="First three chapters").click()
    page.locator('input[data-chapter="1"]').uncheck()
    page.locator('input[data-chapter="2"]').uncheck()
    expect(page.locator("#exportTotals")).to_have_text("1 chapter, 3 scenes, 1,697 words")
    page.locator('[data-chapter-toggle="3"]').click()
    expect(page.locator("#exportTree .export-scene-row")).to_have_count(3)
    page.get_by_role("button", name="Next: Format and style").click()

    # Step 2: an e-book in the Classic style; scene titles stay off.
    expect(page.get_by_role("radio", name="E-book (EPUB)")).to_be_checked()
    expect(page.get_by_role("radio", name="Classic")).to_be_checked()
    expect(page.locator("#exportSceneTitles")).not_to_be_checked()
    page.get_by_role("button", name="Next: Book details").click()

    # Step 3: details and the preview of the styled pages.
    page.get_by_label("Title", exact=True).fill("Alice's Adventures in Wonderland")
    page.get_by_label("Author", exact=True).fill("Lewis Carroll")
    frame = page.frame_locator("#exportPreviewFrame")
    expect(frame.locator(".chapter-number")).to_have_text("Chapter Three")
    expect(frame.locator("p.opener")).to_be_visible()
    expect(page.locator("#exportPreviewStatus")).to_contain_text("page 1 of")
    page.get_by_role("button", name="Next page").click()
    expect(page.locator("#exportPreviewStatus")).to_contain_text("page 2 of")

    page.get_by_role("button", name="Export EPUB").click()
    done = page.locator("#exportDoneBox")
    expect(done).to_contain_text("Your e-book is ready", timeout=30_000)
    expect(done).to_contain_text("1 chapter, 3 scenes, 1,697 words")
    expect(done).to_contain_text("Ready to share with readers")
    expect(done.get_by_role("button", name="Show in folder")).to_be_visible()
    download = done.get_by_role("link", name="Download")
    expect(download).to_have_attribute("href", "/api/export/file?path=" + "exports%2F" + download.get_attribute("download"))

    expect(done.get_by_role("link", name="Download")).to_have_count(1)
    exported = sorted((root / "exports").glob("alices-adventures-in-wonderland-chapter-3-*.epub"))
    assert len(exported) == 1
    assert structural_problems(exported[0]) == []
    with zipfile.ZipFile(exported[0]) as archive:
        chapter = archive.read("OEBPS/text/chapter-001.xhtml").decode()
    assert "Chapter Three" in chapter
    config = (root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "author: Lewis Carroll" in config and "identifier: urn:uuid:" in config
    assert "exports/" in (root / ".gitignore").read_text(encoding="utf-8")

    page.get_by_role("button", name="Done").click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("button", name="Export").first).to_be_focused()
    # The run worked on a copy; the fixture is exactly as it was.
    assert (DEMO / ".proseview.yaml").read_bytes() == fixture_config
    assert not (DEMO / "exports").exists()


def test_export_this_scene_from_the_file_browser(page: Page, demo_book_server: ProseviewServer):
    page.goto(demo_book_server.url("/"))
    page.locator('#sidebarTree [aria-label="More actions for ch05"]').click(force=True)
    expect(page.locator("#sidebarContextMenu")).to_contain_text("Export this chapter…")
    page.keyboard.press("Escape")

    page.goto(demo_book_server.url("/#/scene/ch05%2F01-advice-from-a-caterpillar.md"))
    page.locator("#sceneMoreBtn").click()
    page.locator("#modalExportSceneBtn").click()
    expect(page.locator("#exportTotals")).to_contain_text("1 chapter, 1 scene")
    expect(page.locator('input[data-scene="ch05/01-advice-from-a-caterpillar"]')).to_be_checked()

    # Keyboard: Escape closes the dialog and nothing was written.
    page.keyboard.press("Escape")
    expect(page.locator("#exportDialog")).to_be_hidden()
    assert not (demo_book_server.root / "exports").exists()


def test_p_previews_the_open_scene_as_a_pdf(page: Page, demo_book_server: ProseviewServer):
    page.goto(demo_book_server.url("/#/scene/ch05%2F01-advice-from-a-caterpillar.md"))
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    page.locator("#sceneProseHost").click()
    page.keyboard.press("p")

    # Straight to the preview of just this scene, as a shareable PDF.
    expect(page.locator('[data-export-panel="3"]')).to_be_visible()
    expect(page.locator("#exportPaperView img").first).to_be_visible(timeout=20_000)
    expect(page.get_by_role("button", name="Export PDF")).to_be_visible()
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_role("radio", name="Shareable PDF")).to_be_checked()
    page.get_by_role("button", name="Back").click()
    expect(page.locator("#exportTotals")).to_contain_text("1 chapter, 1 scene")

    page.keyboard.press("Escape")
    expect(page.locator("#exportDialog")).to_be_hidden()
    assert not (demo_book_server.root / "exports").exists()
    # The same from the scene's menu.
    page.locator("#sceneMoreBtn").click()
    expect(page.get_by_role("button", name="Preview as PDF…")).to_be_visible()


def test_export_a_print_pdf_of_one_chapter(page: Page, demo_book_server: ProseviewServer):
    from proseview.pdf_check import pdf_facts

    root = demo_book_server.root
    page.goto(demo_book_server.url("/#/scene/ch03%2F01-a-queer-looking-party.md"))
    page.locator("#sceneMoreBtn").click()
    page.locator("#modalExportChapterBtn").click()
    expect(page.locator("#exportTotals")).to_have_text("1 chapter, 3 scenes, 1,697 words")
    page.get_by_role("button", name="Next: Format and style").click()

    page.get_by_role("radio", name="Print book (PDF)").check()
    expect(page.get_by_label("Trim size")).to_have_value("5.5x8.5")
    page.get_by_label("Trim size").select_option("5x8")
    expect(page.get_by_role("radio", name="Manuscript")).to_have_count(0)
    page.get_by_role("button", name="Next: Book details").click()

    page.get_by_label("Author", exact=True).fill("Lewis Carroll")
    preview = page.locator("#exportPaperView img")
    expect(preview.first).to_be_visible(timeout=20_000)
    expect(page.locator("#exportPreviewStatus")).to_contain_text("of")
    page.get_by_role("button", name="Next page").click()
    expect(page.locator("#exportPreviewStatus")).to_contain_text("Pages")

    page.get_by_role("button", name="Export PDF").click()
    done = page.locator("#exportDoneBox")
    expect(done).to_contain_text("Your PDF is ready", timeout=30_000)
    expect(done).to_contain_text("A 5 × 8 in proof of this part, ready to print")

    (pdf,) = (root / "exports").glob("alice-chapter-3-print-*.pdf")
    facts = pdf_facts(pdf.read_bytes())
    assert facts.page_sizes == ((360.0, 576.0),) and facts.unembedded_fonts == ()
    config = (root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "format: pdf-print" in config and "trim: 5x8" in config
    # A preview still finishing may hold its source for a moment; none stays.
    deadline = time.monotonic() + 10
    while list((root / ".proseview").glob("preview-*.typ")) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not list((root / ".proseview").glob("preview-*.typ"))


def test_manuscript_asks_for_contact_details(page: Page, demo_book_server: ProseviewServer):
    page.goto(demo_book_server.url("/"))
    page.get_by_role("button", name="Export").first.click()
    page.get_by_role("button", name="Next: Format and style").click()
    page.get_by_role("radio", name="Shareable PDF").check()
    page.get_by_role("radio", name="Manuscript").check()
    page.get_by_role("button", name="Next: Book details").click()
    expect(page.get_by_label("Contact details")).to_be_visible()
    expect(page.locator("#exportCoverDrop")).to_be_hidden()
    expect(page.locator("#exportPaperView img").first).to_be_visible(timeout=20_000)
    # The preview opens on the first page of text, after the title page.
    expect(page.locator("#exportPagePick")).to_have_value("1")


@pytest.mark.allow_js_errors("Failed to load resource", "net::ERR_FAILED", "403")
def test_a_server_that_stopped_or_restarted_is_explained(page: Page, demo_book_server: ProseviewServer):
    """The browser only says "Failed to fetch"; the dialog says what to do."""
    page.goto(demo_book_server.url("/"))
    page.get_by_role("button", name="Export").first.click()
    expect(page.locator("#exportTree .export-chapter").first).to_be_visible()
    page.get_by_role("button", name="Next: Format and style").click()
    page.get_by_role("button", name="Next: Book details").click()

    # The server has gone away: nothing answers.
    page.route("**/api/export/start", lambda route: route.abort())
    page.get_by_role("button", name="Export EPUB").click()
    done = page.locator("#exportDoneBox")
    expect(done).to_contain_text("The e-book could not be made")
    expect(done).to_contain_text("Proseview has stopped running")
    expect(done).not_to_contain_text("Failed to fetch")
    expect(done.get_by_role("button", name="Reload page")).to_be_visible()

    # The server restarted: this page's session belongs to the old run.
    page.unroute("**/api/export/start")
    page.route("**/api/export/start", lambda route: route.fulfill(
        status=403, content_type="application/json",
        body='{"ok": false, "error": "invalid or missing page session"}',
    ))
    page.get_by_role("button", name="Back").click()
    page.get_by_role("button", name="Export EPUB").click()
    expect(done).to_contain_text("This page was opened by an earlier run of Proseview")


def test_a_server_older_than_the_page_is_explained(page: Page, demo_book_server: ProseviewServer):
    page.route("**/api/export/outline", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok": true, "chapters": []}',
    ))
    page.goto(demo_book_server.url("/"))
    page.get_by_role("button", name="Export").first.click()
    expect(page.locator("#exportTree")).to_contain_text("Proseview was updated while it was running")


def test_pick_by_character_in_the_modern_style_with_a_dedication(page: Page, demo_book_server: ProseviewServer):
    root = demo_book_server.root
    page.goto(demo_book_server.url("/"))
    page.get_by_role("button", name="Export").first.click()
    expect(page.locator("#exportTree .export-chapter").first).to_be_visible()

    page.get_by_label("What to pick by").select_option("characters")
    page.get_by_label("Which").select_option("Queen")
    page.get_by_role("button", name="Tick these").click()
    expect(page.locator("#exportTotals")).to_have_text("6 chapters, 15 scenes, 10,187 words")

    page.get_by_role("button", name="Next: Format and style").click()
    page.get_by_role("radio", name="Modern").check()
    page.get_by_role("button", name="Next: Book details").click()
    page.locator("#exportMatter summary").click()
    page.get_by_label("Dedication").fill("For Alice Liddell")
    expect(page.frame_locator("#exportPreviewFrame").locator(".chapter-number")).to_have_text("6", timeout=20_000)

    page.get_by_role("button", name="Export EPUB").click()
    expect(page.locator("#exportDoneBox")).to_contain_text("Your e-book is ready", timeout=30_000)
    (epub,) = (root / "exports").glob("*.epub")
    with zipfile.ZipFile(epub) as archive:
        pages = "".join(archive.read(n).decode() for n in archive.namelist() if n.endswith(".xhtml"))
    assert "For Alice Liddell" in pages and "All rights reserved." in pages
    config = (root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "style: modern" in config and "dedication: For Alice Liddell" in config
