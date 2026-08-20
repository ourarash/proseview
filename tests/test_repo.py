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
    resolve_visible_repository_path,
    scene_relative_path,
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
    assert node["abs_path"].endswith("plans/book-plan.md")


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
