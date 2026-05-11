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
import select
import signal
import struct
import tempfile
import threading
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Callable

try:
    import pty
    import termios
    _PTY_AVAILABLE = True
except ImportError:
    _PTY_AVAILABLE = False

from .config import Config
from .generator import TEMPLATE_DIR, _load_asset, build_dashboard, build_scene_data
from .lexical import paragraph_blocks
from .repo import _file_node as _repo_file_node
from .scenes import collect_scene_stats, extract_scene_text, split_frontmatter
from .watch import watch as _watch
from urllib.parse import urlparse, parse_qs
import time as _time

DEFAULT_PORT = 7842


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
    shell = env.get("SHELL", "/bin/zsh")
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
    repo_root: str

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silence default access log

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                self._send_json({"ok": False, "error": "path outside repo"}, 403)
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

    def do_GET(self) -> None:  # noqa: N802
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

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Bad JSON: {exc}"}, 400)
            return
        if self.path == "/insert-todo":
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
    repo_root: str,
) -> type:
    class BoundHandler(_Handler):
        pass
    BoundHandler.get_html = staticmethod(get_html)  # type: ignore[method-assign]
    BoundHandler.invalidate = staticmethod(invalidate)  # type: ignore[method-assign]
    BoundHandler.subscribe = staticmethod(subscribe)  # type: ignore[method-assign]
    BoundHandler.unsubscribe = staticmethod(unsubscribe)  # type: ignore[method-assign]
    BoundHandler.repo_root = repo_root  # type: ignore[method-assign]
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

    def get_html() -> str:
        with lock:
            if _stale[0] or not _cache:
                started = perf_counter()
                cfg = Config.load(root)
                html = build_dashboard(root, cfg)
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

    handler_cls = _make_handler(get_html, invalidate, subscribe, unsubscribe, str(root.resolve()))

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

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
