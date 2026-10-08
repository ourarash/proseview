"""Compile some or all of the manuscript into a book file.

Scene discovery, frontmatter parsing, and body extraction all come from
:mod:`proseview.scenes`, so an export contains exactly the scenes the dashboard
counts, in the same order. :mod:`proseview.book` narrows that to a selection
and shapes it into a book, and :mod:`proseview.epub` writes the EPUB.

pandoc is still supported for one release behind ``engine="pandoc"``. It is
looked up at call time and never at import time, so nothing else needs it.
"""

from __future__ import annotations

import datetime as _dt
import io
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .book import (
    AppendixSection,
    Book,
    ExportError,
    SceneDocument,
    Selection,
    build_book,
    number_documents,
    portable_selection,
    resolve_selection,
)
from .book_styles import StyleError, load_style
from .config import Config
from .epub import EPUB_VERSIONS, EpubOptions, write_epub
from .repo import CONTEXT_SKIP_DIRS, atomic_write_text, resolve_visible_repository_path
from .repo import read_repo_text
from .scenes import (
    _is_scene,
    extract_scene_text,
    iter_scene_paths,
    resolve_manuscript_dir,
    scene_chapter,
    split_frontmatter,
)

__all__ = [
    "AppendixSection", "Book", "EPUB_VERSIONS", "ENGINES", "ExportError", "ExportResult",
    "SceneDocument", "Selection", "build_manuscript_markdown", "candidate_appendix_folders",
    "collect_appendix_documents", "collect_scene_documents", "default_output_path",
    "ensure_gitignored", "ensure_pandoc", "export_book",
    "export_epub", "new_book_identifier", "save_book_identifier", "save_selection", "scene_count_summary",
]

#: How the EPUB is made. ``builtin`` needs nothing installed; ``pandoc`` is
#: today's path, kept for one release so existing scripts keep working.
ENGINES: tuple[str, ...] = ("builtin", "pandoc")

#: Where exports land by default, inside the novel's folder.
EXPORTS_DIR = "exports"


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


def collect_scene_documents(
    root: Path, cfg: Config, selection: Selection | None = None,
) -> list[SceneDocument]:
    """Load manuscript scenes in reading order, optionally narrowed to *selection*.

    Titles and chapters fall back exactly as the dashboard's scene table does:
    frontmatter first, then the filename stem and the chapter folder name.
    Files marked ``scene: false`` are left out, as the dashboard leaves them
    out. With no selection this is the whole book.
    """
    manuscript_dir = resolve_manuscript_dir(root, cfg.manuscript_subdir)
    if not manuscript_dir.is_dir():
        raise ExportError(f"No manuscript directory at {manuscript_dir}")

    documents: list[SceneDocument] = []
    for path in iter_scene_paths(manuscript_dir):
        raw = read_repo_text(path)
        fm, body = split_frontmatter(raw)
        if not _is_scene(fm):
            continue
        relative = path.relative_to(manuscript_dir)
        documents.append(
            SceneDocument(
                path=path.relative_to(root),
                chapter=str(fm.get("chapter", scene_chapter(path, manuscript_dir))).strip(),
                title=str(fm.get("title", path.stem.replace("-", " ").title())).strip(),
                markdown=extract_scene_text(body).strip(),
                key=relative.with_suffix("").as_posix(),
                folder=scene_chapter(path, manuscript_dir),
            )
        )
    if not documents:
        raise ExportError(f"No scenes found under {manuscript_dir}")
    return resolve_selection(number_documents(documents), selection)


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


@dataclass(frozen=True)
class ExportResult:
    path: Path
    book: Book


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[\s_-]+", "-", slug).strip("-") or "book"


def default_output_path(
    root: Path, book: Book, *, selection_name: str = "", today: _dt.date | None = None,
) -> Path:
    """``<root>/exports/<book>[-<part>]-<date>.epub``.

    A part of the book gets its own name, so exporting chapter three does not
    overwrite the day's full-book export.
    """
    if selection_name:
        part = _slug(selection_name)
    elif book.kind == "chapter":
        part = f"chapter-{book.chapters[0].number}"
    elif book.kind == "scene":
        part = f"scene-{_slug(book.chapters[0].scenes[0].title)}"
    elif book.kind == "selection":
        part = "selection"
    else:
        part = ""
    stem = "-".join(bit for bit in (_slug(book.title), part, (today or _dt.date.today()).isoformat()) if bit)
    return root / EXPORTS_DIR / f"{stem}.epub"


def export_book(
    root: Path,
    cfg: Config,
    output: Path | None = None,
    *,
    selection: Selection | None = None,
    title: str = "",
    author: str = "",
    language: str = "en-US",
    identifier: str = "",
    epub_version: str = "epub3",
    engine: str = "builtin",
    style: str = "",
    scene_titles: bool | None = None,
    cover_image: Path | None = None,
    css: list[Path] | None = None,
    toc_depth: int = 2,
    appendix_folders: list[str] | None = None,
) -> ExportResult:
    """Export *selection* (default: the whole book) as an EPUB.

    *output* defaults to a dated file under ``exports/``. *identifier*
    defaults to the one saved in ``.proseview.yaml``; this function never
    writes the config itself (see :func:`ensure_book_identifier`).
    """
    if epub_version not in EPUB_VERSIONS:
        raise ExportError(f"Unknown EPUB version {epub_version!r}; expected one of {', '.join(EPUB_VERSIONS)}")
    if engine not in ENGINES:
        raise ExportError(f"Unknown export engine {engine!r}; expected one of {', '.join(ENGINES)}")
    pandoc = ensure_pandoc() if engine == "pandoc" else ""

    documents = collect_scene_documents(root, cfg)
    selected = resolve_selection(documents, selection)
    appendices = [collect_appendix_documents(root, folder, cfg) for folder in appendix_folders or []]
    book = build_book(
        documents,
        selected,
        title=title or root.resolve().name.replace("-", " ").title(),
        author=author,
        language=language,
        identifier=identifier or cfg.export.identifier,
        selection=selection,
        appendices=appendices,
        root=root.resolve(),
    )

    output = (output or default_output_path(root, book, selection_name=selection.name if selection else "")).resolve()
    if output.is_dir():
        raise ExportError(f"Output path {output} is a directory; pass a file path")
    output.parent.mkdir(parents=True, exist_ok=True)

    if engine == "pandoc":
        _export_with_pandoc(
            pandoc, book, output,
            epub_version=epub_version, cover_image=cover_image, css=css, toc_depth=toc_depth,
        )
        return ExportResult(output, book)

    try:
        book_style = load_style(style or cfg.export.style, base=root)
    except StyleError as exc:
        raise ExportError(str(exc)) from exc
    if scene_titles is None:
        scene_titles = cfg.export.scene_titles
    if scene_titles is None:
        scene_titles = book_style.show_scene_titles
    write_epub(book, output, EpubOptions(
        version=epub_version,
        style=book_style,
        show_scene_titles=scene_titles,
        cover_image=cover_image,
        css=tuple(css or ()),
    ))
    return ExportResult(output, book)


def export_epub(root: Path, cfg: Config, output: Path, **options) -> Path:
    """Write the manuscript to *output* as an EPUB and return the path.

    Kept for callers of the original API; :func:`export_book` takes the same
    options and also returns the book that was written.
    """
    return export_book(root, cfg, output, **options).path


def _export_with_pandoc(
    pandoc: str,
    book: Book,
    output: Path,
    *,
    epub_version: str,
    cover_image: Path | None,
    css: list[Path] | None,
    toc_depth: int,
) -> None:
    markdown = build_manuscript_markdown(
        book.scenes,
        title=book.title,
        author=book.author,
        language=book.language,
        identifier=book.identifier,
        appendices=list(book.appendices),
    )
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
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", timeout=300
            )
        except subprocess.TimeoutExpired as exc:
            raise ExportError("pandoc timed out after 5 minutes") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {result.returncode}"
        raise ExportError(f"pandoc failed: {tail}")


# --------------------------------------------------------------------------
# What an export remembers in .proseview.yaml


def _edit_export_config(root: Path, change) -> None:
    """Apply *change* to the ``export:`` block, keeping the rest of the file as written."""
    import ruamel.yaml

    path = root / ".proseview.yaml"
    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    data = yaml.load(path.read_text(encoding="utf-8-sig")) if path.exists() else None
    if data is None:
        data = ruamel.yaml.comments.CommentedMap()
    if not isinstance(data, dict):
        raise ExportError(f"{path} is not a mapping; cannot save export settings there")
    block = data.get("export")
    if not isinstance(block, dict):
        block = ruamel.yaml.comments.CommentedMap()
        data["export"] = block
    change(block)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    atomic_write_text(path, buffer.getvalue())


def new_book_identifier() -> str:
    return uuid.uuid4().urn


def save_book_identifier(root: Path, identifier: str) -> None:
    """Remember the book's identifier under ``export.identifier``.

    Reusing one identifier is what lets an e-reader replace last week's
    export instead of shelving a second copy. Call it after an export
    succeeds, so a failed first attempt leaves the config untouched.
    """
    _edit_export_config(root, lambda block: block.__setitem__("identifier", identifier))


def save_selection(root: Path, cfg: Config, selection: Selection) -> Selection:
    """Save *selection* under ``export.selections`` by name and return what was saved.

    Chapters and scenes are written by folder and path rather than by number
    where that is unambiguous, so the selection still means the same thing
    after a chapter is inserted earlier in the book.
    """
    if not selection.name.strip():
        raise ExportError("A saved selection needs a name")
    if not selection.picks:
        raise ExportError("Pick chapters or scenes to save as a selection")
    portable = portable_selection(collect_scene_documents(root, cfg), selection)

    def change(block) -> None:
        import ruamel.yaml

        saved = block.get("selections")
        if not isinstance(saved, dict):
            saved = ruamel.yaml.comments.CommentedMap()
            block["selections"] = saved
        for existing in list(saved):
            if str(existing).casefold() == portable.name.casefold():
                del saved[existing]
        body = ruamel.yaml.comments.CommentedMap()
        if portable.order == "custom":
            body["order"] = "custom"
            body["items"] = [{kind: token} for kind, token in portable.picks]
        else:
            chapters = [token for kind, token in portable.picks if kind == "chapter"]
            scenes = [token for kind, token in portable.picks if kind == "scene"]
            if chapters:
                body["chapters"] = [int(t) if t.isdigit() else t for t in chapters]
            if scenes:
                body["scenes"] = scenes
        saved[portable.name] = body

    _edit_export_config(root, change)
    return portable


def ensure_gitignored(root: Path, entry: str = f"{EXPORTS_DIR}/") -> bool:
    """Add *entry* to the novel's ``.gitignore`` so exports are never committed.

    Only in a git repository, and only once. Returns whether the file changed.
    """
    if not (root / ".git").exists():
        return False
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    wanted = {entry, entry.rstrip("/"), "/" + entry, "/" + entry.rstrip("/")}
    if any(line.strip() in wanted for line in text.splitlines()):
        return False
    if text:
        # Finish the last line, then leave a blank line before ours.
        text = text if text.endswith("\n") else text + "\n"
        text += "\n"
    atomic_write_text(path, f"{text}# Books written by `proseview export`\n{entry}\n")
    return True


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
    def count(n: int, noun: str) -> str:
        return f"{n:,} {noun}{'' if n == 1 else 's'}"

    return f"{count(len(documents), 'scene')} across {count(chapters, 'chapter')}, {count(words, 'word')}"
