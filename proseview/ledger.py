"""Where a day's words went: written and cut, scene by scene.

A net figure hides the work in it. Replacing a 1,776-word draft with 697 new
words reads as -1,079, which says nothing about the 697. The ledger splits
each change into the words written and the words cut, by a word-level diff of
each scene against a baseline: the manuscript at the end of the last day
Proseview saw (``.proseview/day-text-prev.json``), or the last commit before
today when it has no such day.

Text moved from one scene to another counts as cut where it left and written
where it landed. A renamed scene is matched to its old file by content, so a
rename alone writes and cuts nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .lexical import WORD_RE

DAY_TEXT_PATH = Path(".proseview") / "day-text.json"
DAY_TEXT_PREV_PATH = Path(".proseview") / "day-text-prev.json"

#: Each closed day's written and cut, scene by scene: {day: {"since", "rows"}}.
DAY_LEDGERS_PATH = Path(".proseview") / "day-ledgers.json"
DAY_LEDGERS_KEEP = 400

#: How alike an added and a removed scene must be to count as one renamed.
RENAME_SIMILARITY = 0.5


@dataclass(frozen=True)
class LedgerRow:
    path: str
    title: str
    status: str  # "changed", "new", "removed" or "renamed"
    old_path: str
    written: int
    cut: int
    saved_at: float | None

    @property
    def net(self) -> int:
        return self.written - self.cut


@dataclass(frozen=True)
class Ledger:
    baseline_date: str
    #: "day" when measured from the end of a day Proseview saw, "commit" when
    #: from the last commit before today.
    baseline_kind: str
    rows: tuple[LedgerRow, ...]

    @property
    def written(self) -> int:
        return sum(row.written for row in self.rows)

    @property
    def cut(self) -> int:
        return sum(row.cut for row in self.rows)


def word_changes(old: str, new: str) -> tuple[int, int]:
    """``(written, cut)`` between two texts, counted in the dashboard's words.

    ``written - cut`` is always the change in word count, so the ledger adds up
    to the net figure beside it.
    """
    a, b = WORD_RE.findall(old), WORD_RE.findall(new)
    if a == b:
        return 0, 0
    written = cut = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            cut += i2 - i1
        if tag in ("replace", "insert"):
            written += j2 - j1
    return written, cut


def _similarity(old: str, new: str) -> float:
    matcher = SequenceMatcher(None, WORD_RE.findall(old), WORD_RE.findall(new), autojunk=False)
    if matcher.real_quick_ratio() < RENAME_SIMILARITY or matcher.quick_ratio() < RENAME_SIMILARITY:
        return 0.0
    return matcher.ratio()


def build_ledger(
    baseline: dict[str, str],
    current: dict[str, str],
    *,
    baseline_date: str,
    baseline_kind: str,
    titles: dict[str, str] | None = None,
    saved_at: dict[str, float] | None = None,
) -> Ledger:
    """Compare two ``{path: prose}`` maps. Paths missing from *baseline* are
    new scenes; paths missing from *current* were removed."""
    titles = titles or {}
    saved_at = saved_at or {}
    rows: list[LedgerRow] = []

    for path in sorted(set(baseline) & set(current)):
        written, cut = word_changes(baseline[path], current[path])
        if written or cut:
            rows.append(LedgerRow(path, titles.get(path, path), "changed", path,
                                  written, cut, saved_at.get(path)))

    removed = sorted(set(baseline) - set(current))
    for path in sorted(set(current) - set(baseline)):
        best, best_score = None, RENAME_SIMILARITY
        for old in removed:
            score = _similarity(baseline[old], current[path])
            if score >= best_score:
                best, best_score = old, score
        if best is not None:
            removed.remove(best)
            written, cut = word_changes(baseline[best], current[path])
            if not (written or cut):
                continue  # renamed only: no words moved
            rows.append(LedgerRow(path, titles.get(path, path), "renamed", best,
                                  written, cut, saved_at.get(path)))
        else:
            rows.append(LedgerRow(path, titles.get(path, path), "new", "",
                                  len(WORD_RE.findall(current[path])), 0, saved_at.get(path)))
    for path in removed:
        rows.append(LedgerRow(path, Path(path).stem, "removed", path,
                              0, len(WORD_RE.findall(baseline[path])), None))

    rows.sort(key=lambda row: (row.saved_at is None, -(row.saved_at or 0), row.path))
    return Ledger(baseline_date, baseline_kind, tuple(rows))


def read_day_text(root: Path, rel: Path = DAY_TEXT_PATH) -> tuple[str, dict[str, str]] | None:
    """``(date, {path: prose})`` from a day snapshot, or None."""
    try:
        raw = json.loads((root / rel).read_text(encoding="utf-8"))
        day, files = str(raw["date"]), raw["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(files, dict):
        return None
    return day, {str(k): str(v) for k, v in files.items() if isinstance(v, str)}


def _write_json(path: Path, data: object) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def record_day_text(root: Path, today: str, current: dict[str, str]) -> tuple[str, dict[str, str]] | None:
    """Keep today's manuscript text, and return the last earlier day's.

    ``day-text.json`` holds the latest text seen today. When a new day starts,
    the old one moves to ``day-text-prev.json`` first: the end of that day, the
    baseline for this one. Two copies of the prose, never more.
    """
    latest = read_day_text(root)
    if latest is not None and latest[0] < today:
        _write_json(root / DAY_TEXT_PREV_PATH, {"date": latest[0], "files": latest[1]})
    if latest is None or latest != (today, current):
        _write_json(root / DAY_TEXT_PATH, {"date": today, "files": current})
    previous = read_day_text(root, DAY_TEXT_PREV_PATH)
    if previous is not None and previous[0] >= today:
        return None
    if latest is not None and latest[0] < today:
        return latest
    return previous


def read_day_ledgers(root: Path) -> dict[str, dict]:
    """``{day: {"since": day, "kind": "day"|"commit", "rows": [...]}}``."""
    try:
        raw = json.loads((root / DAY_LEDGERS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def store_day_ledger(root: Path, day: str, ledger: Ledger) -> None:
    """Keep a closed day's rows, so a week or a month adds up without keeping
    a copy of the book for every day."""
    ledgers = read_day_ledgers(root)
    ledgers[day] = {
        "since": ledger.baseline_date,
        "kind": ledger.baseline_kind,
        "rows": [
            {"path": r.path, "status": r.status, "old_path": r.old_path,
             "written": r.written, "cut": r.cut}
            for r in ledger.rows
        ],
    }
    keep = sorted(ledgers)[-DAY_LEDGERS_KEEP:]
    _write_json(root / DAY_LEDGERS_PATH, {d: ledgers[d] for d in keep})


def combine_rows(groups: list[list[dict]]) -> list[dict]:
    """Add per-scene rows from several days into one row per scene."""
    merged: dict[str, dict] = {}
    for rows in groups:
        for row in rows:
            entry = merged.setdefault(row["path"], {**row, "written": 0, "cut": 0})
            entry["written"] += int(row.get("written", 0))
            entry["cut"] += int(row.get("cut", 0))
            # A scene new on one day and edited later is still new over the span.
            if row.get("status") == "new":
                entry["status"] = "new"
            elif row.get("status") == "removed":
                entry["status"] = "removed"
    return [row for row in merged.values() if row["written"] or row["cut"] or row["status"] == "new"]
