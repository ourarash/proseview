"""Which book plain ``proseview`` opens, and how a new one starts.

A writer who installed Proseview with the one-line installer should never have
to type a path: the last book they opened is remembered, ``proseview open``
shows the system's folder picker, and ``proseview new`` starts a book with its
first scene.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def default_new_book() -> Path:
    return Path.home() / "Documents" / "Proseview" / "MyNovel"


def _books_file() -> Path:
    from .discuss import _state_path

    return _state_path().with_name("books.json")


def last_book() -> Path | None:
    """The book opened most recently, if it still exists."""
    try:
        data = json.loads(_books_file().read_text(encoding="utf-8"))
        path = Path(data["last"]).expanduser()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return path if path.is_dir() else None


def remember_book(path: Path) -> None:
    target = _books_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"last": str(path.resolve())}) + "\n", encoding="utf-8")
    except OSError:
        pass  # Remembering is a convenience; the book still opens.


def looks_like_book(path: Path) -> bool:
    return (path / ".proseview.yaml").is_file() or (path / "manuscript").is_dir()


def seed_book(root: Path) -> bool:
    """Give an empty or missing folder its first chapter and scene.

    Returns False, writing nothing, when the folder already has files: those
    are the writer's, and a new book never lands on top of them.
    """
    if root.is_dir() and any(root.iterdir()):
        return False
    scene = root / "manuscript" / "ch01" / "01-first-scene.md"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text(FIRST_SCENE, encoding="utf-8")
    return True


def default_root(cwd: Path | None = None) -> Path | None:
    """The book plain ``proseview`` opens, or None to ask.

    A book in the current folder wins, so running Proseview inside one works
    as it always has. Otherwise the remembered book; with none, the current
    folder as before, except a home folder, which is never a book.
    """
    cwd = (cwd or Path.cwd()).resolve()
    if looks_like_book(cwd):
        return cwd
    remembered = last_book()
    if remembered is not None:
        return remembered
    if cwd == Path.home().resolve():
        return None
    return cwd


def choose_folder(prompt: str = "Choose your book's folder") -> Path | None:
    """Show the system's folder picker. None if cancelled or unavailable."""
    if sys.platform == "darwin":
        script = f'POSIX path of (choose folder with prompt {json.dumps(prompt)})'
        command = ["osascript", "-e", script]
    elif os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            f"$d.Description = {json.dumps(prompt)};"
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
        )
        command = ["powershell", "-NoProfile", "-STA", "-Command", script]
    elif shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", f"--title={prompt}"]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", str(Path.home()), "--title", prompt]
    else:
        return None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    chosen = result.stdout.strip()
    if result.returncode != 0 or not chosen:
        return None
    path = Path(chosen).expanduser()
    return path if path.is_dir() else None
