"""Tests for the built-in EPUB writer and the export CLI.

Covers:
- every selection type on the demo book produces a structurally sound EPUB:
  mimetype first and stored, a manifest that matches the zip, well-formed
  XHTML, and links and anchors that resolve (EPUB 3 and EPUB 2)
- the Classic style's markup: chapter openers, scene breaks or scene titles,
  a single scene's header, no contents page for one chapter or scene
- images are copied in, and missing, remote, or escaping images fail clearly
- TODO and NOTE comments never reach the book, and raw HTML cannot break it
- the CLI's selection flags, saved selections, identifier, and exports/ folder
- EPUBCheck, when it is installed (``epubcheck`` on PATH, or EPUBCHECK_JAR
  pointing at the jar with Java available); skipped otherwise
"""

from __future__ import annotations

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
from proseview.config import Config, ExportSelection  # noqa: E402
from proseview.epub_check import structural_problems  # noqa: E402
from proseview.export import ExportError, export_book  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"
OPF_NS = "{http://www.idpf.org/2007/opf}"
XHTML_NS = "{http://www.w3.org/1999/xhtml}"

#: One of each selection type, named the way a writer would on the CLI.
SELECTIONS = {
    "whole book": None,
    "one scene": ExportSelection(picks=(("scene", "1.2"),)),
    "one chapter": ExportSelection(picks=(("chapter", "3"),)),
    "several chapters": ExportSelection(picks=(("chapter", "9"), ("chapter", "2-3"))),
    "hand-picked scenes": ExportSelection(picks=(("scene", "ch08/02-off-with-her-head"), ("scene", "1.1"))),
    "custom order": ExportSelection(picks=(("scene", "12.1"), ("chapter", "1")), order="custom"),
}


# -- a structural EPUB check -------------------------------------------------------


def check_epub(path: Path) -> dict[str, bytes]:
    """Assert the container-level rules readers rely on; return the files.

    Not a replacement for EPUBCheck, but it catches what a hand-written
    writer most easily gets wrong, and runs everywhere. The dashboard runs
    the same check after every export (:mod:`proseview.epub_check`).
    """
    assert structural_problems(path) == []
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _text(files: dict[str, bytes]) -> str:
    return "\n".join(data.decode("utf-8") for name, data in sorted(files.items()) if name.endswith(".xhtml"))


def _export(tmp_path: Path, root: Path = DEMO, name: str = "book.epub", **options) -> tuple[Path, object]:
    result = export_book(root, Config.load(root), tmp_path / name, **options)
    return result.path, result.book


# -- every selection type on the demo book -------------------------------------------


@pytest.mark.parametrize("version", ["epub3", "epub2"])
@pytest.mark.parametrize("kind", list(SELECTIONS))
def test_every_selection_type_is_a_sound_epub(tmp_path: Path, kind: str, version: str):
    path, book = _export(
        tmp_path, selection=SELECTIONS[kind], epub_version=version, appendix_folders=["plans"],
    )
    files = check_epub(path)

    contents_in_spine = "OEBPS/text/nav.xhtml" in files and b'idref="nav"' in files["OEBPS/content.opf"]
    assert contents_in_spine == book.has_contents
    assert "Appendix: Plans" in _text(files)


def test_the_demo_book_is_left_untouched(tmp_path: Path):
    before = (DEMO / ".proseview.yaml").read_bytes()
    _export(tmp_path)
    assert (DEMO / ".proseview.yaml").read_bytes() == before
    assert not (DEMO / "exports").exists()


# -- the Classic style's markup ----------------------------------------------------------


def _novel(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    scenes = {
        "ch01/01-opening.md": "---\ntitle: The Opening\nchapter: The Shop\n---\n\n# The Opening\n\nRena opened the shop.\n\nIt was \"early\" -- too early.\n",
        "ch01/02-late.md": "---\ntitle: Lowe Arrives\nchapter: The Shop\n---\n\nLowe arrived late.<!-- TODO: fix his entrance -->\n\n<!-- NOTE[plot]: he knows -->\n\nHe said <br> nothing.\n",
        "ch02/01-ledger.md": "The ledger balanced.\n\n## A heading inside the scene\n\nMore.\n",
    }
    for rel, text in scenes.items():
        path = root / "manuscript" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_chapters_open_with_words_and_a_drop_cap_paragraph(tmp_path: Path):
    path, _ = _export(tmp_path, _novel(tmp_path), title="Novel")
    chapter = check_epub(path)["OEBPS/text/chapter-001.xhtml"].decode()

    assert '<span class="chapter-number">Chapter One</span> <span class="chapter-title">The Shop</span>' in chapter
    # One short line: small capitals, but no drop cap hanging into the next paragraph.
    assert '<p class="opener short">Rena opened the shop.</p>' in chapter
    # Smart punctuation, as pandoc gave it.
    assert "It was “early” – too early." in chapter


def test_a_long_opening_paragraph_gets_the_drop_cap(tmp_path: Path):
    path, _ = _export(tmp_path, selection=ExportSelection(picks=(("chapter", "1"),)))
    chapter = check_epub(path)["OEBPS/text/chapter-001.xhtml"].decode()
    assert '<p class="opener">Alice was beginning' in chapter


def test_a_chapter_named_only_by_its_folder_shows_just_the_number(tmp_path: Path):
    path, _ = _export(tmp_path, _novel(tmp_path))
    chapter = check_epub(path)["OEBPS/text/chapter-002.xhtml"].decode()

    assert '<h1 class="chapter-heading"><span class="chapter-number">Chapter Two</span></h1>' in chapter
    assert "ch02" not in chapter.split("<body", 1)[1].replace('id="chapter-2"', "")
    # Headings inside a scene sit below the chapter's.
    assert "<h4>A heading inside the scene</h4>" in chapter


def test_scene_titles_are_hidden_behind_scene_breaks_by_default(tmp_path: Path):
    path, _ = _export(tmp_path, _novel(tmp_path))
    files = check_epub(path)
    chapter = files["OEBPS/text/chapter-001.xhtml"].decode()

    assert chapter.count('class="scene-break"') == 1
    assert "Lowe Arrives" not in chapter
    assert '<p class="first">Lowe arrived late.</p>' in chapter
    assert "Lowe Arrives" not in files["OEBPS/text/nav.xhtml"].decode()


def test_scene_titles_can_be_shown_as_headings(tmp_path: Path):
    path, _ = _export(tmp_path, _novel(tmp_path), scene_titles=True)
    files = check_epub(path)
    chapter = files["OEBPS/text/chapter-001.xhtml"].decode()

    assert 'class="scene-break"' not in chapter
    assert '<h2 class="scene-title">Lowe Arrives</h2>' in chapter
    assert 'href="chapter-001.xhtml#scene-1-2">Lowe Arrives</a>' in files["OEBPS/text/nav.xhtml"].decode()


def test_the_config_can_turn_scene_titles_on(tmp_path: Path):
    root = _novel(tmp_path)
    (root / ".proseview.yaml").write_text("export:\n  scene_titles: true\n", encoding="utf-8")
    path, _ = _export(tmp_path, root)
    assert 'class="scene-title"' in check_epub(path)["OEBPS/text/chapter-001.xhtml"].decode()


def test_links_to_repository_files_keep_their_text_but_not_the_link(tmp_path: Path):
    root = _novel(tmp_path)
    (root / "manuscript" / "ch02" / "01-ledger.md").write_text(
        "See [Rena](../../story-bible/rena.md), [above](#top) and [the site](https://example.com).\n",
        encoding="utf-8",
    )
    path, _ = _export(tmp_path, root)
    chapter = check_epub(path)["OEBPS/text/chapter-002.xhtml"].decode()

    assert 'See Rena, above and <a href="https://example.com">the site</a>.' in chapter


def test_comments_are_dropped_and_raw_html_cannot_break_the_page(tmp_path: Path):
    path, _ = _export(tmp_path, _novel(tmp_path))
    text = _text(check_epub(path))

    assert "TODO" not in text and "fix his entrance" not in text and "he knows" not in text
    # Understood, not printed: an unclosed <br> is a line break, and the
    # page stays well-formed XHTML (check_epub parsed every page).
    assert "He said <br /> nothing." in text
    assert "&lt;br" not in text


def test_a_single_scene_has_a_small_header_and_no_contents(tmp_path: Path):
    path, book = _export(
        tmp_path, _novel(tmp_path), title="Novel", selection=ExportSelection(picks=(("scene", "1.2"),)),
    )
    files = check_epub(path)
    page = files["OEBPS/text/scene.xhtml"].decode()

    assert book.kind == "scene"
    assert '<p class="book-title">Novel</p>' in page
    assert '<p class="scene-chapter">Chapter One · The Shop</p>' in page
    assert '<h1 class="scene-heading">Lowe Arrives</h1>' in page
    assert "OEBPS/text/title.xhtml" not in files
    assert b'idref="nav"' not in files["OEBPS/content.opf"]


def test_a_partial_book_says_which_chapters_on_its_title_page(tmp_path: Path):
    path, _ = _export(tmp_path, selection=ExportSelection(picks=(("chapter", "3"), ("chapter", "7-9"))))
    assert '<p class="note">Chapters 3, 7–9</p>' in check_epub(path)["OEBPS/text/title.xhtml"].decode()


@pytest.mark.parametrize("plain, typeset", [
    ("Alice's Adventures", "Alice’s Adventures"),
    ('The "Mad" Hatter', "The “Mad” Hatter"),
    ("'Tis the Season", "‘Tis the Season"),
    ("Wait... no -- yes --- maybe", "Wait… no – yes — maybe"),
    ("O'Brien & Sons", "O’Brien & Sons"),
])
def test_smart_punctuation_matches_the_prose(plain: str, typeset: str):
    from proseview.book import smart_punctuation

    assert smart_punctuation(plain) == typeset


def test_title_page_headings_and_metadata_get_curly_quotes(tmp_path: Path):
    path, _ = _export(tmp_path, title="Alice's Adventures", author="Lewis 'Dodgson' Carroll")
    files = check_epub(path)

    title_page = files["OEBPS/text/title.xhtml"].decode()
    assert '<h1 class="title">Alice’s Adventures</h1>' in title_page
    assert "Lewis ‘Dodgson’ Carroll" in title_page
    assert "<dc:title>Alice’s Adventures</dc:title>" in files["OEBPS/content.opf"].decode()
    assert "Alice's" not in files["OEBPS/toc.ncx"].decode()


def test_the_drop_cap_spans_two_lines_and_no_more():
    """A float taller than two lines pushes the third line in around it."""
    import re

    css = (REPO_ROOT / "proseview" / "book_styles" / "classic" / "epub.css").read_text()
    body_line = float(re.search(r"body \{[^}]*line-height: ([\d.]+)", css).group(1))
    rule = re.search(r"p\.opener::first-letter \{([^}]*)\}", css).group(1)
    size = float(re.search(r"font-size: ([\d.]+)em", rule).group(1))
    line = float(re.search(r"line-height: ([\d.]+)", rule).group(1))
    top = float(re.search(r"margin: ([\d.]+)em", rule).group(1))

    assert size * (line + top) < 2 * body_line


def test_metadata_carries_title_author_language_and_identifier(tmp_path: Path):
    path, _ = _export(
        tmp_path, _novel(tmp_path), title="A Novel & More", author="Ari", language="en-GB",
        identifier="urn:uuid:0b6f2d8e-5b0e-4a63-9c1e-2a1c5f9c8d11",
    )
    opf = check_epub(path)["OEBPS/content.opf"].decode()

    assert "<dc:title>A Novel &amp; More</dc:title>" in opf
    assert '<dc:creator id="creator">Ari</dc:creator>' in opf
    assert "<dc:language>en-GB</dc:language>" in opf
    assert ">urn:uuid:0b6f2d8e-5b0e-4a63-9c1e-2a1c5f9c8d11</dc:identifier>" in opf
    assert '<meta property="schema:accessMode">textual</meta>' in opf


def test_cover_and_extra_css_are_packaged(tmp_path: Path):
    root = _novel(tmp_path)
    (root / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    (root / "extra.css").write_text("p { color: black; }\n", encoding="utf-8")

    path, _ = _export(tmp_path, root, cover_image=root / "cover.png", css=[root / "extra.css"])
    files = check_epub(path)

    assert "OEBPS/images/cover.png" in files
    assert 'properties="cover-image"' in files["OEBPS/content.opf"].decode()
    assert files["OEBPS/styles/extra-1.css"] == b"p { color: black; }\n"
    assert '../styles/book.css" />\n    <link rel="stylesheet" type="text/css" href="../styles/extra-1.css"' in (
        files["OEBPS/text/chapter-001.xhtml"].decode()
    )


def test_an_unknown_style_lists_the_built_in_ones(tmp_path: Path):
    with pytest.raises(ExportError, match="Built-in styles: classic"):
        _export(tmp_path, _novel(tmp_path), style="baroque")


def test_a_style_folder_in_the_book_can_be_used(tmp_path: Path):
    root = _novel(tmp_path)
    style = root / "styles" / "plain"
    style.mkdir(parents=True)
    (style / "epub.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (style / "style.yaml").write_text("chapter_numbering: numerals\nscene_break: '~'\n", encoding="utf-8")

    path, _ = _export(tmp_path, root, style="styles/plain")
    files = check_epub(path)

    assert files["OEBPS/styles/book.css"] == b"body { margin: 0; }\n"
    chapter = files["OEBPS/text/chapter-001.xhtml"].decode()
    assert "Chapter 1</span>" in chapter
    assert '<span aria-hidden="true">~</span>' in chapter


# -- images ------------------------------------------------------------------------------


def _with_image(tmp_path: Path, markdown: str) -> Path:
    root = _novel(tmp_path)
    (root / "manuscript" / "ch02" / "01-ledger.md").write_text(f"The ledger.\n\n{markdown}\n", encoding="utf-8")
    return root


def test_a_scene_image_is_copied_into_the_book(tmp_path: Path):
    root = _with_image(tmp_path, "![The ledger page](images/ledger.png)\n\n![Again](images/ledger.png)")
    (root / "manuscript" / "ch02" / "images").mkdir()
    (root / "manuscript" / "ch02" / "images" / "ledger.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    path, _ = _export(tmp_path, root)
    files = check_epub(path)

    assert [n for n in files if n.startswith("OEBPS/images/")] == ["OEBPS/images/image-001.png"]
    assert '<img src="../images/image-001.png" alt="The ledger page" />' in files["OEBPS/text/chapter-002.xhtml"].decode()


@pytest.mark.parametrize("markdown,message", [
    ("![Lost](images/missing.png)", "Scene '01 Ledger' .*has an image that can't be found: images/missing.png"),
    ("![Web](https://example.com/a.png)", "image from the web"),
    ("![Out](../../../../outside.png)", "outside the repository"),
])
def test_bad_images_fail_with_the_scene_named(tmp_path: Path, markdown: str, message: str):
    (tmp_path / "outside.png").write_bytes(b"x")
    with pytest.raises(ExportError, match=message):
        _export(tmp_path, _with_image(tmp_path, markdown))


# -- the command line -----------------------------------------------------------------------


def _git_novel(tmp_path: Path) -> Path:
    root = _novel(tmp_path)
    (root / ".git").mkdir()
    (root / ".gitignore").write_text("*.tmp", encoding="utf-8")
    return root


def test_cli_exports_to_a_dated_file_in_exports_and_ignores_it(tmp_path: Path, capsys):
    root = _git_novel(tmp_path)

    assert cli.main(["export", "--root", str(root), "--title", "My Novel"]) == 0

    written = list((root / "exports").glob("*.epub"))
    assert len(written) == 1 and written[0].name.startswith("my-novel-20")
    check_epub(written[0])
    assert (root / ".gitignore").read_text(encoding="utf-8") == (
        "*.tmp\n\n# Books written by `proseview export`\nexports/\n"
    )
    out = capsys.readouterr().out
    assert "Added exports/ to .gitignore" in out
    assert "3 scenes across 2 chapters" in out

    # A second export reuses the identifier and leaves .gitignore alone.
    identifier = Config.load(root).export.identifier
    assert identifier.startswith("urn:uuid:")
    assert cli.main(["export", "--root", str(root), "--title", "My Novel"]) == 0
    assert Config.load(root).export.identifier == identifier
    assert (root / ".gitignore").read_text(encoding="utf-8").count("exports/") == 1
    with zipfile.ZipFile(written[0]) as book:
        assert identifier in book.read("OEBPS/content.opf").decode()


def test_cli_parts_of_the_book_get_their_own_file_names(tmp_path: Path):
    root = _git_novel(tmp_path)
    cli.main(["export", "--root", str(root), "--chapters", "2"])
    cli.main(["export", "--root", str(root), "--scenes", "1.2"])
    cli.main(["export", "--root", str(root), "--scenes", "1.1", "--chapters", "2"])

    names = sorted(p.name.rsplit("-", 3)[0] for p in (root / "exports").glob("*.epub"))
    assert names == ["novel-chapter-2", "novel-scene-lowe-arrives", "novel-selection"]


def test_cli_saves_and_reuses_a_named_selection(tmp_path: Path, capsys):
    root = _git_novel(tmp_path)
    out = tmp_path / "beta.epub"

    assert cli.main([
        "export", "--root", str(root), "--scenes", "2.1", "--chapters", "1",
        "--order", "custom", "--save-selection", "Beta one", "--output", str(out),
    ]) == 0
    saved = Config.load(root).export.selection("Beta one")
    assert saved.picks == (("scene", "ch02/01-ledger"), ("chapter", "ch01")) and saved.order == "custom"

    out.unlink()
    assert cli.main(["export", "--root", str(root), "--selection", "beta one", "--output", str(out)]) == 0
    files = check_epub(out)
    assert sorted(n for n in files if "chapter-" in n) == [
        "OEBPS/text/chapter-001.xhtml", "OEBPS/text/chapter-002.xhtml",
    ]
    # Custom order: chapter two's scene first.
    assert "Chapter Two" in files["OEBPS/text/chapter-001.xhtml"].decode()

    capsys.readouterr()
    assert cli.main(["export", "--root", str(root), "--list-selections"]) == 0
    assert "Beta one: scene ch02/01-ledger, chapter ch01 (custom order)" in capsys.readouterr().out


@pytest.mark.parametrize("argv,message", [
    (["--selection", "nope"], "No saved selection called 'nope'"),
    (["--selection", "x", "--chapters", "1"], "not both"),
    (["--save-selection", "x"], "needs --chapters or --scenes"),
    (["--chapters", "9"], "no chapter 9"),
    (["--format", "pdf"], None),
])
def test_cli_rejects_bad_requests_without_writing_anything(tmp_path: Path, argv: list[str], message: str | None):
    root = _git_novel(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["export", "--root", str(root), *argv])
    if message:
        assert message in str(exc.value)
    assert not (root / ".proseview.yaml").exists()
    assert not (root / "exports").exists()


def test_cli_pandoc_engine_is_still_available(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("proseview.export.shutil.which", lambda _name: None)
    with pytest.raises(SystemExit, match="pandoc is required"):
        cli.main(["export", "--root", str(_git_novel(tmp_path)), "--engine", "pandoc"])


# -- EPUBCheck, when available ------------------------------------------------------------


def _epubcheck_command() -> list[str] | None:
    if shutil.which("epubcheck"):
        return ["epubcheck"]
    jar = os.environ.get("EPUBCHECK_JAR")
    java = shutil.which("java")
    if jar and java and Path(jar).is_file():
        probe = subprocess.run([java, "-version"], capture_output=True)
        if probe.returncode == 0:
            return [java, "-jar", jar]
    return None


EPUBCHECK = _epubcheck_command()


def test_epubcheck_is_present_where_it_is_required():
    """CI sets PROSEVIEW_REQUIRE_EPUBCHECK, so a broken install fails instead of skipping."""
    if os.environ.get("PROSEVIEW_REQUIRE_EPUBCHECK"):
        assert EPUBCHECK is not None, "EPUBCheck is required here: put epubcheck on PATH or set EPUBCHECK_JAR"


@pytest.mark.skipif(EPUBCHECK is None, reason="EPUBCheck is not installed (epubcheck on PATH, or EPUBCHECK_JAR and Java)")
@pytest.mark.parametrize("version", ["epub3", "epub2"])
@pytest.mark.parametrize("kind", list(SELECTIONS))
def test_epubcheck_passes_for_every_selection_type(tmp_path: Path, kind: str, version: str):
    path, _ = _export(tmp_path, selection=SELECTIONS[kind], epub_version=version,
                      appendix_folders=["plans"], author="Lewis Carroll")
    result = subprocess.run([*EPUBCHECK, str(path)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(EPUBCHECK is None, reason="EPUBCheck is not installed (epubcheck on PATH, or EPUBCHECK_JAR and Java)")
@pytest.mark.parametrize("version", ["epub3", "epub2"])
def test_epubcheck_passes_with_a_subtitle_cover_and_scene_titles(tmp_path: Path, version: str):
    """What the dashboard adds on top of the CLI's usual book."""
    cover = REPO_ROOT / "docs" / "images" / "dashboard.png"
    path, _ = _export(
        tmp_path, title="Alice's Adventures", subtitle="A \"Wonderland\" Tale", author="Lewis Carroll",
        cover_image=cover, scene_titles=True, epub_version=version,
    )
    result = subprocess.run([*EPUBCHECK, str(path)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
