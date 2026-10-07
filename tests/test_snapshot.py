"""A snapshot is the dashboard as static files: readable anywhere, editable nowhere.

It is what the hosted demo is built from, and what a writer would hand to a
beta reader. Both put it on someone else's machine, so it has to work without
a server and must not carry paths from the machine that built it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from proseview.cli import main
from proseview.config import Config
from proseview.generator import build_dashboard
from proseview.snapshot import SnapshotError, write_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "fixtures" / "demo-repo"


def _novel(tmp_path: Path) -> Path:
    root = tmp_path / "my-novel"
    shutil.copytree(FIXTURE, root)
    return root


def _published_text(out: Path) -> dict[str, str]:
    return {
        str(path.relative_to(out)): path.read_text(encoding="utf-8")
        for path in out.rglob("*")
        if path.is_file() and path.suffix in {".html", ".json"}
    }


def test_a_snapshot_is_a_page_its_data_and_the_editor_modules(tmp_path: Path):
    out = tmp_path / "site"
    write_snapshot(_novel(tmp_path), out)

    for name in ("index.html", "analysis.json", "scene-lexical.json", "vendor/chart.js",
                 "vendor/pm/prosemirror-model.js"):
        assert (out / name).is_file(), f"snapshot is missing {name}"
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "window.PROSEVIEW_STATIC = true" in html
    # Hosted under a project path such as /proseview/, a root-absolute URL
    # would leave the host and find nothing.
    assert 'src="/vendor/' not in html
    assert "from '/vendor/" not in html


def test_a_snapshot_publishes_no_path_from_the_machine_that_built_it(tmp_path: Path):
    root = _novel(tmp_path)
    out = tmp_path / "site"
    write_snapshot(root, out)

    for name, text in _published_text(out).items():
        assert str(tmp_path) not in text, f"{name} names the build machine's folder"
        assert str(Path.home()) not in text, f"{name} names the build machine's home"
    # The repository keeps its own name, so links between files still agree.
    assert "/my-novel/manuscript/" in (out / "index.html").read_text(encoding="utf-8")


def test_a_snapshot_answers_the_lexical_read_for_every_scene(tmp_path: Path):
    root = _novel(tmp_path)
    out = tmp_path / "site"
    write_snapshot(root, out)

    cfg = Config.load(root)
    scenes = sorted(
        path.relative_to(root / cfg.manuscript_subdir).as_posix()
        for path in (root / cfg.manuscript_subdir).rglob("*.md")
    )
    lexical = json.loads((out / "scene-lexical.json").read_text(encoding="utf-8"))
    assert sorted(lexical) == scenes
    for row in lexical.values():
        assert row["ok"] is True
        assert set(row) == {"ok", "mattr", "mtld"}


def test_rebuilding_a_snapshot_replaces_the_previous_one(tmp_path: Path):
    root = _novel(tmp_path)
    out = tmp_path / "site"
    write_snapshot(root, out)
    (out / "stale.html").write_text("left over", encoding="utf-8")
    write_snapshot(root, out)
    assert not (out / "stale.html").exists()
    assert (out / "index.html").is_file()


def test_a_folder_that_is_not_a_snapshot_is_never_cleared(tmp_path: Path):
    """--out names a folder that gets emptied; it must be one this made."""
    root = _novel(tmp_path)
    out = tmp_path / "documents"
    out.mkdir()
    (out / "chapter-notes.md").write_text("keep me", encoding="utf-8")
    with pytest.raises(SnapshotError, match="not a Proseview snapshot"):
        write_snapshot(root, out)
    assert (out / "chapter-notes.md").read_text(encoding="utf-8") == "keep me"
    with pytest.raises(SnapshotError, match="inside the repository"):
        write_snapshot(root, root)


def test_the_served_dashboard_is_not_a_snapshot():
    html = build_dashboard(FIXTURE, Config.load(FIXTURE))
    assert "window.PROSEVIEW_STATIC = false" in html


def test_the_snapshot_command_writes_the_site(tmp_path: Path, capsys):
    root = _novel(tmp_path)
    out = tmp_path / "public"
    assert main(["snapshot", "--root", str(root), "--out", str(out)]) == 0
    assert (out / "index.html").is_file()
    assert str(out) in capsys.readouterr().out
