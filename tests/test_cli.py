"""Tests for the proseview CLI surface (server-only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import cli  # noqa: E402
from proseview.server import DEFAULT_PORT  # noqa: E402


def test_parse_args_defaults():
    args = cli.parse_args([])
    assert args.root == Path.cwd()
    assert args.port == DEFAULT_PORT
    assert args.interval == 2.0
    assert args.open_browser is True


def test_parse_args_overrides(tmp_path: Path):
    args = cli.parse_args([
        "--root", str(tmp_path),
        "--port", "9999",
        "--interval", "0.5",
        "--no-open",
    ])
    assert args.root == tmp_path
    assert args.port == 9999
    assert args.interval == 0.5
    assert args.open_browser is False


def test_main_invokes_serve_with_resolved_root(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_serve(root: Path, *, port: int, watch_interval: float, open_browser: bool) -> None:
        captured["root"] = root
        captured["port"] = port
        captured["watch_interval"] = watch_interval
        captured["open_browser"] = open_browser

    monkeypatch.setattr(cli, "serve", fake_serve)

    rc = cli.main(["--root", str(tmp_path), "--port", "9000", "--no-open"])

    assert rc == 0
    assert captured == {
        "root": tmp_path.resolve(),
        "port": 9000,
        "watch_interval": 2.0,
        "open_browser": False,
    }


def test_main_strips_serve_subcommand(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_serve(root: Path, *, port: int, watch_interval: float, open_browser: bool) -> None:
        captured["port"] = port

    monkeypatch.setattr(cli, "serve", fake_serve)

    rc = cli.main(["serve", "--root", str(tmp_path), "--port", "8123"])

    assert rc == 0
    assert captured == {"port": 8123}


def test_main_rejects_non_positive_interval(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli, "serve", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["--root", str(tmp_path), "--interval", "0"])
