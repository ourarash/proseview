"""Filesystem polling for ``proseview --watch``.

The watcher polls the content roots called out in the implementation plan:
``manuscript/``, ``plans/``, ``continuity/``, ``outline/``,
``story-bible/``, plus ``.proseview.yaml``. It compares recursive path
snapshots and invokes a callback after a short debounce window.

Example:
    >>> from pathlib import Path
    >>> from proseview.config import Config
    >>> def on_change(changed): ...
    >>> watch(Path.cwd(), on_change, cfg=Config())  # doctest: +SKIP
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .config import Config

DEFAULT_INTERVAL = 2.0
DEFAULT_DEBOUNCE = 0.5
_EXTRA_WATCH_DIRS: tuple[str, ...] = ("plans", "continuity", "outline", "story-bible")
_CONFIG_KEY = ".proseview.yaml"

Snapshot = dict[str, tuple[str, int | None, int | None]]


def _iter_watched_roots(root: Path, cfg: Config) -> tuple[Path, ...]:
    """Return content directories that should trigger a refresh."""
    dirs = [root / cfg.manuscript_subdir]
    dirs.extend(root / name for name in _EXTRA_WATCH_DIRS)
    return tuple(dirs)


def snapshot_paths(root: Path, cfg: Config) -> Snapshot:
    """Capture the current recursive watcher state for the configured repo.

    Snapshot entries are keyed by repo-relative POSIX path. Each value is a
    tuple of ``(kind, mtime_ns, size)`` where ``kind`` is ``"file"`` or
    ``"dir"``. The config file is always represented, even when missing, so
    creating or deleting ``.proseview.yaml`` still triggers a refresh.
    """
    snapshot: Snapshot = {}

    config_path = root / _CONFIG_KEY
    if config_path.exists():
        stat = config_path.stat()
        snapshot[_CONFIG_KEY] = ("file", stat.st_mtime_ns, stat.st_size)
    else:
        snapshot[_CONFIG_KEY] = ("missing", None, None)

    for watched_root in _iter_watched_roots(root, cfg):
        rel_root = watched_root.relative_to(root).as_posix()
        if watched_root.exists() and watched_root.is_dir():
            root_stat = watched_root.stat()
            snapshot[rel_root] = ("dir", root_stat.st_mtime_ns, None)
        else:
            snapshot[rel_root] = ("missing", None, None)
            continue
        for path in sorted(watched_root.rglob("*")):
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            kind = "dir" if path.is_dir() else "file"
            size = None if path.is_dir() else stat.st_size
            snapshot[rel] = (kind, stat.st_mtime_ns, size)
    return snapshot


def detect_changes(previous: Snapshot, current: Snapshot) -> tuple[str, ...]:
    """Return repo-relative paths whose snapshot entry changed."""
    changed = {
        path
        for path in set(previous) | set(current)
        if previous.get(path) != current.get(path)
    }
    return tuple(sorted(changed))


def wait_for_change(
    root: Path,
    cfg: Config,
    baseline: Snapshot,
    *,
    interval: float = DEFAULT_INTERVAL,
    debounce: float = DEFAULT_DEBOUNCE,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[Snapshot, tuple[str, ...]]:
    """Block until the watched snapshot changes, then debounce briefly."""
    while True:
        sleep_fn(interval)
        current = snapshot_paths(root, cfg)
        if current == baseline:
            continue

        if debounce > 0:
            sleep_fn(debounce)
            current = snapshot_paths(root, cfg)

        return current, detect_changes(baseline, current)


def watch(
    root: Path,
    on_change: Callable[[tuple[str, ...]], None],
    *,
    interval: float = DEFAULT_INTERVAL,
    debounce: float = DEFAULT_DEBOUNCE,
    cfg: Config | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Poll the repo and invoke ``on_change`` after debounced changes.

    ``cfg`` is reloaded after each regenerate so edits to ``.proseview.yaml``
    can change the watched manuscript path without restarting the watcher.
    """
    cfg = cfg or Config.load(root)
    baseline = snapshot_paths(root, cfg)
    while True:
        baseline, changed = wait_for_change(
            root,
            cfg,
            baseline,
            interval=interval,
            debounce=debounce,
            sleep_fn=sleep_fn,
        )
        on_change(changed)
        cfg = Config.load(root)
        baseline = snapshot_paths(root, cfg)
