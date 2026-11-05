"""Tests for Visual Beat Map generation, caching, source anchoring, and API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proseview.beatmap import (
    BEATMAP_SCHEMA_VERSION,
    compute_scene_hash,
    format_beatmap_for_context,
    generate_scene_beatmap,
    get_scene_beatmap,
    heuristic_beatmap_extractor,
    load_cached_beatmap,
    patch_scene_beatmap,
    save_cached_beatmap,
    validate_beatmap_anchors,
)
from proseview.config import Config


SAMPLE_SCENE = """---
title: The confrontation
characters: [Alice, Ben]
---

# The confrontation

Alice pushed the cup towards him. A little tea spilled over the edge, spreading into the cloth.

"It's only paper, Ben," she said quietly.

"Then why are your hands shaking?" Ben asked.

She withdrew her fingers and set the silver spoon down. The room felt suddenly cold.

"I burned it at daybreak," she whispered.
"""


def test_compute_scene_hash_is_deterministic():
    h1 = compute_scene_hash("hello world")
    h2 = compute_scene_hash("hello world")
    h3 = compute_scene_hash("hello world!")
    assert h1.startswith("sha256:")
    assert h1 == h2
    assert h1 != h3


def test_heuristic_beatmap_extractor_produces_valid_structure():
    beatmap = heuristic_beatmap_extractor("ch01/scene1.md", SAMPLE_SCENE, agent="claude")

    assert beatmap["schema_version"] == BEATMAP_SCHEMA_VERSION
    assert beatmap["scene_path"] == "ch01/scene1.md"
    assert beatmap["agent_used"] == "claude"
    assert "beats" in beatmap
    assert len(beatmap["beats"]) >= 3

    # Check beats ordering and tension
    for i, beat in enumerate(beatmap["beats"]):
        assert beat["order"] == i + 1
        assert 0 <= beat["estimated_tension"] <= 100
        assert isinstance(beat["is_turning_point"], bool)
        assert beat["moments"]

    # Check moments numbering and verbatim quotes
    all_moments = []
    for beat in beatmap["beats"]:
        for m in beat["moments"]:
            all_moments.append(m)

    assert len(all_moments) >= 4
    for idx, m in enumerate(all_moments):
        assert m["order"] == idx + 1
        assert m["type"] in {"dialogue", "action", "silent_reaction", "interiority"}
        assert m.get("valid_anchor") is True
        quote = m["source_ref"]["exact_quote"]
        assert quote
        # Quote must exist in sample scene
        assert quote.replace('"', '') in SAMPLE_SCENE.replace('"', '').replace('“', '').replace('”', '')


def test_validate_beatmap_anchors_and_stale_detection():
    beatmap = heuristic_beatmap_extractor("ch01/scene1.md", SAMPLE_SCENE)
    assert beatmap["stale"] is False

    # Validating against identical text remains unstale
    v1 = validate_beatmap_anchors(beatmap, SAMPLE_SCENE)
    assert v1["stale"] is False

    # Modifying scene text causes stale to become True
    modified_scene = SAMPLE_SCENE + "\n\nBen walked out into the corridor."
    v2 = validate_beatmap_anchors(beatmap, modified_scene)
    assert v2["stale"] is True


def test_caching_roundtrip(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # Initial state: no map
    res1 = get_scene_beatmap(tmp_path, scene_rel)
    assert res1["ok"] is True
    assert res1["has_map"] is False

    # Generate map
    res2 = generate_scene_beatmap(tmp_path, scene_rel, agent="claude")
    assert res2["ok"] is True
    assert res2["has_map"] is True
    assert res2["stale"] is False
    assert len(res2["beatmap"]["beats"]) >= 3

    # Persistent file on disk
    cached = load_cached_beatmap(tmp_path, scene_rel)
    assert cached is not None
    assert cached["scene_path"] == scene_rel

    # Retrieve again: should be present and clean
    res3 = get_scene_beatmap(tmp_path, scene_rel)
    assert res3["ok"] is True
    assert res3["has_map"] is True
    assert res3["stale"] is False

    # Modify file on disk: retrieve should report stale
    scene_file.write_text(SAMPLE_SCENE + "\n\nAn added sentence.\n", encoding="utf-8")
    res4 = get_scene_beatmap(tmp_path, scene_rel)
    assert res4["ok"] is True
    assert res4["has_map"] is True
    assert res4["stale"] is True


def test_server_beatmap_endpoints(tmp_path: Path):
    from proseview.server import _Handler

    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    sent: list[tuple[dict, int]] = []

    handler = _Handler.__new__(_Handler)
    handler.repo_root = str(tmp_path)
    handler._is_local_request = lambda: True
    handler._authorize_mutation = lambda: True
    handler._send_json = lambda payload, status=200: sent.append((payload, status))

    # 1. GET before generate
    handler.path = f"/api/scene/beatmap?path={scene_rel}"
    handler.do_GET()
    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["has_map"] is False

    # 2. POST generate
    handler.path = "/api/scene/beatmap/generate"
    handler._read_json_limited = lambda: {"path": scene_rel, "agent": "claude"}
    handler.do_POST()
    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["has_map"] is True
    assert payload["stale"] is False

    # 3. GET after generate
    handler.path = f"/api/scene/beatmap?path={scene_rel}"
    handler.do_GET()
    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["has_map"] is True
    assert payload["stale"] is False

    # 4. POST patch beat 2
    handler.path = "/api/scene/beatmap/patch"
    handler._read_json_limited = lambda: {
        "path": scene_rel,
        "beat_order": 2,
        "patch": {"estimated_tension": 85, "title": "The Confrontation"},
    }
    handler.do_POST()
    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["beatmap"]["beats"][1]["estimated_tension"] == 85
    assert payload["beatmap"]["beats"][1]["title"] == "The Confrontation"


def test_patch_scene_beatmap_operations(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # Generate initial beat map
    generate_scene_beatmap(tmp_path, scene_rel)

    # 1. Single beat patch with clamping
    patch_res = patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {"beat_order": 1, "patch": {"estimated_tension": 150, "title": "Opening Gambit", "is_turning_point": True}},
    )
    assert patch_res["ok"] is True
    beat1 = patch_res["beatmap"]["beats"][0]
    assert beat1["estimated_tension"] == 100  # Clamped to 100
    assert beat1["title"] == "Opening Gambit"
    assert beat1["is_turning_point"] is True

    # 2. Multi-beat batch patch
    batch_res = patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {
            "beats": [
                {"order": 1, "estimated_tension": -10},
                {"order": 2, "estimated_tension": 75, "summary": "Ben questions Alice."},
            ]
        },
    )
    assert batch_res["ok"] is True
    b1 = batch_res["beatmap"]["beats"][0]
    b2 = batch_res["beatmap"]["beats"][1]
    assert b1["estimated_tension"] == 0  # Clamped to 0
    assert b2["estimated_tension"] == 75
    assert b2["summary"] == "Ben questions Alice."

    # 3. Full structural replacement
    replace_res = patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {
            "replace": True,
            "overall_scene_summary": "Replaced entire structure.",
            "beats": [
                {
                    "title": "Custom Beat 1",
                    "summary": "Summary 1",
                    "start_paragraph": 0,
                    "end_paragraph": 1,
                    "estimated_tension": 40,
                    "moments": [],
                },
                {
                    "title": "Custom Beat 2",
                    "summary": "Summary 2",
                    "start_paragraph": 2,
                    "end_paragraph": 4,
                    "estimated_tension": 90,
                    "is_turning_point": True,
                    "moments": [],
                },
            ],
        },
    )
    assert replace_res["ok"] is True
    assert len(replace_res["beatmap"]["beats"]) == 2
    assert replace_res["beatmap"]["beats"][0]["title"] == "Custom Beat 1"
    assert replace_res["beatmap"]["beats"][1]["estimated_tension"] == 90
    assert replace_res["beatmap"]["overall_scene_summary"] == "Replaced entire structure."


def test_guidance_in_generate_scene_beatmap(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    res = generate_scene_beatmap(tmp_path, scene_rel, guidance="Please restructure into 4 beats.")
    assert res["ok"] is True
    assert len(res["beatmap"]["beats"]) == 4


def test_format_beatmap_for_context(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    gen = generate_scene_beatmap(tmp_path, scene_rel)
    bm_text = format_beatmap_for_context(gen["beatmap"])

    assert "BEGIN SCENE BEAT MAP" in bm_text
    assert "END SCENE BEAT MAP" in bm_text
    assert "Scene Path: ch01/01-test.md" in bm_text
    assert "proseview:beatmap-patch" in bm_text
    assert "proseview:beatmap-recreate" in bm_text


def test_discuss_context_builder_includes_beatmap(tmp_path: Path):
    from proseview.discuss import ContextBuilder

    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # Generate beat map
    generate_scene_beatmap(tmp_path, scene_rel)

    builder = ContextBuilder(tmp_path)
    bundle = builder.build_mentions(
        {"kind": "scene", "path": scene_rel},
        "What is the dramatic peak in this scene?",
    )
    assert "BEGIN SCENE BEAT MAP" in bundle.prompt
    assert "END SCENE BEAT MAP" in bundle.prompt

    # Now patch the beat map to have a distinct title
    patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {"beat_order": 2, "patch": {"title": "The Grand Crisis"}},
    )

    # Next turn immediately reads the updated beat map
    bundle2 = builder.build_mentions(
        {"kind": "scene", "path": scene_rel},
        "How is the scene structured?",
    )
    assert "The Grand Crisis" in bundle2.prompt


def test_moment_type_schema_validation_and_xss_protection():
    raw_text = "Alice said hello. Bob nodded."
    malformed_map = {
        "analyzed_revision_hash": "testhash",
        "beats": [
            {
                "order": 1,
                "title": "<script>alert('xss')</script>",
                "summary": "Test summary",
                "moments": [
                    {
                        "order": 1,
                        "type": '"><script>alert("xss")</script>',
                        "text": "Dangerous moment",
                        "source_ref": {"paragraph": 0, "exact_quote": "Alice said hello."},
                    },
                    {
                        "order": 2,
                        "type": "DIALOGUE",  # Uppercase
                        "text": "Dialogue moment",
                        "source_ref": {"paragraph": 0, "exact_quote": "Bob nodded."},
                    },
                    {
                        "order": 3,
                        "type": "custom_weird_type_with_symbols!@#",
                        "text": "Weird moment",
                        "source_ref": {"paragraph": 0, "exact_quote": "Alice said hello."},
                    },
                ],
            }
        ],
    }
    validated = validate_beatmap_anchors(malformed_map, raw_text)
    moments = validated["beats"][0]["moments"]
    # Malicious script type coerced to 'action'
    assert moments[0]["type"] == "action"
    # Case normalized
    assert moments[1]["type"] == "dialogue"
    # Unknown type coerced to 'action'
    assert moments[2]["type"] == "action"


def test_agent_failure_does_not_overwrite_saved_beatmap(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # 1. Initial valid beatmap saved
    initial_res = generate_scene_beatmap(tmp_path, scene_rel)
    assert initial_res["ok"] is True
    initial_beat_title = initial_res["beatmap"]["beats"][0]["title"]

    # 2. Mock a DiscussManager that fails during extraction
    class FailingClient:
        def request(self, method, params):
            if method == "thread/start":
                return {"thread": {"id": "test-thread"}}
            if method == "turn/start":
                raise RuntimeError("CLI failed with out of memory")
            return {}

    class FailingDiscussManager:
        _one_offs = {}

        def _resolve_runner(self, agent):
            return object()

        def _client_for(self, agent):
            return FailingClient()

        def _thread_key(self, agent, thread_id):
            return f"{agent}:{thread_id}"

    # 3. Attempt generation with failing agent: MUST raise and NOT overwrite
    import pytest
    with pytest.raises(RuntimeError, match="CLI failed"):
        generate_scene_beatmap(
            tmp_path,
            scene_rel,
            agent="claude",
            discuss_manager=FailingDiscussManager(),
        )

    # 4. Verify disk cache was NOT overwritten
    cached = load_cached_beatmap(tmp_path, scene_rel)
    assert cached is not None
    assert cached["beats"][0]["title"] == initial_beat_title


def test_patch_scene_beatmap_revision_conflict(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    gen = generate_scene_beatmap(tmp_path, scene_rel)
    rev_hash = gen["beatmap"]["analyzed_revision_hash"]

    # Patch with matching expected_revision succeeds
    res = patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {"beat_order": 1, "expected_revision": rev_hash, "patch": {"title": "Updated Title"}},
    )
    assert res["ok"] is True

    # Patch with conflicting expected_revision raises ValueError
    import pytest
    with pytest.raises(ValueError, match="revision conflict"):
        patch_scene_beatmap(
            tmp_path,
            scene_rel,
            {"beat_order": 1, "expected_revision": "old_hash_12345", "patch": {"title": "Conflict Title"}},
        )


def test_edits_during_generation_mark_beatmap_stale(tmp_path: Path, monkeypatch):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # Patch extract_beatmap_with_agent to simulate scene edit mid-generation
    import proseview.beatmap as bm_module
    original_extract = bm_module.extract_beatmap_with_agent

    def fake_extract(*args, **kwargs):
        # User edits scene during generation
        scene_file.write_text(SAMPLE_SCENE + "\n\nAn unexpected edit occurred during generation!\n", encoding="utf-8")
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(bm_module, "extract_beatmap_with_agent", fake_extract)

    res = generate_scene_beatmap(tmp_path, scene_rel)
    assert res["ok"] is True
    # The returned beatmap MUST be reported as stale: True because file changed while generating
    assert res["stale"] is True


def test_map_version_prevents_old_proposal_on_recreated_map(tmp_path: Path):
    scene_rel = "ch01/01-test.md"
    scene_file = tmp_path / "manuscript" / scene_rel
    scene_file.parent.mkdir(parents=True)
    scene_file.write_text(SAMPLE_SCENE, encoding="utf-8")

    # 1. Generate initial map
    gen1 = generate_scene_beatmap(tmp_path, scene_rel)
    ver1 = gen1["beatmap"]["map_version"]
    assert ver1.startswith("bm_")

    # 2. Re-create map without changing manuscript text (same hash, different map_version)
    gen2 = generate_scene_beatmap(tmp_path, scene_rel)
    ver2 = gen2["beatmap"]["map_version"]
    assert ver2 != ver1
    assert gen1["beatmap"]["analyzed_revision_hash"] == gen2["beatmap"]["analyzed_revision_hash"]

    # 3. Old proposal using ver1 MUST be rejected with a version conflict
    with pytest.raises(ValueError, match="version conflict"):
        patch_scene_beatmap(
            tmp_path,
            scene_rel,
            {"beat_order": 1, "expected_map_version": ver1, "patch": {"title": "Stale proposal"}},
        )

    # 4. Proposal using current ver2 succeeds
    res = patch_scene_beatmap(
        tmp_path,
        scene_rel,
        {"beat_order": 1, "expected_map_version": ver2, "patch": {"title": "Fresh proposal"}},
    )
    assert res["ok"] is True
    assert res["beatmap"]["map_version"] != ver2


def test_validate_beatmap_anchors_sets_both_flags_and_sanitizes_numbers():
    malformed_map = {
        "schema_version": BEATMAP_SCHEMA_VERSION,
        "analyzed_revision_hash": compute_scene_hash(SAMPLE_SCENE),
        "beats": [
            {
                "order": '<script>alert("beat")</script>',
                "title": "Opening",
                "moments": [
                    {
                        "order": "42",
                        "type": "dialogue",
                        "speaker": "Alice",
                        "text": "It is only paper",
                        "source_ref": {
                            "paragraph": 1,
                            "exact_quote": "It's only paper, Ben",
                        },
                    },
                    {
                        "order": "43",
                        "type": "action",
                        "text": "Non-existent text",
                        "source_ref": {
                            "paragraph": 1,
                            "exact_quote": "Completely missing quote from scene",
                        },
                    },
                ],
            }
        ],
    }

    validated = validate_beatmap_anchors(malformed_map, SAMPLE_SCENE)
    beat = validated["beats"][0]
    # Order sanitized to numeric integer
    assert isinstance(beat["order"], int)

    # Valid moment anchor sets both moment.valid_anchor and source_ref.valid_anchor to True
    m1 = beat["moments"][0]
    assert isinstance(m1["order"], int)
    assert m1["order"] == 42
    assert m1["valid_anchor"] is True
    assert m1["source_ref"]["valid_anchor"] is True

    # Invalid moment anchor sets both to False
    m2 = beat["moments"][1]
    assert m2["valid_anchor"] is False
    assert m2["source_ref"]["valid_anchor"] is False


def test_format_beatmap_for_context_includes_stale_warning_and_rubric():
    from proseview.beatmap import build_beatmap_prompt

    # Prompt includes Dramatic Tension rubric
    prompt = build_beatmap_prompt(SAMPLE_SCENE, "ch01/01-test.md")
    assert "estimated_tension: integer between 0 and 100" in prompt
    assert "0-25: Low" in prompt
    assert "76-100: Peak" in prompt

    # Stale beat map formatted context includes OUTDATED warning and UNVERIFIED tags
    bm = {
        "scene_path": "ch01/01-test.md",
        "map_version": "bm_test_123",
        "stale": True,
        "beats": [
            {
                "order": 1,
                "title": "First Beat",
                "estimated_tension": 40,
                "start_paragraph": 0,
                "end_paragraph": 1,
                "moments": [
                    {
                        "order": 1,
                        "type": "dialogue",
                        "speaker": "Alice",
                        "text": "Hello",
                        "valid_anchor": False,
                        "source_ref": {"paragraph": 0, "valid_anchor": False},
                    }
                ],
            }
        ],
    }
    ctx = format_beatmap_for_context(bm)
    assert "Map Version: bm_test_123" in ctx
    assert "Status: OUTDATED (Manuscript edited since map was created)" in ctx
    assert "[UNVERIFIED: Anchor quote missing/changed in manuscript]" in ctx
