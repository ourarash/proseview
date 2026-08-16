"""Platform guards.

Proseview used to `import fcntl` at module scope, so on Windows `import
proseview` failed outright — the dashboard, which needs none of that, never got
a chance to run. Only the in-browser terminal is genuinely Unix-only.

These tests simulate the Windows import rather than skipping on POSIX, because
the maintainers do not run Windows and a skipped test guards nothing.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Every module the terminal needs and Windows does not have.
UNIX_ONLY = {"fcntl", "pty", "termios"}


@pytest.fixture()
def without_unix_modules(monkeypatch):
    """Re-import proseview.server as if the Unix-only modules did not exist."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in UNIX_ONLY:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    for name in UNIX_ONLY:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "proseview.server", raising=False)

    module = importlib.import_module("proseview.server")
    yield module

    # Restore the real module for everything that follows.
    monkeypatch.undo()
    sys.modules.pop("proseview.server", None)
    importlib.import_module("proseview.server")


def test_server_imports_without_the_unix_only_modules(without_unix_modules):
    assert without_unix_modules._PTY_AVAILABLE is False


def test_spawning_a_terminal_fails_clearly_rather_than_at_import(without_unix_modules):
    with pytest.raises(RuntimeError, match="pty"):
        without_unix_modules.spawn_terminal(["sh"], cwd=".")


def test_the_dashboard_still_builds_without_a_pty(without_unix_modules, tmp_path: Path):
    """The point of the guard: everything that is not the terminal keeps working."""
    from proseview.config import Config
    from proseview.generator import build_dashboard

    (tmp_path / "one.md").write_text("# One\n\nShe counted the boats twice.\n", encoding="utf-8")
    html = build_dashboard(tmp_path, Config.load(tmp_path))

    assert "one.md" in html


def test_the_page_is_told_the_terminal_is_unavailable(without_unix_modules, tmp_path: Path):
    from proseview.config import Config
    from proseview.generator import build_dashboard

    (tmp_path / "one.md").write_text("# One\n\nProse.\n", encoding="utf-8")
    html = build_dashboard(tmp_path, Config.load(tmp_path))

    assert "const terminalAvailable = JSON.parse('false')" in html


def test_terminal_is_available_on_this_platform():
    """Sanity: the guard has not disabled the terminal where it should work."""
    from proseview.server import _PTY_AVAILABLE

    assert _PTY_AVAILABLE is (sys.platform != "win32")
