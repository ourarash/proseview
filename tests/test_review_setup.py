from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from proseview.craft import KEEP_RULE
from proseview.discuss import ContextError, default_skill_body
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
        assert 'how the selection works as a whole' in prompt
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
        assert 'Report only problems in these lanes' in contract
        assert 'how the selection works as a whole' in contract


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides()] + [
    'craft_mckee', 'craft_coyne', 'craft_cron', 'craft_snyder', 'craft_king', 'craft_lamott',
])
def test_every_review_card_checks_absence_claims_and_lists_keeps_only_when_asked(action):
    lanes = selected_review_lanes(action, None)
    default = scene_review_contract(action, lanes, scene_count=1, check_plan=False)
    keep = scene_review_contract(action, lanes, scene_count=1, check_plan=False, include_keep=True)
    no_keep = "Don't add a section on what works."
    # A phrase that wraps across manuscript lines once led a review to call a
    # set-up joke unseen.
    if action != 'craft_lamott':
        assert 'search for one distinctive word' in default
    assert 'Mark any new story fact as a possibility' in default
    if action == 'craft_lamott':
        # Its keep/one-assignment format is the review itself.
        assert KEEP_RULE in default and no_keep not in default
    elif action == 'deepen_and_layer':
        assert KEEP_RULE not in keep
    else:
        assert KEEP_RULE not in default and no_keep in default
        assert KEEP_RULE in keep and no_keep not in keep


@pytest.mark.parametrize(('action', 'shown'), [
    ('quick_critique', True), ('comedy_review', True), ('craft_mckee', True),
    ('deepen_and_layer', False), ('craft_lamott', False),
])
@pytest.mark.parametrize('include_keep', [None, True])
def test_the_keep_choice_reaches_the_prompt_receipt_and_context_inspector(tmp_path: Path, monkeypatch, action, shown, include_keep):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='keep', question='', action_id=action,
                       action_scope='scene', scenes=['scene.md'], review_include_keep=include_keep)
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        message = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        if not shown:
            assert 'Keep:' not in message['text']
            assert message['context_sent']['include_keep'] is None
            return
        assert (KEEP_RULE in prompt) is bool(include_keep)
        assert ('Keep: list what to preserve' if include_keep else 'Keep: off') in message['text']
        assert message['context_sent']['include_keep'] is bool(include_keep)
    finally:
        manager.close()


@pytest.mark.parametrize('value', ['on', 1, 'true'])
def test_an_invalid_keep_choice_is_refused_before_a_model_request(tmp_path: Path, monkeypatch, value):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='bad-keep', question='', action_id='quick_critique',
                           action_scope='scene', scenes=['scene.md'], review_include_keep=value)
        assert not clients[0].prompts
    finally:
        manager.close()


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides()] + [
    'craft_mckee', 'craft_coyne', 'craft_cron', 'craft_snyder', 'craft_king',
])
@pytest.mark.parametrize('scene_count', [1, 3])
def test_every_review_card_shares_one_findings_cap(action, scene_count):
    lanes = selected_review_lanes(action, None)
    default = scene_review_contract(action, lanes, scene_count=scene_count, check_plan=False)
    assert 'Give up to 5, most important first.' in default
    assert not re.search(r'\b(three|five)\b[^.]*\b(priorities|findings|opportunities|revisions)\b', default, re.I)
    custom = scene_review_contract(action, lanes, scene_count=scene_count, check_plan=False, max_findings=2)
    assert 'Give up to 2, most important first.' in custom and 'up to 5' not in custom


def test_bird_by_bird_keeps_its_single_assignment():
    lanes = selected_review_lanes('craft_lamott', None)
    contract = scene_review_contract('craft_lamott', lanes, scene_count=1, check_plan=False, max_findings=7)
    assert 'up to 7' not in contract
    assert 'one-assignment format' in contract


@pytest.mark.parametrize('value', [0, 21, True, '3', 2.5])
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
        assert 'Give up to 2, most important first.' in clients[0].prompts[0]
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


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides()] + [
    'craft_mckee', 'craft_coyne', 'craft_cron', 'craft_snyder', 'craft_king',
])
@pytest.mark.parametrize('scene_count', [1, 8])
def test_every_review_card_asks_for_pasteable_fixes_in_the_format_the_app_reads(action, scene_count):
    lanes = selected_review_lanes(action, None)
    contract = scene_review_contract(action, lanes, scene_count=scene_count, check_plan=False)
    # The citation checker reads a quote's link from the line below it; the
    # renderer labels a rewrite from its "Replace [link]:" lead-in.
    for part in ('**Lane: <name> — <why>**', '**Before:** on its own line', 'with its link on the line below it',
                 '**Why:**', '**After:** Replace [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18):',
                 "the quoted scene's own file name",
                 'in a plain blockquote, ready to paste', '**After:** Insert after', 'this format governs the output'):
        assert part in contract
    # Without this, reviews listed only trims and rewordings.
    assert ('how the selection works as a whole' if scene_count > 1 else 'how the scene works as a whole') in contract
    # A review got short and minor when most of its rules said what not to
    # report. None of that wording may come back in one branch.
    for removed in ('Zero necessary revisions', 'quota', 'limit, not a target', 'marginal', 'Book-based reading',
                    'Scene notes', 'smallest complete passage', 'optional replacement', 'beat sequence'):
        assert removed not in contract
    if action != 'comedy_review':  # Its comic guidance is reviewed separately.
        assert len(contract.split('Selected lanes:')[0].split()) < 330


def test_the_contract_comes_before_the_card_skill(tmp_path: Path, monkeypatch):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='order', question='', action_id='quick_critique',
                       action_scope='scene', scenes=['scene.md'])
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        divider = prompt.index('Scene review instructions:')
        contract = prompt.index('this format governs the output')
        skill = prompt.index(default_skill_body('quick_critique').splitlines()[0])
        assert divider < contract < prompt.index('Review guide:') < skill
    finally:
        manager.close()
