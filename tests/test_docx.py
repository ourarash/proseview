"""Tests for Word export: the document, its two layouts, the preview and the check.

Covers:
- the package: every part Word needs, XML that parses, relationships that
  land, every style it uses defined (the same check a writer's export runs)
- the Manuscript layout: Times New Roman 12 pt, double-spaced, indented,
  the title page with contact details and word count, "Surname / TITLE /
  page" with a real PAGE field, numbering from the first text page
- the book layout: chapter openers in the style's manner, front matter on
  pages of their own, page numbers in the footer
- Markdown: emphasis, links, lists, quotes, code, tables, raw HTML and
  images; text that means something to XML stays text
- every selection type, Letter and A4, a file that is the same twice
- the preview read back from the file, the CLI's --format docx and .docx
  output names
"""

from __future__ import annotations

import datetime as dt
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import cli  # noqa: E402
from proseview.book import ExportError  # noqa: E402
from proseview.book_styles import load_style  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.docx import DocxOptions, build_docx, document_paragraphs, preview_pages  # noqa: E402
from proseview.docx_check import readiness, structural_problems  # noqa: E402
from proseview.export import export_book, prepare_book  # noqa: E402

from tests.test_epub import SELECTIONS  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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


def _docx(tmp_path: Path, root: Path, **options):
    return export_book(root, Config.load(root), tmp_path / "book.docx", fmt="docx", **options)


def _parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _document(path: Path):
    return ET.fromstring(_parts(path)["word/document.xml"])


def _paragraphs(path: Path) -> list[tuple[str, str]]:
    """``(style, text)`` for every paragraph, line breaks as newlines."""
    return [
        (record["style"], "".join(text for text, _ in record["runs"]))
        for record in document_paragraphs(path.read_bytes()) if "table" not in record
    ]


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


# -- the package -------------------------------------------------------------------------


@pytest.mark.parametrize("style", ["classic", "modern", "romance", "manuscript"])
def test_every_style_makes_a_sound_document(tmp_path: Path, book: Path, style: str):
    result = _docx(tmp_path, book, style=style, author="Lewis Carroll", contact="lewis@example.com")
    assert result.path.suffix == ".docx" and result.format == "docx" and result.pages == 0
    assert structural_problems(result.path) == []
    parts = _parts(result.path)
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml",
            "docProps/core.xml"} <= set(parts)
    core = parts["docProps/core.xml"].decode()
    assert "<dc:title>Alice</dc:title>" in core and "<dc:creator>Lewis Carroll</dc:creator>" in core
    # Every chapter is a Heading 1, so Word's navigation pane lists the book.
    headings = [text for kind, text in _paragraphs(result.path) if kind == "Heading1"]
    assert len([h for h in headings if "Rabbit-Hole" in h or "Tea-Party" in h]) == 2


@pytest.mark.parametrize("name", list(SELECTIONS))
def test_every_selection_makes_a_sound_document(tmp_path: Path, book: Path, name: str):
    for style in ("classic", "manuscript"):
        result = export_book(
            book, Config.load(book), tmp_path / f"{style}.docx", fmt="docx", style=style, selection=SELECTIONS[name],
        )
        assert structural_problems(result.path) == [], (name, style)
        sections = list(_document(result.path).iter(f"{W}sectPr"))
        # A title section only where the book has a title page.
        assert len(sections) == (2 if result.book.has_contents else 1), (name, style)


def test_the_same_book_is_the_same_file(tmp_path: Path, book: Path):
    stamp = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    whole = prepare_book(book, Config.load(book), title="Alice")
    options = DocxOptions(layout="book", style=load_style("classic"), timestamp=stamp)
    assert build_docx(whole, options) == build_docx(whole, options)


def test_a_broken_package_is_reported(tmp_path: Path, book: Path):
    path = _docx(tmp_path, book).path
    parts = _parts(path)
    parts["word/document.xml"] = parts["word/document.xml"].replace(b'w:val="Heading1"', b'w:val="Nope"', 1)
    del parts["word/settings.xml"]
    broken = tmp_path / "broken.docx"
    with zipfile.ZipFile(broken, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    problems = structural_problems(broken)
    assert any("not defined (Nope)" in p for p in problems)
    assert any("word/settings.xml, which is not in the file" in p for p in problems)
    assert structural_problems(tmp_path / "missing.docx")[0].startswith("the file cannot be opened")


# -- the Manuscript layout ------------------------------------------------------------------


def test_manuscript_is_standard_submission_format(tmp_path: Path, book: Path):
    result = _docx(tmp_path, book, style="manuscript", author="Lewis Carroll",
                   contact="lewis@example.com\n+44 1865 000000")
    parts = _parts(result.path)
    styles = ET.fromstring(parts["word/styles.xml"])
    normal = next(s for s in styles.iter(f"{W}style") if s.get(f"{W}styleId") == "Normal")
    assert normal.find(f".//{W}rFonts").get(f"{W}ascii") == "Times New Roman"
    assert normal.find(f".//{W}sz").get(f"{W}val") == "24"  # 12 pt
    assert normal.find(f".//{W}spacing").get(f"{W}line") == "480"  # double-spaced
    assert normal.find(f".//{W}ind").get(f"{W}firstLine") == "720"  # half an inch

    paragraphs = _paragraphs(result.path)
    assert paragraphs[0] == ("TitlePageDetails", "Lewis Carroll\tabout 26,000 words") or \
        paragraphs[0] == ("TitlePageDetails", "Lewis Carroll\tabout 27,000 words")
    assert paragraphs[1:3] == [("TitlePageDetails", "lewis@example.com"), ("TitlePageDetails", "+44 1865 000000")]
    assert ("Title", "Alice") in paragraphs and ("TitlePageAuthor", "by Lewis Carroll") in paragraphs
    assert ("Heading1", "Chapter 1\nI. Down the Rabbit-Hole") in paragraphs
    assert ("SceneBreak", "#") in paragraphs
    # No front or back matter: agents ask for the story.
    assert not any("Copyright" in text for _, text in paragraphs)

    header = parts["word/header1.xml"].decode()
    assert "Carroll / ALICE / " in header and "<w:instrText xml:space=\"preserve\"> PAGE </w:instrText>" in header
    first, body = list(_document(result.path).iter(f"{W}sectPr"))
    assert first.find(f"{W}headerReference") is None
    assert body.find(f"{W}headerReference") is not None
    assert body.find(f"{W}pgNumType").get(f"{W}start") == "1"
    assert body.find(f"{W}pgMar").get(f"{W}top") == "1440"

    checks = readiness(result.path, result.book, style="manuscript", contact="lewis@example.com")
    assert checks["ready"] and checks["headline"] == "Ready to send to an agent or editor"
    no_contact = readiness(result.path, result.book, style="manuscript")
    assert [f["fix"] for f in no_contact["findings"]] == ["contact"]


def test_paper_size_is_letter_or_a4(tmp_path: Path, book: Path):
    letter = _docx(tmp_path, book, style="manuscript", paper="letter").path
    size = next(_document(letter).iter(f"{W}pgSz"))
    assert (size.get(f"{W}w"), size.get(f"{W}h")) == ("12240", "15840")
    a4 = export_book(book, Config.load(book), tmp_path / "a4.docx", fmt="docx", paper="a4").path
    size = next(_document(a4).iter(f"{W}pgSz"))
    assert (size.get(f"{W}w"), size.get(f"{W}h")) == ("11906", "16838")


# -- the book layout -------------------------------------------------------------------------


def test_a_book_has_its_title_page_matter_and_chapter_openers(tmp_path: Path, book: Path):
    result = _docx(tmp_path, book, author="Lewis Carroll", subtitle="A Tale", dedication="For Alice Liddell")
    paragraphs = _paragraphs(result.path)
    assert paragraphs[:3] == [("Title", "Alice"), ("Subtitle", "A Tale"), ("TitlePageAuthor", "Lewis Carroll")]
    assert ("Dedication", "For Alice Liddell") in paragraphs
    assert any(kind == "MatterText" and text.startswith("Copyright ©") for kind, text in paragraphs)
    opener = paragraphs.index(("Heading1", "Chapter One\nI. Down the Rabbit-Hole"))
    assert paragraphs[opener + 1][0] == "FirstParagraph" and paragraphs[opener + 2][0] == "Normal"
    assert ("SceneBreak", "*   *   *") in paragraphs

    document = _parts(result.path)["word/document.xml"].decode()
    assert '<w:rStyle w:val="ChapterNumber"/>' in document and '<w:rStyle w:val="ChapterTitle"/>' in document
    # Front matter starts its own page without an empty paragraph to do it.
    records = document_paragraphs(result.path.read_bytes())
    dedication = next(r for r in records if r["style"] == "Dedication")
    assert dedication["break_before"]
    assert "PAGE" in _parts(result.path)["word/footer1.xml"].decode()


def test_styles_number_chapters_their_own_way(tmp_path: Path, book: Path):
    modern = _paragraphs(_docx(tmp_path, book, style="modern").path)
    assert ("Heading1", "1\nI. Down the Rabbit-Hole") in modern
    assert ("SceneBreak", "·  ·  ·") in modern
    titled = _paragraphs(_docx(tmp_path, book, scene_titles=True).path)
    plain = _paragraphs(_docx(tmp_path, book).path)
    assert ("Heading2", "Down, Down, Down") in titled and not any(kind == "Heading2" for kind, _ in plain)
    breaks = sum(kind == "SceneBreak" for kind, _ in plain)
    assert sum(kind == "SceneBreak" for kind, _ in titled) < breaks


# -- Markdown ----------------------------------------------------------------------------------


def test_markdown_becomes_word_formatting(tmp_path: Path):
    root = _tiny_novel(tmp_path, "\n".join([
        "She was *very* **sure** of ~~it~~, see [the map](https://example.com/?a=1&b=2) and [notes](notes.md).",
        "",
        "> A quoted line.",
        "",
        "- one",
        "- two",
        "",
        "1. first",
        "2. second",
        "",
        "```",
        "code <line>",
        "```",
        "",
        "| Name | Age |",
        "| ---- | --- |",
        "| Ann  | 30  |",
        "",
        "Raw <em>html</em> and x<sup>2</sup>, & <b>bold</b> < done.",
        "",
        "Bad \x0b control character.",
    ]))
    path = _docx(tmp_path, root).path
    assert structural_problems(path) == []
    records = document_paragraphs(path.read_bytes())
    runs = [run for record in records if "runs" in record for run in record["runs"]]
    assert ("very", ("i",)) in runs and ("sure", ("b",)) in runs and ("it", ("s",)) in runs
    assert ("the map", ("link", "style:Hyperlink")) in runs
    assert ("notes", ()) in runs  # a link into the repository keeps its text only
    assert ("html", ("i",)) in runs and ("2", ("sup",)) in runs and ("bold", ("b",)) in runs
    texts = [(r["style"], "".join(t for t, _ in r["runs"])) for r in records if "runs" in r]
    assert ("BlockText", "A quoted line.") in texts
    assert ("ListItem", "•\tone") in texts and ("ListItem", "2.\tsecond") in texts
    assert ("SourceCode", "code <line>") in texts
    assert any(t.startswith("Bad") and t.endswith("control character.") and "\x0b" not in t for _, t in texts)
    assert {"table": [["Name", "Age"], ["Ann", "30"]]} in records
    rels = _parts(path)["word/_rels/document.xml.rels"].decode()
    assert 'Target="https://example.com/?a=1&amp;b=2" TargetMode="External"' in rels


def test_images_are_embedded_and_sized_to_the_page(tmp_path: Path):
    root = _tiny_novel(tmp_path, "Before.\n\n![A map of the shop](map.png)\n\n<img src=\"map.png\" width=\"300\" alt=\"Half\">")
    (root / "manuscript" / "ch01" / "map.png").write_bytes(_png(1200, 600))
    path = _docx(tmp_path, root).path
    assert structural_problems(path) == []
    parts = _parts(path)
    assert [name for name in parts if name.startswith("word/media/")] == ["word/media/image1.png"]
    extents = [(int(e.get("cx")), int(e.get("cy"))) for e in _document(path).iter(
        "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent")]
    full, half = extents
    assert full == (6.5 * 914400, 3.25 * 914400)  # the text width of a Letter page
    assert half[0] == full[0] // 2
    assert b'descr="A map of the shop"' in parts["word/document.xml"]


def test_an_image_word_cannot_show_names_its_scene(tmp_path: Path):
    root = _tiny_novel(tmp_path, "![Map](map.webp)")
    (root / "manuscript" / "ch01" / "map.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    with pytest.raises(ExportError, match="Save a PNG or JPEG copy") as caught:
        _docx(tmp_path, root)
    assert caught.value.scene == "ch01/01-the-shop"


# -- the preview, the CLI ----------------------------------------------------------------------


def test_the_preview_is_a_page_per_chapter(tmp_path: Path, book: Path):
    path = _docx(tmp_path, book, author="Lewis Carroll").path
    files, pages = preview_pages(path.read_bytes(), "book", load_style("classic"))
    assert pages[0]["label"] == "Title page" and pages[0]["href"].startswith("word/page-")
    chapters = [page for page in pages if page["href"].startswith("word/chapter-")]
    assert len(chapters) == 12 and chapters[0]["label"] == "Chapter One · I. Down the Rabbit-Hole"
    page = files[chapters[0]["href"]].decode()
    assert ET.fromstring(page.split("\n", 2)[2]) is not None  # well-formed XHTML
    assert 'class="Heading1"' in page and "font-family:'Georgia'" in page


def test_cli_writes_a_word_document(tmp_path: Path, book: Path, capsys):
    assert cli.main(["export", "--root", str(book), "--format", "docx", "--style", "manuscript"]) == 0
    (written,) = (book / "exports").glob("*.docx")
    assert written.name.startswith("alice-manuscript-") and structural_problems(written) == []
    out = tmp_path / "named.docx"
    assert cli.main(["export", "--root", str(book), "--output", str(out), "--chapters", "1"]) == 0
    assert out.is_file() and structural_problems(out) == []
    with pytest.raises(SystemExit, match="does not match --format docx"):
        cli.main(["export", "--root", str(book), "--format", "docx", "--output", str(tmp_path / "x.pdf")])
