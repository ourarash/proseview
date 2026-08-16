"""Compile the manuscript into a single document and hand it to pandoc.

Scene discovery, frontmatter parsing, and body extraction all come from
:mod:`proseview.scenes`, so an export contains exactly the scenes the dashboard
counts, in the same order. This module only adds what the dashboard has no
reason to know about: assembling one Markdown document and shelling out.

pandoc is an optional external dependency. It is looked up at call time and
never at import time, so the package installs and the dashboard runs without
it; only ``proseview export`` needs it present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .repo import CONTEXT_SKIP_DIRS, resolve_visible_repository_path
from .repo import read_repo_text
from .scenes import resolve_manuscript_dir, scene_chapter, extract_scene_text, iter_scene_paths, split_frontmatter

#: pandoc targets this module knows how to ask for. EPUB is the one wired to a
#: CLI flag today; the others are here because the pandoc call is identical
#: apart from the writer name.
EPUB_VERSIONS: tuple[str, ...] = ("epub3", "epub2")


class ExportError(RuntimeError):
    """Raised when an export cannot be produced, with a readable reason."""


@dataclass(frozen=True)
class SceneDocument:
    """One manuscript scene, reduced to what an export needs."""

    path: Path
    chapter: str
    title: str
    markdown: str


@dataclass(frozen=True)
class AppendixSection:
    """One repository folder appended to the book after the manuscript."""

    label: str
    documents: list[tuple[str, str]]


def _folder_label(folder: str) -> str:
    """``story-bible`` -> ``Story Bible``."""
    return folder.strip("/").replace("-", " ").replace("_", " ").title()


def collect_appendix_documents(root: Path, folder: str, cfg: Config) -> AppendixSection:
    """Read the Markdown files directly inside *folder* as one appendix.

    Only the folder's own ``*.md`` files are included, not nested directories:
    ``plans/done/`` is archive, not part of the book. READMEs are skipped, and
    frontmatter is stripped only when a file actually opens with it, so a
    document beginning with a horizontal rule keeps it.
    """
    relative = folder.strip("/").strip()
    if not relative:
        raise ExportError("An appendix folder cannot be empty")
    if relative == cfg.manuscript_subdir.strip("/"):
        raise ExportError(
            f"{relative!r} is the manuscript itself; it is already the body of the book"
        )
    try:
        target = resolve_visible_repository_path(root, relative)
    except ValueError as exc:
        raise ExportError(f"Appendix folder {relative!r} is not a usable repository path: {exc}") from exc
    if not target.is_dir():
        raise ExportError(f"Appendix folder {relative!r} does not exist in {root}")

    documents: list[tuple[str, str]] = []
    for path in sorted(target.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = read_repo_text(path)
        body = split_frontmatter(text)[1] if text.startswith("---") else text
        documents.append((path.stem.replace("-", " ").title(), body.strip()))
    if not documents:
        raise ExportError(f"Appendix folder {relative!r} has no Markdown files to include")
    return AppendixSection(label=_folder_label(relative), documents=documents)


def collect_scene_documents(root: Path, cfg: Config) -> list[SceneDocument]:
    """Load manuscript scenes in reading order.

    Titles and chapters fall back exactly as the dashboard's scene table does:
    frontmatter first, then the filename stem and the chapter folder name.
    """
    manuscript_dir = resolve_manuscript_dir(root, cfg.manuscript_subdir)
    if not manuscript_dir.is_dir():
        raise ExportError(f"No manuscript directory at {manuscript_dir}")

    documents: list[SceneDocument] = []
    for path in iter_scene_paths(manuscript_dir):
        raw = read_repo_text(path)
        fm, body = split_frontmatter(raw)
        documents.append(
            SceneDocument(
                path=path.relative_to(root),
                chapter=str(fm.get("chapter", scene_chapter(path, manuscript_dir))).strip(),
                title=str(fm.get("title", path.stem.replace("-", " ").title())).strip(),
                markdown=extract_scene_text(body).strip(),
            )
        )
    if not documents:
        raise ExportError(f"No scenes found under {manuscript_dir}")
    return documents


def _quote_yaml(text: str) -> str:
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _anchor(text: str) -> str:
    """Pandoc-style heading anchor, for the per-appendix contents list."""
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"\s+", "-", slug)


def build_manuscript_markdown(
    documents: list[SceneDocument],
    *,
    title: str,
    author: str = "",
    language: str = "en-US",
    identifier: str = "",
    appendices: list[AppendixSection] | None = None,
) -> str:
    """Assemble scenes into one Markdown document with a metadata block.

    Chapters become ``#`` headings and scenes ``##``, which is what gives
    pandoc a table of contents and one EPUB file per chapter. Appendices
    follow the manuscript with the same two-level shape.
    """
    parts = [
        "---",
        f"title: {_quote_yaml(title)}",
        f"lang: {_quote_yaml(language)}",
        f"identifier: {_quote_yaml(identifier or uuid.uuid4().urn)}",
    ]
    if author:
        parts.append(f"author: {_quote_yaml(author)}")
    parts += ["---", ""]

    current_chapter: str | None = None
    for scene in documents:
        if scene.chapter != current_chapter:
            current_chapter = scene.chapter
            parts += [f"# {scene.chapter}", ""]
        parts += [f"## {scene.title}", ""]
        if scene.markdown:
            parts += [scene.markdown, ""]

    for section in appendices or []:
        parts += [f"# Appendix: {section.label}", ""]
        if len(section.documents) > 1:
            for doc_title, _ in section.documents:
                parts.append(f"- [{doc_title}](#{_anchor(doc_title)})")
            parts.append("")
        for doc_title, content in section.documents:
            # Drop the document's own H1 (the folder-derived title replaces it)
            # and push every remaining heading down two levels, so appendix
            # sub-headings stay below the table-of-contents depth.
            body = re.sub(r"^# [^\n]*\n*", "", content, count=1).strip()
            body = re.sub(r"^(#+)", r"##\1", body, flags=re.MULTILINE)
            parts += [f"## {doc_title}", "", body, ""]

    return "\n".join(parts).rstrip() + "\n"


def ensure_pandoc() -> str:
    """Return the pandoc executable, or explain how to get one."""
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise ExportError(
            "pandoc is required for export and was not found on PATH. "
            "Install it with `brew install pandoc` or `apt install pandoc`, "
            "or see https://pandoc.org/installing.html"
        )
    return pandoc


def export_epub(
    root: Path,
    cfg: Config,
    output: Path,
    *,
    title: str = "",
    author: str = "",
    language: str = "en-US",
    epub_version: str = "epub3",
    cover_image: Path | None = None,
    css: list[Path] | None = None,
    toc_depth: int = 2,
    appendix_folders: list[str] | None = None,
) -> Path:
    """Write the manuscript to *output* as an EPUB and return the path."""
    if epub_version not in EPUB_VERSIONS:
        raise ExportError(f"Unknown EPUB version {epub_version!r}; expected one of {', '.join(EPUB_VERSIONS)}")
    pandoc = ensure_pandoc()
    documents = collect_scene_documents(root, cfg)
    appendices = [collect_appendix_documents(root, folder, cfg) for folder in appendix_folders or []]
    markdown = build_manuscript_markdown(
        documents,
        title=title or root.resolve().name.replace("-", " ").title(),
        author=author,
        language=language,
        appendices=appendices,
    )

    output = output.resolve()
    if output.is_dir():
        raise ExportError(f"Output path {output} is a directory; pass a file path")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "manuscript.md"
        source.write_text(markdown, encoding="utf-8")
        command = [
            pandoc, str(source),
            "--standalone",
            "--from", "markdown+yaml_metadata_block",
            "--to", epub_version,
            "--output", str(output),
            "--toc", "--toc-depth", str(toc_depth),
            "--split-level", "1",
        ]
        for sheet in css or []:
            command += ["--css", str(sheet)]
        if cover_image:
            command += ["--epub-cover-image", str(cover_image)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise ExportError("pandoc timed out after 5 minutes") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {result.returncode}"
        raise ExportError(f"pandoc failed: {tail}")
    return output


def candidate_appendix_folders(root: Path, cfg: Config) -> list[tuple[str, int]]:
    """Return ``(folder, markdown file count)`` for folders you could append.

    Answers "what can I pass to ``--appendix``" without making the user guess
    at their own layout. Hidden and tooling directories are skipped, and the
    manuscript is excluded because it is already the body of the book.
    """
    manuscript = cfg.manuscript_subdir.strip("/")
    found: list[tuple[str, int]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.is_symlink():
            continue
        if entry.name == manuscript or entry.name in CONTEXT_SKIP_DIRS:
            continue
        count = len([p for p in entry.glob("*.md") if p.name.lower() != "readme.md"])
        if count:
            found.append((entry.name, count))
    return found


def scene_count_summary(documents: list[SceneDocument]) -> str:
    """One line for the CLI to print after a successful export."""
    chapters = len({scene.chapter for scene in documents})
    words = sum(len(re.findall(r"\b[\w'’-]+\b", scene.markdown)) for scene in documents)
    return f"{len(documents)} scenes across {chapters} chapters, {words:,} words"
