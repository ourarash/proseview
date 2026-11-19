"""A numbered recommendation is selectable with or without replacement prose."""
import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import CHANGED_SENTENCE, OPENED_SENTENCE, open_scene
from .test_btw_e2e import _open_discuss_agent
from .test_edit_selection_e2e import show_reviews
from .test_edit_notes_e2e import add_note, item_for, note_host
from .test_group_recap_e2e import edit_markdown
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def speaker_instruction(formatting):
    body = (f'> *{OPENED_SENTENCE}*\n\n'
        f'[{SCENE_REL} · Line 18](manuscript/{SCENE_REL}#L18)\n\n'
        'A new paragraph implies a new speaker. Merge it into the paragraph at '
        f'[line 17](manuscript/{SCENE_REL}#L17), or add a speaker tag.')
    if formatting == 'numbered-list':
        return '13. **Unclear speaker**\n\n' + '\n'.join('    ' + line if line else '' for line in body.splitlines())
    return ('## Agreed edits\n\n' if formatting == 'recap' else '') + '### 13. Unclear speaker\n\n' + body


@pytest.mark.parametrize('formatting', ['plain', 'recap', 'numbered-list'])
def test_instruction_items_use_heading_controls_and_send_numbers_and_notes(page, server, formatting, tmp_path):
    pane = show_reviews(page, server, [speaker_instruction(formatting)])
    checkbox = pane.get_by_role('checkbox', name='Select item 13: Unclear speaker', exact=True)
    section = item_for(checkbox)
    expect(section.locator('.edit-selection-item-heading').get_by_role('checkbox')).to_have_count(1)
    expect(section.locator('blockquote input, blockquote .edit-selection-add-note')).to_have_count(0)
    expect(section.locator('blockquote').get_by_role('button', name='Compare', exact=True)).to_have_count(0)
    expect(section.locator('.discuss-quote-compare')).to_have_count(1)
    expect(section.locator('.md-copy-btn')).to_have_count(1)
    checkbox.check()
    expect(pane.locator('.edit-selection-count')).to_contain_text('1 item selected')
    note = 'Merge into the paragraph at line 17. Keep the dialogue unchanged.'
    add_note(section, note)
    pane.locator('.edit-selection-count').click()
    review = pane.locator('.edit-selection-review')
    expect(review).to_contain_text('Suggested action')
    expect(review).to_contain_text('Merge it into the paragraph')
    expect(review).not_to_contain_text('After')
    expect(review.get_by_role('button', name='Compare passage', exact=True)).to_have_count(0)
    expect(review.get_by_role('link', name='line 17', exact=True)).to_have_count(1)
    review.get_by_role('button', name='Close selected items', exact=True).click()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expected = 'Apply item 13.\n\nFor item 13: ' + note
    expect(pane.locator('#groupInput')).to_have_value(expected)
    page.screenshot(path=str(tmp_path / 'instruction-item-selection.png'))
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    expect(checkbox).to_be_checked()
    expect(note_host(item_for(checkbox)).get_by_role('button', name='Change note for item 13', exact=True)).to_contain_text(note)
    before = server.scene_path().read_text()
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action') == 'submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(sent) == 1 and sent[0]['text'] == expected
    assert 'proseview:selected-edits' not in sent[0]['text']
    expect(item_for(checkbox).locator('.edit-selection-item-state')).to_have_text('Requested')
    assert server.scene_path().read_text() == before


def test_a_move_with_no_quoted_passage_can_be_selected(page, server):
    markdown = ('### 7. Move the explanation earlier\n\n'
        f'Move [the final paragraph](manuscript/{SCENE_REL}#L30) before '
        f'[the opening exchange](manuscript/{SCENE_REL}#L20). Keep the wording unchanged.')
    pane = show_reviews(page, server, [markdown])
    checkbox = pane.get_by_role('checkbox', name='Select item 7:', exact=False)
    checkbox.check()
    expect(pane.locator('blockquote')).to_have_count(0)
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 7.')
    outgoing = page.evaluate('editSelectionOutgoing(editSelectionGroupScope(_groupActiveSession), document.querySelector("#groupInput").value)')
    assert outgoing['text'] == 'Apply item 7.'


def test_an_instruction_missing_from_the_receiving_history_keeps_its_quotes_and_target_links(page, server):
    pane = show_reviews(page, server, [speaker_instruction('plain')])
    pane.get_by_role('checkbox', name='Select item 13:', exact=False).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    outgoing = page.evaluate('''() => {
        const scope = editSelectionGroupScope(_groupActiveSession), component = _editSelectionComposers.get(scope);
        component.session = {...component.session, turns: []};
        _groupTargetChoice = 'critic1';
        return editSelectionOutgoing(scope, document.querySelector('#groupInput').value);
    }''')
    assert 'proseview:selected-edits' in outgoing['text']
    assert '### Edit 13: Unclear speaker' in outgoing['text']
    assert OPENED_SENTENCE in outgoing['text']
    assert f'[line 17](manuscript/{SCENE_REL}#L17)' in outgoing['text']
    assert '**After:**' not in outgoing['text']


def test_existing_partial_selections_become_whole_items_and_keep_their_notes(page, server):
    blocks = []
    for index in range(3):
        block = edit_markdown('16. Three connected edits', OPENED_SENTENCE, f'An insertion for step {index + 1}.', 18).replace('**After:** Replace', '**After:** Insert after')
        blocks.append(block if not index else block.split('\n\n', 1)[1])
    pane = show_reviews(page, server, [''.join(blocks)])
    checkbox = pane.get_by_role('checkbox', name='Select item 16:', exact=False)
    expect(pane.get_by_role('checkbox')).to_have_count(1)
    page.evaluate('''() => {
        const scope = editSelectionGroupScope(_groupActiveSession), store = editSelectionStore(scope), rows = Object.values(store.records);
        rows.forEach((row, index) => row.selected = index === 1);
        store.notes[editSelectionItemKey(rows[1])] = 'Keep all three connected.';
        editSelectionSave(scope);
    }''')
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    expect(checkbox).to_be_checked()
    assert page.evaluate('editSelectionRecords(editSelectionGroupScope(_groupActiveSession)).length') == 3
    expect(note_host(item_for(checkbox)).get_by_role('button', name='Change note for item 16', exact=True)).to_contain_text('Keep all three connected.')
    checkbox.uncheck()
    assert page.evaluate('editSelectionRecords(editSelectionGroupScope(_groupActiveSession)).length') == 0
    checkbox.check()
    assert page.evaluate('editSelectionRecords(editSelectionGroupScope(_groupActiveSession)).length') == 3
    expect(item_for(checkbox).locator('blockquote input')).to_have_count(0)


def test_instruction_context_preserves_numbered_steps_inside_one_item(page, server):
    markdown = ('### 13. Move and reconnect\n\nMake these connected changes:\n\n'
        f'1. Move [the final paragraph](manuscript/{SCENE_REL}#L30) to the beginning.\n'
        '2. Remove the repeated transition.\n\n'
        '### 14. Another recommendation\n\nAdd a quieter final image.')
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(2)
    pane.get_by_role('checkbox', name='Select item 13:', exact=False).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    outgoing = page.evaluate('''() => {
        const scope = editSelectionGroupScope(_groupActiveSession), component = _editSelectionComposers.get(scope);
        component.session = {...component.session, turns: []};
        _groupTargetChoice = 'critic1';
        return editSelectionOutgoing(scope, document.querySelector('#groupInput').value);
    }''')
    assert '1. Move [the final paragraph]' in outgoing['text']
    assert '2. Remove the repeated transition.' in outgoing['text']
    assert 'Another recommendation' not in outgoing['text']


def test_connected_changes_within_one_item_do_not_require_unselecting_part_of_it(page, server):
    first = edit_markdown('4. Make the connected changes', OPENED_SENTENCE, CHANGED_SENTENCE, 18)
    second = edit_markdown('Unused heading', 'the same four digits', 'the changed four digits', 18).split('\n\n', 1)[1]
    pane = show_reviews(page, server, [first + second])
    checkbox = pane.get_by_role('checkbox', name='Select item 4:', exact=False)
    expect(pane.get_by_role('checkbox')).to_have_count(1)
    checkbox.check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 4.')
    assert page.evaluate('editSelectionRecords(editSelectionGroupScope(_groupActiveSession)).length') == 2


def test_instruction_item_selection_in_an_individual_chat(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, 'codex')
    page.locator('#discussInput').fill('SHOW_INSTRUCTION_SELECTIONS')
    page.locator('#discussSend').click()
    checkbox = page.locator('#discussLog').get_by_role('checkbox', name='Select item 13: Unclear speaker', exact=True)
    checkbox.check()
    add_note(item_for(checkbox), 'Merge it into line 17.')
    page.locator('#discussComposerArea').get_by_role('button', name='Prepare request', exact=True).click()
    expected = 'Apply item 13.\n\nFor item 13: Merge it into line 17.'
    expect(page.locator('#discussInput')).to_have_value(expected)
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if '/questions' in r.url and r.method == 'POST' else None)
    page.locator('#discussSend').click()
    page.wait_for_function('() => !_discussSnapshot.active_request_id && !_discussSnapshot.active_turn_id && _discussSnapshot.messages.filter(m => m.role === "user").length === 2')
    assert len(sent) == 1 and sent[0]['question'] == expected
    expect(item_for(checkbox).locator('.edit-selection-item-state')).to_have_text('Requested')
