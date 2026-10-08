"""Choose what goes into an export, and shape it into a book.

An export starts from every scene the dashboard counts, in the same order.
A :class:`~proseview.config.ExportSelection` narrows that to some chapters
and scenes, and :func:`build_book` turns the result into a :class:`Book`: the
one model every renderer reads, so an EPUB and (later) a PDF of the same
selection contain the same thing.

Nothing here reads files or writes them. Loading scenes from disk lives in
:mod:`proseview.export`; this module only decides, which keeps it cheap to
test.
"""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import ExportSelection

#: What a selection is shaped into. ``book`` is the whole manuscript;
#: ``selection`` is several chapters or a mix of scenes; ``chapter`` and
#: ``scene`` are a single one of each and get no table of contents.
BOOK_KINDS: tuple[str, ...] = ("book", "selection", "chapter", "scene")

#: Kept as an alias so callers can think of it as what it is used for.
Selection = ExportSelection


class ExportError(RuntimeError):
    """Raised when an export cannot be produced, with a readable reason.

    *scene* names the scene at fault (its path below the manuscript folder,
    without ``.md``) when there is one, so the dashboard can offer to open it.
    """

    def __init__(self, message: str, *, scene: str = "") -> None:
        super().__init__(message)
        self.scene = scene


@dataclass(frozen=True)
class SceneDocument:
    """One manuscript scene, reduced to what an export needs.

    ``chapter_number`` and ``scene_number`` are positions in the whole book,
    counted from 1, so "Chapter Seven" stays chapter seven when only chapters
    7-9 are exported. ``key`` is the scene's path below the manuscript folder
    without ``.md``: the stable way to name it in a saved selection.
    """

    path: Path
    chapter: str
    title: str
    markdown: str
    chapter_number: int = 0
    scene_number: int = 0
    key: str = ""
    folder: str = ""


@dataclass(frozen=True)
class AppendixSection:
    """One repository folder appended to the book after the manuscript."""

    label: str
    documents: list[tuple[str, str]]


#: Front and back matter kinds, with what an EPUB calls them.
MATTER_KINDS: dict[str, str] = {
    "copyright": "copyright-page",
    "dedication": "dedication",
    "epigraph": "epigraph",
    "foreword": "foreword",
    "preface": "preface",
    "prologue-note": "",
    "acknowledgements": "acknowledgments",
    "about-the-author": "",
    "also-by": "",
    "afterword": "afterword",
    "other": "",
}


@dataclass(frozen=True)
class MatterPage:
    """A page before or after the story: a copyright page, a dedication, an "About the author".

    ``source`` is the file it came from (``front-matter/dedication.md``), or
    empty for a page Proseview wrote from the book's details.
    """

    kind: str
    title: str
    markdown: str
    source: str = ""

    @property
    def shows_title(self) -> bool:
        """Copyright, dedication and epigraph pages speak for themselves."""
        return self.kind not in {"copyright", "dedication", "epigraph"}


@dataclass(frozen=True)
class BookChapter:
    """A run of selected scenes from one chapter.

    ``title`` is empty when the chapter has no name of its own (the label is
    only its folder name), so a style shows "Chapter One" rather than
    "Chapter One: ch01".
    """

    number: int
    title: str
    scenes: tuple[SceneDocument, ...]


@dataclass(frozen=True)
class Book:
    """Everything a renderer needs, already selected and ordered."""

    title: str
    author: str
    language: str
    identifier: str
    kind: str
    chapters: tuple[BookChapter, ...]
    appendices: tuple[AppendixSection, ...] = ()
    #: A quiet line for the title page of a partial book, e.g. "Chapters 3, 7–9".
    note: str = ""
    subtitle: str = ""
    front_matter: tuple[MatterPage, ...] = ()
    back_matter: tuple[MatterPage, ...] = ()
    #: The source repository, for resolving images relative to each scene.
    root: Path | None = field(default=None, compare=False)

    @property
    def scenes(self) -> list[SceneDocument]:
        return [scene for chapter in self.chapters for scene in chapter.scenes]

    @property
    def has_contents(self) -> bool:
        """Whether the book gets a title page and a table of contents."""
        return self.kind in {"book", "selection"}


# --------------------------------------------------------------------------
# Numbering


_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_to_words(n: int) -> str:
    """``21`` -> ``Twenty-One``; numerals from 1000 up, where words stop helping."""
    if n < 0 or n >= 1000:
        return str(n)
    if n < 20:
        words = _ONES[n]
    elif n < 100:
        words = _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    else:
        rest = n % 100
        words = f"{_ONES[n // 100]} hundred" + (f" {number_to_words(rest).lower()}" if rest else "")
    return words.title()


def format_ranges(numbers: list[int]) -> str:
    """``[3, 7, 8, 9]`` -> ``3, 7–9``."""
    ordered = sorted(set(numbers))
    runs: list[list[int]] = []
    for n in ordered:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(
        str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}" for run in runs
    )


def number_documents(documents: list[SceneDocument]) -> list[SceneDocument]:
    """Give each scene its chapter and scene position in the whole book.

    A chapter is a run of consecutive scenes sharing a label, exactly how the
    export has always grouped them, so numbering matches the headings.
    """
    numbered: list[SceneDocument] = []
    chapter_number = 0
    scene_number = 0
    previous: str | None = None
    for doc in documents:
        if doc.chapter != previous:
            previous = doc.chapter
            chapter_number += 1
            scene_number = 0
        scene_number += 1
        numbered.append(
            SceneDocument(
                path=doc.path, chapter=doc.chapter, title=doc.title, markdown=doc.markdown,
                chapter_number=chapter_number, scene_number=scene_number,
                key=doc.key, folder=doc.folder,
            )
        )
    return numbered


_OPENS_QUOTE = r"(^|(?<=[\s(\[{—–-]))"


def smart_punctuation(text: str) -> str:
    """Typeset plain text the way scene prose is typeset.

    Scene bodies go through markdown-it's typographer, but titles, author
    names and chapter names never pass through Markdown, so without this a
    title page reads "Alice's" beside a chapter that reads "Alice’s". Quotes
    open after a space or bracket and close everywhere else, which also makes
    a mid-word ``'`` an apostrophe.
    """
    if not text:
        return text
    out = text.replace("---", "—").replace("--", "–").replace("...", "…")
    out = re.sub(_OPENS_QUOTE + '"', "“", out)
    out = out.replace('"', "”")
    out = re.sub(_OPENS_QUOTE + "'(?=\\w)", "‘", out)
    return out.replace("'", "’")


#: An opening paragraph shorter than this (in characters) is set without a
#: drop cap: a two-line letter beside one line of text runs into the next
#: paragraph. It still opens in small capitals.
SHORT_OPENER = 140


# --------------------------------------------------------------------------
# Resolving a selection


def _chapters(documents: list[SceneDocument]) -> dict[int, list[SceneDocument]]:
    grouped: dict[int, list[SceneDocument]] = {}
    for doc in documents:
        grouped.setdefault(doc.chapter_number, []).append(doc)
    return grouped


def _chapter_names(scenes: list[SceneDocument]) -> set[str]:
    first = scenes[0]
    return {name.casefold() for name in (first.chapter, first.folder) if name}


def _suggest(text: str, names: list[str]) -> str:
    """" Did you mean ...?" for near misses, ignoring case."""
    by_folded = {name.casefold(): name for name in names}
    close = difflib.get_close_matches(text.casefold(), list(by_folded), n=3)
    return f" Did you mean {', '.join(by_folded[c] for c in close)}?" if close else ""


def _match_chapters(token: str, chapters: dict[int, list[SceneDocument]]) -> list[int]:
    text = token.strip()
    if not text:
        raise ExportError("An empty chapter name was given")
    span = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", text)
    if span:
        low, high = int(span.group(1)), int(span.group(2))
        if low > high:
            raise ExportError(f"Chapter range {text!r} runs backwards; write it as {high}-{low}")
        numbers = list(range(low, high + 1))
    elif text.isdigit():
        numbers = [int(text)]
    else:
        wanted = text.casefold()
        numbers = [n for n, scenes in chapters.items() if wanted in _chapter_names(scenes)]
        if not numbers:
            names = sorted({name for s in chapters.values() for name in (s[0].folder, s[0].chapter) if name})
            hint = _suggest(text, names)
            raise ExportError(
                f"No chapter called {text!r}.{hint} Chapters can be named by number "
                f"(1-{len(chapters)}), folder, or the chapter title."
            )
        return numbers
    missing = [n for n in numbers if n not in chapters]
    if missing:
        raise ExportError(
            f"There is no chapter {format_ranges(missing)}; the book has chapters 1-{len(chapters)}"
        )
    return numbers


def _match_scene(token: str, documents: list[SceneDocument]) -> SceneDocument:
    text = token.strip().replace("\\", "/")
    if not text:
        raise ExportError("An empty scene name was given")
    position = re.fullmatch(r"(\d+)\.(\d+)", text)
    if position:
        chapter, scene = int(position.group(1)), int(position.group(2))
        for doc in documents:
            if doc.chapter_number == chapter and doc.scene_number == scene:
                return doc
        raise ExportError(f"There is no scene {scene} in chapter {chapter}")

    bare = text.removesuffix(".md").strip("/").casefold()
    tiers = (
        lambda d: d.key.casefold() == bare,
        lambda d: d.path.with_suffix("").as_posix().casefold() == bare,
        lambda d: d.path.stem.casefold() == bare,
        lambda d: d.title.casefold() == text.casefold(),
    )
    for matches_tier in tiers:
        found = [doc for doc in documents if matches_tier(doc)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            options = ", ".join(doc.key for doc in found)
            raise ExportError(f"{text!r} matches more than one scene ({options}); use its path")
    hint = _suggest(text, [doc.key for doc in documents] + [doc.title for doc in documents])
    raise ExportError(
        f"No scene called {text!r}.{hint} Scenes can be named by path (ch01/01-opening), "
        "file name, title, or chapter.scene number (3.2)."
    )


def resolve_selection(documents: list[SceneDocument], selection: Selection | None) -> list[SceneDocument]:
    """Return the scenes *selection* picks, each once.

    ``book`` order keeps the manuscript's order however the picks were
    given; ``custom`` order follows the picks, a chapter contributing its
    scenes in book order. No selection, or an empty one, is the whole book.
    """
    if selection is None or not selection.picks:
        return list(documents)
    if selection.order not in {"book", "custom"}:
        raise ExportError(f"Unknown order {selection.order!r}; expected book or custom")
    chapters = _chapters(documents)
    chosen: list[SceneDocument] = []
    seen: set[Path] = set()
    for kind, token in selection.picks:
        if kind == "chapter":
            picked = [doc for n in _match_chapters(token, chapters) for doc in chapters[n]]
        elif kind == "scene":
            picked = [_match_scene(token, documents)]
        else:
            raise ExportError(f"A selection picks chapters or scenes, not {kind!r}")
        for doc in picked:
            if doc.path not in seen:
                seen.add(doc.path)
                chosen.append(doc)
    if selection.order == "book":
        position = {doc.path: i for i, doc in enumerate(documents)}
        chosen.sort(key=lambda doc: position[doc.path])
    return chosen


def portable_selection(documents: list[SceneDocument], selection: Selection) -> Selection:
    """Rewrite *selection* in names that survive edits to the manuscript.

    A chapter number shifts when a chapter is inserted before it; a folder
    name does not. Chapters are saved by folder when the folder names only
    that chapter, and scenes by their path, so a saved selection keeps
    meaning what it meant.
    """
    chapters = _chapters(documents)
    folder_owners: dict[str, set[int]] = {}
    for number, scenes in chapters.items():
        for doc in scenes:
            folder_owners.setdefault(doc.folder, set()).add(number)
    picks: list[tuple[str, str]] = []
    for kind, token in selection.picks:
        if kind == "scene":
            picks.append(("scene", _match_scene(token, documents).key))
            continue
        for number in _match_chapters(token, chapters):
            folder = chapters[number][0].folder
            portable = folder if folder and folder_owners.get(folder) == {number} else str(number)
            if ("chapter", portable) not in picks:
                picks.append(("chapter", portable))
    return Selection(name=selection.name, picks=tuple(picks), order=selection.order)


# --------------------------------------------------------------------------
# The book


def chapter_title(scene: SceneDocument) -> str:
    """The chapter's own name, or empty when it only has a folder name."""
    label = scene.chapter.strip()
    if not label or label == scene.folder:
        return ""
    return label


def chapter_label(number: int, numbering: str) -> str:
    """``Chapter One`` / ``Chapter 1`` / ``1`` / empty, per a style's numbering."""
    if numbering == "words":
        return f"Chapter {number_to_words(number)}"
    if numbering == "numerals":
        return f"Chapter {number}"
    if numbering == "number":
        return str(number)
    return ""


def selection_identifier(base: str, scenes: list[SceneDocument]) -> str:
    """A stable identifier for a part of the book.

    An excerpt must not share the full book's identifier, or a reader's
    library would replace the novel with chapter three. Deriving it from the
    book identifier and the scenes keeps it stable across re-exports of the
    same selection.
    """
    name = "\n".join(doc.key or doc.path.as_posix() for doc in scenes)
    match = re.fullmatch(r"urn:uuid:([0-9a-fA-F-]{36})", base)
    try:
        namespace = uuid.UUID(match.group(1)) if match else uuid.uuid5(uuid.NAMESPACE_URL, base)
    except ValueError:
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, base)
    return uuid.uuid5(namespace, name).urn


def build_book(
    documents: list[SceneDocument],
    selected: list[SceneDocument],
    *,
    title: str,
    subtitle: str = "",
    author: str = "",
    language: str = "en-US",
    identifier: str = "",
    selection: Selection | None = None,
    appendices: list[AppendixSection] | None = None,
    root: Path | None = None,
) -> Book:
    """Shape *selected* scenes (drawn from *documents* by *selection*) into a :class:`Book`.

    With no selection the result is the whole book, title page and all, even
    when the manuscript has a single chapter. A lone scene is a ``scene``
    only when it was picked as one: asking for a chapter that happens to
    hold one scene still gets a chapter opener.
    """
    if not selected:
        raise ExportError("The selection picks no scenes")
    whole_book = selection is None or not selection.picks
    if whole_book:
        kind = "book"
    elif len({doc.chapter_number for doc in selected}) > 1:
        kind = "selection"
    elif len(selected) == 1 and all(kind == "scene" for kind, _ in selection.picks):
        kind = "scene"
    else:
        kind = "chapter"

    chapters: list[BookChapter] = []
    for doc in selected:
        if chapters and chapters[-1].number == doc.chapter_number:
            last = chapters[-1]
            chapters[-1] = BookChapter(last.number, last.title, last.scenes + (doc,))
        else:
            chapters.append(BookChapter(doc.chapter_number, chapter_title(doc), (doc,)))

    note = ""
    if kind == "selection":
        numbers = [chapter.number for chapter in chapters]
        totals = _chapters(documents)
        complete = all(
            {d.path for d in totals[n]} <= {d.path for d in selected} for n in set(numbers)
        )
        plural = "s" if len(set(numbers)) > 1 else ""
        note = (
            f"Chapter{plural} {format_ranges(numbers)}" if complete
            else f"Scenes from chapter{plural} {format_ranges(numbers)}"
        )

    base = identifier or uuid.uuid4().urn
    return Book(
        title=title,
        subtitle=subtitle,
        author=author,
        language=language,
        identifier=base if whole_book else selection_identifier(base, selected),
        kind=kind,
        chapters=tuple(chapters),
        appendices=tuple(appendices or ()),
        note=note,
        root=root,
    )
