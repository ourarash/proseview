"""The in-browser app (proseview.browser): a new book's first scene, and
requests answered from memory by the same handler the local server uses."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from proseview import browser


@pytest.fixture
def book(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "my-novel"
    root.mkdir()
    monkeypatch.setattr(browser, "ROOT", root)
    monkeypatch.setattr(browser, "_handler_class", None)
    monkeypatch.setattr(browser, "_cache", {"html": None, "analysis": None})
    monkeypatch.setattr(browser, "_events", [])
    browser.seed(root)
    return root


def _post(path: str, data: dict) -> dict:
    return browser.request(
        "POST", path, json.dumps(data).encode("utf-8"),
        {"Content-Type": "application/json", "X-Proseview-Session": browser.SESSION, "Origin": "https://example.org"},
    )


def test_seed_starts_an_empty_book_and_leaves_a_used_one_alone(tmp_path: Path):
    browser.seed(tmp_path / "new")
    scene = tmp_path / "new" / "manuscript" / "ch01" / "01-first-scene.md"
    assert scene.read_text(encoding="utf-8") == browser.FIRST_SCENE

    used = tmp_path / "used"
    (used / "notes.md").parent.mkdir()
    (used / "notes.md").write_text("mine", encoding="utf-8")
    browser.seed(used)
    assert [p.name for p in used.iterdir()] == ["notes.md"]


def test_dashboard_and_data_come_from_the_book(book: Path):
    page = browser.request("GET", "/")
    assert page["status"] == 200
    assert b'id="repoSidebar"' in page["body"] and b"First scene" in page["body"]

    data = browser.request("GET", "/data.json")
    assert data["status"] == 200
    assert data["headers"]["Content-Type"].startswith("application/json")
    json.loads(data["body"])


def test_creating_a_file_saves_it_and_tells_the_page_to_reload(book: Path):
    reply = _post("/api/files/create", {"parent": "manuscript", "name": "ch02", "kind": "folder"})
    assert reply["status"] == 201, reply["body"]
    assert (book / "manuscript" / "ch02").is_dir()
    assert reply["events"] and "ch02" in reply["events"][0]
    # Events are handed over once.
    assert browser.request("GET", "/data.json")["events"] == []


def test_book_zip_holds_the_book_but_not_proseviews_working_files(book: Path):
    (book / ".proseview" / "backups").mkdir(parents=True)
    (book / ".proseview" / "backups" / "x.md").write_text("old", encoding="utf-8")

    reply = browser.request("GET", "/browser/book.zip")
    assert reply["status"] == 200 and reply["headers"]["Content-Type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(reply["body"])).namelist()
    assert names == ["my-novel/manuscript/ch01/01-first-scene.md"]


def test_an_epub_export_is_done_when_the_request_that_starts_it_returns(book: Path):
    reply = _post("/api/export/start", {"details": {"title": "My Novel", "author": "A. Writer", "format": "epub"}})
    assert reply["status"] == 202, reply["body"]
    job = json.loads(reply["body"])

    done = json.loads(browser.request("GET", f"/api/export/jobs/{job['id']}")["body"])
    assert done["state"] == "done", done
    (file,) = done["result"]["files"]
    assert file["path"].endswith(".epub") and (book / file["path"]).is_file()
