"""Tests for :mod:`proseview.export`.

Covers:
- scenes are collected in reading order, with dashboard title/chapter fallbacks
- the compiled Markdown groups chapters as ``#`` and scenes as ``##``
- a missing pandoc fails with an actionable message rather than a traceback
- a real EPUB is produced when pandoc is installed (skipped otherwise)
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

from proseview.config import Config  # noqa: E402
from proseview.export import (  # noqa: E402
    ExportError,
    build_manuscript_markdown,
    candidate_appendix_folders,
    collect_appendix_documents,
    collect_scene_documents,
    export_epub,
    scene_count_summary,
)

FIXTURE = REPO_ROOT / "fixtures" / "demo-repo"
HAS_PANDOC = shutil.which("pandoc") is not None


def _repo(tmp_path: Path) -> Path:
    chapter_one = tmp_path / "manuscript" / "ch01"
    chapter_two = tmp_path / "manuscript" / "ch02"
    chapter_one.mkdir(parents=True)
    chapter_two.mkdir(parents=True)
    (chapter_one / "01-opening.md").write_text(
        "---\ntitle: The Opening\nchapter: Chapter One\n---\n\n# The Opening\n\nRena opened the shop.\n",
        encoding="utf-8",
    )
    # No frontmatter: title and chapter must fall back to filename and folder.
    (chapter_one / "02-second-scene.md").write_text("Lowe arrived late.\n", encoding="utf-8")
    (chapter_two / "01-after.md").write_text(
        "---\ntitle: After\nchapter: Chapter Two\n---\n\n# After\n\nThe ledger balanced.\n",
        encoding="utf-8",
    )
    (chapter_one / "README.md").write_text("not a scene\n", encoding="utf-8")
    return tmp_path


def test_scenes_are_collected_in_reading_order_with_dashboard_fallbacks(tmp_path: Path):
    documents = collect_scene_documents(_repo(tmp_path), Config())

    # The untitled scene falls back to its stem exactly as the scene table does,
    # numeric prefix and all.
    assert [d.title for d in documents] == ["The Opening", "02 Second Scene", "After"]
    assert [d.chapter for d in documents] == ["Chapter One", "ch01", "Chapter Two"]
    # The README is not a scene, and the duplicated H1 is stripped from the body.
    assert all("not a scene" not in d.markdown for d in documents)
    assert documents[0].markdown == "Rena opened the shop."


def test_compiled_markdown_nests_scenes_under_chapter_headings(tmp_path: Path):
    documents = collect_scene_documents(_repo(tmp_path), Config())

    markdown = build_manuscript_markdown(
        documents, title="A Novel", author="Ari", language="en-GB", identifier="urn:test",
    )

    assert markdown.startswith("---\n")
    assert 'title: "A Novel"' in markdown
    assert 'author: "Ari"' in markdown
    assert 'lang: "en-GB"' in markdown
    # Chapter headings appear once each, in order, above their scenes.
    assert markdown.count("# Chapter One") == 1
    assert markdown.index("# Chapter One") < markdown.index("## The Opening") < markdown.index("# Chapter Two")
    assert "## After" in markdown
    assert "The ledger balanced." in markdown


def test_a_folder_with_no_markdown_fails_clearly(tmp_path: Path):
    """A missing ``manuscript/`` is no longer an error by itself.

    The whole folder is treated as the manuscript in that case, so the honest
    complaint is that there is nothing to export -- not that a directory the
    user never had is absent.
    """
    with pytest.raises(ExportError, match="No scenes found"):
        collect_scene_documents(tmp_path, Config())

    (tmp_path / "manuscript").mkdir()
    with pytest.raises(ExportError, match="No scenes found"):
        collect_scene_documents(tmp_path, Config())


def test_export_reads_a_flat_folder_with_no_manuscript_directory(tmp_path: Path):
    (tmp_path / "one.md").write_text("---\ntitle: One\n---\n\n# One\n\nProse.\n", encoding="utf-8")

    documents = collect_scene_documents(tmp_path, Config())

    assert [d.title for d in documents] == ["One"]


def test_missing_pandoc_explains_how_to_install_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("proseview.export.shutil.which", lambda _name: None)

    with pytest.raises(ExportError, match="pandoc is required"):
        export_epub(_repo(tmp_path), Config(), tmp_path / "out.epub")


def test_unknown_epub_version_is_rejected_before_shelling_out(tmp_path: Path):
    with pytest.raises(ExportError, match="Unknown EPUB version"):
        export_epub(_repo(tmp_path), Config(), tmp_path / "out.epub", epub_version="epub9")


def test_summary_counts_scenes_chapters_and_words(tmp_path: Path):
    summary = scene_count_summary(collect_scene_documents(_repo(tmp_path), Config()))
    assert summary.startswith("3 scenes across 3 chapters, ")


def _with_plans(tmp_path: Path) -> Path:
    root = _repo(tmp_path)
    plans = root / "plans"
    plans.mkdir()
    (plans / "book-plan.md").write_text(
        "---\nstatus: draft\n---\n\n# Book Plan\n\nThe spine of the story.\n\n## Beats\n\nOne, two.\n",
        encoding="utf-8",
    )
    (plans / "backlog.md").write_text("Loose ends to chase.\n", encoding="utf-8")
    (plans / "README.md").write_text("skip me\n", encoding="utf-8")
    (plans / "done").mkdir()
    (plans / "done" / "archived.md").write_text("archived, not part of the book\n", encoding="utf-8")
    return root


def test_appendix_collects_top_level_markdown_only(tmp_path: Path):
    section = collect_appendix_documents(_with_plans(tmp_path), "plans", Config())

    assert section.label == "Plans"
    assert [title for title, _ in section.documents] == ["Backlog", "Book Plan"]
    # README skipped, nested archive folder untouched, frontmatter stripped.
    joined = "\n".join(body for _, body in section.documents)
    assert "skip me" not in joined
    assert "archived, not part of the book" not in joined
    assert "status: draft" not in joined
    assert "The spine of the story." in joined


def test_appendix_without_frontmatter_keeps_a_leading_rule(tmp_path: Path):
    root = _with_plans(tmp_path)
    (root / "plans" / "backlog.md").write_text("---\n\nA horizontal rule, not frontmatter.\n", encoding="utf-8")

    section = collect_appendix_documents(root, "plans", Config())
    backlog = dict(section.documents)["Backlog"]
    # A file opening with --- is ambiguous; only strip when it parses as frontmatter.
    assert "horizontal rule" in backlog


@pytest.mark.parametrize(
    "folder,message",
    [
        ("manuscript", "already the body"),
        ("does-not-exist", "does not exist"),
        ("../escape", "not a usable repository path"),
        (".hidden", "not a usable repository path"),
    ],
)
def test_appendix_rejects_unusable_folders(tmp_path: Path, folder: str, message: str):
    with pytest.raises(ExportError, match=message):
        collect_appendix_documents(_with_plans(tmp_path), folder, Config())


def test_appendix_is_appended_after_the_manuscript_with_demoted_headings(tmp_path: Path):
    root = _with_plans(tmp_path)
    documents = collect_scene_documents(root, Config())
    section = collect_appendix_documents(root, "plans", Config())

    markdown = build_manuscript_markdown(documents, title="A Novel", appendices=[section])

    assert markdown.index("## After") < markdown.index("# Appendix: Plans")
    # Two documents, so a contents list is emitted.
    assert "- [Book Plan](#book-plan)" in markdown
    # Compare whole lines: "## Book Plan" contains "# Book Plan" as a substring.
    lines = markdown.splitlines()
    assert "## Book Plan" in lines
    # The document's own H1 is dropped and its H2 pushed to H4, keeping the
    # appendix below the table-of-contents depth.
    assert "# Book Plan" not in lines
    assert "#### Beats" in lines
    assert "## Beats" not in lines


def test_candidate_appendix_folders_lists_what_you_can_append(tmp_path: Path):
    root = _with_plans(tmp_path)
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.md").write_text("no\n", encoding="utf-8")
    (root / "empty-dir").mkdir()

    folders = candidate_appendix_folders(root, Config())

    assert ("plans", 2) in folders
    assert all(name not in {"manuscript", ".hidden", "empty-dir"} for name, _ in folders)


@pytest.mark.skipif(not HAS_PANDOC, reason="pandoc is not installed")
def test_appendix_reaches_the_epub(tmp_path: Path):
    root = _with_plans(tmp_path)
    output = export_epub(root, Config(), tmp_path / "out.epub", appendix_folders=["plans"])

    with zipfile.ZipFile(output) as book:
        text = b"".join(
            book.read(n) for n in book.namelist() if n.endswith(".xhtml")
        ).decode("utf-8")
    assert "The spine of the story." in text
    assert "Appendix: Plans" in text


@pytest.mark.skipif(not HAS_PANDOC, reason="pandoc is not installed")
def test_epub_export_produces_a_readable_book(tmp_path: Path):
    output = export_epub(
        _repo(tmp_path), Config(), tmp_path / "out" / "book.epub",
        title="A Novel", author="Ari",
    )

    assert output.is_file() and output.stat().st_size > 0
    with zipfile.ZipFile(output) as book:
        names = book.namelist()
        assert "mimetype" in names
        assert book.read("mimetype") == b"application/epub+zip"
        text = b"".join(book.read(n) for n in names if n.endswith((".xhtml", ".opf"))).decode("utf-8")
    assert "A Novel" in text
    assert "Rena opened the shop." in text


@pytest.mark.skipif(not HAS_PANDOC, reason="pandoc is not installed")
def test_demo_fixture_exports_end_to_end(tmp_path: Path):
    output = export_epub(FIXTURE, Config.load(FIXTURE), tmp_path / "demo.epub")
    assert output.is_file() and output.stat().st_size > 0
