"""Tests for editing Markdown notes (story bible, plans) from the file view.

Covers:
- what may be saved: an existing .md file anywhere visible in the book, and
  nothing else (no `..`, no absolute paths, no hidden or tooling folders, no
  symlinks, no other file types, no new files)
- a save keeps the frontmatter exactly, backs up the version it replaces, and
  refuses a file changed on disk since the editor opened unless told to
  overwrite
- the route needs the page session and answers each refusal plainly
- scenes are still saved only inside the manuscript, and editing a note does
  not make it count as a scene
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.repo import _file_node  # noqa: E402
from proseview.scenes import collect_scene_stats  # noqa: E402
from proseview.server import (  # noqa: E402
    _FileConflictError, resolve_note_write_target, save_note_content, split_note_header,
)

DEMO = REPO_ROOT / "fixtures" / "demo-book"
NOTE = "story-bible/characters/alice.md"


@pytest.fixture
def book(tmp_path: Path) -> Path:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    return root


@pytest.mark.parametrize("raw, header, body", [
    ("---\nname: Alice\n---\n\n# Alice\n", "---\nname: Alice\n---\n", "# Alice\n"),
    ("---\nname: Alice\n...\nText\n", "---\nname: Alice\n...\n", "Text\n"),
    ("# No frontmatter\n", "", "# No frontmatter\n"),
    ("---\nunclosed\n", "", "---\nunclosed\n"),
])
def test_split_note_header(raw: str, header: str, body: str):
    assert split_note_header(raw) == (header, body)


def test_a_save_keeps_the_frontmatter_and_backs_up_the_old_version(book: Path):
    path = book / NOTE
    before = path.read_text(encoding="utf-8")
    _, mtime = save_note_content(NOTE, "# Alice\n\nShe keeps a diary.", path.stat().st_mtime, str(book))

    after = path.read_text(encoding="utf-8")
    assert after == "---\nname: Alice\nrole: protagonist\n---\n\n# Alice\n\nShe keeps a diary.\n"
    assert mtime == path.stat().st_mtime
    (backup,) = (book / ".proseview" / "backups").rglob("*.json")
    assert json.loads(backup.read_text(encoding="utf-8"))["content"] == before


def test_a_file_changed_on_disk_is_not_overwritten_unless_asked(book: Path):
    path = book / NOTE
    opened = path.stat().st_mtime
    time.sleep(0.05)
    path.write_text(path.read_text(encoding="utf-8") + "\nEdited elsewhere.\n", encoding="utf-8")
    os.utime(path, (opened + 5, opened + 5))

    with pytest.raises(_FileConflictError):
        save_note_content(NOTE, "mine", opened, str(book))
    assert "Edited elsewhere." in path.read_text(encoding="utf-8")

    save_note_content(NOTE, "mine", opened, str(book), overwrite=True)
    assert path.read_text(encoding="utf-8").endswith("---\n\nmine\n")


@pytest.mark.parametrize("target, error", [
    ("../outside.md", PermissionError),
    ("/etc/hosts.md", PermissionError),
    (".proseview/notes.md", PermissionError),
    (".git/notes.md", PermissionError),
    ("plans/book-plan.txt", PermissionError),
    (".proseview.yaml", PermissionError),
    ("story-bible/nobody.md", FileNotFoundError),
])
def test_only_existing_markdown_inside_the_book_can_be_saved(book: Path, target: str, error: type):
    (book / "plans" / "book-plan.txt").write_text("not markdown", encoding="utf-8")
    with pytest.raises(error):
        resolve_note_write_target(target, str(book))


def test_a_symlink_cannot_be_saved_through(book: Path, tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    try:
        (book / "story-bible" / "link.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available here")
    with pytest.raises(PermissionError):
        resolve_note_write_target("story-bible/link.md", str(book))
    assert outside.read_text(encoding="utf-8") == "secret"


def test_the_file_view_gets_the_exact_modification_time(book: Path):
    node = _file_node(book / NOTE, book.resolve(), 100_000)
    assert node["mtime"] == (book / NOTE).stat().st_mtime


def test_editing_a_note_does_not_make_it_a_scene(book: Path):
    before = len(collect_scene_stats(book, Config.load(book), lexical=False))
    path = book / NOTE
    save_note_content(NOTE, "A great many words " * 50, path.stat().st_mtime, str(book))
    assert len(collect_scene_stats(book, Config.load(book), lexical=False)) == before


# -- the route ----------------------------------------------------------------------


@pytest.fixture
def server(book: Path):
    from proseview.discuss import DiscussManager
    from proseview.server import _make_handler

    invalidated: list = []
    handler = _make_handler(
        lambda: "", lambda: b"{}", lambda *a, **k: invalidated.append(a), lambda: None, lambda q: None,
        lambda p: None, str(book), DiscussManager(book), "token",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(body: dict, token: str = "token"):
        request = urllib.request.Request(
            base + "/api/files/save", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Proseview-Session": token},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    post.invalidated = invalidated
    yield post
    httpd.shutdown()


def test_route_saves_a_note(server, book: Path):
    mtime = (book / NOTE).stat().st_mtime
    status, data = server({"path": NOTE, "content": "# Alice\n\nNew.", "open_mtime": mtime})
    assert status == 200 and data["ok"] and data["mtime"] == (book / NOTE).stat().st_mtime
    assert (book / NOTE).read_text(encoding="utf-8").endswith("# Alice\n\nNew.\n")
    assert server.invalidated, "the dashboard is told the file changed"


@pytest.mark.parametrize("body, status, says", [
    ({"path": "../x.md", "content": "x", "open_mtime": 0}, 403, "safe visible"),
    ({"path": "plans/missing.md", "content": "x", "open_mtime": 0}, 404, "No such file"),
    ({"path": NOTE, "content": 3, "open_mtime": 0}, 400, "content must be text"),
    ({"path": NOTE, "content": "x", "open_mtime": "soon"}, 400, "open_mtime"),
    ({"path": NOTE, "content": "x", "open_mtime": 1.0}, 409, "changed on disk"),
])
def test_route_refuses_plainly(server, body: dict, status: int, says: str):
    code, data = server(body)
    assert code == status and says in data["error"]


def test_route_needs_the_page_session(server, book: Path):
    before = (book / NOTE).read_text(encoding="utf-8")
    code, _ = server({"path": NOTE, "content": "x", "open_mtime": (book / NOTE).stat().st_mtime}, token="nope")
    assert code == 403 and (book / NOTE).read_text(encoding="utf-8") == before
