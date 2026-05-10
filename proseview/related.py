"""Heuristic related-document matching for scene modals.

The v1 matcher is intentionally simple and local:

- filename contains the chapter folder name
- filename contains one or more scene filename tokens
- file body contains the scene frontmatter title verbatim

Matches are limited to the planning/reference folders surfaced by the product
plan and return a tiny numeric score so later phases can refine ranking
without changing the renderer contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import Config
from .scenes import SceneStats

RELATED_ROOTS = ("plans", "continuity", "outline", "story-bible")
MAX_RELATED = 8

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _iter_file_nodes(nodes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not nodes:
        return []
    out: list[dict[str, Any]] = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if node.get("is_file"):
            out.append(node)
            continue
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(reversed(children))
    return out


def _scene_filename_tokens(scene: SceneStats) -> tuple[str, ...]:
    tokens = []
    for token in _TOKEN_RE.findall(scene.path.stem.lower()):
        if token.isdigit() or len(token) < 3:
            continue
        tokens.append(token)
    return tuple(dict.fromkeys(tokens))


def _is_related_candidate(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in RELATED_ROOTS)


def find_related(scene: SceneStats, cfg: Config, repo_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return up to eight heuristic related-doc matches for ``scene``.

    ``cfg`` is accepted to keep the signature stable with the implementation
    plan; v1 matching uses only the repo tree.
    """
    del cfg

    chapter_token = scene.path.parent.name.lower()
    filename_tokens = _scene_filename_tokens(scene)
    title = scene.title.strip()
    title_lc = title.lower()

    matches: list[dict[str, Any]] = []
    for node in _iter_file_nodes(repo_tree):
        path = str(node.get("path") or "")
        if not path or not _is_related_candidate(path):
            continue

        name = str(node.get("name") or Path(path).name).lower()
        score = 0
        if chapter_token and chapter_token in name:
            score = max(score, 2)
        if filename_tokens and any(token in name for token in filename_tokens):
            score = max(score, 1)
        body = node.get("body")
        if title_lc and isinstance(body, str) and title_lc in body.lower():
            score = max(score, 3)
        if score <= 0:
            continue

        matches.append({
            "path": path,
            "abs_path": node.get("abs_path"),
            "score": score,
        })

    matches.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return matches[:MAX_RELATED]
