"""Tests for exporting from the dashboard: the data, the routes, the checks.

Covers:
- the outline the Export dialog draws from: chapters, scenes, word counts,
  saved selections and the remembered book details
- turning the dialog's ticks into a selection (everything ticked is the
  whole book; custom order follows the list; stale picks are refused)
- the server routes, in-process on a copy of the demo book: outline,
  preview pages, an export job from start to finished file, download,
  saving a selection, cover upload, and the session-token gate
- readiness checks in plain words: the demo book's missing author and cover,
  a cover too small for stores, an image without a description, a missing
  image naming its scene
- the book details remembered in .proseview.yaml and read back by the CLI
"""

from __future__ import annotations

import base64
import json
import shutil
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import cli  # noqa: E402
from proseview.book import ExportError  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.epub_check import cover_findings, image_size, readiness, structural_problems  # noqa: E402
from proseview.export import collect_scene_documents, export_book, save_book_details  # noqa: E402
from proseview.export_dashboard import outline, selection_from_request  # noqa: E402

DEMO = REPO_ROOT / "fixtures" / "demo-book"


@pytest.fixture
def book(tmp_path: Path) -> Path:
    """A private copy of the demo book, so nothing writes to the fixture."""
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    return root


def png(width: int, height: int) -> bytes:
    """A real, tiny-on-disk PNG of the given size."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\xff" * width * 3 for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# -- the outline ---------------------------------------------------------------------


def test_outline_lists_chapters_and_scenes_with_words(book: Path):
    data = outline(book, Config.load(book))

    assert len(data["chapters"]) == 12
    first = data["chapters"][0]
    assert first["label"] == "Chapter One"
    assert first["title"] == "I. Down the Rabbit-Hole"
    assert [s["key"] for s in first["scenes"]] == [
        "ch01/01-down-the-rabbit-hole", "ch01/02-down-down-down", "ch01/03-drink-me",
    ]
    assert first["scenes"][0]["scene_path"] == "ch01/01-down-the-rabbit-hole.md"
    assert first["scenes"][0]["path"] == "manuscript/ch01/01-down-the-rabbit-hole.md"
    assert first["words"] == sum(s["words"] for s in first["scenes"]) > 0
    assert data["book"]["words"] == sum(c["words"] for c in data["chapters"])
    assert data["details"] == {
        "title": "", "subtitle": "", "author": "", "language": "en-US", "epub_version": "epub3",
        "style": "classic", "scene_titles": False, "cover_image": "", "format": "epub",
        "trim": "5.5x8.5", "paper": "letter", "recto_chapters": True, "contact": "", "watermark": "",
        "copyright_page": True, "isbn": "", "dedication": "", "also_by": "", "matter_files": True,
    }
    styles = {style["name"]: style for style in data["styles"]}
    assert styles["classic"]["formats"] == ["epub", "pdf-print", "pdf-share"]
    assert styles["manuscript"]["formats"] == ["pdf-share"]
    assert [f["name"] for f in data["formats"]] == ["epub", "pdf-print", "pdf-share", "all"]


def test_outline_word_counts_leave_out_todo_comments(book: Path):
    scene = book / "manuscript" / "ch01" / "01-down-the-rabbit-hole.md"
    before = outline(book, Config.load(book))["chapters"][0]["scenes"][0]["words"]
    scene.write_text(scene.read_text(encoding="utf-8") + "\n<!-- TODO: five more words here -->\n")

    assert outline(book, Config.load(book))["chapters"][0]["scenes"][0]["words"] == before


def test_outline_resolves_saved_selections_and_flags_stale_ones(book: Path):
    (book / ".proseview.yaml").write_text(
        (book / ".proseview.yaml").read_text(encoding="utf-8")
        + "export:\n  selections:\n    Opening:\n      chapters: [ch01]\n"
        + "    Gone:\n      scenes: [ch99/01-nowhere]\n"
    )
    selections = {s["name"]: s for s in outline(book, Config.load(book))["selections"]}

    assert selections["Opening"]["scenes"][0] == "ch01/01-down-the-rabbit-hole"
    assert len(selections["Opening"]["scenes"]) == 3
    assert "No scene called" in selections["Gone"]["error"]


# -- the dialog's ticks --------------------------------------------------------------


def _documents(book: Path):
    return collect_scene_documents(book, Config.load(book))


def test_every_scene_ticked_in_book_order_is_the_whole_book(book: Path):
    docs = _documents(book)
    items = [{"kind": "chapter", "id": str(n)} for n in range(12, 0, -1)]

    assert selection_from_request({"selection": {"order": "book", "items": items}}, docs) is None
    assert selection_from_request({}, docs) is None


def test_ticks_become_chapter_and_scene_picks(book: Path):
    docs = _documents(book)
    selection = selection_from_request({"selection": {"order": "custom", "items": [
        {"kind": "scene", "id": "ch12/01-alice-s-evidence"}, {"kind": "chapter", "id": "3"},
    ]}}, docs)

    assert selection.order == "custom"
    assert selection.picks == (("scene", "ch12/01-alice-s-evidence"), ("chapter", "3"))


@pytest.mark.parametrize("selection, message", [
    ({"order": "book", "items": []}, "Tick at least one"),
    ({"order": "book", "items": [{"kind": "scene", "id": "ch99/01-nowhere"}]}, "no longer in the book"),
    ({"order": "book", "items": [{"kind": "chapter", "id": "40"}]}, "no longer in the book"),
    ({"order": "sideways", "items": []}, "Unknown order"),
])
def test_bad_ticks_are_refused_in_plain_words(book: Path, selection: dict, message: str):
    with pytest.raises(ExportError, match=message):
        selection_from_request({"selection": selection}, _documents(book))


# -- readiness -----------------------------------------------------------------------


def test_image_size_reads_png_gif_jpeg_and_webp():
    assert image_size(png(3, 5)) == (3, 5)
    assert image_size(b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 8) == (640, 480)
    jpeg = (
        b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 2400, 1600) + b"\x00" * 10
    )
    assert image_size(jpeg) == (1600, 2400)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x00" * 8 + (1599).to_bytes(3, "little") + (2559).to_bytes(3, "little")
    assert image_size(webp) == (1600, 2560)
    assert image_size(b"not an image") is None


@pytest.mark.parametrize("size, says", [
    ((600, 900), "600 × 900 px. Stores ask for at least 1600 px"),
    ((2400, 1800), "wider than a book"),
])
def test_a_cover_stores_would_reject_is_explained(size: tuple[int, int], says: str):
    (finding,) = cover_findings(png(*size), whole_book=True)
    assert says in finding.message and finding.fix == "cover"


def test_a_store_sized_cover_passes():
    assert cover_findings(png(1600, 2560), whole_book=True) == []


def test_the_demo_book_needs_an_author_and_a_cover_before_stores(book: Path, tmp_path: Path):
    result = export_book(book, Config.load(book), tmp_path / "book.epub")
    checks = readiness(result.path, result.book, title_given=False, cover=None)

    assert not checks["ready"]
    messages = " ".join(f["message"] for f in checks["findings"])
    assert "comes from the folder name" in messages
    assert "Add the author’s name" in messages
    assert "no cover yet" in messages
    assert {f["fix"] for f in checks["findings"]} == {"title", "author", "cover"}


def test_a_finished_book_is_ready_for_the_stores(book: Path, tmp_path: Path):
    cover = book / "cover.png"
    cover.write_bytes(png(1600, 2560))
    result = export_book(book, Config.load(book), tmp_path / "book.epub", author="Lewis Carroll", cover_image=cover)
    checks = readiness(result.path, result.book, title_given=True, cover=cover.read_bytes())

    assert checks == {"ready": True, "headline": "Ready for Apple Books, Kobo and KDP", "findings": []}


def test_a_chapter_for_readers_is_only_checked_for_soundness(book: Path, tmp_path: Path):
    from proseview.book import Selection

    result = export_book(book, Config.load(book), tmp_path / "ch.epub", selection=Selection(picks=(("chapter", "2"),)))
    checks = readiness(result.path, result.book, title_given=False, cover=None)

    assert checks["headline"] == "Ready to share with readers" and checks["ready"]


def test_an_image_without_a_description_names_its_scene(book: Path, tmp_path: Path):
    (book / "manuscript" / "ch02" / "art.png").write_bytes(png(2, 2))
    scene = book / "manuscript" / "ch02" / "02-the-pool-of-tears.md"
    scene.write_text(scene.read_text(encoding="utf-8") + "\n![](art.png)\n")
    result = export_book(book, Config.load(book), tmp_path / "book.epub", author="L. C.")
    checks = readiness(result.path, result.book, title_given=True, cover=None)

    (image,) = [f for f in checks["findings"] if f.get("fix") == "scene"]
    assert image["scene"] == "ch02/02-the-pool-of-tears"
    assert "has no description" in image["message"]


def test_a_missing_image_names_the_scene_to_open(book: Path, tmp_path: Path):
    scene = book / "manuscript" / "ch03" / "02-the-caucus-race.md"
    scene.write_text(scene.read_text(encoding="utf-8") + "\n![The race](race.png)\n")

    with pytest.raises(ExportError) as caught:
        export_book(book, Config.load(book), tmp_path / "book.epub")
    assert caught.value.scene == "ch03/02-the-caucus-race"
    assert "can't be found" in str(caught.value)


def test_structural_problems_catches_a_broken_zip(tmp_path: Path):
    path = tmp_path / "broken.epub"
    path.write_bytes(b"not a zip")
    assert "cannot be opened" in structural_problems(path)[0]


# -- remembered details --------------------------------------------------------------


def test_book_details_are_remembered_and_read_back_by_the_cli(book: Path, capsys):
    save_book_details(book, Config.load(book), {
        "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll", "subtitle": "",
        "epub_version": "epub2", "scene_titles": True,
    })
    text = (book / ".proseview.yaml").read_text(encoding="utf-8")
    assert "title: Alice's Adventures in Wonderland" in text
    assert "subtitle" not in text
    # Comments elsewhere in the file survive.
    assert "# The cast as the prose names it." in text

    out = book / "out.epub"
    assert cli.main(["export", "--root", str(book), "--output", str(out), "--chapters", "1"]) == 0
    import zipfile

    with zipfile.ZipFile(out) as archive:
        opf = archive.read("OEBPS/content.opf").decode()
        chapter = archive.read("OEBPS/text/chapter-001.xhtml").decode()
    assert 'version="2.0"' in opf
    assert "Lewis Carroll" in opf
    assert 'class="scene-title"' in chapter


def test_saving_unchanged_details_leaves_the_file_alone(book: Path):
    cfg = Config.load(book)
    assert save_book_details(book, cfg, {"title": "", "author": ""}) is False
    assert (book / ".proseview.yaml").read_bytes() == (DEMO / ".proseview.yaml").read_bytes()


# -- the routes ----------------------------------------------------------------------


class _Client:
    def __init__(self, base: str, token: str) -> None:
        self.base, self.token = base, token

    def request(self, method: str, path: str, body: dict | None = None, *, token: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "X-Proseview-Session": self.token if token is None else token}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def json(self, method: str, path: str, body: dict | None = None, **kw):
        status, _, raw = self.request(method, path, body, **kw)
        return status, json.loads(raw)

    def wait(self, job_id: str) -> dict:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            _, job = self.json("GET", f"/api/export/jobs/{job_id}")
            if job["state"] != "running":
                return job
            time.sleep(0.05)
        raise AssertionError("export did not finish")


@pytest.fixture
def client(book: Path, monkeypatch):
    from proseview import export_dashboard
    from proseview.discuss import DiscussManager
    from proseview.server import _make_handler

    opened: list[tuple[Path, bool]] = []
    monkeypatch.setattr(export_dashboard, "open_in_system", lambda path, reveal=False: opened.append((path, reveal)))
    import proseview.server as server_module

    monkeypatch.setattr(server_module, "open_in_system", export_dashboard.open_in_system)
    handler = _make_handler(
        lambda: "", lambda: b"{}", lambda *a, **k: None, lambda: None, lambda q: None, lambda p: None,
        str(book), DiscussManager(book), "token",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    c = _Client(f"http://127.0.0.1:{httpd.server_address[1]}", "token")
    c.opened = opened
    c.root = book
    yield c
    httpd.shutdown()


def client_root(client) -> Path:
    return client.root


def test_route_outline(client):
    status, data = client.json("GET", "/api/export/outline")
    assert status == 200 and data["ok"] and len(data["chapters"]) == 12


def test_route_preview_serves_the_styled_pages(client):
    status, data = client.json("POST", "/api/export/preview", {
        "selection": {"order": "book", "items": [{"kind": "chapter", "id": "1"}]},
        "details": {"title": "Alice"},
    })
    assert status == 200 and data["kind"] == "chapter"
    assert data["pages"][0]["href"] == "OEBPS/text/chapter-001.xhtml"
    assert data["pages"][0]["label"].startswith("Chapter One")

    status, headers, page = client.request("GET", f"/api/export/preview/{data['token']}/OEBPS/text/chapter-001.xhtml")
    assert status == 200
    assert headers["Content-Type"].startswith("application/xhtml+xml")
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert b'class="opener"' in page
    status, _, css = client.request("GET", f"/api/export/preview/{data['token']}/OEBPS/styles/book.css")
    assert status == 200 and b"first-letter" in css
    assert client.request("GET", f"/api/export/preview/{data['token']}/OEBPS/../../etc/passwd")[0] == 404
    assert client.request("GET", f"/api/export/preview/{'0' * 32}/OEBPS/styles/book.css")[0] == 404


def test_route_export_job_runs_to_a_dated_file_and_remembers_details(client, book: Path):
    status, job = client.json("POST", "/api/export/start", {
        "selection": {"order": "book", "items": [{"kind": "chapter", "id": "2"}]},
        "details": {"title": "Alice's Adventures", "author": "Lewis Carroll", "scene_titles": False},
    })
    assert status == 202 and job["state"] == "running"
    done = client.wait(job["id"])

    assert done["state"] == "done", done
    result = done["result"]
    (file,) = result["files"]
    assert file["path"].startswith("exports/alices-adventures-chapter-2-") and file["path"].endswith(".epub")
    assert (book / file["path"]).is_file()
    assert result["chapters"] == 1 and result["scenes"] == 3 and result["words"] > 0
    assert file["checks"]["headline"] == "Ready to share with readers"

    config = (book / ".proseview.yaml").read_text(encoding="utf-8")
    assert "title: Alice's Adventures" in config and "author: Lewis Carroll" in config
    assert "identifier: urn:uuid:" in config
    assert Config.load(book).export.title == "Alice's Adventures"

    status, headers, data = client.request("GET", f"/api/export/file?path={file['path']}")
    assert status == 200 and data[:2] == b"PK"
    assert headers["Content-Disposition"].startswith("attachment;")

    assert client.json("POST", "/api/export/reveal", {"path": file["path"]})[0] == 200
    assert client.opened == [(book.resolve() / file["path"], True)]


def test_route_export_failure_names_the_scene(client, book: Path):
    scene = book / "manuscript" / "ch03" / "02-the-caucus-race.md"
    scene.write_text(scene.read_text(encoding="utf-8") + "\n![The race](race.png)\n")
    _, job = client.json("POST", "/api/export/start", {"details": {}})
    done = client.wait(job["id"])

    assert done["state"] == "failed"
    assert done["error"]["scene_path"] == "ch03/02-the-caucus-race.md"
    assert not (book / ".proseview.yaml").read_text(encoding="utf-8").count("identifier")


def test_route_file_refuses_anything_but_an_export(client, book: Path):
    (book / "exports").mkdir()
    (book / "exports" / "notes.txt").write_text("x", encoding="utf-8")
    for path in ("manuscript/ch01/01-down-the-rabbit-hole.md", "exports/notes.txt", "../x.epub", ".proseview.yaml"):
        assert client.request("GET", f"/api/export/file?path={path}")[0] == 404
    assert client.json("POST", "/api/export/open", {"path": ".proseview.yaml"})[0] == 400


def test_route_saves_a_selection(client, book: Path):
    status, data = client.json("POST", "/api/export/selections", {
        "name": "Beta readers", "selection": {"order": "book", "items": [{"kind": "chapter", "id": "1"}]},
    })
    assert status == 200
    assert [s["name"] for s in data["outline"]["selections"]] == ["Beta readers"]
    assert Config.load(book).export.selection("Beta readers").picks == (("chapter", "ch01"),)


def test_route_cover_upload_lands_in_the_novel(client, book: Path):
    status, data = client.json("POST", "/api/export/cover", {
        "name": "My Cover.PNG", "data": base64.b64encode(png(4, 6)).decode(),
    })
    assert status == 200 and data["path"] == "cover.png"
    assert image_size((book / "cover.png").read_bytes()) == (4, 6)

    (book / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"other")
    _, again = client.json("POST", "/api/export/cover", {"name": "c.png", "data": base64.b64encode(png(4, 6)).decode()})
    assert again["path"] == "cover-2.png"

    status, bad = client.json("POST", "/api/export/cover", {"name": "c.svg", "data": base64.b64encode(b"<svg/>").decode()})
    assert status == 400 and "JPEG, PNG, GIF or WebP" in bad["error"]


def test_export_routes_that_change_things_need_the_page_session(client):
    for path in ("/api/export/start", "/api/export/preview", "/api/export/cover", "/api/export/selections"):
        status, data = client.json("POST", path, {"details": {}}, token="wrong")
        assert status == 403, path


# -- PDF from the dashboard ------------------------------------------------------------


def test_route_pdf_preview_draws_the_first_chapters_as_pages(client):
    status, data = client.json("POST", "/api/export/preview", {
        "details": {"title": "Alice", "format": "pdf-print", "trim": "5x8"},
    })
    assert status == 200 and data["format"] == "pdf-print" and data["spreads"] is True
    assert "first 3 chapters" in data["note"]
    # Title page, its blank back, then chapter one.
    assert data["first_text_page"] == 3
    assert not list((client_root(client) / ".proseview").glob("*.typ"))
    assert data["pages"][0] == {"href": "page-001.png", "label": "Page 1"}
    status, headers, png_bytes = client.request("GET", f"/api/export/preview/{data['token']}/page-001.png")
    assert status == 200 and headers["Content-Type"] == "image/png" and png_bytes[:4] == b"\x89PNG"
    # A 5 × 8 in page at the preview's resolution.
    assert image_size(png_bytes) == (550, 880)


def test_route_preview_of_all_formats_shows_the_one_asked_for(client):
    _, data = client.json("POST", "/api/export/preview", {
        "selection": {"order": "book", "items": [{"kind": "chapter", "id": "1"}]},
        "details": {"format": "all"}, "preview": "pdf-share",
    })
    assert data["format"] == "pdf-share" and data["spreads"] is False and data["note"] == ""


def test_route_exports_all_three_formats_and_checks_each(client, book: Path):
    _, job = client.json("POST", "/api/export/start", {
        "selection": {"order": "book", "items": [{"kind": "chapter", "id": "4"}]},
        "details": {"format": "all", "author": "Lewis Carroll", "watermark": "For Sam", "trim": "6x9"},
    })
    done = client.wait(job["id"])
    assert done["state"] == "done", done
    files = {f["format"]: f for f in done["result"]["files"]}

    assert list(files) == ["epub", "pdf-print", "pdf-share"]
    assert files["pdf-print"]["name"].startswith("alice-chapter-4-print-")
    assert files["pdf-print"]["pages"] > 0 and files["epub"]["pages"] == 0
    assert files["pdf-print"]["checks"]["headline"] == "A 6 × 9 in proof of this part, ready to print"
    assert files["pdf-share"]["checks"]["ready"]
    status, headers, data = client.request("GET", f"/api/export/file?path={files['pdf-share']['path']}")
    assert status == 200 and headers["Content-Type"] == "application/pdf" and data[:5] == b"%PDF-"
    config = Config.load(book).export
    assert (config.format, config.trim) == ("all", "6x9")
    # The watermark names one reader; it is never remembered.
    assert "For Sam" not in (book / ".proseview.yaml").read_text(encoding="utf-8")


def test_route_refuses_a_style_that_cannot_make_the_format(client):
    status, data = client.json("POST", "/api/export/start", {"details": {"format": "epub", "style": "manuscript"}})
    assert status == 400 and "The Manuscript style does not make E-book (EPUB)" in data["error"]


def test_a_cleared_detail_stays_cleared(client, book: Path):
    save_book_details(book, Config.load(book), {"subtitle": "Old subtitle", "author": "Old Name"})
    _, data = client.json("POST", "/api/export/preview", {
        "selection": {"order": "book", "items": [{"kind": "chapter", "id": "1"}, {"kind": "chapter", "id": "2"}]},
        "details": {"subtitle": "", "author": ""},
    })
    status, _, title_page = client.request("GET", f"/api/export/preview/{data['token']}/OEBPS/text/title.xhtml")
    assert status == 200 and b"Old subtitle" not in title_page and b"Old Name" not in title_page


# -- when something goes wrong underneath ------------------------------------------------


class _Panic(BaseException):
    """What a Rust panic inside Typst arrives as: not an Exception."""


def test_outline_says_which_dialog_it_serves(client):
    from proseview.export_dashboard import EXPORT_API

    _, data = client.json("GET", "/api/export/outline")
    assert data["api"] == EXPORT_API >= 3


def test_a_crash_in_a_route_is_answered_not_dropped(client, monkeypatch):
    import proseview.server as server_module

    def explode(*args, **kwargs):
        raise _Panic("typst panicked")

    monkeypatch.setattr(server_module, "build_preview", explode)
    status, data = client.json("POST", "/api/export/preview", {"details": {}})
    assert status == 500 and "Something went wrong while doing that (typst panicked)" in data["error"]


def test_a_crash_in_an_export_job_fails_the_job_in_plain_words(client, monkeypatch):
    from proseview import export_dashboard

    def explode(*args, **kwargs):
        raise _Panic("typst panicked")

    monkeypatch.setattr(export_dashboard, "export_book", explode)
    _, job = client.json("POST", "/api/export/start", {"details": {}})
    done = client.wait(job["id"])
    assert done["state"] == "failed"
    assert done["error"]["message"].startswith("The export stopped unexpectedly: typst panicked.")
