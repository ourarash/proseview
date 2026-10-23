"""Git-derived manuscript history and working-copy delta.

History is fully reproducible from the repo: git is the source of truth,
``.proseview/history-cache.json`` is a content-addressed cache keyed by SHA.
Orphaned cache entries (from rebases) are harmless — SHAs are immutable, so
a cached row for an unreachable commit is simply never read.

Public surface:
    iter_manuscript_commits(root, cfg) -> Iterable[CommitInfo]
    stats_for_commit(root, sha, cfg)   -> HistoryRow
    load_history(root, cfg, *, since)  -> list[HistoryRow]
    working_copy_delta(root, cfg, hist) -> WorkingCopyDelta
    HistoryCache                          # persistent SHA->row map
    read_day_log(root) / record_day(...)  # end-of-day totals seen on disk
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:  # imported lazily at runtime; .scenes imports from here
    from .scenes import SceneStats

from . import __version__ as PROSEVIEW_VERSION
from .config import Config
from .ledger import (
    DAY_TEXT_PREV_PATH, Ledger, build_ledger, combine_rows, read_day_ledgers, read_day_text,
    record_day_text, store_day_ledger,
)
from .lexical import calculate_lexical_stats, count_words, prose_only
from .repo import CONTEXT_SKIP_DIRS, decode_repo_bytes
from .scenes import resolve_manuscript_dir


HISTORY_CACHE_PATH = Path(".proseview") / "history-cache.json"

#: The manuscript's word total at the end of each day Proseview saw it, and
#: whether a scene was saved that day. Commits alone miss every day of work
#: that was not committed, which left the goals at zero while the writer wrote.
DAY_LOG_PATH = Path(".proseview") / "day-log.json"
DAY_LOG_KEEP_DAYS = 400

#: How a commit's words and lexical figures are measured. Rows cached under
#: another measure are counted again, so a history never mixes two rules --
#: bump this whenever the measuring changes. 2: TODO and NOTE comments are not
#: prose.
HISTORY_MEASURE = 2

_GIT_WARNED = False


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    committed_at: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class HistoryRow:
    sha: str
    committed_at: str
    total_words: int
    scene_count: int
    chapter_count: int
    mattr: float
    mtld: float
    characters_active: tuple[str, ...]
    tool_version: str


@dataclass(frozen=True)
class WorkingCopyDelta:
    """What the files on disk say about today.

    ``words_added_today`` is net (words written minus words cut), so it can be
    negative on a day of cutting. ``baseline_date`` is the day it is measured
    from: yesterday's end when the day log has it, else the last commit before
    today. ``day_totals`` and ``worked_days`` carry the day log, so the goals
    see work that was never committed.
    """
    words_added_today: int
    scenes_touched_today: int
    baseline_date: str = ""
    day_totals: dict[str, int] = field(default_factory=dict)
    worked_days: frozenset[str] = frozenset()
    ledger: Ledger | None = None


def _run_git(root: Path, args: list[str]) -> tuple[int, str, str]:
    """Run git; its output decoded as UTF-8, never raising on odd bytes."""
    code, out, err = _run_git_bytes(root, args)
    return code, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def _run_git_bytes(root: Path, args: list[str]) -> tuple[int, bytes, bytes]:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError:
        # No git installed, or no processes at all (the in-browser app).
        return 127, b"", b"git executable not found"
    return result.returncode, result.stdout, result.stderr


#: How git-crypt marks an encrypted blob.
_GIT_CRYPT_MAGIC = b"\x00GITCRYPT"


def git_blob_text(root: Path, sha: str, path: str) -> str | None:
    """A committed version of *path* as text, or None when it is not text.

    Read through the repository's filters (``cat-file --filters``), so a
    git-crypt repository that is unlocked gives back the plain file, as the
    working tree shows it. A blob that is still encrypted, or binary, is
    None: it is left out rather than counted as words or shown as prose.
    """
    code, out, _ = _run_git_bytes(root, ["cat-file", "--filters", f"{sha}:{path}"])
    if code != 0:
        code, out, _ = _run_git_bytes(root, ["show", f"{sha}:{path}"])
        if code != 0:
            return None
    if out.startswith(_GIT_CRYPT_MAGIC) or b"\x00" in out[:8000]:
        return None
    text, _is_utf8 = decode_repo_bytes(out)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_git_repo(root: Path) -> bool:
    """True only when ``root`` is the top-level of its own worktree.

    We intentionally reject subdirectories of a larger repo: Proseview's
    ``root`` is the book repo root, and running against a subdir (e.g. a
    fixture inside another project) would otherwise scrape unrelated history
    and pollute ``root/.proseview/``.
    """
    code, out, _ = _run_git(root, ["rev-parse", "--show-toplevel"])
    if code != 0:
        return False
    try:
        return Path(out.strip()).resolve() == root.resolve()
    except OSError:
        return False


def _warn_no_git_once(message: str = "not a git repo; skipping Goals panel") -> None:
    global _GIT_WARNED
    if _GIT_WARNED:
        return
    # A plain line, not a Python warning: the writer reads it in the terminal
    # Proseview runs in, where a warning shows a source line and a class name.
    print(f"proseview: {message}", file=sys.stderr)
    _GIT_WARNED = True


def iter_manuscript_commits(root: Path, cfg: Config) -> Iterable[CommitInfo]:
    """Walk ``git log --first-parent`` for commits that touched
    ``cfg.manuscript_path``. Yields oldest-first so history computations can
    rely on monotonic ordering. Returns an empty iterable (with a single
    warning) when the directory is not a git repo.
    """
    if not is_git_repo(root):
        _warn_no_git_once()
        return []
    code, out, _ = _run_git(root, [
        "log", "--first-parent", "--reverse", "--date=iso-strict",
        "--pretty=format:__PV__ %H %cI",
        "--name-only",
        "--", manuscript_pathspec(root, cfg),
    ])
    if code != 0:
        return []
    return _parse_git_log(out)


def _parse_git_log(out: str) -> list[CommitInfo]:
    rows: list[CommitInfo] = []
    sha: str | None = None
    ts: str = ""
    paths: list[str] = []
    for line in out.splitlines():
        if line.startswith("__PV__ "):
            if sha is not None:
                rows.append(CommitInfo(sha, ts, tuple(paths)))
            parts = line[len("__PV__ "):].split(" ", 1)
            sha = parts[0]
            ts = parts[1] if len(parts) > 1 else ""
            paths = []
        elif line.strip():
            paths.append(line.strip())
    if sha is not None:
        rows.append(CommitInfo(sha, ts, tuple(paths)))
    return rows


def commit_scene_paths(root: Path, cfg: Config, sha: str) -> list[str] | None:
    """The scene files that existed at *sha*, or None when git cannot say."""
    manuscript_dir = resolve_manuscript_dir(root, cfg.manuscript_subdir)
    at_root = manuscript_dir.resolve() == root.resolve()
    manuscript_prefix = "" if at_root else cfg.manuscript_subdir + "/"
    code, out, _ = _run_git(root, [
        "ls-tree", "-r", "--name-only", sha, "--", manuscript_pathspec(root, cfg),
    ])
    if code != 0:
        return None

    strip_parts = 0 if at_root else len(Path(manuscript_prefix.rstrip("/")).parts)
    # Mirrors iter_scene_paths: a scene sits in the manuscript or in a chapter
    # folder; no README, no tool directories.
    return [
        p for p in out.splitlines()
        if p.endswith(".md")
        and len(Path(p).parts) - strip_parts <= 2
        and Path(p).name.lower() != "readme.md"
        and not Path(p).name.startswith(".")
        and p.startswith(manuscript_prefix)
        and not any(
            part.startswith(".") or part in CONTEXT_SKIP_DIRS for part in Path(p).parts[:-1]
        )
    ]


def stats_for_commit(root: Path, sha: str, cfg: Config) -> HistoryRow:
    """Snapshot the manuscript at ``sha``, run lexical and scene analysis over
    it, and return a :class:`HistoryRow`.

    Uses ``git ls-tree`` to enumerate the scene files that existed at the
    commit, then ``git show <sha>:<path>`` to stream each file's content. This
    is slower than a single ``git archive`` but keeps the code straightforward
    and parallelizes well on warm starts.
    """
    # Import locally to avoid a scenes <- history cycle and to keep this module
    # importable even if scenes changes shape later.
    from .scenes import extract_scene_text, split_frontmatter

    manuscript_dir = resolve_manuscript_dir(root, cfg.manuscript_subdir)
    at_root = manuscript_dir.resolve() == root.resolve()
    manuscript_prefix = "" if at_root else cfg.manuscript_subdir + "/"
    paths = commit_scene_paths(root, cfg, sha)
    if paths is None:
        return _empty_row(sha, _committed_at_for(root, sha))
    strip = 0 if at_root else len(Path(manuscript_prefix.rstrip("/")).parts)

    total_words = 0
    scene_count = 0
    chapters: set[str] = set()
    pieces: list[str] = []
    for p in paths:
        content = git_blob_text(root, sha, p)
        if content is None:
            continue
        _, body = split_frontmatter(content)
        text = prose_only(extract_scene_text(body))
        total_words += count_words(text)
        scene_count += 1
        rel_parts = Path(p).parts[strip:]
        chapters.add(rel_parts[0] if len(rel_parts) > 1 else manuscript_dir.name)
        pieces.append(text)

    lex = calculate_lexical_stats("\n".join(pieces)) if pieces else None
    char_list = list(cfg.characters) if cfg.characters else _scan_characters_at_head(root, cfg.characters_dir)
    joined = "\n".join(pieces)
    chars_present = tuple(
        n for n in char_list
        if re.search(rf"\b{re.escape(n)}\b", joined, re.IGNORECASE)
    )

    return HistoryRow(
        sha=sha,
        committed_at=_committed_at_for(root, sha),
        total_words=total_words,
        scene_count=scene_count,
        chapter_count=len(chapters),
        mattr=round(lex.mattr, 4) if lex else 0.0,
        mtld=round(lex.mtld, 2) if lex else 0.0,
        characters_active=chars_present,
        tool_version=PROSEVIEW_VERSION,
    )


def _committed_at_for(root: Path, sha: str) -> str:
    code, out, _ = _run_git(root, ["log", "-1", "--date=iso-strict", "--pretty=format:%cI", sha])
    return out.strip() if code == 0 else ""


def _scan_characters_at_head(root: Path, characters_dir: str = "story-bible/characters") -> list[str]:
    char_dir = root / characters_dir
    if not char_dir.exists():
        return []
    from .generator import character_name_from_file

    return [character_name_from_file(p) for p in sorted(char_dir.glob("*.md"))]


def _empty_row(sha: str, committed_at: str) -> HistoryRow:
    return HistoryRow(
        sha=sha, committed_at=committed_at,
        total_words=0, scene_count=0, chapter_count=0,
        mattr=0.0, mtld=0.0, characters_active=(), tool_version=PROSEVIEW_VERSION,
    )


class HistoryCache:
    """Persistent SHA-keyed cache at ``.proseview/history-cache.json``.

    Lazy-loaded; dirty only when a new row is added. A missing or corrupt
    file is treated as an empty cache (and will be rewritten on save).
    """

    def __init__(self, root: Path) -> None:
        self.path = root / HISTORY_CACHE_PATH
        self._data: dict[str, HistoryRow] = {}
        self._dirty = False
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for sha, d in raw.items():
            if not isinstance(d, dict) or d.get("measure") != HISTORY_MEASURE:
                continue
            try:
                self._data[sha] = HistoryRow(
                    sha=d["sha"],
                    committed_at=d["committed_at"],
                    total_words=int(d["total_words"]),
                    scene_count=int(d["scene_count"]),
                    chapter_count=int(d["chapter_count"]),
                    mattr=float(d["mattr"]),
                    mtld=float(d["mtld"]),
                    characters_active=tuple(d.get("characters_active", ())),
                    tool_version=str(d.get("tool_version", "")),
                )
            except (KeyError, TypeError, ValueError):
                continue

    def get(self, sha: str) -> HistoryRow | None:
        self.load()
        return self._data.get(sha)

    def put(self, row: HistoryRow) -> None:
        self.load()
        self._data[row.sha] = row
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        serialized = {
            sha: {**asdict(row), "measure": HISTORY_MEASURE}
            for sha, row in sorted(self._data.items())
        }
        tmp.write_text(json.dumps(serialized, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False


def load_history(root: Path, cfg: Config, *, since: str | None = None,
                 max_workers: int = 8) -> list[HistoryRow]:
    """Walk manuscript commits and return cached-or-computed history rows.

    Cold start computes every uncached SHA in a thread pool; warm start is
    just a cache read. ``since`` accepts ``"N days ago"`` or an ISO-8601
    date/datetime to limit cold-start cost.
    """
    commits = list(iter_manuscript_commits(root, cfg))
    if since is not None:
        cutoff = _parse_since_to_iso(since)
        commits = [c for c in commits if c.committed_at >= cutoff]
    if not commits:
        return []

    cache = HistoryCache(root)
    cache.load()

    to_compute: list[CommitInfo] = [c for c in commits if cache.get(c.sha) is None]
    if to_compute:
        if len(to_compute) == 1 or max_workers <= 1:
            for c in to_compute:
                cache.put(stats_for_commit(root, c.sha, cfg))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for row in pool.map(lambda c: stats_for_commit(root, c.sha, cfg), to_compute):
                    cache.put(row)
        cache.save()

    rows = [cache.get(c.sha) for c in commits]
    return [r for r in rows if r is not None]


def _parse_since_to_iso(since: str) -> str:
    m = re.fullmatch(r"\s*(\d+)\s+days?\s+ago\s*", since)
    if m:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
        return cutoff.isoformat()
    return since


def manuscript_pathspec(root: Path, cfg: Config) -> str:
    """Git pathspec limiting a query to the manuscript.

    ``cfg.manuscript_path`` is wrong for a repo with no ``manuscript/``
    directory -- the whole repo is the manuscript there, and the literal
    pathspec would match nothing, silently emptying history and the Goals panel.
    """
    manuscript_dir = resolve_manuscript_dir(root, cfg.manuscript_subdir)
    if manuscript_dir.resolve() == root.resolve():
        return "."
    return cfg.manuscript_path


@dataclass(frozen=True)
class DayRecord:
    """What :func:`record_today` saw and wrote."""
    scenes: list
    today: str
    total: int
    touched: set
    saved_days: set
    log: dict
    prose: dict
    previous_day: tuple | None


_RECORD_LOCK = threading.Lock()


def record_today(root: Path, cfg: Config, scenes: list[SceneStats] | None = None) -> DayRecord:
    """Write today's total and a copy of today's prose to ``.proseview/``.

    Called on every dashboard build and, by the server, whenever the file
    watcher sees the manuscript change, so an edit made in any editor while
    Proseview runs lands on the day it was made rather than the next day the
    dashboard happened to be rebuilt.
    """
    with _RECORD_LOCK:
        if scenes is None:
            from .scenes import collect_scene_stats

            scenes = collect_scene_stats(root, cfg.manuscript_subdir, lexical=False)
        current_total = sum(s.words for s in scenes)

        today = date.today().isoformat()
        scene_paths = {s.path.as_posix() for s in scenes}
        touched: set[str] = set()
        # A scene's modification date is also the one trace a day of uncommitted
        # work leaves behind before the day log existed: each file says the last
        # day it was saved.
        saved_days: set[str] = set()
        for rel in scene_paths:
            try:
                saved = date.fromtimestamp((root / rel).stat().st_mtime).isoformat()
            except OSError:
                continue
            saved_days.add(saved)
            if saved == today:
                touched.add(rel)

        code, out, _ = _run_git(root, [
            "log", "--since=midnight", "--pretty=format:", "--name-only",
            "--", manuscript_pathspec(root, cfg),
        ])
        if code == 0:
            for line in out.splitlines():
                s = line.strip()
                if s in scene_paths:
                    touched.add(s)

        log = record_day(root, today, current_total, worked=bool(touched))
        current_prose = {s.path.as_posix(): prose_only(s.text) for s in scenes}
        _close_last_day(root, cfg, today)
        previous_day = record_day_text(root, today, current_prose)
        return DayRecord(scenes, today, current_total, touched, saved_days, log,
                         current_prose, previous_day)


def working_copy_delta(root: Path, cfg: Config,
                       history: list[HistoryRow],
                       scenes: list[SceneStats] | None = None) -> WorkingCopyDelta:
    """Compute "today" numbers from the files on disk.

    words_added_today = current word total - the total at the end of the last
                        earlier day: from the day log when it has that day,
                        else from the last commit before today
    scenes_touched_today = scenes saved today (file modified today) PLUS
                           scenes in commits since midnight

    Records today's total in the day log as a side effect, so tomorrow has an
    exact baseline even when nothing is committed.

    Pass *scenes* when the caller has already indexed the manuscript. Only the
    word total is needed here, and re-indexing runs the full lexical analysis of
    every scene a second time -- about half the cost of a dashboard build.
    """
    if not is_git_repo(root):
        return WorkingCopyDelta(0, 0)

    record = record_today(root, cfg, scenes)
    scenes, today = record.scenes, record.today
    current_total, touched, saved_days = record.total, record.touched, record.saved_days
    log, current_prose, previous_day = record.log, record.prose, record.previous_day
    scene_paths = {s.path.as_posix() for s in scenes}

    baseline, baseline_date, baseline_sha = 0, "", ""
    for row in reversed(history):
        if row.committed_at[:10] < today:
            baseline, baseline_date, baseline_sha = row.total_words, row.committed_at[:10], row.sha
            break
    earlier_logged = [d for d in log if d < today and d >= baseline_date]
    if earlier_logged:
        baseline_date = max(earlier_logged)
        baseline = log[baseline_date]["total"]

    ledger_kwargs = {
        "titles": {s.path.as_posix(): s.title for s in scenes},
        "saved_at": _mtimes(root, scene_paths),
    }
    if previous_day is not None and previous_day[0] >= baseline_date:
        ledger = build_ledger(previous_day[1], current_prose, baseline_date=previous_day[0],
                              baseline_kind="day", **ledger_kwargs)
        # The text and the total come from the same moment: let the banner
        # agree with the ledger under it.
        baseline_date = previous_day[0]
        baseline = sum(count_words(text) for text in previous_day[1].values())
    elif baseline_sha:
        committed = _commit_prose(root, cfg, baseline_sha, current_prose)
        ledger = build_ledger(committed, current_prose,
                              baseline_date=baseline_date, baseline_kind="commit", **ledger_kwargs)
        baseline = sum(count_words(text) for text in committed.values())
    else:
        ledger = None

    return WorkingCopyDelta(
        words_added_today=current_total - baseline,
        scenes_touched_today=len(touched),
        baseline_date=baseline_date,
        day_totals={d: entry["total"] for d, entry in log.items()},
        worked_days=frozenset(saved_days | {d for d, entry in log.items() if entry["worked"]}),
        ledger=ledger,
    )


def _close_last_day(root: Path, cfg: Config, today: str) -> None:
    """When a new day starts, keep the day that just ended as written and
    cut per scene, measured from the end of the day before it -- or, when
    Proseview has no such day, from the last commit before it."""
    latest = read_day_text(root)
    if latest is None or latest[0] >= today or latest[0] in read_day_ledgers(root):
        return
    day, text = latest
    previous = read_day_text(root, DAY_TEXT_PREV_PATH)
    if previous is not None and previous[0] < day:
        ledger = build_ledger(previous[1], text, baseline_date=previous[0], baseline_kind="day")
    else:
        code, out, _ = _run_git(root, [
            "log", "-1", f"--before={day}T00:00:00", "--format=%H%x09%ad", "--date=short",
            "--", manuscript_pathspec(root, cfg),
        ])
        if code != 0 or not out.strip():
            return
        sha, committed = out.strip().split("\t", 1)
        ledger = build_ledger(_commit_prose(root, cfg, sha, None), text,
                              baseline_date=committed, baseline_kind="commit")
    store_day_ledger(root, day, ledger)


def _mtimes(root: Path, paths: Iterable[str]) -> dict[str, float]:
    found: dict[str, float] = {}
    for rel in paths:
        try:
            found[rel] = (root / rel).stat().st_mtime
        except OSError:
            continue
    return found


def _commit_prose(root: Path, cfg: Config, sha: str, current: dict[str, str] | None) -> dict[str, str]:
    """``{path: prose}`` at *sha*, read from git only where it may differ.

    Scenes unchanged since *sha* are copied from *current* (the files now), so
    a ledger costs one ``git show`` per changed file rather than one per
    scene. With ``current=None`` every scene is read from git.
    """
    from .scenes import _is_scene, extract_scene_text, split_frontmatter

    paths = commit_scene_paths(root, cfg, sha) or []
    code, out, _ = _run_git(root, [
        "diff", "--no-renames", "--name-only", sha, "--", manuscript_pathspec(root, cfg),
    ])
    changed = set(out.splitlines()) if code == 0 and current is not None else set(paths)
    prose: dict[str, str] = {}
    for path in paths:
        if path not in changed and current is not None and path in current:
            prose[path] = current[path]
            continue
        content = git_blob_text(root, sha, path)
        if content is None:
            continue
        fm, body = split_frontmatter(content)
        if _is_scene(fm):
            prose[path] = prose_only(extract_scene_text(body))
    return prose


def read_day_log(root: Path) -> dict[str, dict[str, object]]:
    """``{date: {"total": int, "worked": bool}}``; empty when missing or corrupt."""
    try:
        raw = json.loads((root / DAY_LOG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    log: dict[str, dict[str, object]] = {}
    if not isinstance(raw, dict):
        return log
    for day, entry in raw.items():
        if not isinstance(entry, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)):
            continue
        try:
            log[str(day)] = {"total": int(entry["total"]), "worked": bool(entry.get("worked"))}
        except (KeyError, TypeError, ValueError):
            continue
    return log


def record_day(root: Path, day: str, total: int, *, worked: bool) -> dict[str, dict[str, object]]:
    """Set *day*'s total in the day log and return the whole log.

    The last total seen on a day stands for its end. ``worked`` only ever turns
    on: a scene saved in the morning still counts after a later commit makes
    the tree clean. A log that cannot be written is not an error -- the goals
    fall back to commits, as before.
    """
    log = read_day_log(root)
    previous = log.get(day, {})
    entry = {"total": total, "worked": bool(previous.get("worked")) or worked}
    if previous == entry:
        return log
    log[day] = entry
    keep = sorted(log)[-DAY_LOG_KEEP_DAYS:]
    log = {d: log[d] for d in keep}
    path = root / DAY_LOG_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(log, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return log


#: The periods the record answers for, as the number of days they cover.
WHAT_CHANGED_PERIODS = {"today": 1, "yesterday": 1, "week": 7, "month": 30}


def _short_day(iso: str) -> str:
    try:
        moment = date.fromisoformat(iso)
    except ValueError:
        return iso
    return moment.strftime("%b ") + str(moment.day)


def what_changed(root: Path, cfg: Config, *, source: str = "record",
                 period: str = "today", sha: str = "") -> dict[str, object]:
    """The "What changed" dialog's data: words written and cut per scene.

    ``source="record"`` reads Proseview's own daily record for *period*
    (today, yesterday, week, month); ``source="git"`` compares the files now
    with commit *sha* (the last manuscript commit when empty). Every answer
    says what it was measured against, and a gap in the record is named
    rather than hidden.
    """
    if not is_git_repo(root):
        return {"empty": "What changed needs the book to be a git repository."}
    record = record_today(root, cfg)
    prefix = cfg.manuscript_subdir + "/"
    titles = {s.path.as_posix(): s.title for s in record.scenes}
    saved = _mtimes(root, titles)

    def shape(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            path = row["path"]
            out.append({
                "path": path[len(prefix):] if path.startswith(prefix) else path,
                "title": titles.get(path) or Path(path).name,
                "status": row.get("status", "changed"),
                "old_path": row.get("old_path", ""),
                "written": int(row.get("written", 0)),
                "cut": int(row.get("cut", 0)),
                "saved": saved.get(path),
                "live": path in titles,
            })
        out.sort(key=lambda r: (r["saved"] is None, -(r["saved"] or 0), r["path"]))
        return out

    def rows_of(ledger: Ledger) -> list[dict]:
        return [{"path": r.path, "status": r.status, "old_path": r.old_path,
                 "written": r.written, "cut": r.cut} for r in ledger.rows]

    if source == "git":
        code, out, _ = _run_git(root, [
            "log", "-n", "40", "--format=%H%x09%ad%x09%s", "--date=short",
            "--", manuscript_pathspec(root, cfg),
        ])
        commits = []
        for line in out.splitlines() if code == 0 else []:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        if not commits:
            return {"source": "git", "commits": [], "empty": "There are no commits of the manuscript to compare with yet."}
        chosen = next((c for c in commits if c["sha"] == sha), commits[0])
        ledger = build_ledger(_commit_prose(root, cfg, chosen["sha"], record.prose), record.prose,
                              baseline_date=chosen["date"], baseline_kind="commit")
        return {
            "source": "git", "commits": commits, "sha": chosen["sha"],
            "title": f"Since the commit of {_short_day(chosen['date'])}",
            "basis": (
                f"Your files as they are now, including anything not committed, compared "
                f"word by word with commit {chosen['sha'][:7]} from {_short_day(chosen['date'])}: "
                f"“{chosen['subject']}”."
            ),
            "rows": shape(rows_of(ledger)),
        }

    today = record.today
    period = period if period in WHAT_CHANGED_PERIODS else "today"
    ledgers = read_day_ledgers(root)
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    how = ("Proseview keeps a copy of your scenes each day it runs, whatever editor you "
           "write in, and compares them word by word.")
    notes: list[str] = []

    def gap_note(day: str, since: str, kind: str) -> str | None:
        if kind == "commit":
            return (f"{_short_day(day)} is measured from your commit of {_short_day(since)}: "
                    "Proseview had no copy from before it.")
        day_before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        if since < day_before:
            return (f"Proseview didn't see the book between {_short_day(since)} and "
                    f"{_short_day(day)}, so edits from those days are counted on {_short_day(day)}.")
        return None

    if period == "today":
        previous = record.previous_day
        if previous is None:
            return {"source": "record", "period": period,
                    "empty": "Proseview has no copy of your book from before today yet, so it can't "
                             "tell today's writing apart. From tomorrow it can. Until then, compare with a "
                             "commit under Git.",
                    "basis": how}
        ledger = build_ledger(previous[1], record.prose, baseline_date=previous[0], baseline_kind="day")
        note = gap_note(today, previous[0], "day")
        return {"source": "record", "period": period, "title": "Today",
                "basis": how + f" Today is measured from the end of {_short_day(previous[0])}.",
                "notes": [note] if note else [], "rows": shape(rows_of(ledger))}

    if period == "yesterday":
        entry = ledgers.get(yesterday)
        if entry is None:
            return {"source": "record", "period": period, "basis": how,
                    "empty": f"Proseview has no record for {_short_day(yesterday)}: it either wasn't running "
                             "that day or hadn't started keeping one."}
        note = gap_note(yesterday, entry.get("since", ""), entry.get("kind", "day"))
        return {"source": "record", "period": period, "title": f"Yesterday, {_short_day(yesterday)}",
                "basis": how, "notes": [note] if note else [], "rows": shape(entry.get("rows", []))}

    span = WHAT_CHANGED_PERIODS[period]
    start = (date.fromisoformat(today) - timedelta(days=span - 1)).isoformat()
    groups: list[list[dict]] = []
    by_day: list[dict] = []
    for day in sorted(d for d in ledgers if start <= d < today):
        entry = ledgers[day]
        rows = entry.get("rows", [])
        groups.append(rows)
        by_day.append({"day": day, "since": entry.get("since", ""),
                       "written": sum(int(r.get("written", 0)) for r in rows),
                       "cut": sum(int(r.get("cut", 0)) for r in rows)})
        note = gap_note(day, entry.get("since", ""), entry.get("kind", "day"))
        if note:
            notes.append(note)
    if record.previous_day is not None:
        live = rows_of(build_ledger(record.previous_day[1], record.prose,
                                    baseline_date=record.previous_day[0], baseline_kind="day"))
        groups.append(live)
        by_day.append({"day": today, "since": record.previous_day[0],
                       "written": sum(r["written"] for r in live), "cut": sum(r["cut"] for r in live)})
    if not by_day:
        return {"source": "record", "period": period, "basis": how,
                "empty": "Proseview has no daily record in this period yet. It starts keeping one the "
                         "first day it runs; until then, compare with a commit under Git."}
    first = min(d["day"] for d in by_day)
    if first > start:
        notes.append(f"Proseview's record starts on {_short_day(first)}; nothing before it is counted.")
    label = "The last 7 days" if span == 7 else "The last 30 days"
    return {"source": "record", "period": period, "title": label, "basis": how, "notes": notes,
            "rows": shape(combine_rows(groups)), "by_day": list(reversed(by_day))}
