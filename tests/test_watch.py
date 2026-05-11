"""Tests for watch-mode polling and debounce behavior."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.watch import snapshot_paths, wait_for_change  # noqa: E402


def test_snapshot_tracks_missing_and_present_config(tmp_path: Path):
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    scene.write_text("draft", encoding="utf-8")

    baseline = snapshot_paths(tmp_path, Config())
    assert baseline[".proseview.yaml"] == ("missing", None, None)

    cfg_path = tmp_path / ".proseview.yaml"
    cfg_path.write_text("target_words: 90000\n", encoding="utf-8")

    current = snapshot_paths(tmp_path, Config())
    assert current[".proseview.yaml"][0] == "file"
    assert current[".proseview.yaml"][2] == cfg_path.stat().st_size


def test_wait_for_change_debounces_before_returning(tmp_path: Path):
    (tmp_path / "manuscript" / "ch01").mkdir(parents=True)
    (tmp_path / "plans").mkdir()
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    plan = tmp_path / "plans" / "notes.md"
    scene.write_text("draft one", encoding="utf-8")
    plan.write_text("plan one", encoding="utf-8")

    baseline = snapshot_paths(tmp_path, Config())
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            scene.write_text("draft two", encoding="utf-8")
        elif len(sleeps) == 2:
            plan.write_text("plan two", encoding="utf-8")

    current, changed = wait_for_change(
        tmp_path,
        Config(),
        baseline,
        interval=0.2,
        debounce=0.5,
        sleep_fn=fake_sleep,
    )

    assert sleeps == [0.2, 0.5]
    assert "manuscript/ch01/01-opening.md" in changed
    assert "plans/notes.md" in changed
    assert current["manuscript/ch01/01-opening.md"] != baseline["manuscript/ch01/01-opening.md"]


def test_snapshot_tracks_visible_repo_files_outside_legacy_roots(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text("draft", encoding="utf-8")

    snapshot = snapshot_paths(tmp_path, Config())

    assert "docs/note.md" in snapshot


def test_snapshot_ignores_internal_cache_dirs(tmp_path: Path):
    cache = tmp_path / ".proseview"
    cache.mkdir()
    generated = cache / "history-cache.json"
    generated.write_text("{}", encoding="utf-8")

    snapshot = snapshot_paths(tmp_path, Config())

    assert ".proseview/history-cache.json" not in snapshot
