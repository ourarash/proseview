"""Repo file tree for the dashboard's file browser and preview surface.

Walks the top-level folders listed in ``cfg.repo_tab.folders`` (plans,
continuity, outline, story-bible, docs, templates by default) and returns a
nested tree that the client renders. Manuscript content is excluded on
purpose: the Scene tab already covers it.

File bodies are embedded inline for files at or below
``cfg.repo_tab.preview_max_bytes`` so the dashboard can preview without a
server round-trip. Oversized files and non-text files carry metadata only;
the client renders a warning instead of loading their contents into the DOM.

The returned structure is JSON-safe so the generator can embed it directly
with ``json.dumps``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config

TEXT_SUFFIXES: frozenset[str] = frozenset({
    ".md", ".markdown", ".txt", ".yaml", ".yml",
    ".json", ".toml", ".cfg", ".ini", ".rst",
})
CONTEXT_FILE_MAX_BYTES = 512 * 1024
CONTEXT_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".proseview", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "__pycache__",
})


def _read_utf8_text(path: Path, max_bytes: int) -> str | None:
    """Read a bounded UTF-8 text file, rejecting binary-looking content."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        payload = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_context_text_file(path: Path, max_file_bytes: int = CONTEXT_FILE_MAX_BYTES) -> bool:
    """Return whether *path* is attachable UTF-8 repository context.

    Discuss is intentionally not limited to the dashboard preview suffixes:
    source files, templates, prompts, and extensionless text files are useful
    agent context too. Binary, malformed, and oversized files stay outside the
    browser inventory and are rejected again at the API boundary.
    """
    return path.is_file() and _read_utf8_text(path, max_file_bytes) is not None


def _iso_mtime(path: Path) -> str:
    ts = path.stat().st_mtime
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def resolve_visible_repository_path(root: Path, value: str) -> Path:
    """Resolve a path shared by repository-facing browser capabilities."""
    resolved_root = root.resolve()
    raw = str(value or "").strip().replace("\\", "/")
    relative = Path(raw)
    if (
        not raw
        or relative.is_absolute()
        or ".." in relative.parts
        or any(part.startswith(".") or part in CONTEXT_SKIP_DIRS for part in relative.parts)
    ):
        raise ValueError("path must be a safe visible repository-relative path")

    candidate = resolved_root
    has_symlink = False
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            has_symlink = True
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("path resolves outside the repository")
    if has_symlink:
        raise ValueError("symlinks are not a safe visible repository path")
    return resolved


def _file_node(path: Path, root: Path, preview_max: int) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    size = path.stat().st_size
    too_large = size > preview_max
    body = _read_utf8_text(path, preview_max)
    is_text = body is not None or (too_large and path.suffix.lower() in TEXT_SUFFIXES)
    return {
        "name": path.name,
        "path": rel,
        "abs_path": str(path.resolve()),
        "is_file": True,
        "modified_at": _iso_mtime(path),
        "size": size,
        "is_text": is_text,
        "too_large": too_large,
        "body": body,
    }


def _dir_node(path: Path, root: Path, preview_max: int, excluded: set[str]) -> dict[str, Any] | None:
    rel = path.relative_to(root).as_posix()
    if rel in excluded:
        return None
    children: list[dict[str, Any]] = []
    try:
        entries = sorted(
            path.iterdir(),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
    except OSError:
        entries = []
    for child in entries:
        if _is_hidden(child.name):
            continue
        if child.is_dir():
            sub = _dir_node(child, root, preview_max, excluded)
            if sub is not None:
                children.append(sub)
        elif child.is_file():
            children.append(_file_node(child, root, preview_max))
    return {
        "name": path.name,
        "path": rel,
        "is_file": False,
        "modified_at": _iso_mtime(path),
        "children": children,
    }


def _file_node_scene(path: Path, root: Path, manuscript_subdir: str) -> dict[str, Any]:
    """Lightweight node for a manuscript scene file (body omitted; modal has it)."""
    rel = path.relative_to(root).as_posix()
    ms_prefix = manuscript_subdir.rstrip("/") + "/"
    scene_path = rel[len(ms_prefix):] if rel.startswith(ms_prefix) else rel
    return {
        "name": path.name,
        "path": rel,
        "abs_path": str(path.resolve()),
        "is_file": True,
        "is_scene": True,
        "scene_path": scene_path,
        "modified_at": _iso_mtime(path),
        "size": path.stat().st_size,
        "is_text": True,
        "too_large": False,
        "body": None,
    }


def _dir_node_manuscript(path: Path, root: Path, manuscript_subdir: str) -> dict[str, Any] | None:
    """Walk the manuscript directory and mark .md files as scene nodes."""
    children: list[dict[str, Any]] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        entries = []
    for child in entries:
        if _is_hidden(child.name):
            continue
        if child.is_dir():
            sub = _dir_node_manuscript(child, root, manuscript_subdir)
            if sub is not None:
                children.append(sub)
        elif child.is_file() and child.suffix.lower() in {".md", ".markdown"}:
            children.append(_file_node_scene(child, root, manuscript_subdir))
    return {
        "name": path.name,
        "path": path.relative_to(root).as_posix(),
        "is_file": False,
        "modified_at": _iso_mtime(path),
        "children": children,
    }


def _file_node_meta(path: Path, root: Path) -> dict[str, Any]:
    """Minimal sidebar node for a non-manuscript file. No body embedded.

    The JS sidebar click handler uses ``repoFileByPath`` (built from
    ``repoTree``) for the actual body, so there is no need to duplicate it
    here.
    """
    return {
        "name": path.name,
        "path": path.relative_to(root).as_posix(),
        "is_file": True,
        "is_scene": False,
    }


def _dir_node_meta(path: Path, root: Path, excluded: set[str]) -> dict[str, Any] | None:
    """Walk a directory for the sidebar without embedding file bodies."""
    rel = path.relative_to(root).as_posix()
    if rel in excluded:
        return None
    children: list[dict[str, Any]] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        entries = []
    for child in entries:
        if _is_hidden(child.name):
            continue
        if child.is_dir():
            sub = _dir_node_meta(child, root, excluded)
            if sub is not None:
                children.append(sub)
        elif child.is_file():
            children.append(_file_node_meta(child, root))
    return {
        "name": path.name,
        "path": rel,
        "is_file": False,
        "modified_at": _iso_mtime(path),
        "children": children,
    }


def build_sidebar_tree(root: Path, cfg: Config) -> list[dict[str, Any]]:
    """Return tree nodes for the persistent sidebar.

    Manuscript directory is listed first with ``is_scene`` markers so the
    sidebar JS can open the scene modal on click. Non-manuscript repo folders
    follow as metadata-only nodes; their file bodies live in ``repoTree`` /
    ``repoFileByPath`` and are looked up there at click time.
    """
    nodes: list[dict[str, Any]] = []

    ms = root / cfg.manuscript_subdir
    if ms.exists() and ms.is_dir():
        ms_node = _dir_node_manuscript(ms, root, cfg.manuscript_subdir)
        if ms_node is not None:
            nodes.append(ms_node)

    excluded = {cfg.manuscript_subdir}
    for name in cfg.repo_tab.folders:
        trimmed = name.strip("/").strip()
        if not trimmed or trimmed in excluded:
            continue
        candidate = root / trimmed
        if not candidate.exists() or not candidate.is_dir():
            continue
        node = _dir_node_meta(candidate, root, excluded)
        if node is not None:
            nodes.append(node)

    return nodes


def recent_changes(
    root: Path,
    cfg: Config,
    since: str = "7 days ago",
) -> tuple[list[dict[str, Any]], bool]:
    """Return files changed in the last ``since`` period from git log.

    Returns ``(entries, git_available)``.  When git is unavailable or ``root``
    is not the worktree top-level the list is empty and the flag is ``False``.

    Each entry carries:
      path          relative path from repo root (forward slashes)
      abs_path      resolved absolute path string
      is_scene      True when the file is a manuscript Markdown file
      scene_path    path relative to manuscript_subdir for scenes, else None
      modified_at   ISO date string of the most-recent touching commit
    """
    from .history import is_git_repo  # avoid circular at module level
    import subprocess as _sp

    if not is_git_repo(root):
        return [], False

    ms_prefix = cfg.manuscript_subdir.rstrip("/") + "/"
    content_dirs: list[str] = [cfg.manuscript_path, *list(cfg.repo_tab.folders)]

    try:
        result = _sp.run(
            [
                "git", "log",
                "--since", since,
                "--name-only",
                "--diff-filter=AM",
                "--pretty=format:__PV_DATE__ %ai",
                "--first-parent",
                "--",
                *content_dirs,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, _sp.TimeoutExpired):
        return [], False

    if result.returncode != 0:
        return [], False

    # Sentinel lines supply the date; all other non-empty lines are file paths.
    # Deduplicate by path, keeping the first occurrence (most-recent commit).
    entries: dict[str, dict[str, Any]] = {}
    current_date = ""
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("__PV_DATE__ "):
            current_date = line[len("__PV_DATE__ "):]
        elif line not in entries:
            suffix = Path(line).suffix.lower()
            is_scene = line.startswith(ms_prefix) and suffix in {".md", ".markdown"}
            entries[line] = {
                "path": line,
                "abs_path": str((root / line).resolve()),
                "is_scene": is_scene,
                "scene_path": line[len(ms_prefix):] if is_scene else None,
                "modified_at": current_date,
            }

    return list(entries.values()), True


def build_tree(root: Path, cfg: Config) -> list[dict[str, Any]]:
    """Return the top-level tree nodes for the dashboard file browser.

    Only configured folders that exist on disk as directories are included.
    The manuscript directory is excluded even if it appears in
    ``cfg.repo_tab.folders``: the Scene tab is the authoritative surface
    for that content.
    """
    preview_max = cfg.repo_tab.preview_max_bytes
    excluded = {cfg.manuscript_subdir}
    nodes: list[dict[str, Any]] = []
    for name in cfg.repo_tab.folders:
        trimmed = name.strip("/").strip()
        if not trimmed or trimmed in excluded:
            continue
        candidate = root / trimmed
        if not candidate.exists() or not candidate.is_dir():
            continue
        node = _dir_node(candidate, root, preview_max, excluded)
        if node is not None:
            nodes.append(node)
    return nodes


def _repository_file_node(
    path: Path,
    root: Path,
    cfg: Config,
    context_max_bytes: int,
) -> dict[str, Any] | None:
    """Return capability metadata for one contained repository file."""
    try:
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        size = resolved.stat().st_size
    except OSError:
        return None
    inspection_limit = max(cfg.repo_tab.preview_max_bytes, context_max_bytes)
    text = _read_utf8_text(resolved, inspection_limit)
    rel = path.relative_to(root).as_posix()
    manuscript_prefix = cfg.manuscript_subdir.rstrip("/") + "/"
    is_scene = rel.startswith(manuscript_prefix) and path.suffix.lower() in {".md", ".markdown"}
    return {
        "name": path.name,
        "path": rel,
        "is_file": True,
        "is_scene": is_scene,
        "scene_path": rel[len(manuscript_prefix):] if is_scene else None,
        "is_text": text is not None or (
            size > inspection_limit and path.suffix.lower() in TEXT_SUFFIXES
        ),
        "previewable": size <= cfg.repo_tab.preview_max_bytes and text is not None,
        "attachable": size <= context_max_bytes and text is not None,
        "too_large": size > cfg.repo_tab.preview_max_bytes,
        "size": size,
    }


def _repository_dir_node(
    path: Path,
    root: Path,
    cfg: Config,
    context_max_bytes: int,
) -> dict[str, Any] | None:
    """Walk one repository directory for the canonical metadata index."""
    if path.name.startswith(".") or path.name in CONTEXT_SKIP_DIRS or path.is_symlink():
        return None
    try:
        entries = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError:
        return None
    children: list[dict[str, Any]] = []
    for child in entries:
        if child.name.startswith(".") or child.name in CONTEXT_SKIP_DIRS:
            continue
        if child.is_dir():
            node = _repository_dir_node(child, root, cfg, context_max_bytes)
        elif child.is_file():
            node = _repository_file_node(child, root, cfg, context_max_bytes)
        else:
            node = None
        if node is not None:
            children.append(node)
    if not children:
        return None
    return {
        "name": path.name,
        "path": path.relative_to(root).as_posix(),
        "is_file": False,
        "attachable": any(bool(child.get("attachable")) for child in children),
        "children": children,
    }


def build_repository_tree(
    root: Path,
    cfg: Config | None = None,
    *,
    context_max_bytes: int = CONTEXT_FILE_MAX_BYTES,
) -> list[dict[str, Any]]:
    """Return the canonical metadata-only repository inventory.

    Consumers select files by explicit capability flags instead of maintaining
    separate universes for navigation and agent context. Hidden/internal paths
    and symlinks remain outside the inventory; no file bodies or absolute paths
    are serialized into the browser.
    """
    resolved_root = root.resolve()
    cfg = cfg or Config.load(resolved_root)
    try:
        entries = sorted(resolved_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError:
        return []
    nodes: list[dict[str, Any]] = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in CONTEXT_SKIP_DIRS:
            continue
        if entry.is_dir():
            node = _repository_dir_node(entry, resolved_root, cfg, context_max_bytes)
        elif entry.is_file():
            node = _repository_file_node(entry, resolved_root, cfg, context_max_bytes)
        else:
            node = None
        if node is not None:
            nodes.append(node)
    return nodes


def build_context_tree(
    root: Path,
    *,
    max_file_bytes: int = CONTEXT_FILE_MAX_BYTES,
) -> list[dict[str, Any]]:
    """Compatibility projection containing only attachable context paths."""
    repository = build_repository_tree(root, context_max_bytes=max_file_bytes)

    def project(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        projected: list[dict[str, Any]] = []
        for node in nodes:
            if node.get("is_file"):
                if node.get("attachable"):
                    projected.append(dict(node))
                continue
            children = project(list(node.get("children") or []))
            if children:
                copy = dict(node)
                copy["children"] = children
                projected.append(copy)
        return projected

    return project(repository)
