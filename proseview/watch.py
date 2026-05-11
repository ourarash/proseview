"""Filesystem polling for ``proseview --watch``.

The watcher polls the visible repo tree, excluding VCS metadata and common
cache/build output. It compares recursive path snapshots and invokes a
callback after a short debounce window.

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
_CONFIG_KEY = ".proseview.yaml"
_IGNORED_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".proseview",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
})

Snapshot = dict[str, tuple[str, int | None, int | None]]


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _IGNORED_DIR_NAMES for part in rel.parts)


def _iter_visible_paths(root: Path) -> tuple[Path, ...]:
    """Return repo paths while pruning ignored directories before descent."""
    result: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda p: p.as_posix())
        except OSError:
            continue
        for child in children:
            if _is_ignored(child, root):
                continue
            result.append(child)
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir and not child.is_symlink():
                stack.append(child)
    return tuple(result)


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

    for path in _iter_visible_paths(root):
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
