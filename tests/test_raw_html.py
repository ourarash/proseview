"""Tests for raw HTML in scenes: understood by both book renderers, never printed.

Covers:
- reading a fragment: ``<img>`` with straight or curly quotes, over several
  lines, with a ``/repo-asset/`` address and a width; ``<br>``; marks;
  paragraphs and centring; dropped tags keeping their text; script, style
  and iframe dropped with their contents
- the EPUB: an HTML image is embedded like a Markdown one, unbalanced tags
  still make well-formed pages, a missing HTML image names its scene
- the PDF: the same images and marks, with Typst code in HTML text still
  escaped
- Markdown images pointing at ``/repo-asset/`` too
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.book import ExportError, Selection  # noqa: E402
from proseview.book_styles import load_style  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.epub_check import structural_problems  # noqa: E402
from proseview.export import export_book, prepare_book  # noqa: E402
from proseview.pdf import PdfOptions, typst_source  # noqa: E402
from proseview.raw_html import (  # noqa: E402
    HtmlBreak, HtmlClose, HtmlImage, HtmlOpen, HtmlText, read_html, repository_src,
)

PNG = (REPO_ROOT / "docs" / "images" / "dashboard.png").read_bytes()

# As Ari's prologue writes it, curly quotes and all, over three lines.
CURLY_IMG = (
    "<img\nsrc=“/repo-asset/manuscript/ch01/assets/king.png”\n"
    "alt=“Shahrzad holds an unfinished manuscript in the dawn light”\nwidth=“600”>"
)


@pytest.fixture
def novel(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript" / "ch01" / "assets").mkdir(parents=True)
    (root / "manuscript" / "ch01" / "assets" / "king.png").write_bytes(PNG)
    return root


def _scene(root: Path, body: str) -> None:
    (root / "manuscript" / "ch01" / "01-the-king.md").write_text(
        "---\ntitle: The King\nchapter: The Prologue\n---\n\nYou think you know the story.\n\n" + body + "\n",
        encoding="utf-8",
    )


def _epub_text(tmp_path: Path, root: Path) -> str:
    path = export_book(root, Config.load(root), tmp_path / "book.epub",
                       selection=Selection(picks=(("chapter", "1"),))).path
    assert structural_problems(path) == []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        return "\n".join(archive.read(n).decode() for n in names if n.endswith(".xhtml")) + "\n" + "\n".join(names)


def _typst(root: Path) -> str:
    book = prepare_book(root, Config.load(root), Selection(picks=(("chapter", "1"),)))
    return typst_source(book, PdfOptions(layout="print", style=load_style("classic")))


# -- reading a fragment -------------------------------------------------------------


@pytest.mark.parametrize("tag", [
    '<img src="/repo-asset/manuscript/ch01/assets/king.png" alt="The king" width="600">',
    "<img alt='The king' width=600 src='/repo-asset/manuscript/ch01/assets/king.png'/>",
    '<IMG\n  SRC="/repo-asset/manuscript/ch01/assets/king.png"\n  ALT="The king"\n  WIDTH="600px">',
    "<img src=“/repo-asset/manuscript/ch01/assets/king.png” alt=“The king” width=“600”>",
])
def test_an_img_tag_is_an_image_however_it_is_written(tag: str):
    assert read_html(tag) == [HtmlImage("/manuscript/ch01/assets/king.png", "The king", 1.0)]


def test_width_is_a_share_of_the_page():
    assert read_html('<img src="a.png" width="300">')[0].width == 0.5
    assert read_html('<img src="a.png" width="40%">')[0].width == 0.4
    assert read_html('<img src="a.png" style="width: 150px">')[0].width == 0.25
    assert read_html('<img src="a.png" width="2000">')[0].width == 1.0
    assert read_html('<img src="a.png">')[0].width is None


def test_marks_breaks_paragraphs_and_centring():
    assert read_html('<p align="center">One<br>two <b>bold</b> <sup>2</sup></p>') == [
        HtmlOpen("para"), HtmlOpen("center"), HtmlText("One"), HtmlBreak(), HtmlText("two "),
        HtmlOpen("strong"), HtmlText("bold"), HtmlClose("strong"), HtmlText(" "),
        HtmlOpen("sup"), HtmlText("2"), HtmlClose("sup"), HtmlClose("center"), HtmlClose("para"),
    ]


def test_other_tags_go_and_their_text_stays_but_scripts_go_entirely():
    events = read_html(
        '<span class="x">kept</span><script>alert(1)</script><style>p{}</style>'
        '<iframe src="https://example.com">fallback</iframe> <font color=red>also kept</font>'
    )
    assert all(isinstance(e, HtmlText) for e in events)
    assert "".join(e.text for e in events) == "kept also kept"


def test_repo_asset_addresses_read_as_paths_in_the_book():
    assert repository_src("/repo-asset/manuscript/ch01/a%20b.png?v=2") == "/manuscript/ch01/a b.png"
    assert repository_src("images/a.png") == "images/a.png"


# -- the EPUB ---------------------------------------------------------------------------


def test_an_html_image_is_embedded_in_the_epub(tmp_path: Path, novel: Path):
    _scene(novel, CURLY_IMG + "\n\nThe rest of the scene.")
    text = _epub_text(tmp_path, novel)

    assert "<div class=\"figure\"><img class=\"html-image\" src=\"../images/image-001.png\" " in text
    assert 'alt="Shahrzad holds an unfinished manuscript in the dawn light" style="width: 100%" />' in text
    assert "OEBPS/images/image-001.png" in text
    assert "&lt;img" not in text and "repo-asset" not in text


def test_inline_html_keeps_its_meaning_and_never_its_markup(tmp_path: Path, novel: Path):
    _scene(novel, "She said <b>never <i>again</i></b>, then <span>whispered</span> E=mc<sup>2</sup>"
                  "<br>and left. <u>Unclosed <b>bold <script>steal()</script>")
    text = _epub_text(tmp_path, novel)

    assert "<strong>never <em>again</em></strong>, then whispered E=mc<sup>2</sup><br />and left." in text
    assert "steal()" not in text and "&lt;" not in text and "<u>" not in text
    assert "Unclosed <strong>bold </strong></p>" in text


def test_a_centred_html_block_is_centred(tmp_path: Path, novel: Path):
    _scene(novel, '<div align="center">\n<p>THE END</p>\n</div>')
    assert '<p class="html-block center">THE END</p>' in _epub_text(tmp_path, novel)


def test_a_missing_html_image_names_its_scene(tmp_path: Path, novel: Path):
    _scene(novel, '<img src="/repo-asset/manuscript/ch01/assets/gone.png" alt="Gone">')
    with pytest.raises(ExportError) as caught:
        export_book(novel, Config.load(novel), tmp_path / "x.epub")
    assert caught.value.scene == "ch01/01-the-king" and "can't be found" in str(caught.value)


def test_a_markdown_image_may_use_the_dashboard_address(tmp_path: Path, novel: Path):
    _scene(novel, "![The king](/repo-asset/manuscript/ch01/assets/king.png)")
    assert "OEBPS/images/image-001.png" in _epub_text(tmp_path, novel)


# -- the PDF ----------------------------------------------------------------------------


def test_an_html_image_is_laid_out_in_the_pdf(tmp_path: Path, novel: Path):
    _scene(novel, CURLY_IMG)
    source = _typst(novel)
    assert '#book-image("/manuscript/ch01/assets/king.png", alt: "Shahrzad holds an unfinished manuscript in the dawn light", width: 100%)' in source
    result = export_book(novel, Config.load(novel), tmp_path / "book.pdf", fmt="pdf-print")
    data = result.path.read_bytes()
    assert b"/Subtype /Image" in data or b"/Subtype/Image" in data


def test_html_marks_reach_the_pdf_and_typst_code_inside_them_stays_text(tmp_path: Path, novel: Path):
    _scene(novel, "<b>#pagebreak()</b> <i>$x$</i> <sub>@ref</sub> <script>#set page(width: 1in)</script> end")
    source = _typst(novel)
    assert "#strong[\\#pagebreak\\(\\)] #emph[\\$x\\$] #sub[\\@ref]  end" in source
    assert "1in" not in source.split("#show: book", 1)[1]
    assert export_book(novel, Config.load(novel), tmp_path / "book.pdf", fmt="pdf-print").pages >= 1


def test_a_centred_html_block_is_centred_in_the_pdf(novel: Path):
    _scene(novel, '<center>THE END</center>')
    assert "#align(center)[THE END]" in _typst(novel)


def test_ari_style_prologue_exports_in_every_format(tmp_path: Path, novel: Path):
    _scene(novel, CURLY_IMG + "\n\nYou know how it begins.")
    for fmt in ("epub", "pdf-print", "pdf-share"):
        suffix = "epub" if fmt == "epub" else "pdf"
        result = export_book(novel, Config.load(novel), tmp_path / f"b-{fmt}.{suffix}", fmt=fmt)
        assert result.path.stat().st_size > len(PNG) // 2
    shutil.rmtree(tmp_path / "novel" / "exports", ignore_errors=True)
