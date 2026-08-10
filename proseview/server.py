"""Minimal local HTTP server for ``proseview serve``.

Endpoints
---------
GET  /             Serve the dashboard HTML (cached, invalidated on file changes).
POST /insert-todo  Insert a TODO comment into a manuscript file.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import queue
import re
import select
import signal
import struct
import tempfile
import threading
import uuid
import webbrowser
from datetime import datetime
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Callable, Any

try:
    import pty
    import termios
    _PTY_AVAILABLE = True
except ImportError:
    _PTY_AVAILABLE = False

from .config import Config
from .codex_app_server import CodexAuthError, CodexProtocolError, CodexUnavailableError
from .discuss import ContextError, DiscussManager
from .generator import TEMPLATE_DIR, _load_asset, build_dashboard, build_scene_data
from .lexical import paragraph_blocks
from .repo import _file_node as _repo_file_node, resolve_visible_repository_path
from .scenes import collect_scene_stats, extract_scene_text, split_frontmatter
from .watch import watch as _watch
from urllib.parse import urlparse, parse_qs
import time as _time

DEFAULT_PORT = 7842


# ── AI proposal bridge ───────────────────────────────────────────────────────

_ai_proposals: dict[str, dict[str, Any]] = {}
_ai_clients: dict[str, dict[str, Any]] = {}
_ai_lock = threading.Lock()
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: POST endpoints that take an absolute file path from the page and write
#: through it. Each one is containment-checked against the served repo.
_ABS_PATH_ENDPOINTS: frozenset[str] = frozenset({
    "/insert-todo", "/edit-todo", "/delete-todo",
    "/add-note", "/edit-note", "/delete-note",
    "/save-scene",
})


def _runtime_file(root: Path) -> Path:
    return root / ".proseview" / "server.json"


def _write_runtime_file(root: Path, port: int, session_token: str = "") -> None:
    path = _runtime_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": f"http://localhost:{port}",
        "repo_root": str(root.resolve()),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        # How `proseview propose` and friends authenticate. A browser cannot
        # read this file, which is what keeps a hostile page out.
        "session_token": session_token,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _remove_runtime_file(root: Path, port: int) -> None:
    path = _runtime_file(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if data.get("url") != f"http://localhost:{port}":
        return
    try:
        path.unlink()
    except OSError:
        pass


def _normalize_ai_scene_file(repo_root: str, value: str) -> str:
    rel = str(value or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("missing file")
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise PermissionError("file must be a safe repo-relative manuscript path")
    root = Path(repo_root).resolve()
    cfg = Config.load(root)
    manuscript = cfg.manuscript_subdir.rstrip("/")
    if rel.startswith(manuscript + "/"):
        scene_rel = rel[len(manuscript) + 1:]
    else:
        scene_rel = rel
    target = (root / manuscript / scene_rel).resolve()
    manuscript_root = (root / manuscript).resolve()
    if not target.is_relative_to(manuscript_root):
        raise PermissionError("file outside manuscript directory")
    if not target.is_file():
        raise FileNotFoundError(f"scene not found: {scene_rel}")
    return scene_rel


def _proposal_payload(prop: dict[str, Any], action: str) -> dict[str, Any]:
    return {"type": "ai:proposal", "action": action, "proposal": prop}


def _coerce_options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("options must be a non-empty list")
    options: list[dict[str, str]] = []
    for i, item in enumerate(value, start=1):
        if isinstance(item, str):
            text = item.strip()
            label = f"Option {i}"
        elif isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            label = str(item.get("label") or f"Option {i}").strip()
        else:
            raise ValueError("each option must be a string or object")
        if not text:
            raise ValueError("proposal options cannot be empty")
        option = {"label": label, "text": text}
        if isinstance(item, dict) and str(item.get("rationale") or "").strip():
            option["rationale"] = str(item["rationale"]).strip()
        options.append(option)
    return options


def _new_ai_proposal(repo_root: str, body: dict[str, Any]) -> dict[str, Any]:
    scene_rel = _normalize_ai_scene_file(repo_root, body.get("file", ""))
    prop_id = uuid.uuid4().hex[:10]
    now = datetime.now().isoformat(timespec="seconds")
    prop = {
        "id": prop_id,
        "client_id": body.get("client_id") or None,
        "file": scene_rel,
        "quote": str(body.get("quote") or ""),
        "range": body.get("range") or None,
        "message": str(body.get("message") or "").strip(),
        "options": _coerce_options(body.get("options")),
        "status": "created",
        "created_by": str(body.get("created_by") or "codex"),
        "created_at": now,
        "updated_at": now,
    }
    for field in ("origin", "client_request_id", "action_id", "selection_fingerprint", "source_mtime_ns", "task_id", "conversation_id"):
        if body.get(field) is not None:
            prop[field] = body[field]
    if not prop["quote"] and not prop["range"]:
        raise ValueError("proposal requires quote or range")
    if prop.get("origin") == "managed_selection_action" and isinstance(prop.get("range"), dict):
        start = int(prop["range"].get("start"))
        end = int(prop["range"].get("end"))
        if start < 0 or end <= start or not prop["quote"]:
            raise ValueError("managed proposal has an invalid selection target")
        prop["range"] = {"start": start, "end": end}
        prop["resolved_quote"] = str(body.get("resolved_quote") or prop["quote"])
    else:
        prop.update(_resolve_ai_target(repo_root, scene_rel, prop["quote"], prop["range"]))
    with _ai_lock:
        if not prop["client_id"]:
            matching = [c for c in _ai_clients.values() if c.get("active_scene") == scene_rel]
            if len(matching) == 1:
                prop["client_id"] = matching[0]["client_id"]
            elif len(matching) > 1:
                prop["needs_target"] = True
                prop["status"] = "needs_target"
            elif _ai_clients:
                latest = max(_ai_clients.values(), key=lambda c: c.get("last_seen", ""))
                prop["client_id"] = latest["client_id"]
        _ai_proposals[prop_id] = prop
    return prop


def _proposal_editor_text(markdown: str) -> str:
    text = _HTML_COMMENT_RE.sub("", markdown)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?<!\w)(\*\*|__)(.+?)\1(?!\w)", r"\2", text)
    text = re.sub(r"(?<!\w)(\*|_)(.+?)\1(?!\w)", r"\2", text)
    return text


def _comment_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _HTML_COMMENT_RE.finditer(text)]


def _spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _reject_annotation_overlap(start: int, end: int, comment_spans: list[tuple[int, int]]) -> None:
    for c_start, c_end in comment_spans:
        if _spans_overlap(start, end, c_start, c_end):
            raise ValueError("target crosses NOTE/TODO annotations; target visible prose only")


def _editor_text_with_raw_map(markdown: str) -> tuple[str, list[int]]:
    text: list[str] = []
    raw_map: list[int] = []
    comment_ranges = _comment_spans(markdown)
    comment_idx = 0
    i = 0
    while i < len(markdown):
        if comment_idx < len(comment_ranges) and i == comment_ranges[comment_idx][0]:
            i = comment_ranges[comment_idx][1]
            comment_idx += 1
            continue
        text.append(markdown[i])
        raw_map.append(i)
        i += 1
    return _proposal_editor_text("".join(text)), raw_map


def _normalized_text_map(text: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    offsets: list[int] = []
    in_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_space:
                normalized.append(" ")
                offsets.append(i)
                in_space = True
            continue
        normalized.append(ch)
        offsets.append(i)
        in_space = False
    start = 0
    end = len(normalized)
    while start < end and normalized[start].isspace():
        start += 1
    while end > start and normalized[end - 1].isspace():
        end -= 1
    return "".join(normalized[start:end]), offsets[start:end]


def _extract_scene_text_with_offset(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    start = 0
    offset = 0
    while start < len(lines) and not lines[start].strip():
        offset += len(lines[start])
        start += 1
    if start < len(lines) and lines[start].lstrip().startswith("# "):
        offset += len(lines[start])
        start += 1
    while start < len(lines) and not lines[start].strip():
        offset += len(lines[start])
        start += 1
    return "".join(lines[start:]), offset


def _resolve_quote_in_editor_text(editor_text: str, quote: str) -> tuple[int, int, str]:
    normalized_editor, offset_map = _normalized_text_map(editor_text)
    normalized_quote, _ = _normalized_text_map(_proposal_editor_text(quote))
    if not normalized_quote:
        raise ValueError("proposal requires quote or range")
    start = normalized_editor.find(normalized_quote)
    if start < 0:
        raise ValueError("quote not found in scene after editor normalization")
    if normalized_editor.find(normalized_quote, start + len(normalized_quote)) >= 0:
        raise ValueError("quote is ambiguous; use a longer quote")
    end = start + len(normalized_quote)
    if not offset_map or end - 1 >= len(offset_map):
        raise ValueError("quote could not be mapped to editor text")
    from_pos = offset_map[start]
    to_pos = offset_map[end - 1] + 1
    return from_pos, to_pos, editor_text[from_pos:to_pos]


def _line_col_to_offset(text: str, line: int, col: int) -> int:
    if line < 1 or col < 1:
        raise ValueError("line and column numbers are 1-based")
    lines = text.splitlines(keepends=True)
    if line > len(lines):
        raise ValueError(f"line {line} is outside file")
    line_text = lines[line - 1]
    line_no_newline = line_text.rstrip("\r\n")
    if col > len(line_no_newline) + 1:
        raise ValueError(f"column {col} is outside line {line}")
    return sum(len(x) for x in lines[:line - 1]) + col - 1


_BLANK_LINE_SEPARATOR_RE = re.compile(r"\n\s*\n+")


def _scene_to_editor_offset(scene_text: str, target: int) -> int:
    """Convert a position in ``scene_text`` to the offset the browser will
    compute in its flat-text view of the doc.

    The browser's ``aiDocTextMap`` inserts a single ``\\n`` between block-level
    nodes, while ``scene_text`` separates paragraphs with blank lines
    (``\\n\\s*\\n+``). Without this conversion the server's range offsets drift
    by one char per preceding paragraph break, which silently mis-aligns the
    fallback path when the browser cannot match ``resolved_quote`` (e.g. after
    a proposal has been applied).
    """
    if target <= 0:
        return 0
    if target > len(scene_text):
        target = len(scene_text)
    pos = 0
    editor_pos = 0
    first_block = True
    while pos < target:
        m = _BLANK_LINE_SEPARATOR_RE.search(scene_text, pos)
        if m:
            sep_start = m.start()
            sep_end = m.end()
        else:
            sep_start = len(scene_text)
            sep_end = len(scene_text)
        block_end = min(sep_start, target)
        block = scene_text[pos:block_end]
        if block.strip():
            if not first_block:
                editor_pos += 1
            editor_pos += len(_proposal_editor_text(block))
            first_block = False
        if block_end == target:
            return editor_pos
        if target < sep_end:
            return editor_pos
        pos = sep_end
        if pos == target and not first_block:
            editor_pos += 1
            return editor_pos
    return editor_pos


def _browser_editor_text(scene_text: str) -> str:
    """Approximate the flat text emitted by ``aiDocTextMap`` in the browser."""
    blocks = []
    for block in _BLANK_LINE_SEPARATOR_RE.split(scene_text):
        visible = _proposal_editor_text(block).strip()
        if visible:
            blocks.append(visible)
    return "\n".join(blocks)


def _resolve_line_col_target(repo_root: str, scene_rel: str, loc: dict[str, Any]) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    cfg = Config.load(root)
    scene_path = (root / cfg.manuscript_subdir / scene_rel).resolve()
    raw = scene_path.read_text(encoding="utf-8")
    start = _line_col_to_offset(raw, int(loc["start_line"]), int(loc["start_col"]))
    end = _line_col_to_offset(raw, int(loc["end_line"]), int(loc["end_col"]))
    if end <= start:
        raise ValueError("end line/column must be after start line/column")
    _fm, body = split_frontmatter(raw)
    scene_text, scene_offset = _extract_scene_text_with_offset(body)
    body_start = raw.find(body)
    if body_start < 0:
        raise ValueError("could not locate scene body")
    rel_start = start - body_start - scene_offset
    rel_end = end - body_start - scene_offset
    if rel_start < 0 or rel_end > len(scene_text):
        raise ValueError("line/column range must target visible scene prose")
    _reject_annotation_overlap(rel_start, rel_end, _comment_spans(scene_text))
    target_markdown = scene_text[rel_start:rel_end]
    resolved_quote = _proposal_editor_text(target_markdown).strip()
    if not resolved_quote:
        raise ValueError("line/column range has no visible prose")
    start_editor = _scene_to_editor_offset(scene_text, rel_start)
    return {
        "range": {"start": start_editor, "end": start_editor + len(resolved_quote)},
        "resolved_quote": resolved_quote,
        "source_range": {
            "start_line": int(loc["start_line"]),
            "start_col": int(loc["start_col"]),
            "end_line": int(loc["end_line"]),
            "end_col": int(loc["end_col"]),
        },
    }


def _resolve_ai_target(repo_root: str, scene_rel: str, quote: str, range_value: Any) -> dict[str, Any]:
    if isinstance(range_value, dict) and {"start_line", "start_col", "end_line", "end_col"}.issubset(range_value):
        return _resolve_line_col_target(repo_root, scene_rel, range_value)
    if isinstance(range_value, dict):
        start = int(range_value.get("start"))
        end = int(range_value.get("end"))
        if start < 0 or end <= start:
            raise ValueError("range must have start >= 0 and end > start")
        root = Path(repo_root).resolve()
        cfg = Config.load(root)
        scene_path = (root / cfg.manuscript_subdir / scene_rel).resolve()
        raw = scene_path.read_text(encoding="utf-8")
        _fm, body = split_frontmatter(raw)
        editor_text = _browser_editor_text(extract_scene_text(body))
        if end > len(editor_text):
            raise ValueError("range is outside the current scene")
        resolved_quote = editor_text[start:end]
        normalized_target, _ = _normalized_text_map(resolved_quote)
        normalized_quote, _ = _normalized_text_map(_proposal_editor_text(quote))
        if not normalized_target or normalized_target != normalized_quote:
            raise ValueError("range does not match the selected quote in the current scene")
        return {"range": {"start": start, "end": end}, "resolved_quote": resolved_quote}

    root = Path(repo_root).resolve()
    cfg = Config.load(root)
    scene_path = (root / cfg.manuscript_subdir / scene_rel).resolve()
    raw = scene_path.read_text(encoding="utf-8")
    _fm, body = split_frontmatter(raw)
    if _HTML_COMMENT_RE.search(quote):
        raise ValueError("quote includes NOTE/TODO annotations; target visible prose only")
    scene_text = extract_scene_text(body)
    editor_text = _browser_editor_text(scene_text)
    start, end, resolved_quote = _resolve_quote_in_editor_text(editor_text, quote)
    return {
        "range": {"start": start, "end": end},
        "resolved_quote": resolved_quote,
    }


# ── Scene editor ─────────────────────────────────────────────────────────────

class _FileConflictError(Exception):
    pass


def save_scene_content(
    abs_path: str,
    content: str,
    open_mtime: float,
    repo_root: str,
    manuscript_subdir: str = "manuscript",
) -> None:
    """Atomically replace the prose body of a scene file.

    Validates the path is under manuscript/, detects concurrent edits via mtime,
    recomputes the prose boundary from the live file, and writes atomically.
    """
    resolved = Path(abs_path).resolve()
    manuscript_root = (Path(repo_root) / manuscript_subdir).resolve()
    if not resolved.is_relative_to(manuscript_root):
        raise PermissionError(f"Path outside manuscript directory: {abs_path}")

    current_mtime = resolved.stat().st_mtime
    if abs(current_mtime - open_mtime) > 0.01:
        raise _FileConflictError("File was modified since editor opened")

    raw = resolved.read_text(encoding="utf-8")
    _fm, body = split_frontmatter(raw)
    txt = extract_scene_text(body)
    prefix = txt.lstrip("\n")[:60]
    raw_idx = raw.find(prefix) if prefix else -1
    offset = raw[:raw_idx].count("\n") if raw_idx >= 0 else 0
    header = "".join(raw.splitlines(keepends=True)[:offset])

    body_out = content if content.endswith("\n") else content + "\n"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=resolved.parent, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp:
            tmp.write(header + body_out)
            tmp_path = tmp.name
        os.replace(tmp_path, resolved)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── In-browser terminal sessions ─────────────────────────────────────────────

_terminals: dict[str, "TerminalSession"] = {}
_terminals_lock = threading.Lock()


class TerminalSession:
    # 512 KB of raw PTY output kept per session, used to replay scrollback
    # to reconnecting clients (e.g. after a page reload). xterm.js can
    # process the full buffer in one write() because the data still has
    # all its VT/ANSI escape sequences in order.
    BUFFER_MAX = 512 * 1024

    def __init__(
        self,
        terminal_id: str,
        pid: int,
        fd: int,
        *,
        command: list[str] | None = None,
        type: str = "shell",
        label: str = "",
    ) -> None:
        self.id = terminal_id
        self.pid = pid
        self.fd = fd
        self.command = list(command or [])
        self.type = type
        self.label = label
        self._subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()
        # Held while mutating both _buffer and _subscribers, so a reconnecting
        # client gets a buffer snapshot that's strictly older than every
        # event delivered to its queue (no missed bytes, no duplicates).
        self._buffer = bytearray()
        self.alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while self.alive:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.1)
                if r:
                    data = os.read(self.fd, 4096)
                    if not data:
                        break
                    encoded = base64.b64encode(data).decode()
                    with self._sub_lock:
                        self._buffer.extend(data)
                        if len(self._buffer) > self.BUFFER_MAX:
                            del self._buffer[: len(self._buffer) - self.BUFFER_MAX]
                        for q in list(self._subscribers):
                            try:
                                q.put_nowait(encoded)
                            except queue.Full:
                                pass
            except OSError:
                break
        self.alive = False
        with self._sub_lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait("__exit__")
                except queue.Full:
                    pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
        # Drop the dead session from the registry so /terminal-list stays
        # clean and doesn't try to reattach the client to a corpse.
        with _terminals_lock:
            _terminals.pop(self.id, None)

    def write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def kill(self) -> None:
        self.alive = False
        try:
            os.kill(self.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass

    def subscribe(self) -> tuple[bytes, queue.Queue]:
        """Atomically snapshot the scrollback buffer and register a queue.

        The snapshot is what should be written to the client's xterm before
        any events from the queue are processed. Holding _sub_lock across
        both operations guarantees no bytes are lost or duplicated relative
        to the live PTY stream.
        """
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._sub_lock:
            snapshot = bytes(self._buffer)
            self._subscribers.append(q)
        return snapshot, q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


def _default_shell() -> str:
    """Pick a shell when ``$SHELL`` is unset.

    ``$SHELL`` is absent in plenty of real contexts -- systemd units, Docker
    images, CI runners, launchd jobs. Hardcoding ``/bin/zsh`` meant every
    terminal and agent launch failed outright on images that don't ship it,
    which is most Linux ones. Fall back to whatever is actually present.
    """
    for candidate in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if os.path.exists(candidate):
            return candidate
    return "/bin/sh"


def spawn_terminal(
    command: list[str],
    cwd: str | None = None,
    rows: int = 24,
    cols: int = 80,
    *,
    type: str = "shell",
    label: str = "",
) -> "TerminalSession":
    if not _PTY_AVAILABLE:
        raise RuntimeError("pty module not available on this platform")
    import shlex
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["NO_UPDATE_NOTIFIER"] = "1"
    # Wrap in a login shell so the user's PATH (nvm, npm globals, pyenv, etc.) is loaded.
    # `exec` replaces the shell with the command so no shell prompt appears.
    shell = env.get("SHELL") or _default_shell()
    shell_name = os.path.basename(shell)
    if not command:
        # Plain interactive login shell (used by the "$ Shell" button)
        wrapped = [shell, "-l", "-i"] if shell_name != "fish" else [shell, "--login", "--interactive"]
    elif shell_name == "fish":
        wrapped = [shell, "--login", "-c", shlex.join(command)]
    else:
        wrapped = [shell, "-l", "-c", "exec " + shlex.join(command)]
    pid, fd = pty.fork()
    if pid == 0:
        if cwd:
            try:
                os.chdir(cwd)
            except OSError:
                pass
        os.execvpe(wrapped[0], wrapped, env)
        os._exit(1)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    terminal_id = uuid.uuid4().hex[:8]
    session = TerminalSession(
        terminal_id,
        pid,
        fd,
        command=command,
        type=type,
        label=label,
    )
    with _terminals_lock:
        _terminals[terminal_id] = session
    return session


def insert_todo(abs_path: str, selection_text: str, txt_line_offset: int, todo_text: str) -> None:
    """Insert ``<!-- TODO: todo_text -->`` before the paragraph that contains *selection_text*.

    Uses *txt_line_offset* (frontmatter + heading line count) to locate the
    extracted prose within the raw file, then searches paragraph_blocks for the
    first block that contains the selection text and inserts the comment above it.
    """
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")

    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    extracted = "".join(lines[txt_line_offset:])
    paras = paragraph_blocks(extracted)
    if not paras:
        raise ValueError("No paragraphs found in scene")

    # Find the paragraph that contains the selection text
    needle = selection_text.strip()[:50]
    para_idx = 0
    for i, para in enumerate(paras):
        if needle and needle in para:
            para_idx = i
            break

    target_para = paras[para_idx]
    para_start = target_para.lstrip("\n")[:60]
    para_pos = extracted.find(para_start)
    if para_pos < 0:
        raise ValueError(f"Cannot locate paragraph {para_idx} in {path.name}")

    # Absolute 0-based line in the full file where the target paragraph begins
    insert_at = txt_line_offset + extracted[:para_pos].count("\n")

    # Ensure a blank line before the comment if not already present
    to_insert: list[str] = []
    if insert_at > 0 and lines[insert_at - 1].strip():
        to_insert.append("\n")
    to_insert.append(f"<!-- TODO: {todo_text} -->\n")
    to_insert.append("\n")

    for i, line in enumerate(to_insert):
        lines.insert(insert_at + i, line)

    path.write_text("".join(lines), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] inserted TODO into {path.name} (line {insert_at + 1})")


def edit_todo(abs_path: str, old_todo_text: str, new_todo_text: str) -> None:
    """Replace an existing <!-- TODO: old_text --> comment with new text."""
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")
    old_comment = f"<!-- TODO: {old_todo_text} -->"
    new_comment = f"<!-- TODO: {new_todo_text} -->"
    raw = path.read_text(encoding="utf-8")
    if old_comment not in raw:
        raise ValueError(f"TODO not found: {old_comment!r}")
    path.write_text(raw.replace(old_comment, new_comment, 1), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] edited TODO in {path.name}")


def delete_todo(abs_path: str, todo_text: str) -> None:
    """Remove a <!-- TODO: todo_text --> comment from the file."""
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")
    comment = f"<!-- TODO: {todo_text} -->"
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    new_lines = []
    removed = False
    for line in lines:
        if not removed and comment in line:
            removed = True
            continue
        new_lines.append(line)
    if not removed:
        raise ValueError(f"TODO not found: {comment!r}")
    collapsed: list[str] = []
    prev_blank = False
    for line in new_lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank
    path.write_text("".join(collapsed), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] deleted TODO from {path.name}")


def add_note(abs_path: str, selection_text: str, txt_line_offset: int, note_text: str, tag: str) -> None:
    """Insert <!-- NOTE[tag]: note_text --> before the paragraph containing *selection_text*."""
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")

    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    extracted = "".join(lines[txt_line_offset:])
    paras = paragraph_blocks(extracted)
    if not paras:
        raise ValueError("No paragraphs found in scene")

    needle = selection_text.strip()[:50]
    para_idx = 0
    for i, para in enumerate(paras):
        if needle and needle in para:
            para_idx = i
            break

    target_para = paras[para_idx]
    para_start = target_para.lstrip("\n")[:60]
    para_pos = extracted.find(para_start)
    if para_pos < 0:
        raise ValueError(f"Cannot locate paragraph {para_idx} in {path.name}")

    insert_at = txt_line_offset + extracted[:para_pos].count("\n")

    tag = tag.strip().lower() if tag and tag.strip() else "note"
    comment = f"<!-- NOTE: {note_text} -->" if tag == "note" else f"<!-- NOTE[{tag}]: {note_text} -->"

    to_insert: list[str] = []
    if insert_at > 0 and lines[insert_at - 1].strip():
        to_insert.append("\n")
    to_insert.append(comment + "\n")
    to_insert.append("\n")

    for i, line in enumerate(to_insert):
        lines.insert(insert_at + i, line)

    path.write_text("".join(lines), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] inserted NOTE into {path.name} (line {insert_at + 1})")


def edit_note(abs_path: str, old_note_text: str, old_tag: str, new_note_text: str, new_tag: str) -> None:
    """Replace an existing NOTE comment with updated text/tag in-place."""
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")

    old_tag = old_tag.strip().lower() if old_tag and old_tag.strip() else "note"
    new_tag = new_tag.strip().lower() if new_tag and new_tag.strip() else "note"
    old_comment = f"<!-- NOTE: {old_note_text} -->" if old_tag == "note" else f"<!-- NOTE[{old_tag}]: {old_note_text} -->"
    new_comment = f"<!-- NOTE: {new_note_text} -->" if new_tag == "note" else f"<!-- NOTE[{new_tag}]: {new_note_text} -->"

    raw = path.read_text(encoding="utf-8")
    if old_comment not in raw:
        raise ValueError(f"Note not found: {old_comment!r}")

    path.write_text(raw.replace(old_comment, new_comment, 1), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] edited NOTE in {path.name}")


def delete_note(abs_path: str, note_text: str, tag: str) -> None:
    """Remove the <!-- NOTE[tag]: note_text --> comment from the file."""
    path = Path(abs_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")

    tag = tag.strip().lower() if tag and tag.strip() else "note"
    comment = f"<!-- NOTE: {note_text} -->" if tag == "note" else f"<!-- NOTE[{tag}]: {note_text} -->"

    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    new_lines = []
    removed = False
    for line in lines:
        if not removed and comment in line:
            removed = True
            continue
        new_lines.append(line)

    if not removed:
        raise ValueError(f"Note not found: {comment!r}")

    # Collapse any double blank lines that result from the removal
    collapsed: list[str] = []
    prev_blank = False
    for line in new_lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    path.write_text("".join(collapsed), encoding="utf-8")
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] deleted NOTE from {path.name}")


class _Handler(BaseHTTPRequestHandler):
    """Bound HTTP handler; concrete attributes injected by :func:`_make_handler`."""

    get_html: Callable[[], str]
    invalidate: Callable[[], None]
    subscribe: Callable[[], "queue.Queue[str]"]
    unsubscribe: Callable[["queue.Queue[str]"], None]
    publish_event: Callable[[dict[str, Any]], None]
    repo_root: str
    discuss_manager: DiscussManager
    session_token: str

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silence default access log

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_limited(self, limit: int = 3 * 1024 * 1024) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ContextError("invalid Content-Length") from exc
        if length <= 0 or length > limit:
            raise ContextError(f"request body must be between 1 and {limit} bytes")
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContextError(f"invalid JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise ContextError("JSON body must be an object")
        return body

    @staticmethod
    def _is_loopback_authority(value: str) -> bool:
        try:
            parsed = urlparse(value if "://" in value else f"http://{value}")
        except ValueError:
            return False
        return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}

    def _is_local_request(self) -> bool:
        """Whether Host (and Origin, when sent) name this loopback server.

        The socket only listens on localhost, but that is not a boundary on its
        own: a DNS-rebinding page resolves its own hostname to 127.0.0.1 and
        then talks to us with its origin intact. Pinning Host closes that.
        """
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if not self._is_loopback_authority(host):
            return False
        return not origin or self._is_loopback_authority(origin)

    def _contained_abs_path(self, body: dict[str, Any]) -> str | None:
        """Validate a client-supplied ``abs_path`` before we write through it.

        The annotation and save endpoints take an absolute path from the page.
        Resolving it unchecked lets a caller edit any file the user owns, so
        require it to land inside the served repository and to not be reached
        through a symlink.
        """
        raw = str(body.get("abs_path") or "")
        if not raw:
            self._send_json({"ok": False, "error": "missing abs_path"}, 400)
            return None
        root = Path(self.repo_root).resolve()
        candidate = Path(raw)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or candidate.is_symlink():
            self._send_json({"ok": False, "error": "path is outside this repository"}, 403)
            return None
        return str(resolved)

    def _authorize_mutation(self) -> bool:
        """Gate every state-changing request on the per-run session token.

        Without this, any page the user visits can post here: a form with
        ``enctype="text/plain"`` is not preflighted, so the browser sends it
        cross-origin and the side effect lands even though the response is
        unreadable. Requiring a custom header forces a preflight we never
        answer, and the token keeps out anything that cannot read the page or
        ``.proseview/server.json`` (which is how the local CLI authenticates).
        """
        if not self._is_local_request():
            self._send_json({"ok": False, "error": "request must come from this local Proseview server"}, 403)
            return False
        supplied = self.headers.get("X-Proseview-Session", "")
        if not self.session_token or not compare_digest(supplied, self.session_token):
            self._send_json({"ok": False, "error": "invalid or missing page session"}, 403)
            return False
        return True

    def _send_discuss_error(self, exc: Exception) -> None:
        message = str(exc) or exc.__class__.__name__
        if isinstance(exc, CodexAuthError):
            status = 401
        elif isinstance(exc, (CodexUnavailableError, CodexProtocolError)):
            status = 503
        elif isinstance(exc, ContextError):
            status = 409 if any(word in message.lower() for word in ("stale", "already", "not active", "busy")) else 400
            if "queue is full" in message.lower():
                status = 429
            elif "conversation not found" in message.lower():
                status = 404
        else:
            status = 500
        self._send_json({"ok": False, "error": message}, status)

    def _handle_discuss_events(self, conversation_id: str) -> None:
        raw_last = self.headers.get("Last-Event-ID")
        try:
            last_id = int(raw_last) if raw_last not in (None, "") else None
            if last_id is not None and last_id < 0:
                raise ValueError
        except ValueError:
            self._send_json({"ok": False, "error": "Last-Event-ID must be an integer"}, 400)
            return
        try:
            snapshot, replay, subscriber = self.discuss_manager.subscribe(conversation_id, last_id)
        except Exception as exc:
            self._send_discuss_error(exc)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def write_event(event_type: str, data: dict[str, Any], event_id: int | None = None) -> None:
                if event_id is not None:
                    self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
                self.wfile.write(("data: " + json.dumps(data, separators=(",", ":")) + "\n\n").encode("utf-8"))

            if snapshot is not None:
                write_event("snapshot", snapshot, snapshot.get("event_cursor"))
            for event in replay:
                write_event(event.type, event.data, event.id)
            self.wfile.flush()
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    write_event(event.type, event.data, event.id)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.discuss_manager.unsubscribe(conversation_id, subscriber)

    # Static MIME map for the small set of vendored asset extensions.
    _VENDOR_MIME: dict[str, str] = {
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".map": "application/json; charset=utf-8",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }

    def _handle_vendor(self) -> None:
        """Serve files under ``proseview/templates/vendor/`` at ``/vendor/*``.

        Lets the dashboard load chart.js, marked, xterm, etc. from the
        same origin instead of jsDelivr, so the page works offline and
        major upstream bumps can't break the dashboard mid-session.
        """
        rel = urlparse(self.path).path[len("/vendor/"):]
        if not rel or "/" in rel or ".." in rel:
            self.send_response(404)
            self.end_headers()
            return
        vendor_root = (TEMPLATE_DIR / "vendor").resolve()
        target = (vendor_root / rel).resolve()
        if not target.is_relative_to(vendor_root) or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        try:
            data = target.read_bytes()
        except OSError:
            self.send_response(500)
            self.end_headers()
            return
        ext = target.suffix.lower()
        mime = self._VENDOR_MIME.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        # Vendored bytes are immutable per file (filename includes
        # version semantics or is generic; reload busts via path).
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_repo_file(self) -> None:
        """Return a fresh single-file node so the client can refresh a preview
        without reloading the whole page (which would tear down terminal
        sessions). Mirrors the shape produced by ``proseview.repo._file_node``.
        """
        try:
            qs = parse_qs(urlparse(self.path).query)
            rel = (qs.get("path") or [""])[0]
            if not rel:
                self._send_json({"ok": False, "error": "missing path"}, 400)
                return
            root = Path(self.repo_root).resolve()
            try:
                target = resolve_visible_repository_path(root, rel)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 403)
                return
            if not target.is_file():
                self._send_json({"ok": False, "error": "not a file"}, 404)
                return
            cfg = Config.load(root)
            preview_max = cfg.repo_tab.preview_max_bytes
            node = _repo_file_node(target, root, preview_max)
            self._send_json({"ok": True, "node": node})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def _handle_ai_client(self, body: dict[str, Any]) -> None:
        client_id = str(body.get("client_id") or "").strip()
        if not client_id:
            self._send_json({"ok": False, "error": "missing client_id"}, 400)
            return
        with _ai_lock:
            _ai_clients[client_id] = {
                "client_id": client_id,
                "active_scene": body.get("active_scene") or None,
                "last_seen": datetime.now().isoformat(timespec="seconds"),
            }
        self._send_json({"ok": True, "client_id": client_id})

    def _handle_ai_proposal_update(self, proposal_id: str, body: dict[str, Any]) -> None:
        try:
            with _ai_lock:
                prop = _ai_proposals.get(proposal_id)
                if not prop:
                    self._send_json({"ok": False, "error": "proposal not found"}, 404)
                    return
                for key in ("client_id", "message", "quote", "status", "error"):
                    if key in body:
                        prop[key] = body[key]
                if body.get("client_id"):
                    prop.pop("needs_target", None)
                if "range" in body:
                    resolved = _resolve_ai_target(
                        self.repo_root,
                        str(prop["file"]),
                        str(body.get("quote", prop.get("quote", ""))),
                        body["range"],
                    )
                    prop.update(resolved)
                    prop.pop("error", None)
                elif "quote" in body:
                    resolved = _resolve_ai_target(
                        self.repo_root,
                        str(prop["file"]),
                        str(body["quote"]),
                        None,
                    )
                    prop.update(resolved)
                    prop.pop("error", None)
                if "selected_option" in body:
                    prop["selected_option"] = body["selected_option"]
                if "options" in body:
                    prop["options"] = _coerce_options(body["options"])
                prop["updated_at"] = datetime.now().isoformat(timespec="seconds")
                event = _proposal_payload(dict(prop), "updated")
            self.publish_event(event)
            self._send_json({"ok": True, "proposal": event["proposal"]})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def _handle_ai_proposal_action(self, proposal_id: str, action: str, body: dict[str, Any]) -> None:
        try:
            with _ai_lock:
                prop = _ai_proposals.get(proposal_id)
                if not prop:
                    self._send_json({"ok": False, "error": "proposal not found"}, 404)
                    return
                if body.get("client_id"):
                    prop["client_id"] = str(body["client_id"])
                if action == "focus":
                    prop["status"] = "focused"
                elif action == "skip":
                    prop["status"] = "skipped"
                elif action == "validate":
                    scene_rel = _normalize_ai_scene_file(self.repo_root, str(prop["file"]))
                    cfg = Config.load(Path(self.repo_root))
                    target = Path(self.repo_root) / cfg.manuscript_subdir / scene_rel
                    expected_mtime = prop.get("source_mtime_ns")
                    if expected_mtime is not None and target.stat().st_mtime_ns != int(expected_mtime):
                        prop["status"] = "stale"
                        self._send_json({"ok": False, "error": "The scene changed after this rewrite was generated. Reselect the passage and try again."}, 409)
                        return
                    # Re-resolving the exact quote proves it still has one safe,
                    # unambiguous target. Managed actions additionally carry a
                    # source mtime, checked above, so no fuzzy retargeting occurs.
                    if prop.get("origin") != "managed_selection_action":
                        _resolve_ai_target(
                            self.repo_root, scene_rel, str(prop.get("quote") or ""), prop.get("range")
                        )
                    self._send_json({"ok": True, "proposal": dict(prop)})
                    return
                elif action == "apply":
                    if prop.get("needs_target") and not prop.get("client_id"):
                        self._send_json({"ok": False, "error": "proposal needs a target browser tab"}, 409)
                        return
                    option_index = int(body.get("option_index", body.get("option", 1))) - 1
                    if option_index < 0 or option_index >= len(prop.get("options", [])):
                        self._send_json({"ok": False, "error": "option index out of range"}, 400)
                        return
                    prop["selected_option"] = option_index
                    prop["status"] = "apply_requested"
                else:
                    self._send_json({"ok": False, "error": "unknown proposal action"}, 400)
                    return
                prop["updated_at"] = datetime.now().isoformat(timespec="seconds")
                event = _proposal_payload(dict(prop), action)
            self.publish_event(event)
            self._send_json({"ok": True, "proposal": event["proposal"]})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def do_GET(self) -> None:  # noqa: N802
        # Reads are not token-gated (a browser navigating here cannot send a
        # custom header), but they must still address us as localhost so a
        # rebound hostname cannot pull scene text or terminal output.
        if not self._is_local_request():
            self._send_json({"ok": False, "error": "request must come from this local Proseview server"}, 403)
            return
        discuss_path = urlparse(self.path).path
        discuss_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/(snapshot|events)", discuss_path)
        if discuss_match:
            conversation_id, action = discuss_match.groups()
            if action == "events":
                self._handle_discuss_events(conversation_id)
            else:
                try:
                    self._send_json({"ok": True, "snapshot": self.discuss_manager.get_snapshot(conversation_id)})
                except Exception as exc:
                    self._send_discuss_error(exc)
            return
        if self.path.startswith("/terminal-output/"):
            # Allow query string (e.g. /terminal-output/<id>?...).
            tid = urlparse(self.path).path.split("/")[-1]
            with _terminals_lock:
                session = _terminals.get(tid)
            if not session:
                self.send_response(404)
                self.end_headers()
                return
            snapshot, q = session.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b"data: connected\n\n")
                # Replay scrollback as a single base64 SSE frame so a
                # reconnecting client (after a page reload) sees its prior
                # output. For freshly-spawned sessions this is empty.
                if snapshot:
                    encoded = base64.b64encode(snapshot).decode()
                    self.wfile.write(f"data: {encoded}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=5)
                        if msg == "__exit__":
                            self.wfile.write(b"data: __exit__\n\n")
                            self.wfile.flush()
                            break
                        self.wfile.write(f"data: {msg}\n\n".encode())
                        self.wfile.flush()
                    except queue.Empty:
                        if not session.alive:
                            break
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                session.unsubscribe(q)
            return
        if self.path == "/events":
            q: queue.Queue[str] = self.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(b"data: connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {msg}\n\n".encode())
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                self.unsubscribe(q)
            return
        if self.path == "/data.json":
            try:
                root = Path(self.repo_root)
                cfg = Config.load(root)
                scenes = collect_scene_stats(root, cfg)
                data = build_scene_data(scenes, root, cfg)
                body = json.dumps(data).encode("utf-8")
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/ai/proposals":
            with _ai_lock:
                proposals = [dict(p) for p in _ai_proposals.values()]
            self._send_json({"ok": True, "proposals": proposals})
            return
        if self.path.startswith("/ai/proposals/"):
            proposal_id = urlparse(self.path).path.rstrip("/").split("/")[-1]
            with _ai_lock:
                prop = _ai_proposals.get(proposal_id)
                if not prop:
                    self._send_json({"ok": False, "error": "proposal not found"}, 404)
                    return
                data = dict(prop)
            self._send_json({"ok": True, "proposal": data})
            return
        if self.path.startswith("/scene-data"):
            try:
                qs = parse_qs(urlparse(self.path).query)
                rel = (qs.get("path") or [""])[0]
                if not rel:
                    self._send_json({"ok": False, "error": "missing path"}, 400)
                    return
                root = Path(self.repo_root)
                cfg = Config.load(root)
                scene_path = (root / cfg.manuscript_subdir / rel).resolve()
                manuscript_root = (root / cfg.manuscript_subdir).resolve()
                if not scene_path.is_relative_to(manuscript_root):
                    self._send_json({"ok": False, "error": "path outside manuscript"}, 403)
                    return
                scenes = collect_scene_stats(root, cfg)
                data = build_scene_data(scenes, root, cfg)
                if rel not in data["contents"]:
                    self._send_json({"ok": False, "error": "scene not found"}, 404)
                    return
                body = json.dumps({
                    "contents": {rel: data["contents"][rel]},
                    "meta": {rel: data["meta"][rel]},
                    "highlightsByPath": {rel: data["highlightsByPath"][rel]},
                }).encode("utf-8")
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/repo-file"):
            self._handle_repo_file()
            return
        if self.path == "/terminal-list":
            # Live PTY sessions known to this server. Used by the client on
            # page load to reattach existing terminal tabs after a reload
            # so an HTML/JS asset refresh is non-destructive.
            with _terminals_lock:
                items = [
                    {
                        "id": s.id,
                        "type": s.type,
                        "label": s.label,
                        "command": s.command,
                        "alive": s.alive,
                    }
                    for s in _terminals.values()
                    if s.alive
                ]
            self._send_json({"ok": True, "sessions": items})
            return
        if self.path.startswith("/app.css"):
            try:
                # cache_clear() is called by the asset watcher when CSS changes,
                # so this returns the current on-disk content.
                css = _load_asset("assets/app.css").encode("utf-8")
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(css)))
            self.end_headers()
            self.wfile.write(css)
            return
        if self.path.startswith("/vendor/"):
            self._handle_vendor()
            return
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            html = self.get_html().encode("utf-8")
        except Exception as exc:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._authorize_mutation():
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Bad JSON: {exc}"}, 400)
            return
        path = urlparse(self.path).path
        if path.startswith("/ai/proposals/"):
            proposal_id = path.rstrip("/").split("/")[-1]
            self._handle_ai_proposal_update(proposal_id, body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._authorize_mutation():
            return
        if path.startswith("/api/discuss/"):
            try:
                body = self._read_json_limited()
                if path == "/api/discuss/conversations/open":
                    snapshot = self.discuss_manager.open({"kind": body.get("kind"), "path": body.get("path")})
                    self._send_json({"ok": True, "conversation_id": snapshot["conversation_id"], "snapshot": snapshot})
                    return
                if path == "/api/discuss/skills":
                    skills = self.discuss_manager.list_skills(force_reload=bool(body.get("force_reload")))
                    self._send_json({"ok": True, "skills": skills})
                    return
                question_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/questions", path)
                proposal_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/tasks/([^/]+)/proposal", path)
                clear_tasks_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/tasks/clear", path)
                task_status_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/tasks/([^/]+)/status", path)
                cancel_queue_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/queue/([^/]+)/cancel", path)
                history_list_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/history/list", path)
                history_action_match = re.fullmatch(
                    r"/api/discuss/conversations/([^/]+)/history/([^/]+)/(open|rename|remove|export)", path
                )
                new_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/new", path)
                stop_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/turns/([^/]+)/stop", path)
                approval_match = re.fullmatch(r"/api/discuss/conversations/([^/]+)/approvals/([^/]+)", path)
                if question_match:
                    result = self.discuss_manager.submit(
                        question_match.group(1),
                        client_request_id=body.get("client_request_id", ""),
                        question=body.get("question", ""),
                        selection=body.get("selection", ""),
                        selection_range=body.get("selection_range") if isinstance(body.get("selection_range"), dict) else None,
                        live_document=body.get("live_document") if isinstance(body.get("live_document"), dict) else None,
                        attachments=body.get("attachments") or [],
                        include_current_document=body.get("include_current_document", True),
                        action_id=str(body.get("action_id") or ""),
                        custom_instruction=str(body.get("custom_instruction") or ""),
                        skill=body.get("skill") if isinstance(body.get("skill"), dict) else None,
                        retry_of_task_id=str(body.get("retry_of_task_id") or ""),
                    )
                    self._send_json({"ok": True, **result}, 202)
                    return
                if proposal_match:
                    proposal_body = self.discuss_manager.proposal_for_task(
                        proposal_match.group(1), proposal_match.group(2)
                    )
                    proposal_body["client_id"] = body.get("client_id") or None
                    prop = _new_ai_proposal(self.repo_root, proposal_body)
                    self.publish_event(_proposal_payload(dict(prop), "created"))
                    self._send_json({"ok": True, "proposal": prop})
                    return
                if clear_tasks_match:
                    result = self.discuss_manager.clear_tasks(clear_tasks_match.group(1))
                    self._send_json({"ok": True, **result})
                    return
                if task_status_match:
                    result = self.discuss_manager.set_task_status(
                        task_status_match.group(1), task_status_match.group(2), str(body.get("status") or "")
                    )
                    self._send_json({"ok": True, **result})
                    return
                if cancel_queue_match:
                    result = self.discuss_manager.cancel_queued(
                        cancel_queue_match.group(1), cancel_queue_match.group(2)
                    )
                    self._send_json({"ok": True, **result})
                    return
                if history_list_match:
                    result = self.discuss_manager.list_conversations(history_list_match.group(1))
                    self._send_json({"ok": True, **result})
                    return
                if history_action_match:
                    conversation_id, thread_id, action = history_action_match.groups()
                    if action == "open":
                        snapshot = self.discuss_manager.open_conversation(conversation_id, thread_id)
                        self._send_json({"ok": True, "snapshot": snapshot})
                    elif action == "rename":
                        result = self.discuss_manager.rename_conversation(
                            conversation_id, thread_id, str(body.get("title") or "")
                        )
                        self._send_json({"ok": True, "conversation": result})
                    elif action == "remove":
                        result = self.discuss_manager.remove_conversation(conversation_id, thread_id)
                        self._send_json({"ok": True, **result})
                    else:
                        result = self.discuss_manager.export_conversation(conversation_id, thread_id)
                        self._send_json({"ok": True, "export": result})
                    return
                if new_match:
                    snapshot = self.discuss_manager.new_conversation(new_match.group(1))
                    self._send_json({"ok": True, "snapshot": snapshot})
                    return
                if stop_match:
                    result = self.discuss_manager.stop(stop_match.group(1), stop_match.group(2))
                    self._send_json({"ok": True, **result})
                    return
                if approval_match:
                    result = self.discuss_manager.approve(
                        approval_match.group(1), approval_match.group(2), str(body.get("decision") or ""), body
                    )
                    self._send_json({"ok": True, "approval": result})
                    return
                self._send_json({"ok": False, "error": "Discuss endpoint not found"}, 404)
            except Exception as exc:
                self._send_discuss_error(exc)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Bad JSON: {exc}"}, 400)
            return
        path = urlparse(self.path).path
        if path in _ABS_PATH_ENDPOINTS:
            contained = self._contained_abs_path(body)
            if contained is None:
                return
            body["abs_path"] = contained
        if path in ("/ai/clients/register", "/ai/clients/heartbeat"):
            self._handle_ai_client(body)
        elif path == "/ai/proposals":
            try:
                prop = _new_ai_proposal(self.repo_root, body)
                self.publish_event(_proposal_payload(dict(prop), "created"))
                self._send_json({"ok": True, "proposal": prop})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif path.startswith("/ai/proposals/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "ai" and parts[1] == "proposals":
                self._handle_ai_proposal_update(parts[2], body)
            elif len(parts) == 4 and parts[0] == "ai" and parts[1] == "proposals":
                self._handle_ai_proposal_action(parts[2], parts[3], body)
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path == "/insert-todo":
            try:
                insert_todo(
                    body["abs_path"],
                    body.get("selection_text", ""),
                    int(body.get("txt_line_offset", 0)),
                    body["todo_text"],
                )
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/edit-todo":
            try:
                edit_todo(body["abs_path"], body["old_todo_text"], body["new_todo_text"])
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/delete-todo":
            try:
                delete_todo(body["abs_path"], body["todo_text"])
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/add-note":
            try:
                add_note(
                    body["abs_path"],
                    body.get("selection_text", ""),
                    int(body.get("txt_line_offset", 0)),
                    body["note_text"],
                    body.get("tag", "note"),
                )
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/edit-note":
            try:
                edit_note(
                    body["abs_path"],
                    body["old_note_text"],
                    body.get("old_tag", "note"),
                    body["new_note_text"],
                    body.get("new_tag", "note"),
                )
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/delete-note":
            try:
                delete_note(
                    body["abs_path"],
                    body["note_text"],
                    body.get("tag", "note"),
                )
                self.invalidate()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/save-scene":
            try:
                save_scene_content(
                    body["abs_path"],
                    body["content"],
                    float(body["open_mtime"]),
                    self.repo_root,
                )
                self.invalidate()
                # Return the post-save mtime so the client can update its
                # baseline and keep editing without hitting a stale-mtime
                # conflict on the next save.
                try:
                    new_mtime = Path(body["abs_path"]).stat().st_mtime
                except OSError:
                    new_mtime = None
                self._send_json({"ok": True, "mtime": new_mtime})
            except _FileConflictError:
                self._send_json({"conflict": True}, 409)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/terminal-spawn":
            try:
                command = body.get("command", ["codex"])
                cwd = self.repo_root  # always run from repo root so AGENTS.md is visible
                rows = int(body.get("rows", 24))
                cols = int(body.get("cols", 120))
                t_type = str(body.get("type") or "shell")
                t_label = str(body.get("label") or "")
                session = spawn_terminal(
                    command,
                    cwd=cwd,
                    rows=rows,
                    cols=cols,
                    type=t_type,
                    label=t_label,
                )
                self._send_json({"ok": True, "id": session.id})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/terminal-input":
            try:
                tid = body["id"]
                data = base64.b64decode(body["data"])
                with _terminals_lock:
                    session = _terminals.get(tid)
                if session:
                    session.write(data)
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/terminal-resize":
            try:
                tid = body["id"]
                rows = int(body.get("rows", 24))
                cols = int(body.get("cols", 120))
                with _terminals_lock:
                    session = _terminals.get(tid)
                if session:
                    session.resize(rows, cols)
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif self.path == "/terminal-kill":
            try:
                tid = body["id"]
                with _terminals_lock:
                    session = _terminals.pop(tid, None)
                if session:
                    session.kill()
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        else:
            self.send_response(404)
            self.end_headers()


def _make_handler(
    get_html: Callable[[], str],
    invalidate: Callable[[], None],
    subscribe: Callable[[], "queue.Queue[str]"],
    unsubscribe: Callable[["queue.Queue[str]"], None],
    publish_event: Callable[[dict[str, Any]], None],
    repo_root: str,
    discuss_manager: DiscussManager,
    session_token: str,
) -> type:
    class BoundHandler(_Handler):
        pass
    BoundHandler.get_html = staticmethod(get_html)  # type: ignore[method-assign]
    BoundHandler.invalidate = staticmethod(invalidate)  # type: ignore[method-assign]
    BoundHandler.subscribe = staticmethod(subscribe)  # type: ignore[method-assign]
    BoundHandler.unsubscribe = staticmethod(unsubscribe)  # type: ignore[method-assign]
    BoundHandler.publish_event = staticmethod(publish_event)  # type: ignore[method-assign]
    BoundHandler.repo_root = repo_root  # type: ignore[method-assign]
    BoundHandler.discuss_manager = discuss_manager  # type: ignore[method-assign]
    BoundHandler.session_token = session_token  # type: ignore[method-assign]
    return BoundHandler


def serve(
    root: Path,
    port: int = DEFAULT_PORT,
    watch_interval: float = 2.0,
    open_browser: bool = True,
) -> None:
    """Start the proseview HTTP server and block until interrupted."""
    lock = threading.Lock()
    _cache: list[str] = []
    _stale = [True]
    _sse_clients: list[queue.Queue[str]] = []
    _sse_lock = threading.Lock()
    discuss_manager = DiscussManager(root)
    session_token = uuid.uuid4().hex

    def get_html() -> str:
        with lock:
            if _stale[0] or not _cache:
                started = perf_counter()
                cfg = Config.load(root)
                html = build_dashboard(root, cfg, session_token=session_token)
                _cache[:] = [html]
                _stale[0] = False
                elapsed = perf_counter() - started
                stamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{stamp}] regenerated dashboard in {elapsed:.2f}s")
            return _cache[0]

    def invalidate(kind: str = "content", changed_paths: tuple[str, ...] = ()) -> None:
        """Invalidate the cached HTML and notify SSE clients.

        ``kind`` controls the SSE message:
        - ``"content"`` (default) -> ``reload`` so existing clients re-fetch
          ``/data.json`` and re-render the open scene without losing terminal
          sessions.
        - ``"css"`` -> ``reload:css`` so the client hot-swaps the inlined
          stylesheet from ``/app.css``.
        - ``"html"`` (or ``"js"``) -> ``reload:html`` so the client surfaces a
          banner offering a full page reload (which the user can defer to
          preserve in-browser terminals).
        """
        with lock:
            _stale[0] = True
        if kind == "content" and changed_paths:
            msg = json.dumps({"type": "reload", "paths": list(changed_paths)})
        else:
            msg = "reload" if kind == "content" else f"reload:{kind}"
        with _sse_lock:
            for q in list(_sse_clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def publish_event(payload: dict[str, Any]) -> None:
        msg = json.dumps(payload)
        with _sse_lock:
            for q in list(_sse_clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe() -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=4)
        with _sse_lock:
            _sse_clients.append(q)
        return q

    def unsubscribe(q: queue.Queue[str]) -> None:
        with _sse_lock:
            try:
                _sse_clients.remove(q)
            except ValueError:
                pass

    def on_change(changed: tuple[str, ...]) -> None:
        invalidate("content", changed)

    cfg = Config.load(root)
    watcher = threading.Thread(
        target=_watch,
        args=(root, on_change),
        kwargs={"interval": watch_interval, "cfg": cfg},
        daemon=True,
    )
    watcher.start()

    # Asset watcher: poll the proseview templates dir on its own loop so edits
    # to .css / .js / .j2 files trigger an SSE event without restarting the
    # server. CSS-only changes are hot-swapped in the browser; .js and .j2
    # changes raise a "Reload to apply" banner that the user can defer so
    # in-browser terminal sessions are not lost.
    def _snap_assets() -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        try:
            for fp in TEMPLATE_DIR.rglob("*"):
                if not fp.is_file():
                    continue
                try:
                    st = fp.stat()
                except OSError:
                    continue
                rel = str(fp.relative_to(TEMPLATE_DIR))
                result[rel] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass
        return result

    def _classify_asset_changes(changed: set[str]) -> str:
        if changed and all(p.endswith(".css") for p in changed):
            return "css"
        return "html"

    def _watch_assets() -> None:
        baseline = _snap_assets()
        while True:
            _time.sleep(max(0.5, watch_interval))
            current = _snap_assets()
            if current == baseline:
                continue
            _time.sleep(0.3)  # debounce
            current = _snap_assets()
            changed = {p for p in set(baseline) | set(current)
                       if baseline.get(p) != current.get(p)}
            baseline = current
            if not changed:
                continue
            kind = _classify_asset_changes(changed)
            try:
                _load_asset.cache_clear()
            except AttributeError:
                pass
            invalidate(kind)

    asset_watcher = threading.Thread(target=_watch_assets, daemon=True)
    asset_watcher.start()

    handler_cls = _make_handler(
        get_html,
        invalidate,
        subscribe,
        unsubscribe,
        publish_event,
        str(root.resolve()),
        discuss_manager,
        session_token,
    )

    class _Server(ThreadingHTTPServer):
        def handle_error(self, request: object, client_address: object) -> None:
            import sys
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
                return  # normal on browser reload / SSE disconnect
            super().handle_error(request, client_address)

    httpd = _Server(("localhost", port), handler_cls)

    url = f"http://localhost:{port}"
    print(f"proseview serving at {url}")
    print("Press Ctrl-C to stop.")
    _write_runtime_file(root, port, session_token)

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        discuss_manager.close()
        _remove_runtime_file(root, port)
