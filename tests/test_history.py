"""Tests for :mod:`proseview.history`.

The tests build a tiny git repo in ``tmp_path`` and drive it through the real
``git`` CLI so we exercise the same ``git log`` / ``git show`` / ``git status``
code paths the generator will hit on a real book. A couple of tests also run
against the non-git demo fixture to cover the warning-once and empty-delta
branches.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import history  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.history import (  # noqa: E402
    HistoryCache,
    is_git_repo,
    iter_manuscript_commits,
    load_history,
    stats_for_commit,
    working_copy_delta,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-repo"


def _run(cmd: list[str], cwd: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(cmd, cwd=cwd, check=True, env=env,
                   capture_output=True, text=True, encoding="utf-8")


@pytest.fixture
def tiny_book(tmp_path: Path) -> Path:
    """A minimal git repo with two commits touching ``manuscript/`` and a
    third commit that touches only ``notes/`` (should be filtered out).
    """
    repo = tmp_path / "book"
    shutil.copytree(FIXTURE, repo)
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)

    scene = repo / "manuscript" / "ch01" / "01-opening.md"
    scene.write_text(
        scene.read_text(encoding="utf-8")
        + "\n\nAn added paragraph with a clutch of new words to bump the total.\n",
        encoding="utf-8",
    )
    _run(["git", "add", "manuscript/ch01/01-opening.md"], repo)
    _run(["git", "commit", "-q", "-m", "extend opening"], repo)

    notes = repo / "notes.md"
    notes.write_text("side channel\n", encoding="utf-8")
    _run(["git", "add", "notes.md"], repo)
    _run(["git", "commit", "-q", "-m", "side note"], repo)
    return repo


def test_is_git_repo_matches_expectation(tiny_book: Path, tmp_path: Path):
    assert is_git_repo(tiny_book) is True
    assert is_git_repo(tmp_path) is False


def test_iter_manuscript_commits_filters_and_orders(tiny_book: Path):
    commits = list(iter_manuscript_commits(tiny_book, Config()))
    # Two manuscript-touching commits; "side note" is filtered out.
    assert len(commits) == 2
    # Oldest first (--reverse).
    assert commits[0].committed_at <= commits[1].committed_at
    # Changed-paths include at least one manuscript scene for each.
    for c in commits:
        assert any(p.startswith("manuscript/") for p in c.changed_paths)


def test_iter_manuscript_commits_on_non_git_warns_once(tmp_path: Path):
    history._GIT_WARNED = False
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        list(iter_manuscript_commits(tmp_path, Config()))
        list(iter_manuscript_commits(tmp_path, Config()))
    messages = [str(w.message) for w in captured]
    assert sum("not a git repo" in m for m in messages) == 1


def test_stats_for_commit_matches_head_snapshot(tiny_book: Path):
    commits = list(iter_manuscript_commits(tiny_book, Config()))
    row = stats_for_commit(tiny_book, commits[-1].sha, Config())
    assert row.total_words > 0
    assert row.scene_count > 0
    assert row.chapter_count >= 1
    assert row.tool_version


def test_load_history_uses_cache_on_second_call(tiny_book: Path):
    cfg = Config()
    rows1 = load_history(tiny_book, cfg)
    assert len(rows1) == 2
    cache_path = tiny_book / ".proseview" / "history-cache.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(data) == {r.sha for r in rows1}

    # Monkeypatch stats_for_commit to prove the warm path doesn't recompute.
    original = history.stats_for_commit
    called: list[str] = []

    def spy(root, sha, cfg):
        called.append(sha)
        return original(root, sha, cfg)

    history.stats_for_commit = spy
    try:
        rows2 = load_history(tiny_book, cfg)
    finally:
        history.stats_for_commit = original
    assert rows2 == rows1
    assert called == [], "warm-start load should not recompute any SHA"


def test_history_cache_roundtrip(tmp_path: Path):
    cache = HistoryCache(tmp_path)
    row = history.HistoryRow(
        sha="abc123", committed_at="2026-04-17T10:00:00-07:00",
        total_words=42, scene_count=3, chapter_count=1,
        mattr=0.75, mtld=110.5, characters_active=("Rena",),
        tool_version="test",
    )
    cache.put(row)
    cache.save()
    # Fresh instance reads from disk.
    reloaded = HistoryCache(tmp_path)
    assert reloaded.get("abc123") == row


def test_history_cache_tolerates_corrupt_json(tmp_path: Path):
    path = tmp_path / ".proseview" / "history-cache.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    cache = HistoryCache(tmp_path)
    assert cache.get("anything") is None


def test_working_copy_delta_counts_added_words_today(tiny_book: Path):
    cfg = Config()
    rows = load_history(tiny_book, cfg)
    # Dirty the working tree.
    scene = tiny_book / "manuscript" / "ch01" / "01-opening.md"
    scene.write_text(scene.read_text(encoding="utf-8")
                     + "\n\nword " * 25,
                     encoding="utf-8")
    delta = working_copy_delta(tiny_book, cfg, rows)
    # 25 extra words minimum, minus any commit-since-midnight baseline math.
    assert delta.words_added_today >= 1
    assert delta.scenes_touched_today >= 1


def test_working_copy_delta_on_non_git_returns_zero(tmp_path: Path):
    delta = working_copy_delta(tmp_path, Config(), [])
    assert delta.words_added_today == 0
    assert delta.scenes_touched_today == 0
