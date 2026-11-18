"""Fork setup and the shared second-opinion workflow through real HTTP transports."""
import json

import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import open_scene
from .test_btw_e2e import _open_discuss_agent
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def answer(page, agent):
    _open_discuss_agent(page, agent)
    page.locator('#discussInput').fill('Please discuss the quiet ending.')
    page.locator('#discussInput').press('Enter')
    page.wait_for_function('() => !_discussSnapshot.active_request_id && !_discussSnapshot.active_turn_id && _discussSnapshot.messages.some(m => m.role === "assistant")')
    page.locator('#discussGroupFork:not([disabled])').wait_for()


@pytest.mark.parametrize('agent', ['codex', 'claude', 'agy'])
def test_manual_fork_preserves_source_and_routes_untagged_group_messages(page, server, agent):
    open_scene(page, server, SCENE_REL)
    answer(page, agent)
    original_count = page.evaluate('_discussSnapshot.messages.length')
    source_thread = page.evaluate('_discussSnapshot.thread_id')
    posts = []
    page.on('request', lambda req: posts.append(req.post_data_json) if req.url.endswith('/api/discuss/group-run') and req.method == 'POST' else None)
    page.locator('#discussGroupFork').click()
    setup = page.locator('#discussGroupForkDialog')
    setup.locator('#groupForkConfirm:not([disabled])').wait_for()
    assert setup.get_by_text('None — I’ll direct it', exact=True).get_attribute('aria-pressed') == 'true'
    assert setup.get_by_label('Original assistant provider').input_value() == agent
    assert setup.locator('[data-preset="editorial_critique"]').count() == 0
    setup.locator('#groupForkConfirm').click()
    pane = page.locator('#sceneGroupPane')
    pane.wait_for(state='visible')
    page.wait_for_function('() => _groupActiveSession?.managed && !_groupActiveSession.busy')
    transfer = pane.locator('.group-transferred-context')
    assert transfer.count() == 1
    assert not transfer.evaluate('el=>el.open')
    assert transfer.locator('summary').first.inner_text() == 'Context transferred'
    assert transfer.evaluate('el=>el.parentElement.firstElementChild===el')
    assert pane.locator('.group-runtime-notice').count() == 0
    assert 'private reasoning' not in pane.inner_text()
    if agent == 'agy':
        transfer.locator(':scope > summary').click()
        expect(transfer).to_contain_text('Started a new session with transferred context.')
        assert 'thread/fork' not in transfer.inner_text()
        transfer.locator('.group-transfer-technical > summary').click()
        expect(transfer).to_contain_text('thread/fork')
        transfer.locator(':scope > summary').click()
    assert all(t['inherited'] for t in page.evaluate('_groupActiveSession.turns'))
    assert not [p for p in posts if p.get('action') in ('submit', 'preset')]
    pane.locator('#groupInput').fill('Tell me more about the ending.')
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert any(not t.get('inherited') and t['role'] == 'critic' for t in page.evaluate('_groupActiveSession.turns'))
    assert transfer.count() == 1 and not transfer.evaluate('el=>el.open')
    assert pane.locator('.group-runtime-notice').count() == 0
    pane.locator('#groupInput').fill('Remember the previous Group reply and continue.')
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    if agent == 'claude':
        rows = [json.loads(line) for line in (server.home / 'fake-claude-received.jsonl').read_text().splitlines()]
        child_calls = [r for r in rows if r.get('method') == 'query' and 'Tell me more about the ending.' in r.get('prompt', '')]
        assert child_calls and child_calls[-1]['session_id'] != child_calls[-1]['resume']
        later = [r for r in rows if r.get('method') == 'query' and 'Remember the previous Group reply' in r.get('prompt', '')]
        assert later[-1]['session_id'] == child_calls[-1]['session_id']
    pane.get_by_role('button', name='Source chat ↗', exact=True).click()
    page.wait_for_function('() => !!_discussConversationId && !_discussSnapshot.active_request_id && !document.querySelector("#discussLog").hidden')
    assert page.evaluate('_discussSnapshot.messages.length') == original_count
    assert page.evaluate('_discussSnapshot.thread_id') == source_thread
    page.locator('#discussForkGroupLink').wait_for()
    page.locator('#discussForkGroupLink').click()
    pane.wait_for(state='visible')
    group_id = page.evaluate('_groupActiveSession.id')
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    page.wait_for_function('id => _groupActiveSession?.id === id && _groupActiveSession?.managed && !!_groupActiveSession.source', arg=group_id)
    pane.get_by_role('button', name='Source chat ↗', exact=True).wait_for()
    assert transfer.count() == 1 and not transfer.evaluate('el=>el.open')
    assert pane.locator('.group-runtime-notice').count() == 0


def test_second_opinion_is_shared_and_starts_only_the_selected_workflow(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator('#sceneGroupPane')
    flow = pane.locator('[data-preset="second_opinion"]')
    flow.wait_for()
    assert flow.is_disabled(), 'An empty Group has no answer to assess'
    answer(page, 'codex')
    page.locator('#discussGroupFork').click()
    setup = page.locator('#discussGroupForkDialog')
    setup.locator('[data-preset="second_opinion"]').wait_for()
    setup.locator('[data-preset="second_opinion"]').click()
    assert setup.get_by_label('Include agent positions in Discussion for Second opinion & recap').is_checked()
    setup.locator('#groupForkConfirm').click()
    pane.wait_for(state='visible')
    _group_idle(page)
    page.wait_for_function('() => _groupActiveSession?.turns.filter(t => t.role === "invitation").length === 4 && !_groupActiveSession.busy')
    invitations = page.evaluate('_groupActiveSession.turns.filter(t => t.role === "invitation").map(t => t.seat)')
    assert invitations == [2, 3, 1, 3]
    assert pane.locator('.group-positions-card').count() == 1
    assert not pane.locator('.group-positions-card').evaluate('el => el.open')
    pane.locator('.group-positions-card > summary').click()
    assert pane.get_by_role('table', name='Recorded positions').count() == 1
    assert pane.locator('#groupContinueToFiveBtn').count() == 0
    pane.get_by_text('Conversation workflows', exact=True).click()
    assert pane.locator('[data-preset="second_opinion"]').count() == 1
    assert 'STANCE |' not in pane.inner_text()


def test_task_recap_keeps_revision_plan_with_optional_positions_table(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator('#sceneGroupPane')
    pane.locator('[data-preset="editorial_critique"]').click()
    pane.get_by_label('Include agent positions in Discussion for Editorial critique').check()
    pane.locator('#groupStartPresetBtn').click()
    _group_idle(page)
    assert pane.get_by_text('Revision plan', exact=True).count() == 1
    assert pane.locator('.group-positions-card').count() == 1
    pane.get_by_text('Conversation workflows', exact=True).click()
    pane.locator('[data-preset="second_opinion"]').click()
    page.wait_for_function('() => _groupActiveSession?.presetId === "second_opinion" && _groupActiveSession.turns.filter(t => t.tag === "Recap").length === 2')
    _group_idle(page)
    assert pane.get_by_text('Revision plan', exact=True).count() == 1
    assert pane.locator('.group-positions-card').count() == 2
