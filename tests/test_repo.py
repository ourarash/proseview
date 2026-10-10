"""Tests for :mod:`proseview.repo` (M5).

Covers:
- non-manuscript folders in the demo fixture surface in the tree
- manuscript is excluded even if mistakenly listed in ``repo_tab.folders``
- oversized files are flagged ``too_large`` and their body is omitted
- small Markdown files ship inline bodies so the preview has no round-trip
- hidden entries are skipped
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config, RepoTabConfig  # noqa: E402
from proseview.repo import (  # noqa: E402
    build_context_tree,
    build_repository_tree,
    build_sidebar_tree,
    build_tree,
    create_repository_entry,
    rename_repository_entry,
    resolve_visible_repository_path,
    scene_relative_path,
    trash_repository_entry,
)
from proseview.scenes import iter_scene_paths  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-repo"


def _find_node(nodes: list[dict], name: str) -> dict | None:
    for n in nodes:
        if n["name"] == name:
            return n
    return None


def _find_descendant(nodes: list[dict], path: str) -> dict | None:
    for n in nodes:
        if n.get("path") == path:
            return n
        children = n.get("children") or []
        hit = _find_descendant(children, path)
        if hit is not None:
            return hit
    return None


def test_demo_fixture_surfaces_non_manuscript_folders():
    tree = build_tree(FIXTURE, Config.load(FIXTURE))
    names = {n["name"] for n in tree}
    assert "plans" in names
    assert "story-bible" in names
    assert "manuscript" not in names


def test_manuscript_excluded_even_if_listed(tmp_path: Path):
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    (tmp_path / "manuscript" / "ch01" / "scene.md").write_text("text", encoding="utf-8")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan.md").write_text("# plan", encoding="utf-8")

    cfg = Config().with_overrides(
        repo_tab=RepoTabConfig(folders=("manuscript", "plans"))
    )
    tree = build_tree(tmp_path, cfg)
    names = {n["name"] for n in tree}
    assert names == {"plans"}


def test_small_markdown_file_ships_body_inline(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    body = "# Plan\n\nParagraph.\n"
    # newline="" so the file holds exactly these bytes. Text mode on Windows
    # would translate to CRLF, and the assertions below compare bytes.
    (tmp_path / "plans" / "book-plan.md").write_text(body, encoding="utf-8", newline="")

    tree = build_tree(tmp_path, Config())
    node = _find_descendant(tree, "plans/book-plan.md")
    assert node is not None
    assert node["is_file"] is True
    assert node["is_text"] is True
    assert node["too_large"] is False
    assert node["body"] == body
    assert node["size"] == len(body.encode("utf-8"))
    # abs_path stays OS-native because it is what the editor handoff opens.
    assert Path(node["abs_path"]).parts[-2:] == ("plans", "book-plan.md")


def test_oversized_file_omits_body_and_flags_too_large(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    big = "x" * 2048
    (tmp_path / "plans" / "big.md").write_text(big, encoding="utf-8")

    cfg = Config().with_overrides(repo_tab=RepoTabConfig(preview_max_bytes=1024))
    tree = build_tree(tmp_path, cfg)
    node = _find_descendant(tree, "plans/big.md")
    assert node is not None
    assert node["too_large"] is True
    assert node["body"] is None


def test_binary_file_is_listed_without_body(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    tree = build_tree(tmp_path, Config())
    node = _find_descendant(tree, "plans/cover.png")
    assert node is not None
    assert node["is_text"] is False
    assert node["body"] is None
    assert node["too_large"] is False


def test_hidden_files_and_directories_are_skipped(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / ".secret.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "plans" / ".hidden-dir").mkdir()
    (tmp_path / "plans" / ".hidden-dir" / "x.md").write_text("x", encoding="utf-8")
    (tmp_path / "plans" / "visible.md").write_text("visible", encoding="utf-8")

    tree = build_tree(tmp_path, Config())
    plans = _find_node(tree, "plans")
    assert plans is not None
    child_names = {c["name"] for c in plans["children"]}
    assert child_names == {"visible.md"}


def test_missing_folders_do_not_error(tmp_path: Path):
    # No folders from the default list exist. Tree should be empty.
    tree = build_tree(tmp_path, Config())
    assert tree == []


def test_nested_directories_recurse(tmp_path: Path):
    (tmp_path / "story-bible" / "characters").mkdir(parents=True)
    (tmp_path / "story-bible" / "characters" / "nima.md").write_text("# Nima", encoding="utf-8")
    (tmp_path / "story-bible" / "themes.md").write_text("# Themes", encoding="utf-8")

    tree = build_tree(tmp_path, Config())
    sb = _find_node(tree, "story-bible")
    assert sb is not None
    # Directories come before files when sorted (dir=False sorts before file=True).
    child_kinds = [c["is_file"] for c in sb["children"]]
    assert child_kinds == [False, True]
    chars = _find_descendant(tree, "story-bible/characters")
    assert chars is not None
    assert chars["is_file"] is False
    nima = _find_descendant(tree, "story-bible/characters/nima.md")
    assert nima is not None
    assert nima["body"] == "# Nima"


def test_custom_folders_config_is_honored(tmp_path: Path):
    (tmp_path / "craft").mkdir()
    (tmp_path / "craft" / "note.md").write_text("note", encoding="utf-8")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan.md").write_text("plan", encoding="utf-8")

    cfg = Config().with_overrides(repo_tab=RepoTabConfig(folders=("craft",)))
    tree = build_tree(tmp_path, cfg)
    names = {n["name"] for n in tree}
    assert names == {"craft"}


def test_context_tree_includes_attachable_files_across_the_repository(tmp_path: Path):
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    (tmp_path / "manuscript" / "ch01" / "scene.md").write_text("scene", encoding="utf-8")
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "timeline.txt").write_text("timeline", encoding="utf-8")
    (tmp_path / "README.md").write_text("read me", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "panel.js").write_text("export const panel = true;\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    (tmp_path / "cover.png").write_bytes(b"\x89PNG")
    (tmp_path / "too-large.md").write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    (tmp_path / ".private").mkdir()
    (tmp_path / ".private" / "secret.md").write_text("secret", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.md").write_text("dependency", encoding="utf-8")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "research" / "escape.md").symlink_to(outside)

    tree = build_context_tree(tmp_path)

    assert _find_descendant(tree, "manuscript/ch01/scene.md") is not None
    assert _find_descendant(tree, "research/timeline.txt") is not None
    assert _find_descendant(tree, "README.md") is not None
    assert _find_descendant(tree, "src/agent.py") is not None
    assert _find_descendant(tree, "web/panel.js") is not None
    assert _find_descendant(tree, "Makefile") is not None
    assert _find_descendant(tree, "cover.png") is None
    assert _find_descendant(tree, "too-large.md") is None
    assert _find_descendant(tree, ".private/secret.md") is None
    assert _find_descendant(tree, "node_modules/package.md") is None
    assert _find_descendant(tree, "research/escape.md") is None
    scene = _find_descendant(tree, "manuscript/ch01/scene.md")
    assert scene is not None
    assert "body" not in scene
    assert "abs_path" not in scene


def test_repository_tree_is_canonical_across_navigation_and_context_boundaries(tmp_path: Path):
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    (tmp_path / "manuscript" / "ch01" / "scene.md").write_text("scene", encoding="utf-8")
    (tmp_path / "outside-preview").mkdir()
    (tmp_path / "outside-preview" / "tool.py").write_text("print('tool')\n", encoding="utf-8")
    (tmp_path / "outside-preview" / "cover.png").write_bytes(b"\x89PNG\x00")

    tree = build_repository_tree(tmp_path, Config())

    scene = _find_descendant(tree, "manuscript/ch01/scene.md")
    tool = _find_descendant(tree, "outside-preview/tool.py")
    binary = _find_descendant(tree, "outside-preview/cover.png")
    assert scene and scene["is_scene"] is True and scene["scene_path"] == "ch01/scene.md"
    assert tool and tool["attachable"] is True and tool["previewable"] is True
    assert binary and binary["attachable"] is False and binary["previewable"] is False
    assert "body" not in tool and "abs_path" not in tool


def test_manuscript_files_outside_the_scene_index_are_plain_repository_files(tmp_path: Path):
    """Only files ``iter_scene_paths`` indexes may be flagged ``is_scene``.

    A note nested below a chapter dir has no entry in the client's scene
    index, so routing it to the scene modal would dead-end the click.
    """
    chapter = tmp_path / "manuscript" / "ch05"
    (chapter / "review").mkdir(parents=True)
    (chapter / "05-work-session.md").write_text("scene", encoding="utf-8")
    (chapter / "README.md").write_text("chapter readme", encoding="utf-8")
    (chapter / "review" / "05-work-session-review.md").write_text("note", encoding="utf-8")

    tree = build_repository_tree(tmp_path, Config())
    indexed = {p.relative_to(tmp_path / "manuscript").as_posix()
               for p in iter_scene_paths(tmp_path / "manuscript")}

    scene = _find_descendant(tree, "manuscript/ch05/05-work-session.md")
    nested = _find_descendant(tree, "manuscript/ch05/review/05-work-session-review.md")
    readme = _find_descendant(tree, "manuscript/ch05/README.md")

    assert scene and scene["is_scene"] is True and scene["scene_path"] in indexed
    assert nested and nested["is_scene"] is False and nested["scene_path"] is None
    assert readme and readme["is_scene"] is False and readme["scene_path"] is None


def test_sidebar_lists_nested_manuscript_notes_as_plain_files(tmp_path: Path):
    """The sidebar keeps nested manuscript notes but does not call them scenes.

    They stay clickable through the file preview; marking them ``is_scene``
    would send the click to a scene the client cannot render.
    """
    chapter = tmp_path / "manuscript" / "ch05"
    (chapter / "review").mkdir(parents=True)
    (chapter / "05-work-session.md").write_text("scene", encoding="utf-8")
    (chapter / "review" / "05-work-session-review.md").write_text("note", encoding="utf-8")

    tree = build_sidebar_tree(tmp_path, Config())

    scene = _find_descendant(tree, "manuscript/ch05/05-work-session.md")
    nested = _find_descendant(tree, "manuscript/ch05/review/05-work-session-review.md")
    assert scene and scene["is_scene"] is True and scene["scene_path"] == "ch05/05-work-session.md"
    assert nested and nested["is_scene"] is False and nested["scene_path"] is None


def test_sidebar_lists_images_and_other_files_beside_the_prose(tmp_path: Path):
    """They can be found and opened from the file browser, but are never scenes."""
    chapter = tmp_path / "manuscript" / "ch01"
    chapter.mkdir(parents=True)
    (chapter / "01-opening.md").write_text("scene", encoding="utf-8")
    (chapter / "map.png").write_bytes(b"\x89PNG\r\n")
    (chapter / "notes.txt").write_text("loose notes", encoding="utf-8")
    (chapter / ".DS_Store").write_bytes(b"\0")

    tree = build_sidebar_tree(tmp_path, Config())

    names = [child["name"] for child in _find_descendant(tree, "manuscript/ch01")["children"]]
    assert names == ["01-opening.md", "map.png", "notes.txt"]
    for rel in ("manuscript/ch01/map.png", "manuscript/ch01/notes.txt"):
        node = _find_descendant(tree, rel)
        assert node["is_scene"] is False and not node.get("scene_path")
    from proseview.scenes import iter_scene_paths

    assert [p.name for p in iter_scene_paths(tmp_path / "manuscript")] == ["01-opening.md"]


def test_sidebar_lists_a_folder_without_a_manuscript_subfolder(tmp_path: Path):
    """With no manuscript folder the browser lists everything as plain files;
    once the folder is named the book, its scenes are marked as scenes."""
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "Chapter 1").mkdir()
    (tmp_path / "Chapter 1" / "01 Café.md").write_text("scene", encoding="utf-8")
    (tmp_path / "chapter-02.md").write_text("scene", encoding="utf-8")
    (tmp_path / "map.png").write_bytes(b"\x89PNG")

    tree = build_sidebar_tree(tmp_path, Config())
    assert [node["name"] for node in tree] == ["Chapter 1", "chapter-02.md", "map.png"]
    assert not _find_descendant(tree, "Chapter 1/01 Café.md")["is_scene"]

    tree = build_sidebar_tree(tmp_path, Config(manuscript_path="./"))
    cafe = _find_descendant(tree, "Chapter 1/01 Café.md")
    assert cafe["is_scene"] is True and cafe["scene_path"] == "Chapter 1/01 Café.md"
    assert _find_descendant(tree, "chapter-02.md")["scene_path"] == "chapter-02.md"
    assert _find_descendant(tree, "map.png")["is_scene"] is False


@pytest.mark.parametrize(
    "relative,expected",
    [
        ("manuscript/ch05/scene.md", "ch05/scene.md"),
        ("manuscript/ch05/review/note.md", None),
        ("manuscript/ch05/README.md", None),
        ("manuscript/loose.md", None),
        ("plans/ch05/scene.md", None),
    ],
)
def test_scene_relative_path_matches_scene_discovery(relative: str, expected: str | None):
    assert scene_relative_path(relative, "manuscript") == expected


# "/tmp/secret.txt" is only absolute off Windows; there it is just a relative
# path that happens to start with a slash, and the rejection has a different
# reason. Name an absolute path the platform actually recognises.
_ABSOLUTE_OUTSIDE = "C:/Windows/secret.txt" if os.name == "nt" else "/tmp/secret.txt"


@pytest.mark.parametrize(
    "relative",
    [".private/token.txt", "docs/.private/token.txt", ".git/config", _ABSOLUTE_OUTSIDE, "../secret.txt"],
)
def test_visible_repository_path_rejects_internal_or_non_relative_paths(tmp_path: Path, relative: str):
    with pytest.raises(ValueError, match="safe visible repository"):
        resolve_visible_repository_path(tmp_path, relative)


def test_visible_repository_path_rejects_symlinks_even_when_the_target_is_contained(tmp_path: Path):
    target = tmp_path / "target.md"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="safe visible repository"):
        resolve_visible_repository_path(tmp_path, "link.md")


# ── File explorer mutations ─────────────────────────────────────────────────


def _managed_repo(tmp_path: Path) -> Config:
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    (tmp_path / "story-bible" / "characters").mkdir(parents=True)
    return Config()


def test_create_repository_entry_adds_empty_markdown_and_one_folder(tmp_path: Path):
    cfg = _managed_repo(tmp_path)

    created = create_repository_entry(
        tmp_path, cfg, "manuscript/ch01", "03-café-at-dawn", "file"
    )
    folder = create_repository_entry(
        tmp_path, cfg, "story-bible", "locations", "folder"
    )

    assert created == "manuscript/ch01/03-café-at-dawn.md"
    assert (tmp_path / created).read_bytes() == b""
    assert folder == "story-bible/locations"
    assert (tmp_path / folder).is_dir()


def test_create_repository_entry_never_overwrites_or_reaches_unmanaged_paths(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    existing = tmp_path / "manuscript" / "ch01" / "existing.md"
    existing.write_bytes(b"keep me")
    (tmp_path / "private").mkdir()

    with pytest.raises(FileExistsError):
        create_repository_entry(tmp_path, cfg, "manuscript/ch01", "existing", "file")
    with pytest.raises(PermissionError, match="managed file-browser folder"):
        create_repository_entry(tmp_path, cfg, "private", "escape", "file")
    with pytest.raises(ValueError, match="single visible name"):
        create_repository_entry(tmp_path, cfg, "manuscript/ch01", "../escape", "file")

    assert existing.read_bytes() == b"keep me"
    assert not (tmp_path / "private" / "escape.md").exists()


def test_a_folder_without_manuscript_manages_files_anywhere_in_it(tmp_path: Path):
    """In a vault the whole folder is the manuscript, so the file browser can
    create, rename and trash anywhere in it, but never the folder itself."""
    cfg = Config()
    (tmp_path / "Part One" / "Chapter 2").mkdir(parents=True)

    created = create_repository_entry(tmp_path, cfg, "Part One/Chapter 2", "02 Été à Montréal", "file")
    assert created == "Part One/Chapter 2/02 Été à Montréal.md"
    renamed = rename_repository_entry(tmp_path, cfg, "Part One/Chapter 2", "Chapitre Deux")
    assert renamed == "Part One/Chapitre Deux"
    assert (tmp_path / "Part One" / "Chapitre Deux" / "02 Été à Montréal.md").is_file()
    assert create_repository_entry(tmp_path, cfg, "", "loose", "file") == "loose.md"
    trash_repository_entry(tmp_path, cfg, "loose.md")
    assert not (tmp_path / "loose.md").exists()


def test_create_repository_entry_rejects_symlinked_parent(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "manuscript" / "linked"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="safe visible repository"):
        create_repository_entry(tmp_path, cfg, "manuscript/linked", "scene", "file")
    assert not (outside / "scene.md").exists()


def test_rename_repository_entry_preserves_markdown_extension_and_bytes(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    source = tmp_path / "manuscript" / "ch01" / "03-draft.md"
    original = b"# Draft\n\nUnchanged prose.\n"
    source.write_bytes(original)

    renamed = rename_repository_entry(
        tmp_path, cfg, "manuscript/ch01/03-draft.md", "03-final"
    )

    assert renamed == "manuscript/ch01/03-final.md"
    assert not source.exists()
    assert (tmp_path / renamed).read_bytes() == original


def test_rename_repository_entry_moves_a_folder_without_rewriting_descendants(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    chapter = tmp_path / "manuscript" / "ch01"
    scene = chapter / "01-opening.md"
    scene.write_bytes(b"exact scene bytes\r\n")

    renamed = rename_repository_entry(tmp_path, cfg, "manuscript/ch01", "chapter-one")

    assert renamed == "manuscript/chapter-one"
    assert (tmp_path / renamed / "01-opening.md").read_bytes() == b"exact scene bytes\r\n"
    assert not chapter.exists()


def test_rename_repository_entry_protects_roots_and_existing_destinations(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    chapter = tmp_path / "manuscript" / "ch01"
    (chapter / "one.md").write_text("one", encoding="utf-8")
    (chapter / "two.md").write_text("two", encoding="utf-8")

    with pytest.raises(PermissionError, match="top-level managed folder"):
        rename_repository_entry(tmp_path, cfg, "manuscript", "draft")
    with pytest.raises(FileExistsError):
        rename_repository_entry(tmp_path, cfg, "manuscript/ch01/one.md", "two")

    assert (chapter / "one.md").read_text(encoding="utf-8") == "one"
    assert (chapter / "two.md").read_text(encoding="utf-8") == "two"


def test_trash_repository_entry_preserves_a_nonempty_folder_for_recovery(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    chapter = tmp_path / "manuscript" / "ch01"
    (chapter / "one.md").write_bytes(b"one\n")
    (chapter / "notes").mkdir()
    (chapter / "notes" / "private.txt").write_bytes(b"recoverable\n")

    result = trash_repository_entry(tmp_path, cfg, "manuscript/ch01")
    trashed = tmp_path / result["trash_path"]

    assert result["path"] == "manuscript/ch01"
    assert result["kind"] == "folder"
    assert result["entry_count"] == 3
    assert not chapter.exists()
    assert trashed.is_relative_to(tmp_path / ".proseview" / "trash")
    assert (trashed / "one.md").read_bytes() == b"one\n"
    assert (trashed / "notes" / "private.txt").read_bytes() == b"recoverable\n"


def test_trash_repository_entry_rejects_managed_roots_and_symlinks(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    outside = tmp_path / "delete-outside.md"
    outside.write_text("safe", encoding="utf-8")
    link = tmp_path / "manuscript" / "ch01" / "link.md"
    link.symlink_to(outside)

    with pytest.raises(PermissionError, match="top-level managed folder"):
        trash_repository_entry(tmp_path, cfg, "manuscript")
    with pytest.raises(ValueError, match="safe visible repository"):
        trash_repository_entry(tmp_path, cfg, "manuscript/ch01/link.md")

    assert outside.read_text(encoding="utf-8") == "safe"


def test_trash_repository_entry_rejects_a_symlinked_trash_directory(tmp_path: Path):
    cfg = _managed_repo(tmp_path)
    scene = tmp_path / "manuscript" / "ch01" / "scene.md"
    scene.write_text("keep me", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    internal = tmp_path / ".proseview"
    internal.mkdir()
    (internal / "trash").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(PermissionError, match="must not be a symlink"):
        trash_repository_entry(tmp_path, cfg, "manuscript/ch01/scene.md")

    assert scene.read_text(encoding="utf-8") == "keep me"
    assert list(elsewhere.iterdir()) == []


def test_a_file_in_another_encoding_reads_and_is_not_rewritten(tmp_path: Path):
    """One Windows-1252 scene used to fail the whole page with a decode error."""
    from proseview.repo import _file_node, read_repo_text, require_utf8_file
    from proseview.scenes import collect_scene_stats
    from proseview.server import save_note_content

    chapter = tmp_path / "manuscript" / "ch01"
    chapter.mkdir(parents=True)
    old = chapter / "01.md"
    old.write_bytes("Café au lait, déjà vu.\n".encode("cp1252"))
    (chapter / "02.md").write_text("Plain prose.\n", encoding="utf-8")
    utf16 = tmp_path / "notes.md"
    utf16.write_bytes("Notes in UTF-16.\n".encode("utf-16"))

    assert read_repo_text(old) == "Café au lait, déjà vu.\n"
    assert read_repo_text(utf16) == "Notes in UTF-16.\n"
    assert len(collect_scene_stats(tmp_path, "manuscript")) == 2

    node = _file_node(old, tmp_path, 100_000)
    assert node["body"] == "Café au lait, déjà vu.\n" and node["not_utf8"] is True

    with pytest.raises(ValueError, match="not saved as UTF-8"):
        require_utf8_file(old)
    before = old.read_bytes()
    with pytest.raises(ValueError, match="not saved as UTF-8"):
        save_note_content("manuscript/ch01/01.md", "Rewritten.", old.stat().st_mtime, str(tmp_path))
    assert old.read_bytes() == before


def test_windows_line_endings_read_as_newlines(tmp_path: Path):
    """Reading bytes, not text, once let a checkout's \\r\\n through, so a save
    on Windows doubled every line of frontmatter."""
    from proseview.repo import read_repo_text

    path = tmp_path / "scene.md"
    path.write_bytes(b"---\r\ntitle: One\r\n---\r\n\r\nProse.\r\n")
    assert read_repo_text(path) == "---\ntitle: One\n---\n\nProse.\n"


def test_recently_modified_reads_file_dates_and_marks_uncommitted_work(tmp_path: Path):
    """It used to list only files in commits from the last seven days, so a
    writer with a week of unsaved-to-git edits saw "No files changed"."""
    import os
    import subprocess
    import time

    from proseview.repo import recent_changes

    chapter = tmp_path / "manuscript" / "ch01"
    chapter.mkdir(parents=True)
    old = chapter / "01.md"
    old.write_text("Old prose.\n", encoding="utf-8")
    committed = chapter / "02.md"
    committed.write_text("Committed today.\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    month_ago = time.time() - 30 * 86400
    os.utime(old, (month_ago, month_ago))
    edited = chapter / "03.md"
    edited.write_text("Written today, not committed.\n", encoding="utf-8")

    entries, available = recent_changes(tmp_path, Config())

    assert available is True
    assert [e["path"] for e in entries] == ["manuscript/ch01/03.md", "manuscript/ch01/02.md"]
    assert [e["uncommitted"] for e in entries] == [True, False]
    assert entries[0]["is_scene"] and entries[0]["scene_path"] == "ch01/03.md"

    # Without git the list is the same, just with nothing marked.
    plain = tmp_path / "plain"
    (plain / "manuscript" / "ch01").mkdir(parents=True)
    (plain / "manuscript" / "ch01" / "01.md").write_text("Prose.\n", encoding="utf-8")
    entries, _ = recent_changes(plain, Config())
    assert [(e["path"], e["uncommitted"]) for e in entries] == [("manuscript/ch01/01.md", False)]
