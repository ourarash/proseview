"""Proseview in a web browser, with no server: the "Start a new book" page.

The site runs this module in Pyodide, in a Web Worker. Each request the page
makes is fed through the same handler the local server uses, from memory
instead of a socket, so every route behaves as it does on a writer's own
computer. The book lives in ``/my-novel``, which the worker keeps in the
browser's own storage.

There are no threads or processes in a browser: git is simply absent, and an
export runs inside the request that starts it.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .config import Config
from .discuss import DiscussManager
from .export_dashboard import ExportJobs
from .generator import build_analysis_payload, build_dashboard
from .privacy import PrivacyLock
from .server import _make_handler

ROOT = Path("/my-novel")
SESSION = "browser"

#: The scene a new book starts with: enough to show where writing happens and
#: how the rest of the book grows.
FIRST_SCENE = """\
---
title: First scene
---

This is the first scene of your book. Press **E** to write in it, and
**Cmd-S** (Ctrl-S) to save.

Add scenes and chapters with **+** in the Files sidebar: a folder inside
`manuscript` is a chapter, and each Markdown file in it is a scene.
"""

_cache: dict[str, Any] = {"html": None, "analysis": None}
_events: list[str] = []


def seed(root: Path = ROOT) -> None:
    """Give an empty book its first chapter and scene."""
    if root.is_dir() and any(root.iterdir()):
        return
    scene = root / "manuscript" / "ch01" / "01-first-scene.md"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text(FIRST_SCENE, encoding="utf-8")


def _get_html() -> str:
    if _cache["html"] is None:
        _cache["html"] = build_dashboard(ROOT, Config.load(ROOT), session_token=SESSION)
    return _cache["html"]


def _get_analysis_json() -> bytes:
    if _cache["analysis"] is None:
        _cache["analysis"] = json.dumps(build_analysis_payload(ROOT, Config.load(ROOT))).encode("utf-8")
    return _cache["analysis"]


def _invalidate(kind: str = "content", changed_paths: tuple[str, ...] = ()) -> None:
    _cache["html"] = _cache["analysis"] = None
    if kind == "content" and changed_paths:
        _events.append(json.dumps({"type": "reload", "paths": list(changed_paths)}))
    else:
        _events.append("reload" if kind == "content" else f"reload:{kind}")


def _publish(payload: dict[str, Any]) -> None:
    _events.append(json.dumps(payload))


_handler_class = None


def _handler():
    global _handler_class
    if _handler_class is None:
        bound = _make_handler(
            _get_html, _get_analysis_json, _invalidate,
            lambda: None, lambda q: None, _publish,
            str(ROOT), DiscussManager(ROOT), SESSION,
            export_jobs=ExportJobs(on_written=_invalidate, inline=True),
            privacy=PrivacyLock(available=False),
        )

        class InMemory(bound):
            def setup(self) -> None:
                self.rfile = io.BytesIO(self.request)
                self.wfile = io.BytesIO()

            def finish(self) -> None:
                self.response = self.wfile.getvalue()

        _handler_class = InMemory
    return _handler_class


def book_zip(root: Path = ROOT) -> bytes:
    """The book as a zip of its folder, to carry into the installed app."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            # Proseview's own working files (backups, conversations) stay behind.
            if path.is_file() and relative.parts[0] != ".proseview":
                archive.write(path, Path(root.name) / relative)
    return buffer.getvalue()


def request(method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Answer one request from the page: status, headers, body and the
    live-reload events it caused."""
    if method == "GET" and path.split("?")[0] == "/browser/book.zip":
        data = book_zip(ROOT)
        response = {
            "status": 200,
            "headers": {
                "Content-Type": "application/zip",
                "Content-Disposition": 'attachment; filename="my-novel.zip"',
            },
            "body": data,
        }
    else:
        lines = [f"{method} {path} HTTP/1.1", "Host: localhost"]
        # The page and this handler are one program here, so the loopback
        # checks meant for a socket are answered as a local server would be.
        for key, value in (headers or {}).items():
            if key.lower() not in {"host", "origin", "content-length"}:
                lines.append(f"{key}: {value}")
        lines.append(f"Content-Length: {len(body)}")
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
        answer = _handler()(raw, ("127.0.0.1", 0), None).response
        head, _, payload = answer.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        response = {
            "status": int(status_line.split()[1]),
            "headers": dict(line.split(": ", 1) for line in header_lines if ": " in line),
            "body": payload,
        }
    response["events"] = _events[:]
    _events.clear()
    return response
