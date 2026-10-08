"""A version is released by tagging it, so what the tag publishes has to agree.

The release workflow builds from ``pyproject.toml`` and makes the GitHub
release notes from that version's section of ``CHANGELOG.md``. These catch the
disagreements before a tag does.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import proseview

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES_SCRIPT = REPO_ROOT / ".github" / "release-notes.sh"


def _packaged_version() -> str:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_the_module_reports_the_packaged_version():
    assert proseview.__version__ == _packaged_version()


def test_the_changelog_describes_the_packaged_version():
    # Work not yet released collects under "Unreleased"; the newest version
    # section is the one a tag publishes.
    headings = [
        line.split()[1]
        for line in (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ") and line.split()[1] != "Unreleased"
    ]
    assert headings, "CHANGELOG.md has no version sections"
    assert headings[0] == _packaged_version(), "the newest changelog section is not the packaged version"


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs a POSIX shell, as the workflow has")
def test_the_release_notes_are_exactly_that_versions_section():
    def notes(version: str) -> str:
        return subprocess.run(
            ["sh", str(NOTES_SCRIPT), version], capture_output=True, text=True, check=True
        ).stdout

    current = notes(_packaged_version())
    assert "### " in current
    assert "\n## " not in current, "the notes ran into the next version's section"
    assert notes("0.0.0-never-released") == ""
