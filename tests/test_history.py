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


def test_iter_manuscript_commits_on_non_git_says_so_once(tmp_path: Path, capsys):
    history._GIT_WARNED = False
    list(iter_manuscript_commits(tmp_path, Config()))
    list(iter_manuscript_commits(tmp_path, Config()))
    err = capsys.readouterr().err
    assert err.count("not a git repo") == 1
    assert "Warning" not in err


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


def test_rows_cached_under_an_older_measure_are_measured_again(tmp_path: Path):
    """A cached row keeps the numbers of the rule that counted it.

    When the count itself changes -- TODO and NOTE comments stopped counting
    as words -- rows cached before it would keep the old totals beside new
    ones, and the goal history would show a drop nobody wrote.
    """
    import json
    from proseview.history import HISTORY_MEASURE

    row = {
        "sha": "abc123", "committed_at": "2026-01-01T00:00:00+00:00", "total_words": 1000,
        "scene_count": 1, "chapter_count": 1, "mattr": 0.7, "mtld": 80.0,
        "characters_active": [], "tool_version": "0.3.0",
    }
    path = tmp_path / ".proseview" / "history-cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"abc123": row}), encoding="utf-8")
    assert HistoryCache(tmp_path).get("abc123") is None

    path.write_text(json.dumps({"abc123": {**row, "measure": HISTORY_MEASURE}}), encoding="utf-8")
    cache = HistoryCache(tmp_path)
    assert cache.get("abc123").total_words == 1000
    cache.put(cache.get("abc123"))
    cache.save()
    assert json.loads(path.read_text(encoding="utf-8"))["abc123"]["measure"] == HISTORY_MEASURE


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


def test_working_copy_delta_measures_today_from_the_day_log(tiny_book: Path):
    """Yesterday's logged total is today's baseline, even with no commit since.

    Against commits alone, every uncommitted day was folded into "today" and a
    net cut was floored to +0.
    """
    from datetime import date, timedelta

    cfg = Config()
    rows = load_history(tiny_book, cfg)
    first = working_copy_delta(tiny_book, cfg, rows)
    log_path = tiny_book / ".proseview" / "day-log.json"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    current = log[today]["total"]

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    log[yesterday] = {"total": current + 40, "worked": True}
    log_path.write_text(json.dumps(log), encoding="utf-8")
    delta = working_copy_delta(tiny_book, cfg, rows)
    assert delta.baseline_date == yesterday
    assert delta.words_added_today == -40, "a day of cutting reads as a negative, not +0"
    assert yesterday in delta.worked_days
    assert delta.day_totals[today] == current
    assert first.scenes_touched_today >= 1
    # Every commit is from today: nothing earlier to measure a ledger against.
    assert first.ledger is None


def test_scenes_touched_today_ignores_edits_from_earlier_days(tiny_book: Path):
    """An uncommitted change saved three days ago is not today's work."""
    import time

    cfg = Config()
    rows = load_history(tiny_book, cfg)
    before = working_copy_delta(tiny_book, cfg, rows).scenes_touched_today
    scenes = sorted((tiny_book / "manuscript").rglob("*.md"))
    other = next(p for p in scenes if p.name != "01-opening.md" and p.name != "README.md")
    other.write_text(other.read_text(encoding="utf-8") + "\n\nOld edit.\n", encoding="utf-8")
    old = time.time() - 3 * 86400
    os.utime(other, (old, old))
    assert working_copy_delta(tiny_book, cfg, rows).scenes_touched_today == before


def test_day_log_tolerates_a_corrupt_file(tmp_path: Path):
    from proseview.history import read_day_log, record_day

    path = tmp_path / ".proseview" / "day-log.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    assert read_day_log(tmp_path) == {}
    log = record_day(tmp_path, "2026-10-22", 1200, worked=False)
    assert log == {"2026-10-22": {"total": 1200, "worked": False}}
    # "worked" never turns back off within a day.
    record_day(tmp_path, "2026-10-22", 1300, worked=True)
    assert record_day(tmp_path, "2026-10-22", 1250, worked=False)["2026-10-22"] == {"total": 1250, "worked": True}


def test_working_copy_delta_on_non_git_returns_zero(tmp_path: Path):
    delta = working_copy_delta(tmp_path, Config(), [])
    assert delta.words_added_today == 0
    assert delta.scenes_touched_today == 0


def _encrypted_book(tmp_path: Path, *, unlocked: bool) -> Path:
    """A repo whose committed Markdown is stored the way git-crypt stores it.

    The clean filter writes a git-crypt header and scrambled bytes, so a blob
    read without the smudge filter is not text. With *unlocked*, the smudge
    filter is configured and reading through filters gives the plain file.
    """
    repo = tmp_path / "crypt"
    (repo / "manuscript" / "ch01").mkdir(parents=True)
    (repo / "manuscript" / "ch01" / "01.md").write_text("Café prose in four words.\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.md filter=crypt\n", encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text(
        "import sys\nb = sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(b'\\x00GITCRYPT\\x00' + bytes(x ^ 0xF9 for x in b))\n",
        encoding="utf-8",
    )
    smudge = tmp_path / "smudge.py"
    smudge.write_text(
        "import sys\nb = sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(bytes(x ^ 0xF9 for x in b[10:]) if b.startswith(b'\\x00GITCRYPT') else b)\n",
        encoding="utf-8",
    )
    python = Path(sys.executable).as_posix()
    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "filter.crypt.clean", f'"{python}" "{clean.as_posix()}"'], repo)
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)
    if not unlocked:
        _run(["git", "config", "--unset", "filter.crypt.clean"], repo)
    else:
        _run(["git", "config", "filter.crypt.smudge", f'"{python}" "{smudge.as_posix()}"'], repo)
    return repo


def test_history_reads_an_unlocked_git_crypt_repo_through_its_filters(tmp_path: Path):
    repo = _encrypted_book(tmp_path, unlocked=True)
    commits = list(iter_manuscript_commits(repo, Config()))
    row = stats_for_commit(repo, commits[-1].sha, Config())
    assert row.total_words == 5 and row.scene_count == 1


def test_history_skips_encrypted_blobs_instead_of_failing(tmp_path: Path):
    """A locked git-crypt repo used to take the whole dashboard down with a
    UnicodeDecodeError from ``git show``."""
    repo = _encrypted_book(tmp_path, unlocked=False)
    commits = list(iter_manuscript_commits(repo, Config()))
    row = stats_for_commit(repo, commits[-1].sha, Config())
    assert row.total_words == 0 and row.scene_count == 0
    assert load_history(repo, Config()) is not None


def test_git_that_cannot_be_started_reads_as_not_installed(tmp_path: Path, monkeypatch):
    # The in-browser app has no processes: starting one raises a plain OSError.
    def refuse(*args, **kwargs):
        raise OSError(95, "Operation not supported")

    monkeypatch.setattr(history.subprocess, "run", refuse)
    assert history._run_git_bytes(tmp_path, ["status"]) == (127, b"", b"git executable not found")
    assert not is_git_repo(tmp_path)


def test_ledger_measures_today_from_the_end_of_yesterday(tiny_book: Path):
    from datetime import date, timedelta
    from proseview.ledger import DAY_TEXT_PATH

    cfg = Config()
    rows = load_history(tiny_book, cfg)
    working_copy_delta(tiny_book, cfg, rows)
    # Pretend that snapshot was taken yesterday, then write today.
    path = tiny_book / DAY_TEXT_PATH
    snap = json.loads(path.read_text(encoding="utf-8"))
    snap["date"] = (date.today() - timedelta(days=1)).isoformat()
    path.write_text(json.dumps(snap), encoding="utf-8")
    scene = tiny_book / "manuscript" / "ch01" / "01-opening.md"
    scene.write_text(scene.read_text(encoding="utf-8") + "\n\nSeven brand new words arrive right here.\n",
                     encoding="utf-8")

    delta = working_copy_delta(tiny_book, cfg, rows)
    ledger = delta.ledger
    assert ledger.baseline_kind == "day"
    assert (ledger.written, ledger.cut) == (7, 0)
    assert delta.words_added_today == 7


def test_what_changed_says_when_there_is_no_record_yet(tiny_book: Path):
    from proseview.history import what_changed

    data = what_changed(tiny_book, Config(), source="record", period="today")
    assert "no copy of your book from before today" in data["empty"]


def test_what_changed_against_a_chosen_commit(tiny_book: Path):
    from proseview.history import what_changed

    scene = tiny_book / "manuscript" / "ch01" / "01-opening.md"
    scene.write_text(scene.read_text(encoding="utf-8") + "\n\nFive new words right here.\n", encoding="utf-8")
    data = what_changed(tiny_book, Config(), source="git")
    assert len(data["commits"]) == 2
    assert data["sha"] == data["commits"][0]["sha"]
    assert data["sha"][:7] in data["basis"] and "not committed" in data["basis"]
    row = next(r for r in data["rows"] if r["path"].endswith("01-opening.md"))
    assert (row["written"], row["cut"]) == (5, 0)

    # Against the first commit, the opening paragraph added by the second
    # commit counts too.
    older = what_changed(tiny_book, Config(), source="git", sha=data["commits"][1]["sha"])
    row = next(r for r in older["rows"] if r["path"].endswith("01-opening.md"))
    assert row["written"] > 5


def test_a_closed_day_is_kept_for_yesterday_and_the_week(tiny_book: Path):
    """When a new day starts, the day that ended is stored as written and cut
    per scene, measured from the end of the day before it."""
    from datetime import date, timedelta
    from proseview.history import what_changed
    from proseview.ledger import DAY_TEXT_PATH, DAY_TEXT_PREV_PATH

    cfg = Config()
    rows = load_history(tiny_book, cfg)
    working_copy_delta(tiny_book, cfg, rows)
    path = tiny_book / DAY_TEXT_PATH
    snap = json.loads(path.read_text(encoding="utf-8"))
    rel = next(p for p in snap["files"] if p.endswith("01-opening.md"))
    days = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731
    before = dict(snap["files"])
    before[rel] = before[rel] + "\n\nThree cut words."
    (tiny_book / DAY_TEXT_PREV_PATH).write_text(json.dumps({"date": days(2), "files": before}), encoding="utf-8")
    snap["date"] = days(1)
    path.write_text(json.dumps(snap), encoding="utf-8")

    yesterday = what_changed(tiny_book, cfg, source="record", period="yesterday")
    row = next(r for r in yesterday["rows"] if r["path"].endswith("01-opening.md"))
    assert (row["written"], row["cut"]) == (0, 3)
    assert not yesterday["notes"], "the day before was seen, so there is no gap to name"

    week = what_changed(tiny_book, cfg, source="record", period="week")
    assert [d["day"] for d in week["by_day"]] == [days(0), days(1)]
    assert any("record starts on" in note for note in week["notes"])
