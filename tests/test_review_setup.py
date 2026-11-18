from __future__ import annotations

import re
import time
from dataclasses import replace
from pathlib import Path

import pytest

from proseview.config import Config
from proseview.craft import KEEP_RULE, craft_guides, lane_name
from proseview.discuss import ContextError, default_skill_body
from proseview.reviews import review_guides, review_self_check, scene_review_contract, selected_review_lanes
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
            assert lane['brief'] in prompt
            assert (lane['summary'] in prompt) is action.startswith('craft_')
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


@pytest.mark.parametrize('guide', review_guides() + craft_guides(), ids=lambda guide: guide['id'])
def test_guide_and_prompt_share_lane_definitions_and_honor_multiple_selected_lanes(guide):
    action = guide['id']
    lanes = selected_review_lanes(action, [lane['id'] for lane in guide['lanes'][:2]])
    contract = scene_review_contract(action, lanes, scene_count=2, check_plan=False)
    for lane in guide['lanes']:
        selected = lane in lanes
        assert (lane['brief'] in contract) is selected
        assert (lane['summary'] in contract) is (selected and action.startswith('craft_'))
        assert lane['spot'] not in contract
        assert lane['flat'] and lane['working'] and lane['why'] and lane['caution']
    if action.startswith('craft_'):
        assert contract.count(f"Selected book: {guide['book']}\n") == 1
        rows = contract.split('Selected book principles:\n', 1)[1].lstrip()
        assert rows == '\n\n'.join(f"- {lane_name(lane)} — {lane['brief']}\nPrinciple: {lane['summary']}" for lane in lanes)
    assert '**Writer-plan gap**' not in contract
    assert 'Stay within the selected lanes.' in contract
    if action != 'craft_lamott':
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
    assert '**Why:** the specific weakness or missed opportunity, and what the change improves for the reader.' in contract
    assert 'group the connected edits under one finding' in contract
    assert 'write out each replacement or insertion' in contract
    assert 'Stay within the selected lanes.' in contract
    assert 'Report only problems' not in contract
    assert ('For each opportunity' if action == 'deepen_and_layer' else 'For each finding') in contract
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


@pytest.mark.parametrize('action', [guide['id'] for guide in review_guides() + craft_guides()])
@pytest.mark.parametrize('scene_count', [1, 2])
@pytest.mark.parametrize('guide_source', ['builtin', 'file', 'yaml'])
def test_review_self_check_follows_builtin_and_writer_owned_guides(tmp_path, monkeypatch, action, scene_count, guide_source):
    manager, cid, clients, custom_skill = _manager(tmp_path, monkeypatch)
    custom_skill.unlink()
    owned = manager.root / '.proseview/skills' / action / 'SKILL.md'
    body = default_skill_body(action)
    if guide_source == 'file':
        body = 'WRITER_OWNED_GUIDE_MARKER'
        owned.parent.mkdir(parents=True, exist_ok=True)
        owned.write_text(f'---\nname: {action}\n---\n\n{body}\n')
    elif guide_source == 'yaml':
        body = 'WRITER_YAML_GUIDE_MARKER'
        cfg = Config.load(manager.root)
        cfg.with_overrides(discuss=replace(cfg.discuss, skill_prompts=((action, body),))).save(manager.root)
    try:
        manager.submit(cid, client_request_id='final-check', question='', action_id=action,
                       action_scope='scenes', scenes=['scene.md', 'z-next.md'][:scene_count])
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        check = review_self_check(action)
        assert prompt.count('Before returning feedback, check silently:') == 1
        assert prompt.index('Review guide:\n' + body) < prompt.index(check)
        assert prompt.endswith(check)
        assert check.count('\n- ') == (2 if action == 'craft_lamott' else 3)
        assert 'quotations' not in check and 'voice' not in check
        if action == 'craft_lamott':
            assert 'single assignment useful, manageable' in check
            assert 'pasteable edits' not in check and 'configured limit' not in check
        else:
            assert 'retain worthwhile findings within the configured limit' in check
            assert 'complete, pasteable edits' in check
        if guide_source == 'file':
            assert owned.read_text() == f'---\nname: {action}\n---\n\n{body}\n'
        assert clients[0].turn_params[0]['sandboxPolicy']['type'] == 'readOnly'
    finally:
        manager.close()


@pytest.mark.parametrize('action', ['craft_mckee', 'quick_critique', 'comedy_review'])
@pytest.mark.parametrize('scene_count', [1, 3])
def test_big_picture_contract_relaxes_rewrites_and_preserves_lane_focus(action, scene_count):
    all_lanes = selected_review_lanes(action, None)
    wide = scene_review_contract(action, all_lanes, scene_count=scene_count, check_plan=False, big_picture=True)
    assert 'Give high-level feedback' in wide
    assert 'rather than sentence-level polish' in wide
    assert 'When you suggest a concrete rewrite' in wide
    assert 'as text the writer can paste' not in wide
    assert 'Stay within the selected lanes' not in wide
    assert 'Draw freely on the wider structural principles' in wide

    narrowed = scene_review_contract(action, all_lanes[:2], scene_count=scene_count, check_plan=False, big_picture=True)
    assert 'Pay particular attention to the selected lanes:' in narrowed
    assert 'Connect wider structural issues' in narrowed
    assert 'Stay within the selected lanes' not in narrowed


@pytest.mark.parametrize(('action', 'shown'), [
    ('quick_critique', True), ('comedy_review', True), ('craft_mckee', True),
    ('deepen_and_layer', False), ('craft_lamott', False),
])
@pytest.mark.parametrize('big_picture', [None, True])
def test_big_picture_choice_reaches_prompt_receipt_and_context_inspector(tmp_path: Path, monkeypatch, action, shown, big_picture):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='bp', question='', action_id=action,
                       action_scope='scene', scenes=['scene.md'], review_big_picture=big_picture)
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        message = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        if not shown:
            assert 'Format: big-picture critique' not in message['text']
            assert message['context_sent']['big_picture'] is None
            return
        expected = bool(big_picture)
        assert ('Give high-level feedback' in prompt) is expected
        assert ('rather than sentence polish?' in prompt) is expected
        assert ('Format: big-picture critique (Before/After optional)' in message['text']) is expected
        assert message['context_sent']['big_picture'] is expected
    finally:
        manager.close()


@pytest.mark.parametrize('value', ['on', 1, 'true'])
def test_an_invalid_big_picture_choice_is_refused_before_a_model_request(tmp_path: Path, monkeypatch, value):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='bad-bp', question='', action_id='craft_mckee',
                           action_scope='scene', scenes=['scene.md'], review_big_picture=value)
        assert not clients[0].prompts
    finally:
        manager.close()
