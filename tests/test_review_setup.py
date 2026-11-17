from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from proseview.craft import ABSENCE_RULE, KEEP_RULE
from proseview.discuss import ContextError
from proseview.reviews import review_guides, scene_review_contract, selected_review_lanes
from .test_craft_review_context import _manager


@pytest.mark.parametrize(('action', 'ids'), [
    ('quick_critique', ['motivation', 'prose']),
    ('deepen_and_layer', ['subtext', 'emotion']),
    ('craft_mckee', ['want', 'subtext']),
])
def test_review_sends_selected_lanes_full_scenes_and_each_scenes_notes(tmp_path: Path, monkeypatch, action, ids):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.craft_story_context('scene.md', 'SAVED_FIRST_SCENE_CONTEXT')
        manager.craft_story_context('z-next.md', 'OLDER_SECOND_SCENE_CONTEXT')
        manager.submit(
            cid, client_request_id='shared-review', question='', action_id=action,
            action_scope='scenes', scenes=['scene.md', 'z-next.md'], review_lanes=ids,
            review_contexts={'z-next.md': 'CURRENT_SECOND_SCENE_CONTEXT'},
            craft_check_plan=True, custom_instruction='Preserve the quiet ending.',
            include_frontmatter=False, include_adjacent=False,
        )
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        assert 'SAVED_FIRST_SCENE_CONTEXT' in prompt
        assert 'CURRENT_SECOND_SCENE_CONTEXT' in prompt
        assert 'OLDER_SECOND_SCENE_CONTEXT' not in prompt
        assert 'STALE_CHARACTER_MARKER' not in prompt
        assert '   6| She put the key on the table.' in prompt
        assert '   3| UNSELECTED_NEIGHBOR_MARKER' in prompt
        assert 'EVERY selected scene' in prompt
        assert '**Writer-plan gap**' in prompt
        assert 'Preserve the quiet ending.' in prompt
        assert clients[0].turn_params[0]['sandboxPolicy']['type'] == 'readOnly'
        message = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        assert message['context_sent']['check_plan'] is True
        assert 'CURRENT_SECOND_SCENE_CONTEXT' in message['text']
        for lane in selected_review_lanes(action, ids):
            assert lane['summary'] in prompt
    finally:
        manager.close()


@pytest.mark.parametrize('extra', [
    {'review_lanes': []},
    {'review_lanes': 'motivation'},
    {'review_lanes': ['subtext']},  # A valid Deepen lane is not a Quick critique lane.
    {'review_lanes': [False]},
    {'review_contexts': []},
    {'review_contexts': {'z-next.md': 'Unselected context'}},
    {'review_contexts': {'scene.md': 'x' * 8193}},
    {'review_contexts': {'../outside.md': 'Unsafe context'}},
])
def test_review_rejects_invalid_lanes_and_unselected_context(tmp_path: Path, monkeypatch, extra):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='invalid-review', question='', action_id='quick_critique',
                           action_scope='scene', scenes=['scene.md'], **extra)
        assert not clients[0].prompts
    finally:
        manager.close()


def test_guide_and_prompt_share_lane_definitions_and_honor_multiple_selected_lanes():
    for guide in review_guides():
        lanes = selected_review_lanes(guide['id'], [lane['id'] for lane in guide['lanes'][:2]])
        contract = scene_review_contract(guide['id'], lanes, scene_count=2, check_plan=False)
        for lane in guide['lanes'][:2]:
            assert lane['summary'] in contract
            assert lane['spot'] in contract
            assert lane['flat'] and lane['working'] and lane['why'] and lane['caution']
        for lane in guide['lanes'][2:]:
            assert lane['summary'] not in contract
        assert '**Writer-plan gap**' not in contract
        assert 'Only these lanes' in contract
        assert 'EVERY selected scene' in contract


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides()] + [
    'craft_mckee', 'craft_coyne', 'craft_cron', 'craft_snyder', 'craft_king', 'craft_lamott',
])
def test_every_review_card_lists_keeps_apart_and_checks_absence_claims(action):
    lanes = selected_review_lanes(action, None)
    contract = scene_review_contract(action, lanes, scene_count=1, check_plan=False)
    # A phrase that wraps across manuscript lines once led a review to call a
    # set-up joke unseen.
    assert ABSENCE_RULE in contract
    assert (KEEP_RULE in contract) is (action != 'deepen_and_layer')


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides()] + [
    'craft_mckee', 'craft_coyne', 'craft_cron', 'craft_snyder', 'craft_king',
])
@pytest.mark.parametrize('scene_count', [1, 3])
def test_every_review_card_shares_one_findings_cap(action, scene_count):
    lanes = selected_review_lanes(action, None)
    default = scene_review_contract(action, lanes, scene_count=scene_count, check_plan=False)
    assert 'at most 5 ' in default and 'limit, not a target' in default
    assert not re.search(r'\b(three|five)\b[^.]*\b(priorities|findings|opportunities|revisions)\b', default, re.I)
    custom = scene_review_contract(action, lanes, scene_count=scene_count, check_plan=False, max_findings=2)
    assert 'at most 2 ' in custom and 'at most 5 ' not in custom and 'up to 5' not in custom


def test_bird_by_bird_keeps_its_single_assignment():
    lanes = selected_review_lanes('craft_lamott', None)
    contract = scene_review_contract('craft_lamott', lanes, scene_count=1, check_plan=False, max_findings=7)
    assert 'at most 7' not in contract
    assert 'one-assignment format' in contract


@pytest.mark.parametrize('value', [0, 9, True, '3', 2.5])
def test_an_invalid_findings_cap_is_refused_before_a_model_request(tmp_path: Path, monkeypatch, value):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='bad-cap', question='', action_id='quick_critique',
                           action_scope='scene', scenes=['scene.md'], review_max_findings=value)
        assert not clients[0].prompts
    finally:
        manager.close()


def test_the_findings_cap_reaches_the_prompt_receipt_and_context_inspector(tmp_path: Path, monkeypatch):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='cap', question='', action_id='craft_mckee',
                       action_scope='scene', scenes=['scene.md'], review_max_findings=2)
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        assert 'Give at most 2 revision priorities' in clients[0].prompts[0]
        message = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        assert 'Revision priorities: up to 2' in message['text']
        assert message['context_sent']['max_findings'] == 2
    finally:
        manager.close()


@pytest.mark.parametrize('action', ['quick_critique', 'deepen_and_layer', 'craft_king', 'craft_lamott'])
def test_single_scene_neighbor_toggle_supplies_both_sides_consistently(tmp_path: Path, monkeypatch, action):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='neighbors-on', question='', action_id=action,
                       action_scope='scene', scenes=['scene.md'], include_adjacent=True)
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        assert 'Opening of next scene (z-next.md)' in clients[0].prompts[0]
        assert 'UNSELECTED_NEIGHBOR_MARKER' in clients[0].prompts[0]
    finally:
        manager.close()
