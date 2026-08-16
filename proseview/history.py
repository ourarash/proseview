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
"""

from __future__ import annotations

import json
import re
import subprocess
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:  # imported lazily at runtime; .scenes imports from here
    from .scenes import SceneStats

from . import __version__ as PROSEVIEW_VERSION
from .config import Config
from .lexical import calculate_lexical_stats, count_words
from .repo import CONTEXT_SKIP_DIRS
from .scenes import resolve_manuscript_dir


HISTORY_CACHE_PATH = Path(".proseview") / "history-cache.json"

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
    words_added_today: int
    scenes_touched_today: int


def _run_git(root: Path, args: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return 127, "", "git executable not found"
    return result.returncode, result.stdout, result.stderr


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
    warnings.warn(f"proseview: {message}", stacklevel=3)
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
    code, out, _ = _run_git(root, [
        "ls-tree", "-r", "--name-only", sha, "--", manuscript_pathspec(root, cfg),
    ])
    if code != 0:
        return _empty_row(sha, _committed_at_for(root, sha))

    # Mirrors iter_scene_paths: any depth, no README, no tool directories. The
    # old `len(parts) >= 3` here was the two-level assumption again, and would
    # have reported zero words for every flat or deeply nested manuscript.
    paths = [
        p for p in out.splitlines()
        if p.endswith(".md")
        and Path(p).name.lower() != "readme.md"
        and not Path(p).name.startswith(".")
        and p.startswith(manuscript_prefix)
        and not any(
            part.startswith(".") or part in CONTEXT_SKIP_DIRS for part in Path(p).parts[:-1]
        )
    ]
    strip = 0 if at_root else len(Path(manuscript_prefix.rstrip("/")).parts)

    total_words = 0
    scene_count = 0
    chapters: set[str] = set()
    pieces: list[str] = []
    for p in paths:
        code, content, _ = _run_git(root, ["show", f"{sha}:{p}"])
        if code != 0:
            continue
        _, body = split_frontmatter(content)
        text = extract_scene_text(body)
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
        serialized = {sha: asdict(row) for sha, row in sorted(self._data.items())}
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


def working_copy_delta(root: Path, cfg: Config,
                       history: list[HistoryRow],
                       scenes: list[SceneStats] | None = None) -> WorkingCopyDelta:
    """Compute "today" numbers from the working tree against the last commit
    from before today.

    words_added_today = max(0, current working-tree word total - baseline)
    scenes_touched_today = files changed in commits since midnight PLUS files
                           dirty in the working tree

    Pass *scenes* when the caller has already indexed the manuscript. Only the
    word total is needed here, and re-indexing runs the full lexical analysis of
    every scene a second time -- about half the cost of a dashboard build.
    """
    if not is_git_repo(root):
        return WorkingCopyDelta(0, 0)

    if scenes is None:
        from .scenes import collect_scene_stats

        scenes = collect_scene_stats(root, cfg.manuscript_subdir)
    current_total = sum(s.words for s in scenes)

    today = date.today().isoformat()
    baseline = 0
    for row in reversed(history):
        if row.committed_at[:10] < today:
            baseline = row.total_words
            break

    touched: set[str] = set()
    code, out, _ = _run_git(root, [
        "log", "--since=midnight", "--pretty=format:", "--name-only",
        "--", manuscript_pathspec(root, cfg),
    ])
    if code == 0:
        for line in out.splitlines():
            s = line.strip()
            if s.endswith(".md") and s.startswith(cfg.manuscript_subdir + "/"):
                touched.add(s)

    code, out, _ = _run_git(root, ["status", "--porcelain", "--", manuscript_pathspec(root, cfg)])
    if code == 0:
        for line in out.splitlines():
            # Format: "XY PATH" (X and Y are status codes, path starts at col 3)
            if len(line) < 4:
                continue
            path = line[3:].strip()
            # Rename format "X  old -> new": take the new path
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path.endswith(".md") and path.startswith(cfg.manuscript_subdir + "/"):
                touched.add(path)

    return WorkingCopyDelta(
        words_added_today=max(0, current_total - baseline),
        scenes_touched_today=len(touched),
    )
