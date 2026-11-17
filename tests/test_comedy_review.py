from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from proseview.config import Config
from proseview.discuss import ContextError, DiscussManager, action_instruction, default_skill_body
from proseview.reviews import comedy_review_options, review_guide, scene_review_contract, selected_review_lanes
from .test_craft_review_context import _manager
from .transport_fakes import CodexFakeClient


def wait_prompt(clients):
    deadline = time.monotonic() + 3
    while not clients[0].prompts and time.monotonic() < deadline:
        time.sleep(.01)
    assert clients[0].prompts
    return clients[0].prompts[0]


@pytest.mark.parametrize(('styles', 'goals'), [
    ([], None), (['dark', 'sarcastic'], ['strengthen', 'explore']),
    (['deadpan'], ['strengthen']), ([], ['explore']),
])
def test_comedy_request_honors_lanes_goal_styles_context_and_read_only_scope(tmp_path, monkeypatch, styles, goals):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        manager.craft_story_context('z-next.md', 'The character uses formal language to cope with fear.')
        manager.submit(
            cid, client_request_id='comedy-options', question='', action_id='comedy_review',
            action_scope='scenes', scenes=['scene.md', 'z-next.md'],
            review_lanes=['truth_pain', 'deadpan_subtext'], comedy_styles=styles, comedy_goals=goals,
            include_frontmatter=False, include_adjacent=False,
            custom_instruction='Keep the narrator affectionate toward the family.',
        )
        prompt = wait_prompt(clients)
        selected_styles, selected_goals = comedy_review_options(styles, goals=goals)
        assert '   6| She put the key on the table.' in prompt
        assert '   3| UNSELECTED_NEIGHBOR_MARKER' in prompt
        assert 'STALE_CHARACTER_MARKER' not in prompt
        assert 'The character uses formal language to cope with fear.' in prompt
        assert 'Keep the narrator affectionate toward the family.' in prompt
        assert 'EVERY selected scene' in prompt
        assert 'Comic reading' in prompt and 'up to 5 distinct Revision priorities' in prompt
        assert 'numerical funniness scores' in prompt
        assert '**Writer-plan gap**' not in prompt
        assert clients[0].turn_params[0]['sandboxPolicy']['type'] == 'readOnly'
        guide = review_guide('comedy_review')
        for lane in guide['lanes']:
            assert (lane['summary'] in prompt) == (lane['id'] in {'truth_pain', 'deadpan_subtext'})
        for style in guide['styles']:
            assert (style['prompt'] in prompt) == (style['id'] in styles)
        assert all(goal['prompt'] in prompt for goal in selected_goals)
        assert 'up to 5 priorities TOTAL across all selected goals' in prompt
        assert ('**Type: Strengthen existing humor**' in prompt) == any(goal['id'] == 'strengthen' for goal in selected_goals)
        assert ('**Type: Comic opportunity**' in prompt) == any(goal['id'] == 'explore' for goal in selected_goals)
        receipt = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        assert 'Review goals: ' + ', '.join(goal['label'] for goal in selected_goals) in receipt['text']
        assert receipt['context_sent']['check_plan'] is False
        if not selected_styles:
            assert 'Comic styles: Follow the draft' in receipt['text']
        assert not (manager.root / '.proseview/skills/comedy_review').exists()
    finally:
        manager.close()


@pytest.mark.parametrize('extra', [
    {'comedy_styles': 'dark'}, {'comedy_styles': [False]}, {'comedy_styles': ['violent']},
    {'comedy_styles': ['dark'] * 4}, {'comedy_goal': ''}, {'comedy_goal': 'add jokes everywhere'},
    {'comedy_goal': False}, {'review_lanes': ['adverbs']},
    {'comedy_goals': []}, {'comedy_goals': 'explore'}, {'comedy_goals': [False]},
    {'comedy_goals': ['unknown']}, {'comedy_goals': ['strengthen', 'explore', 'strengthen']},
    {'comedy_goals': ['strengthen'], 'comedy_goal': 'explore'},
])
def test_invalid_comedy_options_fail_before_a_model_request(tmp_path, monkeypatch, extra):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='invalid-comedy', question='', action_id='comedy_review',
                           action_scope='scene', scenes=['scene.md'], **extra)
        assert not clients[0].prompts
    finally:
        manager.close()


def test_legacy_singular_goal_is_accepted_and_selection_scope_is_explicitly_rejected(tmp_path, monkeypatch):
    styles, goals = comedy_review_options(['dark'], 'explore')
    assert [goal['id'] for goal in goals] == ['explore']
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError, match='full scenes'):
            manager.submit(cid, client_request_id='selection-comedy', question='', action_id='comedy_review',
                           selection='She put the key on the table.', comedy_styles=['dark'])
        assert not clients[0].prompts
    finally:
        manager.close()


def test_comedy_options_are_not_silently_applied_to_another_review(tmp_path, monkeypatch):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError, match='only for Comedy review'):
            manager.submit(cid, client_request_id='wrong-action', question='', action_id='quick_critique',
                           action_scope='scene', scenes=['scene.md'], comedy_styles=['dark'])
        assert not clients[0].prompts
    finally:
        manager.close()


def test_comedy_guides_cover_the_requested_techniques_and_keep_the_prompt_selective():
    guide = review_guide('comedy_review')
    assert {lane['id'] for lane in guide['lanes']} == {
        'truth_pain', 'premise', 'character_status', 'deadpan_subtext', 'setup_surprise',
        'escalation_callbacks', 'specificity', 'timing_wording', 'tone_target', 'violation_distance',
    }
    for lane in guide['lanes']:
        contract = scene_review_contract('comedy_review', [lane], scene_count=1, check_plan=False)
        assert lane['summary'] in contract and lane['spot'] in contract and lane['fix'] in contract
        assert lane['flat'] != lane['working']
        assert lane['why'] and lane['tryIt'] and lane['caution']
        assert lane['anotherExample']['text'] and lane['anotherExample']['why']
        assert all(other['summary'] not in contract for other in guide['lanes'] if other is not lane)
    all_lanes = selected_review_lanes('comedy_review', None)
    contract = scene_review_contract('comedy_review', all_lanes, scene_count=2, check_plan=True)
    assert 'Three beats are an option' in next(lane['caution'] for lane in all_lanes if lane['id'] == 'escalation_callbacks')
    assert '**Writer-plan gap**' in contract
    assert 'theory and a useful question' in next(lane['caution'] for lane in all_lanes if lane['id'] == 'violation_distance')
    assert next(source for source in guide['sources'] if source['id'] == 'violation')['label'].startswith('Peter McGraw & Caleb Warren')


def test_new_comedy_builtin_stays_in_app_and_writer_takeover_is_preserved(tmp_path, monkeypatch):
    manager, _, _, _ = _manager(tmp_path, monkeypatch)
    root = manager.root
    assert action_instruction(root, 'comedy_review') == default_skill_body('comedy_review')
    settings_row = next(row for row in manager.discuss_settings()['skills'] if row['id'] == 'comedy_review')
    assert settings_row['source'] == 'builtin' and not settings_row['customized']
    manager.close()
    owned = root / '.proseview/skills/comedy_review/SKILL.md'
    owned.parent.mkdir(parents=True)
    owned.write_text('---\nname: comedy_review\n---\n\nFocus on this writer’s comic voice.\n')
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: CodexFakeClient(callback))
    try:
        assert owned.exists()
        assert action_instruction(root, 'comedy_review') == 'Focus on this writer’s comic voice.'
        cfg = Config.load(root)
        cfg.with_overrides(discuss=replace(cfg.discuss, skill_prompts=(('comedy_review', 'This book’s comedy instructions.'),))).save(root)
        assert action_instruction(root, 'comedy_review') == 'This book’s comedy instructions.'
        settings_row = next(row for row in manager.discuss_settings()['skills'] if row['id'] == 'comedy_review')
        assert settings_row['source'] == 'yaml' and settings_row['customized']
    finally:
        manager.close()
