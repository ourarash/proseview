"""Tests for the book styles: Classic, Modern, Romance and Manuscript.

Covers:
- which styles ship and what each can make; Modern and Romance build on
  Classic (its stylesheet first, then theirs; its PDF layout with their
  choices); a style cannot extend itself or set unknown layout choices
- Modern and Romance lay out every selection type as sound EPUBs (EPUBCheck
  where installed) and PDFs, with their own chapter openers
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.book import Selection  # noqa: E402
from proseview.book_styles import StyleError, available_styles, load_style  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.epub_check import structural_problems  # noqa: E402
from proseview.export import export_book, prepare_book  # noqa: E402
from proseview.pdf import PdfOptions, typst_source  # noqa: E402
from proseview.pdf_check import pdf_facts  # noqa: E402

from tests.test_epub import EPUBCHECK, SELECTIONS  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"
BOOK_STYLES = ["classic", "modern", "romance"]


def test_four_styles_ship_and_say_what_they_make():
    assert available_styles() == ["classic", "manuscript", "modern", "romance"]
    for name in BOOK_STYLES:
        assert load_style(name).formats == ("epub", "pdf-print", "pdf-share")
    assert load_style("manuscript").formats == ("pdf-share",)


def test_modern_and_romance_build_on_classic():
    classic, modern, romance = (load_style(n) for n in BOOK_STYLES)
    assert modern.css.startswith(classic.css) and "/* ---- Modern ---- */" in modern.css
    assert modern.pdf_template == classic.pdf_template == romance.pdf_template
    assert dict(modern.pdf_settings) == {
        "body_font": "Libertinus Serif", "heading_font": "Noto Sans", "title_font": "", "opener": "modern",
        "drop_cap": False, "ornament": "",
    }
    assert dict(romance.pdf_settings)["opener"] == "romance" and dict(romance.pdf_settings)["drop_cap"] is True
    assert modern.chapter_numbering == romance.chapter_numbering == "number"


@pytest.mark.parametrize("yaml, message", [
    ("extends: mine\n", "cannot extend itself"),
    ("extends: classic\npdf:\n  colour: red\n", "pdf may set"),
    ("extends: classic\npdf:\n  opener: baroque\n", "pdf.opener must be one of"),
])
def test_a_bad_style_is_explained(tmp_path: Path, yaml: str, message: str):
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "style.yaml").write_text(yaml, encoding="utf-8")
    with pytest.raises(StyleError, match=message):
        load_style(str(folder))


def test_a_style_of_your_own_can_extend_a_built_in_one(tmp_path: Path):
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "style.yaml").write_text("name: Mine\nextends: modern\nscene_break: '~'\n", encoding="utf-8")
    (folder / "epub.css").write_text("body { color: #222; }\n", encoding="utf-8")
    mine = load_style(str(folder))
    assert mine.name == "Mine" and mine.scene_break == "~"
    assert mine.css.endswith("body { color: #222; }\n") and "Modern" in mine.css
    assert dict(mine.pdf_settings)["opener"] == "modern"


@pytest.mark.parametrize("style", ["modern", "romance"])
@pytest.mark.parametrize("kind", list(SELECTIONS))
def test_every_selection_type_is_sound_in_each_style(tmp_path: Path, style: str, kind: str):
    cfg = Config.load(DEMO)
    path = export_book(DEMO, cfg, tmp_path / "b.epub", style=style, selection=SELECTIONS[kind]).path
    assert structural_problems(path) == []
    for fmt in ("pdf-print", "pdf-share"):
        result = export_book(DEMO, cfg, tmp_path / f"b-{fmt}.pdf", style=style, fmt=fmt, selection=SELECTIONS[kind])
        assert result.pages > 0 and pdf_facts(result.path.read_bytes()).unembedded_fonts == ()


def test_modern_opens_chapters_with_a_numeral_and_no_drop_cap(tmp_path: Path):
    path = export_book(DEMO, Config.load(DEMO), tmp_path / "m.epub", style="modern",
                       selection=Selection(picks=(("chapter", "2"),))).path
    with zipfile.ZipFile(path) as archive:
        chapter = archive.read("OEBPS/text/chapter-001.xhtml").decode()
        nav = archive.read("OEBPS/text/nav.xhtml").decode()
    assert '<span class="chapter-number">2</span>' in chapter
    assert "2. II. The Pool of Tears" in nav
    source = typst_source(prepare_book(DEMO, Config.load(DEMO), Selection(picks=(("chapter", "2"),))),
                          PdfOptions(layout="print", style=load_style("modern")))
    assert 'heading-font: "Noto Sans"' in source and "drop-cap: false" in source and ", n: 2)" in source


def test_modern_embeds_its_heading_font(tmp_path: Path):
    import re

    result = export_book(DEMO, Config.load(DEMO), tmp_path / "m.pdf", style="modern", fmt="pdf-print",
                         selection=Selection(picks=(("chapter", "2"),)))
    fonts = {n.split(b"+")[-1] for n in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+-]+)", result.path.read_bytes())}
    assert any(name.startswith(b"NotoSans") for name in fonts)
    assert any(name.startswith(b"LibertinusSerif") for name in fonts)


def test_romance_frames_the_numeral_in_florals():
    source = typst_source(prepare_book(DEMO, Config.load(DEMO), Selection(picks=(("chapter", "2"),))),
                          PdfOptions(layout="print", style=load_style("romance")))
    assert 'ornament: "❦"' in source and 'scene-break: "❦"' in source


@pytest.mark.skipif(EPUBCHECK is None, reason="EPUBCheck is not installed")
@pytest.mark.parametrize("version", ["epub3", "epub2"])
@pytest.mark.parametrize("style", ["modern", "romance"])
def test_epubcheck_passes_for_modern_and_romance(tmp_path: Path, style: str, version: str):
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    path = export_book(root, Config.load(root), tmp_path / "b.epub", style=style, author="Lewis Carroll",
                       dedication="For Alice", epub_version=version).path
    result = subprocess.run([*EPUBCHECK, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_romance_sets_titles_in_a_script_it_carries(tmp_path: Path):
    """Great Vibes is bundled, embedded in the PDF, and packed into the EPUB."""
    import re

    romance = load_style("romance")
    assert dict(romance.pdf_settings)["title_font"] == "Great Vibes"
    assert [font.name for font in romance.epub_fonts] == ["GreatVibes-Regular.ttf"]

    result = export_book(DEMO, Config.load(DEMO), tmp_path / "r.pdf", style="romance", fmt="pdf-print",
                         selection=Selection(picks=(("chapter", "2"),)))
    fonts = {n.split(b"+")[-1] for n in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+-]+)", result.path.read_bytes())}
    assert b"GreatVibes-Regular" in fonts
    assert pdf_facts(result.path.read_bytes()).unembedded_fonts == ()

    for version, media_type in (("epub3", "font/ttf"), ("epub2", "application/x-font-truetype")):
        path = export_book(DEMO, Config.load(DEMO), tmp_path / f"r-{version}.epub", style="romance",
                           epub_version=version).path
        with zipfile.ZipFile(path) as archive:
            opf = archive.read("OEBPS/content.opf").decode()
            css = archive.read("OEBPS/styles/book.css").decode()
            assert archive.read("OEBPS/fonts/GreatVibes-Regular.ttf")[:4] == b"\x00\x01\x00\x00"
        assert f'href="fonts/GreatVibes-Regular.ttf" media-type="{media_type}"' in opf
        assert 'src: url("../fonts/GreatVibes-Regular.ttf")' in css
        assert structural_problems(path) == []


def test_other_styles_carry_no_fonts(tmp_path: Path):
    for style in ("classic", "modern"):
        assert load_style(style).epub_fonts == ()
        path = export_book(DEMO, Config.load(DEMO), tmp_path / f"{style}.epub", style=style,
                           selection=Selection(picks=(("chapter", "1"),))).path
        with zipfile.ZipFile(path) as archive:
            assert not [n for n in archive.namelist() if n.startswith("OEBPS/fonts/")]
