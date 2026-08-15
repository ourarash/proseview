"""Scene discovery across manuscript layouts.

Proseview used to index exactly one shape: ``manuscript/<chapter>/<scene>.md``.
Anything else -- a flat folder, a deeper tree, an Obsidian vault -- produced an
empty dashboard with no explanation, which made the README's "companion to
Obsidian and Longform" pitch untrue in the only way that matters.

These tests pin the layouts that must work, and the things that must still be
skipped when the whole repo is the manuscript.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.scenes import (  # noqa: E402
    collect_scene_stats,
    iter_scene_paths,
    resolve_manuscript_dir,
    scene_chapter,
)

SCENE = """\
---
title: A Scene
---

# A Scene

She counted the boats twice, and then a third time.
"""


def write(path: Path, text: str = SCENE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── Layouts that must be indexed ─────────────────────────────────────────────

def test_conventional_two_level_layout_still_works(tmp_path: Path):
    write(tmp_path / "manuscript" / "ch01" / "01-opening.md")
    write(tmp_path / "manuscript" / "ch02" / "01-turn.md")

    scenes = collect_scene_stats(tmp_path, "manuscript")

    assert len(scenes) == 2
    assert {s.chapter for s in scenes} == {"ch01", "ch02"}


def test_flat_folder_of_markdown_is_indexed(tmp_path: Path):
    write(tmp_path / "manuscript" / "one.md")
    write(tmp_path / "manuscript" / "two.md")

    scenes = collect_scene_stats(tmp_path, "manuscript")

    assert len(scenes) == 2
    # Nothing groups them, so they share the manuscript root's own name.
    assert {s.chapter for s in scenes} == {"manuscript"}


def test_deeply_nested_scenes_are_indexed_and_group_by_first_directory(tmp_path: Path):
    write(tmp_path / "manuscript" / "ch01" / "01.md")
    write(tmp_path / "manuscript" / "ch01" / "drafts" / "02.md")
    write(tmp_path / "manuscript" / "ch01" / "drafts" / "old" / "03.md")

    scenes = collect_scene_stats(tmp_path, "manuscript")

    assert len(scenes) == 3
    assert {s.chapter for s in scenes} == {"ch01"}, \
        "a deeper draft belongs to its chapter, not to a chapter of its own"


def test_a_vault_with_no_manuscript_directory_uses_the_repo_root(tmp_path: Path):
    """The Obsidian case: point it at the folder and it just works."""
    vault = tmp_path / "my-vault"
    write(vault / "daily.md")
    write(vault / "chapters" / "one.md")

    assert resolve_manuscript_dir(vault, "manuscript") == vault

    scenes = collect_scene_stats(vault, "manuscript")
    assert {s.path.name for s in scenes} == {"daily.md", "one.md"}


def test_explicit_dot_manuscript_path_selects_the_root(tmp_path: Path):
    write(tmp_path / "note.md")
    assert resolve_manuscript_dir(tmp_path, ".") == tmp_path
    assert resolve_manuscript_dir(tmp_path, "") == tmp_path


def test_an_existing_manuscript_directory_still_wins_over_the_root(tmp_path: Path):
    write(tmp_path / "manuscript" / "ch01" / "01.md")
    write(tmp_path / "stray.md")

    scenes = collect_scene_stats(tmp_path, "manuscript")

    assert [s.path.name for s in scenes] == ["01.md"], \
        "a repo with manuscript/ must not suddenly index the whole tree"


# ── Things that must stay out ────────────────────────────────────────────────

@pytest.mark.parametrize("skipped", [".obsidian", ".git", "node_modules", "__pycache__"])
def test_tool_directories_are_never_indexed(tmp_path: Path, skipped: str):
    write(tmp_path / "keep.md")
    write(tmp_path / skipped / "junk.md")

    names = {p.name for p in iter_scene_paths(tmp_path)}

    assert names == {"keep.md"}, f"{skipped}/ leaked into the scene index"


def test_readme_and_dotfiles_are_skipped(tmp_path: Path):
    write(tmp_path / "keep.md")
    write(tmp_path / "README.md")
    # Case-insensitively, in a separate directory so this works on macOS too,
    # where README.md and readme.md are the same file.
    write(tmp_path / "sub" / "ReadMe.md")
    write(tmp_path / ".hidden.md")

    names = {p.name for p in iter_scene_paths(tmp_path)}

    assert names == {"keep.md"}


def test_missing_directory_yields_no_scenes_rather_than_raising(tmp_path: Path):
    assert iter_scene_paths(tmp_path / "nope") == []


# ── Chapter labelling ────────────────────────────────────────────────────────

def test_frontmatter_chapter_always_wins(tmp_path: Path):
    write(
        tmp_path / "manuscript" / "ch01" / "01.md",
        SCENE.replace("title: A Scene", "title: A Scene\nchapter: Part One"),
    )

    scenes = collect_scene_stats(tmp_path, "manuscript")

    assert scenes[0].chapter == "Part One"


def test_scene_chapter_derivation(tmp_path: Path):
    root = tmp_path / "manuscript"
    assert scene_chapter(root / "ch01" / "01.md", root) == "ch01"
    assert scene_chapter(root / "ch01" / "drafts" / "01.md", root) == "ch01"
    assert scene_chapter(root / "01.md", root) == "manuscript"


# ── The dashboard must survive these layouts end to end ──────────────────────

def test_dashboard_builds_for_a_flat_vault(tmp_path: Path):
    from proseview.generator import build_dashboard

    vault = tmp_path / "vault"
    write(vault / "one.md")
    write(vault / "two.md")

    html = build_dashboard(vault, Config.load(vault))

    assert "one.md" in html and "two.md" in html


def test_saving_a_scene_works_in_a_vault(tmp_path: Path):
    """The failure that made vaults read-only.

    ``save_scene_content`` validated the target against ``root/manuscript``,
    which does not exist in a vault, so every save was rejected as "outside the
    manuscript directory" while reading worked fine.
    """
    from proseview.server import save_scene_content

    vault = tmp_path / "vault"
    scene = write(vault / "chapters" / "one.md")

    save_scene_content(
        str(scene), "Rewritten prose.\n", scene.stat().st_mtime, str(vault), "manuscript"
    )

    assert "Rewritten prose." in scene.read_text(encoding="utf-8")


def test_saving_outside_the_vault_is_still_refused(tmp_path: Path):
    from proseview.server import save_scene_content

    vault = tmp_path / "vault"
    write(vault / "one.md")
    outsider = write(tmp_path / "elsewhere" / "secret.md")

    with pytest.raises(PermissionError):
        save_scene_content(
            str(outsider), "nope\n", outsider.stat().st_mtime, str(vault), "manuscript"
        )


def test_git_history_covers_a_vault(tmp_path: Path):
    """The pathspec used to be the literal ``manuscript/``.

    In a vault that matches nothing, so history, the Goals panel, and the
    word-count delta all silently reported zero.
    """
    import subprocess

    from proseview import history

    vault = tmp_path / "vault"
    write(vault / "chapters" / "one.md")
    write(vault / "daily.md")
    env = {
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e",
        "PATH": os.environ["PATH"],
    }
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=vault, env=env, check=True, capture_output=True)

    cfg = Config.load(vault)
    assert history.manuscript_pathspec(vault, cfg) == "."

    commits = list(history.iter_manuscript_commits(vault, cfg))
    assert len(commits) == 1

    row = history.stats_for_commit(vault, commits[0].sha, cfg)
    assert row.scene_count == 2, "history must count the same scenes the dashboard indexes"
    assert row.total_words > 0


def test_export_collects_scenes_from_a_flat_vault(tmp_path: Path):
    from proseview.export import collect_scene_documents

    vault = tmp_path / "vault"
    write(vault / "one.md")
    write(vault / "chapters" / "two.md")

    documents = collect_scene_documents(vault, Config.load(vault))

    assert {d.path.name for d in documents} == {"one.md", "two.md"}
