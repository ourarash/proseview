"""Tests for front and back matter, and the facts behind the dialog's quick picks.

Covers:
- the pages Proseview writes (copyright with the year, author and ISBN; a
  dedication; "Also by" at the back) and the writer's own front-matter/ and
  back-matter/ files, which replace a written page of the same kind
- only a whole book or a selection gets them; Manuscript never does
- the EPUB marks each page for what it is and lists back matter in the
  contents; EPUBCheck passes; the print PDF puts the copyright page on the
  back of the title page
- remembered settings, read by the command line too
- per-scene status, point of view, characters and last change, and the
  menus built from them
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import cli  # noqa: E402
from proseview.book import Selection  # noqa: E402
from proseview.book_styles import load_style  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.epub_check import structural_problems  # noqa: E402
from proseview.export import build_matter, export_book, prepare_book  # noqa: E402
from proseview.export_dashboard import outline  # noqa: E402
from proseview.pdf import PdfOptions, typst_source  # noqa: E402

from tests.test_epub import EPUBCHECK  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"
TODAY = dt.date(2026, 10, 8)


@pytest.fixture
def book(tmp_path: Path) -> Path:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    return root


def test_proseview_writes_copyright_dedication_and_also_by(book: Path):
    front, back = build_matter(
        book, author="Lewis Carroll", copyright_page=True, isbn="978-1-23", dedication="For Alice",
        also_by="Through the Looking-Glass\n- Sylvie and Bruno", include_files=True, today=TODAY,
    )
    assert [(p.kind, p.markdown) for p in front] == [
        ("copyright", "Copyright © 2026 Lewis Carroll\n\nAll rights reserved.\n\nISBN 978-1-23"),
        ("dedication", "For Alice"),
    ]
    assert [(p.kind, p.title, p.markdown) for p in back] == [
        ("also-by", "Also by Lewis Carroll", "*Through the Looking-Glass*\n\n*Sylvie and Bruno*"),
    ]


def test_the_writers_own_pages_come_first_and_replace_written_ones(book: Path):
    (book / "front-matter").mkdir()
    (book / "front-matter" / "01-dedication.md").write_text("To my sister, who read it first.\n", encoding="utf-8")
    (book / "front-matter" / "02-epigraph.md").write_text("> Curiouser and curiouser!\n", encoding="utf-8")
    (book / "back-matter").mkdir()
    (book / "back-matter" / "about-the-author.md").write_text("Lewis Carroll taught mathematics at Oxford.\n", encoding="utf-8")
    (book / "back-matter" / "README.md").write_text("notes, not a page\n", encoding="utf-8")
    front, back = build_matter(
        book, author="L.", copyright_page=True, isbn="", dedication="For Alice", also_by="",
        include_files=True, today=TODAY,
    )
    assert [(p.kind, p.source) for p in front] == [
        ("copyright", ""), ("dedication", "front-matter/01-dedication.md"), ("epigraph", "front-matter/02-epigraph.md"),
    ]
    assert [(p.kind, p.title) for p in back] == [("about-the-author", "About the Author")]

    front, back = build_matter(
        book, author="L.", copyright_page=False, isbn="", dedication="", also_by="", include_files=False,
    )
    assert front == () and back == ()


def test_only_a_whole_book_or_a_selection_gets_matter(book: Path):
    cfg = Config.load(book)
    assert prepare_book(book, cfg).front_matter
    assert prepare_book(book, cfg, Selection(picks=(("chapter", "2"), ("chapter", "4")))).front_matter
    assert prepare_book(book, cfg, Selection(picks=(("chapter", "2"),))).front_matter == ()
    assert prepare_book(book, cfg, Selection(picks=(("scene", "2.1"),))).back_matter == ()


def test_the_epub_marks_each_page_and_lists_back_matter(tmp_path: Path, book: Path):
    (book / "back-matter").mkdir()
    (book / "back-matter" / "acknowledgements.md").write_text("Thanks to the Liddells.\n", encoding="utf-8")
    path = export_book(book, Config.load(book), tmp_path / "b.epub", author="Lewis Carroll",
                       dedication="For Alice", also_by="Sylvie and Bruno").path
    assert structural_problems(path) == []
    with zipfile.ZipFile(path) as archive:
        copyright_page = archive.read("OEBPS/text/front-01.xhtml").decode()
        dedication = archive.read("OEBPS/text/front-02.xhtml").decode()
        thanks = archive.read("OEBPS/text/back-01.xhtml").decode()
        nav = archive.read("OEBPS/text/nav.xhtml").decode()
        opf = archive.read("OEBPS/content.opf").decode()
    assert 'epub:type="copyright-page"' in copyright_page and "All rights reserved." in copyright_page
    assert 'epub:type="dedication"' in dedication and "<h1>" not in dedication
    assert 'epub:type="acknowledgments"' in thanks and "<h1>Acknowledgements</h1>" in thanks
    assert "Acknowledgements" in nav and "Also by Lewis Carroll" in nav and ">Dedication<" not in nav
    # Front matter, then the contents, then the story.
    spine = opf.split("<spine", 1)[1]
    assert spine.index('"title-page"') < spine.index('"front-01"') < spine.index('"nav"') < spine.index('"chapter-001"')


@pytest.mark.skipif(EPUBCHECK is None, reason="EPUBCheck is not installed")
@pytest.mark.parametrize("version", ["epub3", "epub2"])
def test_epubcheck_passes_with_front_and_back_matter(tmp_path: Path, book: Path, version: str):
    (book / "back-matter").mkdir()
    (book / "back-matter" / "about-the-author.md").write_text("Lewis Carroll taught mathematics.\n", encoding="utf-8")
    path = export_book(book, Config.load(book), tmp_path / "b.epub", author="Lewis Carroll", epub_version=version,
                       dedication="For Alice", also_by="Sylvie and Bruno", isbn="978-1-23").path
    result = subprocess.run([*EPUBCHECK, str(path)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_print_puts_the_copyright_page_on_the_back_of_the_title_page(book: Path):
    pages = prepare_book(book, Config.load(book), author="L.", dedication="For Alice")
    source = typst_source(pages, PdfOptions(layout="print", style=load_style("classic")))
    assert "#title-page(verso: false)" in source
    assert source.index('#matter("copyright"') < source.index('#matter("dedication"') < source.index("#chapter(")

    no_copyright = prepare_book(book, Config.load(book), copyright_page=False)
    assert "#title-page(verso: true)" in typst_source(no_copyright, PdfOptions(layout="print", style=load_style("classic")))


def test_manuscript_leaves_out_front_and_back_matter(tmp_path: Path, book: Path):
    result = export_book(book, Config.load(book), tmp_path / "m.pdf", fmt="pdf-share", style="manuscript",
                         dedication="For Alice")
    without = export_book(book, Config.load(book), tmp_path / "n.pdf", fmt="pdf-share", style="manuscript",
                          copyright_page=False)
    assert result.pages == without.pages


def test_matter_settings_are_remembered_and_read_by_the_cli(tmp_path: Path, book: Path):
    (book / ".proseview.yaml").write_text(
        (book / ".proseview.yaml").read_text(encoding="utf-8")
        + "export:\n  dedication: For Alice Liddell\n  also_by:\n    - Sylvie and Bruno\n  copyright_page: false\n"
    )
    out = tmp_path / "b.epub"
    assert cli.main(["export", "--root", str(book), "--output", str(out)]) == 0
    with zipfile.ZipFile(out) as archive:
        text = "".join(archive.read(n).decode() for n in archive.namelist() if n.endswith(".xhtml"))
    assert "For Alice Liddell" in text and "Sylvie and Bruno" in text and "All rights reserved" not in text


# -- quick-pick facts -------------------------------------------------------------------


def test_outline_carries_status_pov_characters_and_menus(book: Path):
    data = outline(book, Config.load(book))
    scene = data["chapters"][1]["scenes"][0]
    assert scene["status"] == "drafted" and scene["pov"] == "Alice"
    assert scene["characters"][0] == "Alice"
    assert data["facets"]["status"] == [{"value": "drafted", "count": 39}]
    names = [entry["value"] for entry in data["facets"]["characters"]]
    assert names[0] == "Alice" and "Queen" in names
    assert data["words_per_page"]["5.5x8.5"] == 290


def test_changed_dates_come_from_git_and_uncommitted_edits(book: Path):
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-01-02T12:00:00", "GIT_COMMITTER_DATE": "2026-01-02T12:00:00",
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    for command in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "draft"]):
        subprocess.run(["git", "-C", str(book), *command], check=True, env=env, capture_output=True)
    edited = book / "manuscript" / "ch03" / "02-the-caucus-race.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nA new line.\n")

    scenes = {s["key"]: s for c in outline(book, Config.load(book))["chapters"] for s in c["scenes"]}
    assert scenes["ch01/01-down-the-rabbit-hole"]["changed"] == "2026-01-02"
    assert scenes["ch03/02-the-caucus-race"]["changed"] == dt.date.today().isoformat()
