"""The empty-frontmatter scaffold writer.

The Scene tab is driven entirely by frontmatter, and a manuscript written
without it -- an Obsidian vault, an imported draft -- has none. The panel now
offers to write the block rather than only describing it.

Every key is written blank, and that is the whole design. A guessed
``where: The riverbank`` or ``characters: [Alice]`` would read exactly like
something the writer typed, so a wrong guess becomes a wrong fact inside their
manuscript. Filling the values in belongs to a Codex skill, where a proposal is
reviewed before it lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.scenes import split_frontmatter  # noqa: E402
from proseview.server import (  # noqa: E402
    FRONTMATTER_SCAFFOLD_FIELDS,
    _FileConflictError,
    _FrontmatterExistsError,
    add_frontmatter_scaffold,
)

BARE = """\
# The Long Way Round

The shop was shut by the time she reached it.

She waited on the step anyway.
"""


@pytest.fixture()
def bare_scene(tmp_path: Path) -> Path:
    path = tmp_path / "04-bare.md"
    path.write_text(BARE, encoding="utf-8")
    return path


def test_scaffold_is_prepended_and_parses_as_frontmatter(bare_scene: Path):
    add_frontmatter_scaffold(str(bare_scene))
    raw = bare_scene.read_text(encoding="utf-8")

    assert raw.startswith("---\n")
    fm, body = split_frontmatter(raw)
    assert isinstance(fm, dict)
    assert body.lstrip().startswith("# The Long Way Round")


def test_every_scaffold_key_is_written_empty(bare_scene: Path):
    """The keys are a prompt, not an answer. Nothing may be guessed."""
    add_frontmatter_scaffold(str(bare_scene))
    fm, _body = split_frontmatter(bare_scene.read_text(encoding="utf-8"))

    assert set(fm) == set(FRONTMATTER_SCAFFOLD_FIELDS)
    for key, value in fm.items():
        assert value in (None, "", [], {}), f"{key} was pre-filled with {value!r}"


def test_the_prose_is_untouched(bare_scene: Path):
    before = bare_scene.read_text(encoding="utf-8")
    add_frontmatter_scaffold(str(bare_scene))
    _fm, body = split_frontmatter(bare_scene.read_text(encoding="utf-8"))

    assert body.strip() == before.strip()


def test_refuses_a_scene_that_already_has_frontmatter(tmp_path: Path):
    """Never clobber a block someone is already using."""
    path = tmp_path / "01-opening.md"
    original = "---\ntitle: Opening\ngoal: Something real\n---\n\n# Opening\n\nProse.\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(_FrontmatterExistsError, match="already has"):
        add_frontmatter_scaffold(str(path))
    assert path.read_text(encoding="utf-8") == original


def test_refuses_when_the_file_changed_since_the_page_loaded(bare_scene: Path):
    """Same mtime guard as every other manuscript writer."""
    stale = bare_scene.stat().st_mtime - 100
    with pytest.raises(_FileConflictError, match="changed on disk"):
        add_frontmatter_scaffold(str(bare_scene), stale)
    assert not bare_scene.read_text(encoding="utf-8").startswith("---")


def test_accepts_the_current_mtime(bare_scene: Path):
    add_frontmatter_scaffold(str(bare_scene), bare_scene.stat().st_mtime)
    assert bare_scene.read_text(encoding="utf-8").startswith("---\n")


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        add_frontmatter_scaffold(str(tmp_path / "nope.md"))


def test_a_utf8_bom_file_is_not_double_wrapped(tmp_path: Path):
    """``read_repo_text`` strips the BOM; the guard has to see through it too."""
    path = tmp_path / "bom.md"
    path.write_text(BARE, encoding="utf-8-sig")
    add_frontmatter_scaffold(str(path))

    fm, body = split_frontmatter(path.read_text(encoding="utf-8-sig"))
    assert set(fm) == set(FRONTMATTER_SCAFFOLD_FIELDS)
    assert "The Long Way Round" in body


def test_a_bom_file_that_already_has_frontmatter_is_refused(tmp_path: Path):
    path = tmp_path / "bom-fm.md"
    path.write_text("---\ntitle: Opening\n---\n\n# Opening\n", encoding="utf-8-sig")
    with pytest.raises(_FrontmatterExistsError):
        add_frontmatter_scaffold(str(path))


def test_the_write_is_atomic(bare_scene: Path, monkeypatch: pytest.MonkeyPatch):
    """A failure mid-write must not leave a truncated manuscript behind."""
    import proseview.server as server

    original = bare_scene.read_text(encoding="utf-8")

    def boom(_path: Path, _text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(server, "_atomic_write_text", boom)
    with pytest.raises(OSError):
        add_frontmatter_scaffold(str(bare_scene))

    assert bare_scene.read_text(encoding="utf-8") == original
