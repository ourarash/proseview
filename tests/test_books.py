"""Which book plain `proseview` opens, `proseview new`, and `proseview open`."""

from __future__ import annotations

from pathlib import Path

import pytest

from proseview import books, cli


@pytest.fixture(autouse=True)
def _own_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


@pytest.fixture
def served(monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(cli, "serve", lambda root, **_: calls.append(root))
    return calls


def _book(path: Path) -> Path:
    (path / "manuscript" / "ch01").mkdir(parents=True)
    return path


def test_new_starts_a_book_in_documents_and_remembers_it(served):
    assert cli.main(["new", "--no-open"]) == 0
    book = Path.home() / "Documents" / "Proseview" / "MyNovel"
    assert (book / "manuscript" / "ch01" / "01-first-scene.md").read_text().startswith("---\ntitle: First scene")
    assert served == [book.resolve()]
    assert books.last_book() == book.resolve()


def test_new_never_writes_into_a_folder_that_has_files(tmp_path: Path, served):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "todo.txt").write_text("keep me")
    assert cli.main(["new", str(folder), "--no-serve"]) == 0
    assert sorted(p.name for p in folder.iterdir()) == ["todo.txt"]
    assert served == []


def test_plain_proseview_reopens_the_last_book(tmp_path: Path, monkeypatch, served):
    book = _book(tmp_path / "Novel")
    assert cli.main(["open", str(book), "--no-serve"]) == 0
    monkeypatch.chdir(Path.home())
    assert cli.main([]) == 0
    assert served == [book.resolve()]


def test_a_book_in_the_current_folder_wins_over_the_remembered_one(tmp_path: Path, monkeypatch, served):
    books.remember_book(_book(tmp_path / "Old"))
    here = _book(tmp_path / "Here")
    monkeypatch.chdir(here)
    assert cli.main([]) == 0
    assert served == [here.resolve()]


def test_a_folder_path_alone_opens_that_book(tmp_path: Path, served):
    book = _book(tmp_path / "My Book")
    assert cli.main([str(book), "--no-open"]) == 0
    assert served == [book.resolve()]
    assert books.last_book() == book.resolve()


def test_home_with_no_remembered_book_asks_for_a_folder(tmp_path: Path, monkeypatch, served):
    chosen = _book(tmp_path / "Picked")
    monkeypatch.chdir(Path.home())
    monkeypatch.setattr(books, "choose_folder", lambda *a, **k: chosen)
    assert cli.main([]) == 0
    assert served == [chosen.resolve()]
    assert books.last_book() == chosen.resolve()


def test_a_cancelled_picker_explains_what_to_run(monkeypatch, served, capsys):
    monkeypatch.chdir(Path.home())
    monkeypatch.setattr(books, "choose_folder", lambda *a, **k: None)
    assert cli.main([]) == 1
    assert "proseview open" in capsys.readouterr().err
    assert served == []


def test_open_without_a_path_uses_the_picker(tmp_path: Path, monkeypatch, served):
    chosen = _book(tmp_path / "Picked")
    monkeypatch.setattr(books, "choose_folder", lambda *a, **k: chosen)
    assert cli.main(["open", "--no-open"]) == 0
    assert served == [chosen.resolve()]


def test_a_forgotten_book_that_was_deleted_is_not_reopened(tmp_path: Path, monkeypatch):
    book = _book(tmp_path / "Gone")
    books.remember_book(book)
    for path in sorted(book.rglob("*"), reverse=True):
        path.rmdir()
    book.rmdir()
    assert books.last_book() is None
