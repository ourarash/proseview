from __future__ import annotations

import time
from pathlib import Path

import pytest

from proseview.discuss import ContextError, DiscussManager
from proseview.craft import craft_guides, craft_review_contract, lane_name
from .transport_fakes import CodexFakeClient


def _manager(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'novel'
    manuscript = root / 'manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'scene.md').write_text('---\npov: STALE_CHARACTER_MARKER\n---\n# A choice\n\nShe put the key on the table.\n')
    (manuscript / 'z-next.md').write_text('# Next\n\nUNSELECTED_NEIGHBOR_MARKER\n')
    custom_skill = root / '.proseview/skills/craft_mckee/SKILL.md'
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text('---\nname: craft_mckee\n---\n\nSuggested fixes & replacements: label each fix with checklist item numbers.\n')
    clients = []
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: clients.append(CodexFakeClient(callback)) or clients[-1])
    cid = manager.open({'kind': 'scene', 'path': 'scene.md'})['conversation_id']
    return manager, cid, clients, custom_skill


def test_craft_context_and_lane_names_reach_prompt_even_with_custom_skill(tmp_path: Path, monkeypatch):
    manager, cid, clients, custom_skill = _manager(tmp_path, monkeypatch)
    custom_prompt = custom_skill.read_text()
    try:
        manager.submit(
            cid, client_request_id='named-lanes', question='', action_id='craft_mckee',
            action_scope='scene', scenes=['scene.md'], craft_focus='What is said and what is meant',
            craft_context='Family drama. The key is an offer of trust, not a practical request.',
            craft_lanes=['Desire', 'Resistance', 'Actions & reactions', 'Subtext', 'Change'],
            custom_instruction='Preserve the understatement.', include_frontmatter=False, include_adjacent=False,
        )
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        prompt = clients[0].prompts[0]
        assert 'Writer-supplied story context:\nFamily drama.' in prompt
        assert 'Focus: Subtext' in prompt
        assert 'Writer instructions:\nPreserve the understatement.' in prompt
        assert 'Available review lanes:\n- Desire\n- Resistance\n- Actions & reactions\n- Subtext\n- Change' in prompt
        assert '**Lane: <name> — <why this finding belongs here>**' in prompt
        assert 'for numbered and unnumbered suggestions' in prompt
        assert 'never checklist item numbers' in prompt
        assert prompt.index('Feedback lane labels:') > prompt.index('label each fix with checklist item numbers')
        assert 'STALE_CHARACTER_MARKER' not in prompt
        assert 'UNSELECTED_NEIGHBOR_MARKER' not in prompt
        assert clients[0].turn_params[0]['sandboxPolicy']['type'] == 'readOnly'
        assert custom_skill.read_text() == custom_prompt
        asked = [m['text'] for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user']
        assert 'Writer-supplied story context:' in asked[-1]
    finally:
        manager.close()


@pytest.mark.parametrize('extra', [
    {'craft_context': 'x' * 8193},
    {'craft_lanes': 'Resistance'},
    {'craft_lanes': ['']},
    {'craft_lanes': ['x' * 401]},
    {'craft_lanes': ['Change'] * 13},
])
def test_craft_context_and_lane_names_are_bounded(tmp_path: Path, monkeypatch, extra):
    manager, cid, clients, _ = _manager(tmp_path, monkeypatch)
    try:
        with pytest.raises(ContextError):
            manager.submit(cid, client_request_id='invalid-context', question='', action_id='craft_mckee',
                           action_scope='scene', scenes=['scene.md'], **extra)
        assert not clients[0].prompts
    finally:
        manager.close()


def test_saved_story_context_survives_manager_restart_and_is_separate_per_scene(tmp_path: Path, monkeypatch):
    manager, _, _, _ = _manager(tmp_path, monkeypatch)
    root = manager.root
    assert manager.craft_story_context('scene.md') == ''
    notes = 'Family fiction. This scene starts a tentative reconnection.'
    assert manager.craft_story_context('scene.md', notes) == notes
    assert manager.craft_story_context('z-next.md') == ''
    manager.close()
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: CodexFakeClient(callback))
    try:
        assert manager.craft_story_context('scene.md') == notes
        with pytest.raises(ContextError):
            manager.craft_story_context('../outside.md', 'Do not write here')
        with pytest.raises(ContextError):
            manager.craft_story_context('scene.md', 'x' * 8193)
        assert manager.craft_story_context('scene.md', '') == ''
        assert not (root / '.proseview/craft-context.json').exists()
    finally:
        manager.close()


def test_review_contract_uses_the_same_principles_as_the_guide_and_covers_each_scene():
    for guide in craft_guides():
        contract = craft_review_contract(guide['id'], scene_count=3)
        for lane in guide['lanes']:
            assert lane_name(lane) in contract
            assert lane['summary'] in contract
            assert lane['spot'] in contract
            focused = craft_review_contract(guide['id'], focus=lane['id'])
            assert 'Selected focus: ' + lane_name(lane) in focused
            assert lane['summary'] in focused
        if guide['id'] != 'craft_lamott':
            assert 'EVERY selected scene' in contract
            assert 'concrete demonstration' in contract
            assert 'Book-based reading' in contract


def test_plan_check_is_off_unless_the_writer_asks():
    """A note the writer has outgrown must not lead every review."""
    for guide in craft_guides():
        off = craft_review_contract(guide['id'])
        assert 'Writer-plan gap' not in off
        assert 'Do not report\na beat, setup, or dependency' in off
        # Story context typed for this review still informs it.
        assert 'Writer-supplied\nstory context for this review is current' in off
        on = craft_review_contract(guide['id'], check_plan=True)
        assert '**Writer-plan gap**' in on
        assert 'Judge the drafted prose on the page' not in on
        # No principle quietly asks for the note check the toggle governs.
        for lane in guide['lanes']:
            assert 'notes' not in lane['spot'].lower()
            assert 'writer notes' not in lane['summary'].lower()


def test_plan_check_reaches_the_prompt_receipt_and_context_inspector(tmp_path: Path, monkeypatch):
    manager, cid, clients, _custom_skill = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(
            cid, client_request_id='plan-on', question='', action_id='craft_mckee',
            action_scope='scene', scenes=['scene.md'], craft_check_plan=True,
        )
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        assert '**Writer-plan gap**' in clients[0].prompts[0]
        asked = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        assert 'Plan check: compare the draft with planned beats in my notes.' in asked['text']
        assert asked['context_sent']['check_plan'] is True
    finally:
        manager.close()


def test_plan_check_defaults_off_in_the_prompt(tmp_path: Path, monkeypatch):
    manager, cid, clients, _custom_skill = _manager(tmp_path, monkeypatch)
    try:
        manager.submit(cid, client_request_id='plan-off', question='', action_id='craft_mckee',
                       action_scope='scene', scenes=['scene.md'])
        deadline = time.monotonic() + 3
        while not clients[0].prompts and time.monotonic() < deadline:
            time.sleep(.01)
        assert 'Writer-plan gap' not in clients[0].prompts[0]
        asked = [m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'user'][-1]
        assert 'Plan check' not in asked['text']
        assert asked['context_sent']['check_plan'] is False
    finally:
        manager.close()
