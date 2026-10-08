"""Tests for PDF export: the Typst renderer, the layouts, and the checks.

Covers:
- escaping: whatever a writer types reaches the page as text and can never
  run as Typst (a scene full of ``#pagebreak()`` stays one page, ``#set page``
  changes nothing)
- the Markdown renderer: emphasis, lists, quotes, tables, code, links,
  headings and images all lay out; the drop-cap opener keeps its formatting
- print PDFs: every trim size, embedded fonts, a gutter that grows with the
  page count; shareable PDFs: Letter and A4, the watermark, the cover
- the Manuscript style: PDF only, its title page and running head
- every selection type lays out in both layouts
- readiness in plain words, the CLI's --format, saved PDF settings
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import cli  # noqa: E402
from proseview.book import ExportError, Selection, build_book, number_documents  # noqa: E402
from proseview.book_styles import load_style  # noqa: E402
from proseview.config import Config, ConfigError  # noqa: E402
from proseview.export import collect_scene_documents, default_output_path, export_book  # noqa: E402
from proseview.pdf import (  # noqa: E402
    TRIM_SIZES, PdfOptions, approximate_words, default_paper, gutter_for, page_count, typst_source,
)
from proseview.pdf_check import pdf_facts, readiness, structural_problems  # noqa: E402
from proseview.typst_render import RenderContext, TypstRenderer, escape  # noqa: E402

from tests.test_epub import SELECTIONS  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"
POINTS = {"in": 72.0, "mm": 72.0 / 25.4}


def _points(length: str) -> float:
    return float(length[:-2]) * POINTS[length[-2:]]


@pytest.fixture
def book(tmp_path: Path) -> Path:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    return root


def _tiny_novel(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript" / "ch01").mkdir(parents=True)
    (root / "manuscript" / "ch01" / "01-the-shop.md").write_text(
        "---\ntitle: The Shop\nchapter: The Shop\n---\n\n" + text + "\n", encoding="utf-8",
    )
    return root


def _pdf(tmp_path: Path, root: Path, fmt: str = "pdf-print", **options):
    return export_book(root, Config.load(root), tmp_path / f"book-{fmt}.pdf", fmt=fmt, **options)


# -- escaping ------------------------------------------------------------------------


def test_escape_backslashes_every_character_typst_reads():
    assert escape("#emph[x] $1 @me <b> *a* _b_ `c` = - + ~ / : ; ' \"") == (
        "\\#emph\\[x\\] \\$1 \\@me \\<b\\> \\*a\\* \\_b\\_ \\`c\\` \\= \\- \\+ \\~ \\/ \\: \\; \\' \\\""
    )
    assert escape("one\n  two") == "one two"


def test_typst_code_in_a_scene_stays_text(tmp_path: Path):
    hostile = " ".join(["#pagebreak()"] * 6) + " #set page(width: 2in) $x^2$ @ref <label> // not a comment"
    plain = _pdf(tmp_path / "plain", _tiny_novel(tmp_path / "plain", "Rena opened the shop."),
                 fmt="pdf-share", paper="a4")
    result = _pdf(tmp_path, _tiny_novel(tmp_path, "Rena opened the shop.\n\n" + hostile), fmt="pdf-share",
                  paper="a4")

    assert pdf_facts(result.path.read_bytes()).page_sizes == ((595.3, 841.9),)
    # However many "#pagebreak()"s the prose holds, it takes no more pages.
    assert result.pages == plain.pages


def test_the_renderer_lays_out_everything_markdown_can_write(tmp_path: Path):
    markdown = "\n\n".join([
        "The opening paragraph, with its drop cap.",
        "First *emphasised*, **strong**, ~~struck~~ and `code` words, a [web link](https://example.com) "
        "and a [file link](../story-bible/rena.md).",
        "## A heading inside the scene",
        "> A quotation\n> over two lines.",
        "- one\n- two\n  - nested",
        "3. three\n4. four",
        "| Name | Role |\n| --- | --- |\n| Rena | Owner |",
        "```\nraw #code $here\n```",
        "Line one  \nline two.",
        "---",
        "<!-- TODO: never printed -->Last paragraph with <b>raw html</b>.",
    ])
    root = _tiny_novel(tmp_path, markdown)
    result = _pdf(tmp_path, root)
    assert result.pages >= 1
    assert structural_problems(result.path) == []

    source = typst_source(result.book, PdfOptions(layout="print", style=load_style("classic")))
    assert "never printed" not in source
    assert '#link("https://example.com")[web link]' in source
    assert "file link" in source and "rena.md" not in source
    assert "#enum(start: 3," in source
    assert "\\<b\\>raw html\\<\\/b\\>" in source


def test_the_opener_keeps_formatting_word_by_word():
    renderer = TypstRenderer()
    out = renderer.render("*Every* word was “hers”.", RenderContext(None), opener=True)
    assert out == "#opener([E], ([#emph[very]], [word], [was], [“hers”\\.],), joined: true)"
    out = renderer.render("A cat sat.", RenderContext(None), opener=True)
    assert out.startswith("#opener([A], ([cat],") and "joined: false" in out
    out = renderer.render("“Curiouser!” cried Alice.", RenderContext(None), opener=True)
    assert out.startswith("#opener([“C], ([uriouser!”],")


# -- print and share -----------------------------------------------------------------


@pytest.mark.parametrize("trim", list(TRIM_SIZES))
def test_a_print_pdf_is_the_trim_size_with_every_font_embedded(tmp_path: Path, book: Path, trim: str):
    result = _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "1"),)), trim=trim)
    facts = pdf_facts(result.path.read_bytes())
    width, height = (round(_points(v), 1) for v in TRIM_SIZES[trim])

    assert facts.page_sizes == ((width, height),)
    assert facts.fonts > 0 and facts.unembedded_fonts == ()
    assert structural_problems(result.path, expected=TRIM_SIZES[trim]) == []


def test_the_whole_demo_book_prints_with_a_title_page_and_its_back(tmp_path: Path, book: Path):
    result = _pdf(tmp_path, book, author="Lewis Carroll", title="Alice's Adventures in Wonderland")
    checks = readiness(result.path, result.book, layout="print", trim="5.5x8.5")

    assert 60 < result.pages < 140
    assert checks == {
        "ready": True, "headline": "Ready to upload to KDP as a 5.5 × 8.5 in paperback interior",
        "findings": [], "pages": result.pages,
    }


def test_the_gutter_grows_with_the_page_count():
    assert gutter_for(24) == 0.375
    assert gutter_for(151) == 0.5
    assert gutter_for(420) == 0.625
    assert gutter_for(900) == 0.875


def test_paper_follows_the_language():
    assert default_paper("en-US") == "letter"
    assert default_paper("en-GB") == "a4"
    assert default_paper("fr-FR") == "a4"


def test_a_shareable_pdf_has_the_cover_contents_and_a_watermark(tmp_path: Path, book: Path):
    cover = REPO_ROOT / "docs" / "images" / "dashboard.png"
    shutil.copy(cover, book / "cover.png")
    result = _pdf(tmp_path, book, fmt="pdf-share", cover_image=book / "cover.png",
                  watermark="Advance copy for Sam", paper="letter", author="L. C.")
    data = result.path.read_bytes()

    assert pdf_facts(data).page_sizes == ((612.0, 792.0),)
    assert b"/Subtype /Image" in data or b"/Subtype/Image" in data
    assert b"/Outlines" in data  # PDF bookmarks for every chapter
    source = typst_source(result.book, PdfOptions(
        layout="share", style=load_style("classic"), watermark="Advance copy for Sam",
        cover_image=book / "cover.png",
    ))
    assert 'watermark: "Advance copy for Sam"' in source
    assert "#contents()" in source


def test_a_print_pdf_leaves_the_cover_for_the_printer(tmp_path: Path, book: Path):
    shutil.copy(REPO_ROOT / "docs" / "images" / "dashboard.png", book / "cover.png")
    result = _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "1"),)), cover_image=book / "cover.png")
    assert b"/Subtype /Image" not in result.path.read_bytes()
    assert b"/Subtype/Image" not in result.path.read_bytes()


@pytest.mark.parametrize("fmt", ["pdf-print", "pdf-share"])
@pytest.mark.parametrize("kind", list(SELECTIONS))
def test_every_selection_type_lays_out(tmp_path: Path, book: Path, kind: str, fmt: str):
    result = _pdf(tmp_path, book, fmt=fmt, selection=SELECTIONS[kind], appendix_folders=["plans"])
    assert result.pages > 0
    assert structural_problems(result.path) == []


def test_a_scene_image_is_printed_and_a_missing_one_names_its_scene(tmp_path: Path, book: Path):
    shutil.copy(REPO_ROOT / "docs" / "images" / "dashboard.png", book / "manuscript" / "ch02" / "pool.png")
    scene = book / "manuscript" / "ch02" / "02-the-pool-of-tears.md"
    scene.write_text(scene.read_text() + "\n![The pool](pool.png)\n")
    result = _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "2"),)))
    assert b"/Subtype /Image" in result.path.read_bytes() or b"/Subtype/Image" in result.path.read_bytes()

    scene.write_text(scene.read_text() + "\n![Gone](gone.png)\n")
    with pytest.raises(ExportError) as caught:
        _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "2"),)))
    assert caught.value.scene == "ch02/02-the-pool-of-tears"


# -- manuscript ---------------------------------------------------------------------


def test_manuscript_is_a_shareable_pdf_only(tmp_path: Path, book: Path):
    assert load_style("manuscript").formats == ("pdf-share",)
    with pytest.raises(ExportError, match="The Manuscript style makes Shareable PDF, not E-book"):
        export_book(book, Config.load(book), tmp_path / "x.epub", style="manuscript")


def test_manuscript_has_contact_details_and_a_word_count(tmp_path: Path, book: Path):
    result = _pdf(tmp_path, book, fmt="pdf-share", style="manuscript", author="Lewis Carroll",
                  contact="lewis@example.com\n+44 1865 000000", paper="letter")
    source = typst_source(result.book, PdfOptions(
        layout="share", style=load_style("manuscript"), contact="lewis@example.com\n+44 1865 000000",
    ))
    assert 'contact: "lewis@example.com\\n+44 1865 000000"' in source
    assert 'word-count: "about 27,000 words"' in source or 'word-count: "about 26,000 words"' in source
    assert "#chapter([Chapter 1]," in source
    checks = readiness(result.path, result.book, layout="share", paper="letter", style="manuscript",
                       contact="lewis@example.com")
    assert checks["headline"] == "Ready to send to an agent or editor"

    no_contact = readiness(result.path, result.book, layout="share", paper="letter", style="manuscript")
    assert [f["fix"] for f in no_contact["findings"]] == ["contact"]


def test_approximate_words_rounds_like_a_manuscript():
    def book_of(words: int):
        docs = number_documents(collect_scene_documents(DEMO, Config.load(DEMO))[:1])
        doc = docs[0].__class__(**{**docs[0].__dict__, "markdown": " ".join(["word"] * words)})
        return build_book([doc], [doc], title="T")

    assert approximate_words(book_of(84_612)) == "about 85,000 words"
    assert approximate_words(book_of(3_249)) == "about 3,200 words"
    assert approximate_words(book_of(12)) == "about 100 words"


# -- readiness ------------------------------------------------------------------------


def test_a_paperback_needs_twenty_four_pages(tmp_path: Path):
    root = _tiny_novel(tmp_path, "Rena opened the shop.")
    result = _pdf(tmp_path, root, author="Rena", title="The Shop")
    checks = readiness(result.path, result.book, layout="print", trim="5.5x8.5")

    assert result.book.kind == "book"
    assert [f["message"] for f in checks["findings"]] == [
        f"The book is {result.pages} pages. A paperback needs at least 24."
    ]


def test_structural_problems_catches_a_wrong_size_and_a_broken_file(tmp_path: Path, book: Path):
    result = _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "1"),)), trim="6x9")
    assert structural_problems(result.path, expected=TRIM_SIZES["5x8"]) == [
        "some pages are not the size that was asked for"
    ]
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 nothing")
    assert structural_problems(broken) == ["the file is not a complete PDF"]


def test_page_count_reads_typst_output(tmp_path: Path, book: Path):
    result = _pdf(tmp_path, book, selection=Selection(picks=(("chapter", "1"),)))
    assert page_count(result.path.read_bytes()) == result.pages > 2


# -- names, config, CLI ----------------------------------------------------------------


def test_each_format_gets_its_own_file_name(book: Path):
    import datetime

    result_book = build_book(collect_scene_documents(book, Config.load(book)), collect_scene_documents(book, Config.load(book)), title="Alice")
    day = datetime.date(2026, 10, 8)
    assert default_output_path(book, result_book, today=day).name == "alice-2026-10-08.epub"
    assert default_output_path(book, result_book, today=day, fmt="pdf-print").name == "alice-print-2026-10-08.pdf"
    assert default_output_path(book, result_book, today=day, fmt="pdf-share").name == "alice-2026-10-08.pdf"
    assert default_output_path(book, result_book, today=day, fmt="pdf-share", style="manuscript").name == (
        "alice-manuscript-2026-10-08.pdf"
    )


def test_pdf_settings_are_read_from_the_config(tmp_path: Path, book: Path):
    (book / ".proseview.yaml").write_text(
        (book / ".proseview.yaml").read_text()
        + "export:\n  format: pdf-print\n  trim: 6x9\n  recto_chapters: false\n  author: Lewis Carroll\n"
    )
    cfg = Config.load(book)
    assert (cfg.export.format, cfg.export.trim, cfg.export.recto_chapters) == ("pdf-print", "6x9", False)
    assert cli.main(["export", "--root", str(book), "--chapters", "1"]) == 0
    (pdf,) = (book / "exports").glob("*-print-*.pdf")
    assert pdf_facts(pdf.read_bytes()).page_sizes == ((432.0, 648.0),)


@pytest.mark.parametrize("raw, message", [
    ("export:\n  format: docx\n", "export.format"),
    ("export:\n  recto_chapters: maybe\n", "export.recto_chapters"),
])
def test_bad_pdf_settings_are_refused(tmp_path: Path, raw: str, message: str):
    (tmp_path / ".proseview.yaml").write_text(raw)
    with pytest.raises(ConfigError, match=message):
        Config.load(tmp_path)


def test_cli_exports_all_three_formats(tmp_path: Path, book: Path, capsys):
    assert cli.main(["export", "--root", str(book), "--format", "all", "--chapters", "2"]) == 0
    names = sorted(path.name for path in (book / "exports").iterdir())
    assert [name.rsplit("-2", 1)[0] for name in names] == [
        "alice-chapter-2", "alice-chapter-2", "alice-chapter-2-print",
    ]
    assert {Path(name).suffix for name in names} == {".epub", ".pdf"}
    assert "pages)" in capsys.readouterr().out


def test_cli_refuses_one_output_for_three_formats(tmp_path: Path, book: Path):
    with pytest.raises(SystemExit, match="--output names one file"):
        cli.main(["export", "--root", str(book), "--format", "all", "--output", str(tmp_path / "x.pdf")])


def test_cli_pandoc_engine_is_epub_only(tmp_path: Path, book: Path):
    with pytest.raises(SystemExit, match="only makes EPUBs"):
        cli.main(["export", "--root", str(book), "--format", "pdf-print", "--engine", "pandoc"])


def test_titles_and_headings_are_never_hyphenated():
    """A title page reading "Wonder-land" looks like a mistake, not a style."""
    template = (REPO_ROOT / "proseview" / "book_styles" / "classic" / "pdf.typ").read_text()
    for function in ("#let title-page()", "#let chapter(", "#let single-scene(", "#let running-head()"):
        body = template.split(function, 1)[1].split("\n#let ", 1)[0]
        assert "hyphenate: false" in body, function
