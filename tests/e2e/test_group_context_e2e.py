"""Conversation context choices through the real setup, server and transports."""
import json

import pytest

pytest.importorskip('playwright.sync_api')
from .conftest import SCENE_REL
from .test_browser_e2e import open_scene
from .test_group_fork_e2e import answer
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def source_history(page, server, agent='codex'):
    open_scene(page, server, SCENE_REL)
    answer(page, agent)
    for question in ('OLDER_GOAL_ONLY: protect the city callback.', 'Keep the first envelope touch.', 'What remains open for a second opinion?'):
        page.locator('#discussInput').fill(question)
        page.locator('#discussInput').press('Enter')
        page.wait_for_function('question => { const s = _discussSnapshot, users = s.messages.filter(m => m.role === "user"), replies = s.messages.filter(m => m.role === "assistant"); return !s.active_request_id && !s.active_turn_id && !s.queue.length && users.at(-1)?.text === question && replies.at(-1)?.client_request_id === users.at(-1)?.client_request_id; }', arg=question)
    page.locator('#discussGroupFork').click()
    page.locator('#groupForkConfirm:not([disabled])').wait_for()
    return page.locator('#discussGroupForkDialog')


def select_recent(page, setup):
    setup.get_by_role('radio', name='Recent exchanges', exact=True).check()
    setup.locator('#groupForkExchangeCount').fill('2')
    page.wait_for_function('() => !_groupForkDialogState.checking && _groupForkDialogState.counts.kept === 2')
    setup.locator('#groupForkConfirm:not([disabled])').wait_for()


@pytest.mark.parametrize('agent', ['codex', 'claude'])
def test_summary_is_first_context_message_and_source_stays_unchanged(page, server, agent):
    setup = source_history(page, server, agent)
    source_count = page.evaluate('_discussSnapshot.messages.length')
    source_id = page.evaluate('_discussSnapshot.thread_id')
    select_recent(page, setup)
    assert setup.locator('#groupForkIncludeSummary').is_checked()
    setup.locator('#groupForkConfirm').click()
    pane = page.locator('#sceneGroupPane')
    pane.locator('.group-conversation-summary').wait_for()
    page.wait_for_function('() => !_groupActiveSession.busy')
    turns = page.evaluate('_groupActiveSession.turns')
    assert turns[0]['role'] == 'context' and len(turns) == 5
    assert all('OLDER_GOAL_ONLY' not in t['text'] for t in turns[1:])
    assert not page.evaluate('_groupActiveSession.runtime.steps.length')
    pane.get_by_role('button', name='Source chat ↗').click()
    page.wait_for_function('() => !!_discussSnapshot && !document.querySelector("#discussLog").hidden')
    assert page.evaluate('_discussSnapshot.thread_id') == source_id
    assert page.evaluate('_discussSnapshot.messages.length') == source_count


def test_recent_only_is_remembered_and_does_not_replay_old_context(page, server):
    setup = source_history(page, server)
    select_recent(page, setup)
    setup.locator('#groupForkIncludeSummary').uncheck()
    setup.locator('#groupForkConfirm').click()
    pane = page.locator('#sceneGroupPane')
    pane.wait_for(state='visible')
    assert pane.locator('.group-conversation-summary').count() == 0
    assert len(page.evaluate('_groupActiveSession.turns')) == 4
    pane.locator('#groupInput').fill('Continue from the selected context.')
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    rows = [json.loads(line) for line in (server.home / 'fake-codex-received.jsonl').read_text().splitlines()]
    turn = next(r for r in reversed(rows) if 'Continue from the selected context.' in str(r.get('params', {}).get('input', '')))
    prompt = turn['params']['input'][0]['text']
    assert 'OLDER_GOAL_ONLY' not in prompt
    assert 'CURRENT FILE' in prompt and '| ' in prompt
    pane.get_by_role('button', name='Source chat ↗').click()
    page.locator('#discussGroupFork:not([disabled])').wait_for()
    page.locator('#discussGroupFork').click()
    page.locator('#groupForkConfirm:not([disabled])').wait_for()
    assert setup.get_by_role('radio', name='Recent exchanges', exact=True).is_checked()
    assert setup.locator('#groupForkExchangeCount').input_value() == '2'
    assert not setup.locator('#groupForkIncludeSummary').is_checked()


def test_cancel_returns_to_setup_with_choices_and_opens_no_group(page, server):
    setup = source_history(page, server)
    select_recent(page, setup)
    setup.locator('[data-preset="second_opinion"]').click()
    hold = server.root / '.proseview' / 'hold-group-summary'
    hold.parent.mkdir(exist_ok=True)
    hold.touch()
    try:
        setup.locator('#groupForkConfirm').click()
        setup.locator('#groupForkCancelSummary').wait_for()
        setup.locator('#groupForkCancelSummary').click()
        setup.locator('#groupForkConfirm:not([disabled])').wait_for()
        assert setup.locator('#groupForkExchangeCount').input_value() == '2'
        assert setup.locator('#groupForkIncludeSummary').is_checked()
        assert setup.locator('[data-preset="second_opinion"]').get_attribute('aria-pressed') == 'true'
        assert page.evaluate('!_groupActiveSession || !_groupActiveSession.managed')
    finally:
        hold.unlink(missing_ok=True)


def test_failed_summary_shows_persistent_notice_and_only_kept_exchanges(page, server):
    setup = source_history(page, server)
    select_recent(page, setup)
    marker = server.root / '.proseview' / 'fail-group-summary'
    marker.parent.mkdir(exist_ok=True)
    marker.touch()
    setup.locator('#groupForkConfirm').click()
    pane = page.locator('#sceneGroupPane')
    pane.locator('.group-summary-missing').wait_for()
    assert 'Summary missing' in pane.locator('.group-summary-missing').inner_text()
    assert len(page.evaluate('_groupActiveSession.turns')) == 4
    assert pane.locator('.group-conversation-summary').count() == 0
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane.locator('.group-summary-missing').wait_for()
