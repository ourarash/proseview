from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.related import find_related  # noqa: E402
from proseview.repo import build_tree  # noqa: E402
from proseview.scenes import collect_scene_stats  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-repo"


def test_find_related_returns_title_match_from_plan_file(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    plan = repo / "plans" / "opening-ledger-notes.md"
    plan.write_text(
        "# Opening Ledger Notes\n\nThis note covers Opening Ledger in detail.\n",
        encoding="utf-8",
    )

    cfg = Config.load(repo)
    tree = build_tree(repo, cfg)
    scene = next(s for s in collect_scene_stats(repo, cfg.manuscript_subdir)
                 if s.path.as_posix() == "manuscript/ch01/01-opening.md")

    related = find_related(scene, cfg, tree)

    assert related
    assert related[0]["path"] == "plans/opening-ledger-notes.md"
    assert related[0]["score"] == 3


def test_find_related_returns_empty_list_for_scene_without_matches():
    cfg = Config.load(FIXTURE)
    tree = build_tree(FIXTURE, cfg)
    scene = next(s for s in collect_scene_stats(FIXTURE, cfg.manuscript_subdir)
                 if s.path.as_posix() == "manuscript/ch02/02-night.md")

    assert find_related(scene, cfg, tree) == []
