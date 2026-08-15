"""Scaling characteristics of the dashboard build at book length.

``fixtures/demo-repo`` is four scenes, so every other test in the suite runs
against a corpus small enough to hide cost. These tests build a synthetic 90k
word novel and assert on the two things that actually degrade with size: how
long the build takes, and how much the page weighs.

They are regression guards, not targets. The thresholds sit just above measured
behaviour so a change for the worse fails loudly, while the numbers themselves
are printed for whoever is looking.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import generator  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.scenes import collect_scene_stats  # noqa: E402
from tests.e2e.bookgen import build_book  # noqa: E402


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory):
    """A full-length novel: 30 chapters, 300 scenes, ~98k words."""
    root = tmp_path_factory.mktemp("novel")
    return build_book(root)


def _manuscript_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*.md"))


def test_the_generated_book_is_actually_book_shaped(book):
    assert book.scenes == 300
    assert 85_000 < book.words < 110_000, f"expected a novel-length corpus, got {book.words} words"

    scenes = collect_scene_stats(book.root, "manuscript")
    assert len(scenes) == book.scenes, "every generated scene must be indexed"


def test_dashboard_builds_at_book_length(book):
    start = time.perf_counter()
    html = generator.build_dashboard(book.root, Config.load(book.root))
    elapsed = time.perf_counter() - start

    print(f"\nbuild_dashboard: {elapsed:.2f}s for {book.scenes} scenes / {book.words} words")
    assert html
    assert elapsed < 10.0, f"dashboard build took {elapsed:.2f}s at book length"


def test_build_time_stays_roughly_linear_in_scene_count(tmp_path_factory):
    """Catch an accidental O(n^2) in the analytics.

    Character co-occurrence and per-scene comparisons are the tempting places to
    write one, and at four scenes a quadratic is invisible.
    """
    small_root = tmp_path_factory.mktemp("small")
    large_root = tmp_path_factory.mktemp("large")
    small = build_book(small_root, chapters=10)
    large = build_book(large_root, chapters=30)

    def build_seconds(root: Path) -> float:
        start = time.perf_counter()
        generator.build_dashboard(root, Config.load(root))
        return time.perf_counter() - start

    small_s = build_seconds(small.root)
    large_s = build_seconds(large.root)
    ratio = large_s / small_s

    print(
        f"\n{small.scenes} scenes {small_s:.2f}s -> {large.scenes} scenes {large_s:.2f}s "
        f"(3x the scenes, {ratio:.1f}x the time)"
    )
    # Linear would be ~3x. Quadratic would be ~9x. Allow generous headroom for
    # timing noise on a loaded CI box while still failing on a quadratic.
    assert ratio < 6.0, f"build time grew {ratio:.1f}x for 3x the scenes; suspect superlinear work"


def test_page_weight_is_dominated_by_the_inlined_manuscript(book):
    """Document where the payload goes, and fail if it gets worse.

    The whole manuscript is embedded in the page as a JSON string literal, which
    the browser must download and parse on every load and every live reload. At
    book length that is several megabytes of the total, and JSON escaping makes
    it multiples of the manuscript's size on disk.

    This test does not claim that is wrong -- it makes the cost visible and
    pins it, so a change that inflates it further does not land unnoticed.
    """
    html = generator.build_dashboard(book.root, Config.load(book.root))
    on_disk = _manuscript_bytes(book.root)

    match = re.search(r"let contents = JSON\.parse\(", html)
    assert match, "the embedded-contents payload moved; update this guard"
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S)
    contents_script = max(scripts, key=len)

    ratio = len(html) / on_disk
    print(
        f"\nmanuscript on disk {on_disk / 1e6:.2f} MB -> page {len(html) / 1e6:.2f} MB "
        f"({ratio:.1f}x), largest script {len(contents_script) / 1e6:.2f} MB"
    )

    assert ratio < 8.0, (
        f"the dashboard now ships {ratio:.1f}x the manuscript's bytes; "
        "the inlined contents payload has grown"
    )
