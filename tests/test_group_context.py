"""Compact Group handoffs keep request boundaries and use isolated summary forks."""
import copy
import threading

import pytest

from proseview.discuss import ContextError
from proseview.group_context import options, select
from proseview.group_fork import materialize
from tests.test_group_fork import answered, wait_for, send, state
from tests.test_highlight_suggestions import _manager, _repo


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude'))


def more_answers(manager, cid, count=4):
    for index in range(count):
        request = 'question-' + str(index)
        manager.submit(cid, client_request_id=request, question=f'Constraint {index}: keep this exact goal.')
        wait_for(lambda: not manager._get(cid).active_request_id and not manager._get(cid).pending
                 and any(m.get('client_request_id') == request and m['role'] == 'assistant' for m in manager._get(cid).messages))


def compact(count=2, summary=True):
    return {'scene': 'one.md', 'context_options': {'mode': 'recent', 'exchanges': count, 'include_summary': summary}}


def summarize(manager, cid, body):
    job = manager.fork_group(cid, {**body, 'action': 'summarize'})
    ready = wait_for(lambda: (s := manager.fork_group(cid, {'action': 'summary-state', 'summary_id': job['summary_id']}))['status'] != 'summarizing' and s)
    assert ready['status'] == 'ready'
    return {**body, 'summary_id': job['summary_id']}


def test_exchange_selection_keeps_commentary_and_structured_results_with_their_request():
    messages = [
        {'role': 'user', 'text': 'old question', 'client_request_id': 'old', 'created_at': 1},
        {'role': 'assistant', 'text': 'old answer', 'client_request_id': 'old', 'turn_id': 't1'},
        {'role': 'user', 'text': 'latest question', 'client_request_id': 'latest', 'created_at': 3},
        {'role': 'assistant', 'text': 'working', 'phase': 'thought', 'client_request_id': 'latest'},
        {'role': 'assistant', 'text': 'latest answer', 'client_request_id': 'latest', 'turn_id': 't3'},
    ]
    tasks = [{'id': 'review-2', 'client_request_id': 'review', 'turn_id': 't2', 'created_at': 2,
              'label': 'Review the scene', 'result': {'findings': [{'id': 'f7', 'number': 7, 'quote': 'Evidence', 'decision': 'intentional'}]}}]
    native = {'turns': [{'id': f't{i}', 'items': [{'type': 'userMessage'}]} for i in (1, 2, 3)]}
    selected = select(messages, tasks, native, options(compact()))
    assert selected['counts'] == {'total': 3, 'kept': 2, 'older': 1}
    assert selected['cutoff']['last_message'] == 'old answer'
    assert selected['cutoff']['native_turn_ids'] == ['t1']
    assert selected['tasks'] == tasks
    assert [t['id'] for t in selected['native']['turns']] == ['t2', 't3']
    assert any(m['text'] == 'working' for m in selected['messages'])


@pytest.mark.parametrize('agent', ['codex', 'claude'])
def test_recent_only_drops_older_instructions_and_other_file_bodies(tmp_path, agent):
    root = _repo(tmp_path)
    manager = _manager(root, clients := [])
    try:
        cid = answered(manager, agent)
        more_answers(manager, cid)
        source = manager._get(cid)
        source.messages[0]['context_sent']['request_instructions'] = 'EXCLUDED_OLD_INSTRUCTIONS'
        recent_request = next(m for m in source.messages if m.get('client_request_id') == 'question-3' and m['role'] == 'user')
        recent_request['context_sent']['documents'] = ['story-bible/characters/mira.md']
        call_count = sum(len(c.turn_params) for c in clients)
        group = manager.fork_group(cid, compact(summary=False), create=True)['group']
        assert group['context_counts'] == {'total': 5, 'kept': 2, 'older': 3}
        assert len(group['turns']) == 4
        assert not manager.group_runtime.groups[group['id']]['native_threads']
        assert sum(len(c.turn_params) for c in clients) == call_count
        context = manager.group_runtime.groups[group['id']]['fork_context']
        text = materialize(manager, context)
        assert 'EXCLUDED_OLD_INSTRUCTIONS' not in text
        assert 'Constraint 3: keep this exact goal.' in text
        assert 'story-bible/characters/mira.md' in text and 'Mira never swears.' not in text
        assert '7| First document.' in text
        assert text.count('First document.') == 1
        send(manager, group['id'], 'Continue from this context.', [1])
        wait_for(lambda: len(state(manager, group['id'])['turns']) > 5)
        assert 'EXCLUDED_OLD_INSTRUCTIONS' not in clients[0].prompts[-1]
        assert 'Constraint 0:' not in clients[0].prompts[-1]
    finally:
        manager.close()


@pytest.mark.parametrize('agent', ['codex', 'claude'])
def test_summary_uses_one_no_tool_ephemeral_source_fork_and_emits_no_source_events(tmp_path, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager, agent)
        more_answers(manager, cid)
        source = manager._get(cid)
        before = copy.deepcopy(source.messages)
        parent = source.thread_id
        events = []
        source.publish = lambda kind, payload: events.append(kind)
        body = compact()
        payload = summarize(manager, cid, body)
        request = clients[0].forks[-1]
        assert request['threadId'] == parent and request['ephemeral'] and request['approvalPolicy'] == 'never'
        assert request['tools'] == [] and not request['allowWrite']
        turn = clients[0].turn_params[-1]
        assert turn['approvalPolicy'] == 'never' and not turn['mayWrite']
        assert turn['sandboxPolicy']['type'] == 'readOnly'
        prompt = clients[0].prompts[-1]
        assert 'last message/result before the retained exchanges' in prompt
        assert '"exchange": 3' in prompt and 'Do not summarize anything after this cutoff' in prompt
        assert 'Constraint 0:' not in prompt and 'Constraint 3:' not in prompt
        group = manager.fork_group(cid, payload, create=True)['group']
        assert group['turns'][0]['role'] == 'context'
        assert group['turns'][0]['label'] == 'Generated conversation summary'
        assert len(group['turns']) == 5 and not group['summary_missing']
        assert manager.group_runtime.history.get(group['id'])['turns'][0]['role'] == 'context'
        assert source.thread_id == parent and source.messages == before and not events
        assert not manager.group_runtime.groups[group['id']]['native_threads']
    finally:
        manager.close()


@pytest.mark.parametrize('failure', ['fork', 'timeout'])
def test_summary_failure_uses_recent_only_without_seeded_fallback(tmp_path, failure):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        more_answers(manager, cid)
        starts = len(clients[0].thread_start_params)
        if failure == 'fork':
            clients[0].fork_error = RuntimeError('Unavailable native session')
        else:
            clients[0].hold_next_turn = True
            manager.SIDE_TIMEOUT = .05
        payload = summarize(manager, cid, compact())
        group = manager.fork_group(cid, payload, create=True)['group']
        assert group['summary_missing'] and len(group['turns']) == 4
        assert any(w.startswith('Summary missing.') for w in group['handoff_warnings'])
        assert len(clients[0].thread_start_params) == starts
        assert not any(t['role'] == 'context' for t in group['turns'])
    finally:
        manager.close()


def test_cancel_summary_interrupts_and_never_creates_group(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        more_answers(manager, cid)
        clients[0].hold_next_turn = True
        calls = len(clients[0].turn_params)
        job = manager.fork_group(cid, {**compact(), 'action': 'summarize'})
        wait_for(lambda: len(clients[0].turn_params) > calls)
        result = manager.fork_group(cid, {'action': 'cancel-summary', 'summary_id': job['summary_id']})
        assert result['status'] == 'cancelled'
        wait_for(lambda: clients[0].interrupts)
        assert not manager.group_runtime.groups
        assert not manager._get(cid).forking
        with pytest.raises(ContextError, match='changed'):
            manager.fork_group(cid, {**compact(), 'summary_id': job['summary_id']}, create=True)
        assert not manager.group_runtime.history.list()
    finally:
        manager.close()


def test_cancel_before_native_fork_returns_starts_no_summary_turn(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), clients := [])
    entered, release = threading.Event(), threading.Event()
    try:
        cid = answered(manager)
        more_answers(manager, cid)
        calls = len(clients[0].turn_params)
        request = clients[0].request
        def held(method, params, **kwargs):
            if method == 'thread/fork' and params.get('ephemeral'):
                entered.set()
                assert release.wait(3)
            return request(method, params, **kwargs)
        monkeypatch.setattr(clients[0], 'request', held)
        job = manager.fork_group(cid, {**compact(), 'action': 'summarize'})
        assert entered.wait(2)
        manager.fork_group(cid, {'action': 'cancel-summary', 'summary_id': job['summary_id']})
        release.set()
        wait_for(lambda: manager._fork_jobs[job['summary_id']].get('completed_at'))
        assert len(clients[0].turn_params) == calls
        assert not manager.group_runtime.groups and not manager._get(cid).forking
    finally:
        release.set()
        manager.close()


@pytest.mark.parametrize('draft', ['A current unsaved line.\nA second line.', ''])
def test_current_scene_uses_the_numbered_unsaved_draft_once(tmp_path, draft):
    root = _repo(tmp_path)
    manager = _manager(root, [])
    try:
        cid = answered(manager)
        live = {'content': draft, 'base_mtime': (root / 'manuscript/one.md').stat().st_mtime}
        group = manager.fork_group(cid, {**compact(summary=False), 'live_document': live}, create=True)['group']
        text = materialize(manager, manager.group_runtime.groups[group['id']]['fork_context'])
        assert 'First document.' not in text
        if draft:
            assert '1| A current unsaved line.' in text and '2| A second line.' in text
            assert text.count('A current unsaved line.') == 1
        assert group['context_counts']['kept'] == 1
    finally:
        manager.close()


def test_limit_is_checked_again_after_summary_before_workflow(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        cid = answered(manager)
        more_answers(manager, cid)
        body = {**compact(), 'workflow': 'second_opinion'}
        payload = summarize(manager, cid, body)
        monkeypatch.setattr(manager, 'list_models', lambda agent: {'default': {'model': 'tiny'}, 'models': [{'id': 'tiny', 'context_window': 100}]})
        with pytest.raises(ContextError, match='model limit'):
            manager.fork_group(cid, payload, create=True)
        assert not manager.group_runtime.groups
    finally:
        manager.close()


@pytest.mark.parametrize('count', [0, 11, -1, 1.5, True])
def test_exchange_count_has_no_summary_only_mode(count):
    with pytest.raises(ValueError, match='between 1 and 10'):
        options(compact(count=count))


def test_short_chat_needs_no_summary_call(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        cid = answered(manager)
        group = manager.fork_group(cid, compact(count=3), create=True)['group']
        assert group['context_counts'] == {'total': 1, 'kept': 1, 'older': 0}
        assert len(clients[0].turn_params) == 1 and not clients[0].forks
    finally:
        manager.close()
