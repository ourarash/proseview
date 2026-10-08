"""Tests for :mod:`proseview.book`: selections and the book model.

Covers:
- the whole book is the default, and every selection keeps book order unless
  asked for a custom order
- chapters and scenes can be named the ways a writer would name them, and
  bad names fail with a suggestion rather than a traceback
- the book's kind (whole, selection, chapter, scene) and its title-page note
- partial books get their own stable identifier
- saved selections parse from ``.proseview.yaml`` and are written portably
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.book import (  # noqa: E402
    ExportError,
    SceneDocument,
    build_book,
    chapter_label,
    format_ranges,
    number_documents,
    number_to_words,
    portable_selection,
    resolve_selection,
    selection_identifier,
)
from proseview.config import Config, ConfigError, ExportSelection  # noqa: E402
from proseview.export import collect_scene_documents, save_selection  # noqa: E402


def _doc(chapter: str, folder: str, stem: str, title: str = "") -> SceneDocument:
    return SceneDocument(
        path=Path("manuscript") / folder / f"{stem}.md",
        chapter=chapter,
        title=title or stem.title(),
        markdown=f"Prose of {stem}.",
        key=f"{folder}/{stem}",
        folder=folder,
    )


def _book() -> list[SceneDocument]:
    """Four chapters; chapter two has no title of its own, only a folder."""
    return number_documents([
        _doc("The Shop", "ch01", "01-opening", "The Opening"),
        _doc("The Shop", "ch01", "02-late", "Lowe Arrives"),
        _doc("ch02", "ch02", "01-ledger", "The Ledger"),
        _doc("The Bridge", "ch03", "01-crossing", "Crossing"),
        _doc("The Bridge", "ch03", "02-fall", "The Fall"),
        _doc("Home", "ch04", "01-home", "Home Again"),
    ])


def _pick(*picks: tuple[str, str], order: str = "book", name: str = "") -> ExportSelection:
    return ExportSelection(name=name, picks=tuple(picks), order=order)


def _keys(documents: list[SceneDocument]) -> list[str]:
    return [d.key for d in documents]


# -- numbering ----------------------------------------------------------------


def test_scenes_are_numbered_by_chapter_and_position():
    docs = _book()
    assert [(d.chapter_number, d.scene_number) for d in docs] == [
        (1, 1), (1, 2), (2, 1), (3, 1), (3, 2), (4, 1),
    ]


@pytest.mark.parametrize("n,words", [
    (1, "One"), (12, "Twelve"), (21, "Twenty-One"), (40, "Forty"),
    (100, "One Hundred"), (342, "Three Hundred Forty-Two"), (1000, "1000"),
])
def test_number_to_words(n: int, words: str):
    assert number_to_words(n) == words


def test_chapter_labels_follow_the_style_numbering():
    assert chapter_label(7, "words") == "Chapter Seven"
    assert chapter_label(7, "numerals") == "Chapter 7"
    assert chapter_label(7, "none") == ""


def test_ranges_collapse_runs():
    assert format_ranges([9, 3, 7, 8]) == "3, 7–9"
    assert format_ranges([2]) == "2"


# -- resolving a selection ------------------------------------------------------


def test_no_selection_is_the_whole_book():
    docs = _book()
    assert resolve_selection(docs, None) == docs
    assert resolve_selection(docs, ExportSelection()) == docs


@pytest.mark.parametrize("token", ["3", "ch03", "CH03", "the bridge"])
def test_a_chapter_can_be_named_by_number_folder_or_title(token: str):
    chosen = resolve_selection(_book(), _pick(("chapter", token)))
    assert _keys(chosen) == ["ch03/01-crossing", "ch03/02-fall"]


@pytest.mark.parametrize("token", [
    "ch03/02-fall", "ch03/02-fall.md", "manuscript/ch03/02-fall.md", "02-fall", "the fall", "3.2",
])
def test_a_scene_can_be_named_by_path_stem_title_or_number(token: str):
    assert _keys(resolve_selection(_book(), _pick(("scene", token)))) == ["ch03/02-fall"]


def test_non_adjacent_chapters_keep_book_order():
    chosen = resolve_selection(_book(), _pick(("chapter", "4"), ("chapter", "1")))
    assert [d.chapter_number for d in chosen] == [1, 1, 4]


def test_a_chapter_range_takes_every_chapter_in_it():
    chosen = resolve_selection(_book(), _pick(("chapter", "2-3")))
    assert [d.chapter_number for d in chosen] == [2, 3, 3]


def test_hand_picked_scenes_keep_book_order_and_appear_once():
    chosen = resolve_selection(
        _book(), _pick(("scene", "4.1"), ("scene", "1.2"), ("chapter", "1")),
    )
    assert _keys(chosen) == ["ch01/01-opening", "ch01/02-late", "ch04/01-home"]


def test_custom_order_follows_the_picks():
    chosen = resolve_selection(
        _book(), _pick(("scene", "3.2"), ("chapter", "1"), ("scene", "1.1"), order="custom"),
    )
    # 1.1 was already taken by chapter 1, so it is not repeated.
    assert _keys(chosen) == ["ch03/02-fall", "ch01/01-opening", "ch01/02-late"]


@pytest.mark.parametrize("pick,message", [
    (("chapter", "9"), "no chapter 9; the book has chapters 1-4"),
    (("chapter", "3-1"), "runs backwards"),
    (("chapter", "brige"), "Did you mean"),
    (("scene", "7.1"), "no scene 1 in chapter 7"),
    (("scene", "nowhere"), "No scene called 'nowhere'"),
    (("verse", "1"), "not 'verse'"),
])
def test_bad_names_fail_with_a_readable_reason(pick: tuple[str, str], message: str):
    with pytest.raises(ExportError, match=message):
        resolve_selection(_book(), _pick(pick))


def test_an_ambiguous_scene_name_asks_for_its_path():
    docs = number_documents([
        _doc("A", "ch01", "01-arrival", "Arrival"),
        _doc("B", "ch02", "01-arrival", "Arrival"),
    ])
    with pytest.raises(ExportError, match="matches more than one scene"):
        resolve_selection(docs, _pick(("scene", "01-arrival")))


# -- the book --------------------------------------------------------------------


def _build(selection: ExportSelection | None):
    docs = _book()
    return build_book(
        docs, resolve_selection(docs, selection), title="Novel",
        identifier="urn:uuid:0b6f2d8e-5b0e-4a63-9c1e-2a1c5f9c8d11",
        selection=selection,
    )


def test_the_whole_book_is_a_book_with_its_own_identifier():
    book = _build(None)
    assert book.kind == "book" and book.has_contents
    assert book.identifier == "urn:uuid:0b6f2d8e-5b0e-4a63-9c1e-2a1c5f9c8d11"
    assert [c.number for c in book.chapters] == [1, 2, 3, 4]
    # A chapter named only by its folder has no title of its own.
    assert book.chapters[1].title == "" and book.chapters[0].title == "The Shop"


def test_one_scene_is_a_scene_without_contents():
    book = _build(_pick(("scene", "3.2")))
    assert book.kind == "scene" and not book.has_contents


def test_a_one_scene_chapter_picked_as_a_chapter_is_still_a_chapter():
    assert _build(_pick(("chapter", "2"))).kind == "chapter"
    assert _build(_pick(("scene", "2.1"))).kind == "scene"


def test_one_chapter_is_a_chapter_without_contents():
    book = _build(_pick(("chapter", "3")))
    assert book.kind == "chapter" and not book.has_contents
    assert book.chapters[0].number == 3


def test_several_whole_chapters_note_which_ones():
    book = _build(_pick(("chapter", "1"), ("chapter", "3-4")))
    assert book.kind == "selection" and book.has_contents
    assert book.note == "Chapters 1, 3–4"


def test_partial_chapters_are_noted_as_scenes_from_them():
    book = _build(_pick(("scene", "1.1"), ("scene", "3.2")))
    assert book.note == "Scenes from chapters 1, 3"


def test_custom_order_can_revisit_a_chapter():
    book = _build(_pick(("scene", "3.1"), ("scene", "1.1"), ("scene", "3.2"), order="custom"))
    assert [c.number for c in book.chapters] == [3, 1, 3]


def test_a_partial_book_has_a_stable_identifier_distinct_from_the_whole():
    first = _build(_pick(("chapter", "3")))
    again = _build(_pick(("chapter", "ch03")))
    other = _build(_pick(("chapter", "1")))
    whole = _build(None)
    assert first.identifier == again.identifier
    assert first.identifier != other.identifier != whole.identifier
    assert first.identifier.startswith("urn:uuid:")


def test_a_non_uuid_identifier_still_derives_part_identifiers():
    scenes = _book()[:1]
    assert selection_identifier("isbn:9780000000000", scenes) == selection_identifier("isbn:9780000000000", scenes)


def test_an_empty_selection_result_is_an_error():
    with pytest.raises(ExportError, match="picks no scenes"):
        build_book(_book(), [], title="Novel", selection=_pick(("chapter", "1")))


# -- saved selections --------------------------------------------------------------


def test_portable_selection_names_chapters_by_folder_and_scenes_by_path():
    portable = portable_selection(
        _book(), _pick(("chapter", "1-2"), ("scene", "3.2"), name="Beta"),
    )
    assert portable.picks == (("chapter", "ch01"), ("chapter", "ch02"), ("scene", "ch03/02-fall"))
    assert portable.name == "Beta"


def test_saved_selections_parse_from_config(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "export:\n"
        "  identifier: urn:uuid:0b6f2d8e-5b0e-4a63-9c1e-2a1c5f9c8d11\n"
        "  style: classic\n"
        "  scene_titles: true\n"
        "  selections:\n"
        "    Beta readers part 1:\n"
        "      chapters: [1, ch03]\n"
        "      scenes: ch04/01-home\n"
        "    Arc:\n"
        "      order: custom\n"
        "      items:\n"
        "        - scene: '3.2'\n"
        "        - chapter: 1\n",
        encoding="utf-8",
    )
    export = Config.load(tmp_path).export

    assert export.identifier.startswith("urn:uuid:") and export.style == "classic"
    assert export.scene_titles is True
    beta = export.selection("beta readers PART 1")
    assert beta.picks == (("chapter", "1"), ("chapter", "ch03"), ("scene", "ch04/01-home"))
    assert export.selection("Arc").picks == (("scene", "3.2"), ("chapter", "1"))
    assert export.selection("Arc").order == "custom"
    assert export.selection("missing") is None


@pytest.mark.parametrize("body,message", [
    ("export: [1]", "export must be a mapping"),
    ("export:\n  scene_titles: maybe", "scene_titles must be true or false"),
    ("export:\n  selections:\n    A:\n      order: random\n      chapters: [1]", "order must be one of"),
    ("export:\n  selections:\n    A: {}", "picks no chapters or scenes"),
    ("export:\n  selections:\n    A:\n      items:\n        - verse: 1", "must be a chapter or a scene"),
    ("export:\n  selections:\n    A:\n      scenes: [3.10]", "put chapter.scene numbers in quotes"),
])
def test_bad_export_config_fails_loudly(tmp_path: Path, body: str, message: str):
    (tmp_path / ".proseview.yaml").write_text(body + "\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        Config.load(tmp_path)


def _manuscript(tmp_path: Path) -> Path:
    for folder, stem, chapter in [
        ("ch01", "01-opening", "The Shop"), ("ch02", "01-ledger", "The Ledger"),
        ("ch03", "01-crossing", "The Bridge"),
    ]:
        path = tmp_path / "manuscript" / folder / f"{stem}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nchapter: {chapter}\n---\n\nProse.\n", encoding="utf-8")
    return tmp_path


def test_saving_a_selection_keeps_the_rest_of_the_config(tmp_path: Path):
    root = _manuscript(tmp_path)
    (root / ".proseview.yaml").write_text(
        "# My novel\ntarget_words: 90000  # a stretch\n", encoding="utf-8",
    )

    save_selection(root, Config.load(root), _pick(("chapter", "1"), ("chapter", "3"), name="Beta"))
    save_selection(root, Config.load(root), _pick(("scene", "2.1"), ("chapter", "1"), order="custom", name="Arc"))
    # Saving under an existing name (any case) replaces it.
    save_selection(root, Config.load(root), _pick(("chapter", "2"), name="beta"))

    text = (root / ".proseview.yaml").read_text(encoding="utf-8")
    assert text.startswith("# My novel\ntarget_words: 90000  # a stretch\n")
    export = Config.load(root).export
    assert [s.name for s in export.selections] == ["Arc", "beta"]
    assert export.selection("beta").picks == (("chapter", "ch02"),)
    assert export.selection("Arc").picks == (("scene", "ch02/01-ledger"), ("chapter", "ch01"))
    assert export.selection("Arc").order == "custom"
    assert _keys(collect_scene_documents(root, Config.load(root), export.selection("Arc"))) == [
        "ch02/01-ledger", "ch01/01-opening",
    ]


def test_a_saved_chapter_picks_up_scenes_added_later(tmp_path: Path):
    root = _manuscript(tmp_path)
    save_selection(root, Config(), _pick(("chapter", "3"), name="Bridge"))
    (root / "manuscript" / "ch03" / "02-after.md").write_text(
        "---\nchapter: The Bridge\n---\n\nLater.\n", encoding="utf-8",
    )

    cfg = Config.load(root)
    chosen = collect_scene_documents(root, cfg, cfg.export.selection("Bridge"))

    assert _keys(chosen) == ["ch03/01-crossing", "ch03/02-after"]
