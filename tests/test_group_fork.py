"""Native Group forks preserve source sessions and export portable context once."""
import copy
import json
import time

import pytest

from proseview.discuss import ContextError
from proseview.group import extract_stances, positions_table, visible_reply
from proseview.group_fork import materialize, split_prompt
from tests.test_highlight_suggestions import _manager, _repo


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude'))


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('Timed out waiting for the Group')


def answered(manager, agent='codex'):
    snap = manager.open({'kind': 'scene', 'path': 'one.md'}, agent)
    cid = snap['conversation_id']
    manager.submit(cid, client_request_id='original', question='Preserve the quiet ending. What do you think?')
    wait_for(lambda: any(m.get('phase') == 'final_answer' for m in manager.get_snapshot(cid)['messages']))
    wait_for(lambda: not manager._get(cid).active_request_id)
    return cid


def state(manager, key):
    return manager.group_command({'action': 'state', 'group_id': key})


def send(manager, key, text, seats=None):
    return manager.group_command({'action': 'submit', 'group_id': key, 'request_id': str(time.monotonic_ns()),
                                  'message_id': str(time.monotonic_ns()), 'text': text,
                                  **({'seats': seats} if seats is not None else {})})


@pytest.mark.parametrize('agent', ['codex', 'claude'])
def test_manual_fork_is_idle_and_original_native_session_is_isolated(tmp_path, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager, agent)
        source = manager._get(cid)
        parent = source.thread_id
        messages = copy.deepcopy(source.messages)
        total_calls = sum(len(c.turn_params) for c in clients)
        result = manager.fork_group(cid, {'scene': 'one.md'}, create=True)
        saved = result['group']
        assert saved['status'] == 'idle' and saved['steps'] == []
        assert saved['source']['thread_id'] == parent
        assert all(t['inherited'] for t in saved['turns'])
        assert source.thread_id == parent and source.messages == messages
        assert sum(len(c.turn_params) for c in clients) == total_calls
        record = manager.group_runtime.store.read('groups', saved['id'])
        child = record['native_threads']['1']['thread_id']
        assert child != parent
        assert clients[0].forks[-1]['threadId'] == parent
        assert not clients[0].forks[-1].get('ephemeral')
        send(manager, saved['id'], 'Continue only in the Group.', [1])
        wait_for(lambda: len(state(manager, saved['id'])['turns']) > len(saved['turns']) + 1)
        assert clients[0].turn_params[-1]['threadId'] == child
        assert 'Preserve the quiet ending' not in clients[0].prompts[-1]
        assert source.thread_id == parent and source.messages == messages
        assert manager.fork_group(cid, {'action': 'links'})['groups'][0]['id'] == saved['id']
    finally:
        manager.close()


def test_fresh_model_gets_all_files_once_and_structured_results_without_live_actions(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        source = manager._get(cid)
        receipt = source.messages[0]['context_sent']
        receipt['documents'] = ['manuscript/one.md', 'story-bible/characters/mira.md']
        receipt['request_instructions'] = 'Keep this exact instruction and the selected quote.'
        source.tasks['review'] = {'id': 'review', 'kind': 'continuity_report', 'status': 'ready', 'result': {
            'findings': [{'id': 'finding-7', 'number': 7, 'quote': 'Mira left at dawn.', 'decision': 'intentional'}]}}
        source.file_before['manuscript/one.md'] = 'Earlier file content'
        settings = manager.fork_group(cid, {'scene': 'one.md'})
        profiles = settings['participants']
        profiles[0]['model'] = 'custom-new-model'
        created = manager.fork_group(cid, {'scene': 'one.md', 'participants': profiles}, create=True)['group']
        record = manager.group_runtime.store.read('groups', created['id'])
        assert record['native_threads'] == {}
        text = materialize(manager, record['fork_context'])
        assert text.count('First document.') == 1
        assert text.count('Mira never swears.') == 1
        assert 'Keep this exact instruction' in text
        inherited = '\n'.join(t['text'] for t in created['turns'])
        assert 'finding-7' in inherited and 'intentional' in inherited and 'Mira left at dawn.' in inherited
        assert not any(t.get('review_pending') or t.get('tool_conversation_id') for t in created['turns'])
        assert source.file_before and source.tasks['review']['result']
        assert 'fresh session' in created['notice']
    finally:
        manager.close()


def test_context_export_deduplicates_documents_but_preserves_user_literals():
    document = 'manuscript/one.md'
    attached = f'BEGIN UNTRUSTED DOCUMENT {json.dumps(document)}\nold scene\nEND UNTRUSTED DOCUMENT {json.dumps(document)}'
    literal = f'Keep this literal:\n{attached}'
    compact, files = split_prompt('Read this.\n' + attached + '\n\nUSER QUESTION\n' + literal)
    assert files == [document]
    assert compact.count('old scene') == 1
    assert literal in compact


def test_lost_native_fork_restores_instructions_and_keeps_fallback_disclosure(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        source = manager._get(cid)
        source.messages[0]['context_sent']['request_instructions'] = 'Keep the original constraint exactly.'
        created = manager.fork_group(cid, {'scene': 'one.md'}, create=True)['group']
        child = manager.group_runtime.groups[created['id']]['native_threads']['1']['thread_id']
        clients[0].threads.pop(child)
        send(manager, created['id'], 'Continue in this Group.', [1])
        done = wait_for(lambda: (s := state(manager, created['id']))['status'] == 'idle' and len(s['turns']) > len(created['turns']) + 1 and s)
        assert 'Keep the original constraint exactly.' in clients[0].prompts[-1]
        assert clients[0].prompts[-1].count('First document.') == 1
        assert any('fresh session' in w for w in done['handoff_warnings'])
        assert manager.group_runtime.history.get(done['id'])['handoff_warnings'] == done['handoff_warnings']
    finally:
        manager.close()


def test_models_remain_attributed_after_source_chat_is_reopened(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        first = next(m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'assistant')
        assert first['model'] == 'gpt-5.6-sol'
        source = manager._get(cid)
        clients[0].threads[source.thread_id]['turns'] = [{'id': first['turn_id'], 'items': [
            {'type': 'userMessage', 'content': [{'type': 'text', 'text': clients[0].prompts[0]}]},
            {'type': 'agentMessage', 'text': first['text']},
        ]}]
        manager.set_model(cid, {'model': 'another-model'})
        manager.open_conversation(cid, source.thread_id)
        restored = next(m for m in manager.get_snapshot(cid)['messages'] if m['role'] == 'assistant')
        assert restored['model'] == first['model']
        forked = manager.fork_group(cid, {'scene': 'one.md'}, create=True)['group']
        inherited = next(t for t in forked['turns'] if t['role'] == 'critic')
        assert inherited['model'] == first['model'] and not inherited['model_inferred']
    finally:
        manager.close()


def test_model_limit_preflight_skips_unknown_custom_limits(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        cid = answered(manager)
        monkeypatch.setattr(manager, 'list_models', lambda agent: {'default': {'model': 'tiny'},
            'models': [{'id': 'tiny', 'context_window': 100}]})
        setup = manager.fork_group(cid, {'scene': 'one.md'})
        assert setup['limit_errors']
        with pytest.raises(ContextError, match='model limit'):
            manager.fork_group(cid, {'scene': 'one.md', 'workflow': 'second_opinion'}, create=True)
        for profile in setup['participants']:
            profile['model'] = 'unknown-custom'
        assert manager.fork_group(cid, {'scene': 'one.md', 'participants': setup['participants']})['limit_errors'] == []
    finally:
        manager.close()


@pytest.mark.parametrize('busy', ['active', 'queued', 'approval', 'other-group'])
def test_fork_refuses_busy_source_or_any_book_group(tmp_path, busy):
    manager = _manager(_repo(tmp_path), [])
    try:
        cid = answered(manager)
        source = manager._get(cid)
        if busy == 'active':
            source.active_request_id = 'still-running'
        elif busy == 'queued':
            source.pending.append(object())
        elif busy == 'approval':
            source.approvals['a'] = {'status': 'pending'}
        else:
            manager.group_runtime.groups['elsewhere'] = {'id': 'elsewhere', 'scene': 'another.md', 'status': 'running'}
        with pytest.raises(ContextError, match='Wait'):
            manager.fork_group(cid, {'scene': 'one.md'}, create=True)
    finally:
        source.active_request_id = None
        source.pending.clear()
        source.approvals.clear()
        manager.close()


def test_workflow_is_shared_has_two_invitations_and_keeps_latest_stances(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    calls = []
    try:
        cid = answered(manager)
        preset = next(p for p in manager.group_settings()['library']['presets'] if p['id'] == 'second_opinion')
        assert preset['kind'] == 'workflow' and preset['positions_table'] and [s['seat'] for s in preset['invitations']] == [2, 1]
        def run(**kw):
            calls.append(kw)
            raw = ('1. Keep the callback\n\nUseful reply.\nSTANCE | 1 | disagree | line 8 has A | B' if len(calls) == 1 else
                   '1. Keep the callback\n\nI revise that.\nSTANCE | 1 | revised | line 8 has A | B')
            return {'reply': raw, 'agent': kw['participants'][kw['seat'] - 1]['agent'], 'passed': False}
        monkeypatch.setattr(manager, 'run_group_turn', run)
        created = manager.fork_group(cid, {'scene': 'one.md', 'workflow': 'second_opinion'}, create=True)['group']
        done = wait_for(lambda: (s := state(manager, created['id']))['status'] == 'idle' and len(calls) == 3 and s)
        assert [kw['seat'] for kw in calls] == [2, 1, 2]
        assert all('STANCE' not in t['text'] for t in done['turns'])
        row = done['turns'][-1]['positions'][0]
        assert row['agents']['1']['stance'] == row['agents']['2']['stance'] == 'revised'
        assert row['agents']['1']['evidence'] == 'line 8 has A | B'
        restored = manager.group_runtime.history.get(done['id'])
        assert restored['source'] == done['source'] and restored['turns'][-1]['positions'] == done['turns'][-1]['positions']
    finally:
        manager.close()


def test_partial_stance_records_never_reach_streamed_chat():
    assert visible_reply('A reply.\nST', streaming=True) == 'A reply.'
    assert visible_reply('A reply.\nSTANCE | 1 | agree | x\nNext') == 'A reply.\nNext'
    assert extract_stances('STANCE | 7 | revised | A | B')[0]['evidence'] == 'A | B'
    rows = positions_table([{'role': 'critic', 'seat': 1, 'text': '7. Keep the title',
                             'stances': extract_stances('STANCE | 7 | agree | yes\nSTANCE | 7 | withdrawn | changed')}])
    assert rows[0]['agents']['1']['stance'] == 'withdrawn' and '2' not in rows[0]['agents']
