"""Callouts in every export: a framed box in EPUB, PDF and Word, never a quotation.

The scene mixes a callout with a title, an untitled one, a plain quotation
and a TODO comment, so each format is checked for keeping the four apart.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from proseview.book_styles import load_style
from proseview.config import Config
from proseview.docx import document_paragraphs
from proseview.export import export_book
from proseview.pdf import PdfOptions, typst_source
from tests.test_epub import check_epub

SCENE = """She found the letter folded inside the atlas.

> [!letter] A *letter*, undated
> Mara, if you are reading this, the boat has gone.
>
> — T.

<!-- TODO: check the boat's name -->

> Every harbour keeps one ghost.

> [!NOTE]-
> An untitled box.
"""

COLOURS = """callouts:
  letter:
    background: "#f7f1e6"
  note:
    background:
      dark: "#222b30"
"""


def _novel(tmp_path: Path, config: str = COLOURS) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript" / "ch01").mkdir(parents=True)
    (root / "manuscript" / "ch01" / "01-atlas.md").write_text(
        "---\ntitle: The Atlas\nchapter: The Atlas\n---\n\n" + SCENE, encoding="utf-8",
    )
    (root / ".proseview.yaml").write_text(config, encoding="utf-8")
    return root


def _export(tmp_path: Path, root: Path, fmt: str, **options):
    suffix = {"epub": "epub", "docx": "docx"}.get(fmt, "pdf")
    return export_book(root, Config.load(root), tmp_path / f"book.{suffix}", fmt=fmt, **options)


def test_epub_draws_a_callout_as_a_box_with_its_colour(tmp_path: Path):
    result = _export(tmp_path, _novel(tmp_path), "epub")
    files = check_epub(result.path)
    chapter = files["OEBPS/text/chapter-001.xhtml"].decode()
    css = files["OEBPS/styles/book.css"].decode()

    assert '<div class="callout callout-letter" data-callout="letter">' in chapter
    assert '<p class="callout-title">A <em>letter</em>, undated</p>' in chapter
    assert "[!letter]" not in chapter and "[!NOTE]" not in chapter
    # Untitled: no word for its type is printed.
    assert '<div class="callout callout-note" data-callout="note">\n<p>An untitled box.</p>' in chapter
    assert "<blockquote>\n<p>Every harbour keeps one ghost.</p>" in chapter
    assert "TODO" not in chapter and "boat's name" not in chapter
    assert ".callout {" in css
    assert ".callout-letter { background-color: #f7f1e6; }" in css
    # A colour set only for a screen theme does not print.
    assert ".callout-note {" not in css


def test_typst_calls_the_styles_callout_with_title_and_fill(tmp_path: Path):
    root = _novel(tmp_path)
    from proseview.export import prepare_book

    book = prepare_book(root, Config.load(root))
    source = typst_source(book, PdfOptions(layout="print", style=load_style("classic")))
    assert '#callout("letter", title: [A #emph[letter], undated], fill: rgb("#f7f1e6"))[' in source
    assert '#callout("note", title: none, fill: none)[An untitled box\\.]' in source
    assert "#quote(block: true)[Every harbour keeps one ghost\\.]" in source
    assert "boat's name" not in source


@pytest.mark.parametrize(("style", "fmt"), [("classic", "pdf-print"), ("modern", "pdf-share"), ("manuscript", "pdf-share")])
def test_a_book_with_callouts_compiles_in_every_pdf_style(tmp_path: Path, style: str, fmt: str):
    result = _export(tmp_path, _novel(tmp_path), fmt, style=style)
    assert result.path.read_bytes().startswith(b"%PDF")


def test_a_style_of_your_own_without_callout_still_compiles(tmp_path: Path):
    root = _novel(tmp_path)
    own = root / "styles" / "mine"
    own.mkdir(parents=True)
    template = load_style("classic").pdf_template
    start = template.index("// A letter, a text message, a sidebar")
    (own / "pdf.typ").write_text(template[:start], encoding="utf-8")
    result = _export(tmp_path, root, "pdf-share", style="styles/mine")
    assert result.path.read_bytes().startswith(b"%PDF")


def test_word_puts_a_callout_in_boxed_styles_shaded_per_type(tmp_path: Path):
    result = _export(tmp_path, _novel(tmp_path), "docx")
    data = result.path.read_bytes()
    paragraphs = [(r["style"], "".join(t for t, _ in r["runs"])) for r in document_paragraphs(data) if "table" not in r]

    assert ("CalloutTitle-letter", "A letter, undated") in paragraphs
    assert ("Callout-letter", "Mara, if you are reading this, the boat has gone.") in paragraphs
    assert ("Callout", "An untitled box.") in paragraphs
    assert ("BlockText", "Every harbour keeps one ghost.") in paragraphs
    assert not any("[!" in text or "boat's name" in text for _, text in paragraphs)

    with zipfile.ZipFile(result.path) as archive:
        styles = archive.read("word/styles.xml").decode()
    assert 'w:styleId="Callout"><w:name w:val="Callout"/>' in styles
    assert "<w:pBdr>" in styles
    assert 'w:styleId="Callout-letter"' in styles and 'w:fill="F7F1E6"' in styles
    assert 'w:styleId="Callout-note"' not in styles


def test_a_style_can_ship_colours_and_the_project_wins(tmp_path: Path):
    root = _novel(tmp_path, config="callouts:\n  letter:\n    background:\n      print: \"#eeeeee\"\n")
    own = root / "styles" / "warm"
    own.mkdir(parents=True)
    (own / "style.yaml").write_text(
        "extends: classic\ncallouts:\n  letter:\n    background: \"#ffeedd\"\n  note:\n    background: \"#ddeeff\"\n",
        encoding="utf-8",
    )
    css = check_epub(_export(tmp_path, root, "epub", style="styles/warm").path)["OEBPS/styles/book.css"].decode()
    assert ".callout-letter { background-color: #eeeeee; }" in css
    assert ".callout-note { background-color: #ddeeff; }" in css


def test_the_word_preview_shows_the_box_and_its_shading(tmp_path: Path):
    from proseview.docx import preview_pages

    result = _export(tmp_path, _novel(tmp_path), "docx")
    files, pages = preview_pages(result.path.read_bytes(), "book", load_style("classic"))
    page = next(data.decode() for name, data in files.items() if name.endswith(".xhtml") and b"Mara" in data)
    assert '<p class="Callout Callout-letter CalloutTitle-letter">A <em>letter</em>, undated</p>' in page
    assert ".Callout-letter{background:#F7F1E6}" in page
    assert ".Callout{" in page and "border:0.5pt solid #888" in page
