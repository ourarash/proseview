"""Genre-derived MTLD bands, and the manuscript's own median.

Proseview compared every scene against ``mtld_band = (105.0, 130.0)`` -- two
numbers that arrived in the initial commit with nothing behind them. Alice in
Wonderland has a median MTLD of 77.7, so the default badged most of Lewis
Carroll as too repetitive.

Two references replace it. The genre range says whether a book sits anywhere
normal; the manuscript's own median says which scenes are unlike the rest of
*this* book. The second one was already computed and thrown away --
``build_dashboard`` opened with ``del baseline``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import (  # noqa: E402
    DEFAULT_GENRE,
    GENRE_LABELS,
    GENRE_MTLD_BANDS,
    Config,
    ConfigError,
)
from proseview.lexical import MTLD_THRESHOLD  # noqa: E402
from proseview.scenes import (  # noqa: E402
    SceneStats,
    scene_mattr_median,
    scene_mtld_median,
)


def write_config(root: Path, body: str) -> Config:
    (root / ".proseview.yaml").write_text(body, encoding="utf-8")
    return Config.load(root)


# ── The threshold that makes any of this comparable ──────────────────────────

def test_mtld_threshold_is_the_published_one():
    """0.72 is McCarthy & Jarvis (2010).

    It is what makes MTLD length-independent, and therefore what makes a
    published range meaningful against scenes of wildly different sizes. Change
    it and every band in this module stops applying.
    """
    assert MTLD_THRESHOLD == 0.72


# ── Genre selects the band ───────────────────────────────────────────────────

@pytest.mark.parametrize("genre,band", sorted(GENRE_MTLD_BANDS.items()))
def test_each_genre_selects_its_band(tmp_path: Path, genre: str, band):
    cfg = write_config(tmp_path, f"genre: {genre}\n")
    assert cfg.genre == genre
    assert cfg.mtld_band == band


def test_the_default_genre_no_longer_fails_alice(tmp_path: Path):
    """The regression this whole change exists for.

    Alice's median is 77.7. Under the old default of (105, 130) that read as
    too repetitive; under any honest range it does not.
    """
    cfg = Config.load(tmp_path)
    assert cfg.genre == DEFAULT_GENRE
    low, high = cfg.mtld_band
    assert low <= 77.7 <= high


def test_bands_ascend_by_genre():
    """Dialogue-heavy prose scores lower; world-building scores higher.

    The ordering is the part of these ranges that is not controversial, so it
    is the part worth pinning.
    """
    order = ["childrens", "contemporary", "literary", "speculative"]
    lows = [GENRE_MTLD_BANDS[g][0] for g in order]
    assert lows == sorted(lows)
    assert all(GENRE_MTLD_BANDS[g][0] < GENRE_MTLD_BANDS[g][1] for g in order)
    assert set(GENRE_LABELS) == set(GENRE_MTLD_BANDS)


@pytest.mark.parametrize(
    "written,expected",
    [
        ("Literary", "literary"),
        ("  SPECULATIVE  ", "speculative"),
        ("children", "childrens"),
        ("middle grade", "childrens"),
        ("commercial", "contemporary"),
        ("historical", "literary"),
        ("science fiction", "speculative"),
        ("sci_fi", "speculative"),
    ],
)
def test_genre_accepts_the_names_people_actually_write(
    tmp_path: Path, written: str, expected: str
):
    assert write_config(tmp_path, f"genre: {written}\n").genre == expected


def test_an_unknown_genre_is_an_error_not_a_silent_default(tmp_path: Path):
    """Falling back quietly would show a band the writer never chose."""
    with pytest.raises(ConfigError, match="genre"):
        write_config(tmp_path, "genre: cyberpunk-noir\n")


def test_an_explicit_band_still_wins_over_the_genre(tmp_path: Path):
    """Someone who measured their own corpus must not be overruled by a label."""
    cfg = write_config(tmp_path, "genre: childrens\nmtld_band: [70, 90]\n")
    assert cfg.genre == "childrens"
    assert cfg.mtld_band == (70.0, 90.0)


# ── The manuscript's own median ──────────────────────────────────────────────

def _make_scene(mtld: float, mattr: float) -> SceneStats:
    """Build a SceneStats with only the two fields these helpers read."""
    import dataclasses

    values: dict[str, object] = {}
    for f in dataclasses.fields(SceneStats):
        if f.name == "mtld":
            values[f.name] = mtld
        elif f.name == "mattr":
            values[f.name] = mattr
        elif f.type == "str" or f.name in {"chapter", "title", "status", "text", "location"}:
            values[f.name] = ""
        elif f.name == "path":
            values[f.name] = Path("x.md")
        elif f.name == "frontmatter":
            values[f.name] = {}
        elif f.name in {"repetition_examples", "top_dialogue_words", "flavor_words",
                        "todos", "notes"}:
            values[f.name] = ()
        else:
            values[f.name] = 0
    return SceneStats(**values)  # type: ignore[arg-type]


def test_median_is_the_middle_scene():
    scenes = [_make_scene(m, 0.7) for m in (38.4, 77.7, 117.8)]
    assert scene_mtld_median(scenes) == pytest.approx(77.7)


def test_median_ignores_scenes_with_no_lexical_pass():
    """``collect_scene_stats(lexical=False)`` leaves mtld at 0.

    Averaging those in would drag the median toward zero and quietly make every
    real scene look like an outlier.
    """
    scenes = [_make_scene(m, 0.7) for m in (0.0, 0.0, 80.0, 90.0)]
    assert scene_mtld_median(scenes) == pytest.approx(85.0)


def test_medians_of_an_empty_manuscript_do_not_raise():
    assert scene_mtld_median([]) == 0.0
    assert scene_mattr_median([]) == 0.0


# ── End to end, against the demo book ────────────────────────────────────────

def test_the_analysis_payload_carries_both_references():
    """The numbers a reader sees under the MTLD gauge."""
    from proseview.generator import build_analysis_payload

    root = REPO_ROOT / "fixtures" / "demo-book"
    if not root.is_dir():
        pytest.skip("demo book fixture not present")

    lexical = build_analysis_payload(root, Config.load(root))["lexical"]

    assert float(lexical["mtldMedian"]) > 0, "the median must not be discarded again"
    assert lexical["mtldBand"] == list(GENRE_MTLD_BANDS[DEFAULT_GENRE])
    assert lexical["genreLabel"] == GENRE_LABELS[DEFAULT_GENRE]

    # Alice sits inside the contemporary range, which is the whole point.
    low, high = lexical["mtldBand"]
    assert low <= float(lexical["mtldMedian"]) <= high
