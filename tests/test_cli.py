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


def test_parse_propose_command():
    args = cli.parse_args([
        "propose",
        "--file", "manuscript/ch01/01-opening.md",
        "--quote", "old line",
        "--start", "5",
        "--end", "13",
        "--message", "Issue",
        "--option", "New line A",
        "--option", "New line B",
    ])
    assert args.cmd == "propose"
    assert args.file == "manuscript/ch01/01-opening.md"
    assert args.start == 5
    assert args.end == 13
    assert args.option == ["New line A", "New line B"]


def test_parse_proposal_apply_command():
    args = cli.parse_args(["proposal", "apply", "abc123", "--option", "2"])
    assert args.cmd == "proposal"
    assert args.proposal_cmd == "apply"
    assert args.id == "abc123"
    assert args.option == 2


def test_parse_proposal_status_command():
    args = cli.parse_args(["proposal", "status", "abc123"])
    assert args.cmd == "proposal"
    assert args.proposal_cmd == "status"
    assert args.id == "abc123"


def test_parse_proposal_update_accepts_offsets():
    args = cli.parse_args([
        "proposal", "update", "abc123",
        "--start", "10",
        "--end", "20",
    ])
    assert args.proposal_cmd == "update"
    assert args.start == 10
    assert args.end == 20


def test_parse_propose_accepts_line_columns():
    args = cli.parse_args([
        "propose",
        "--file", "manuscript/ch01/01-opening.md",
        "--start-line", "7",
        "--start-col", "1",
        "--end-line", "8",
        "--end-col", "12",
        "--message", "Issue",
        "--option", "Replacement",
    ])
    assert args.start_line == 7
    assert args.start_col == 1
    assert args.end_line == 8
    assert args.end_col == 12


def test_main_rejects_non_positive_interval(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli, "serve", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli.main(["--root", str(tmp_path), "--interval", "0"])


# ── ``proseview init`` subcommand ────────────────────────────────────────────


def test_init_writes_starter_config(tmp_path: Path, capsys):
    rc = cli.main(["init", "--root", str(tmp_path)])
    assert rc == 0
    config_path = tmp_path / ".proseview.yaml"
    assert config_path.exists()
    body = config_path.read_text(encoding="utf-8")
    # Spot-check that the well-known keys ship in the starter file.
    for key in ("manuscript_path", "characters_path", "skills_path",
                "target_words", "mattr_band", "editor", "repo_tab"):
        assert key in body, f"starter config missing key {key!r}"
    out = capsys.readouterr().out
    assert ".proseview.yaml" in out


def test_init_refuses_to_overwrite_without_force(tmp_path: Path, capsys):
    config_path = tmp_path / ".proseview.yaml"
    config_path.write_text("# existing user config\n", encoding="utf-8")

    rc = cli.main(["init", "--root", str(tmp_path)])
    assert rc == 1
    # The user's content was preserved.
    assert config_path.read_text(encoding="utf-8") == "# existing user config\n"
    err = capsys.readouterr().err
    assert "refusing to overwrite" in err


def test_init_force_overwrites(tmp_path: Path):
    config_path = tmp_path / ".proseview.yaml"
    config_path.write_text("# stale\n", encoding="utf-8")

    rc = cli.main(["init", "--root", str(tmp_path), "--force"])
    assert rc == 0
    assert "manuscript_path" in config_path.read_text(encoding="utf-8")
