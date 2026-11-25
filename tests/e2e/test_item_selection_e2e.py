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
    expect(pane.locator('#groupInput')).to_have_value('Apply item 7.')
    outgoing = page.evaluate('editSelectionOutgoing(editSelectionGroupScope(_groupActiveSession), document.querySelector("#groupInput").value)')
    assert outgoing['text'] == 'Apply item 7.'


def test_an_instruction_missing_from_the_receiving_history_keeps_its_quotes_and_target_links(page, server):
    pane = show_reviews(page, server, [speaker_instruction('plain')])
    pane.get_by_role('checkbox', name='Select item 13:', exact=False).check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 13.')
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
    expect(pane.locator('#groupInput')).to_have_value('Apply item 13.')
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
    expected = 'Apply item 13.\n\nFor item 13: Merge it into line 17.'
    expect(page.locator('#discussInput')).to_have_value(expected)
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if '/questions' in r.url and r.method == 'POST' else None)
    page.locator('#discussSend').click()
    page.wait_for_function('() => !_discussSnapshot.active_request_id && !_discussSnapshot.active_turn_id && _discussSnapshot.messages.filter(m => m.role === "user").length === 2')
    assert len(sent) == 1 and sent[0]['question'] == expected
    expect(item_for(checkbox).locator('.edit-selection-item-state')).to_have_text('Requested')


def test_standalone_option_rewrites_get_checkboxes_and_detect_overlap(page, server):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    ref = f'[line {line}](manuscript/{SCENE_REL}#L{line})'
    markdown = (
        'Yes. The easiest way is to let the detail do the work. (Note: **biceps** and **pecs**.)\n\n'
        '**Option 1 (the shirt does the work)**\n\n'
        f'> {CHANGED_SENTENCE}\n\n{ref}\n\n'
        '**Option 2 (shorter)**\n\n'
        f'> She had reset the code in March.\n\n{ref}\n\n'
        '**Option 3 (with emphasis)**\n\n'
        f'> She had *already* reset the code in March.\n\n{ref}'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(3)
    opt1 = pane.get_by_role('checkbox', name='Select item: Option 1 (the shirt does the work)', exact=True)
    opt2 = pane.get_by_role('checkbox', name='Select item: Option 2 (shorter)', exact=True)
    opt3 = pane.get_by_role('checkbox', name='Select item: Option 3 (with emphasis)', exact=True)
    expect(opt1).to_be_visible()
    expect(opt2).to_be_visible()
    expect(opt3).to_be_visible()
    opt1.check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item “Option 1 (the shirt does the work)”.')
    opt2.check()
    expect(pane.get_by_role('button', name='Choose wording', exact=True)).to_be_visible()
    opt2.uncheck()
    expect(pane.locator('#groupInput')).to_have_value('Apply item “Option 1 (the shirt does the work)”.')
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-item p em')).to_contain_text(OPENED_SENTENCE)


def test_paired_trim_section_stays_one_checkbox_even_when_trimmed_line_exists_in_scene(page, server):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    other = 'He carried two mugs and a look that had been his apology for months.'
    other_line = next(i for i, text in enumerate(source, 1) if other in text)
    span_ref = f'[lines {line}–{other_line}](manuscript/{SCENE_REL}#L{line}-L{other_line})'
    markdown = (
        '**The trim**\n\n'
        'Cut the redundant line from this passage:\n\n'
        f'> *{OPENED_SENTENCE}*\n\n{span_ref}\n\n'
        'Trimmed, the passage reads:\n\n'
        f'> {other}\n\n{span_ref}\n\n'
        'That keeps the beat moving straight into the next line.'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(1)
    checkbox = pane.get_by_role('checkbox', name='Select item: The trim', exact=True)
    checkbox.check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item “The trim”.')


def test_numbered_standalone_options_all_get_replacement_checkboxes(page, server):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    ref = f'[line {line}](manuscript/{SCENE_REL}#L{line})'
    markdown = (
        '**Options**\n\n'
        '**1. Plain, with a jab (recommended)**\n\n'
        f'> {CHANGED_SENTENCE}\n\n{ref}\n\n'
        '**2. Plain, with how he says it**\n\n'
        f'> She had reset the code in March.\n\n{ref}\n\n'
        '**3. Definition only**\n\n'
        f'> She changed the code.\n\n{ref}\n\n'
        'My vote is 1 — it keeps the dry voice.'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(3)
    for number in (1, 2, 3):
        expect(pane.get_by_role('checkbox', name=f'Select item {number}:', exact=False)).to_be_visible()
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 1.')
    kinds = page.evaluate('Object.values(editSelectionStore(editSelectionGroupScope(_groupActiveSession)).records).map(r => r.kind)')
    assert kinds == ['replace', 'replace', 'replace']


def test_unheaded_rewrite_gets_checkbox_outside_blockquote_while_verbatim_plain_citation_does_not(page, server):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    ref = f'[line {line}](manuscript/{SCENE_REL}#L{line})'
    citation_only = f'Look closely at this line:\n\n> {OPENED_SENTENCE}\n\n{ref}'
    casual_epigraph = 'As the old craft rule puts it:\n\n> Show, do not tell.'
    standalone_rewrite = f'Try tightening that beat like this:\n\n> {CHANGED_SENTENCE}\n\n{ref}'
    pane = show_reviews(page, server, [citation_only, casual_epigraph, standalone_rewrite])
    expect(pane.get_by_role('checkbox')).to_have_count(1)
    expect(pane.locator('blockquote input')).to_have_count(0)
    checkbox = pane.get_by_role('checkbox').first
    checkbox.check()
    expect(pane.locator('#groupInput')).to_have_value(f'Apply item “{CHANGED_SENTENCE}”.')
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-item p em')).to_contain_text(OPENED_SENTENCE)


def test_numbered_options_without_line_numbers_all_get_checkboxes_and_prepare_cleanly(page, server):
    markdown = (
        'Yes. "What kind of maybe" is too indirect, so say it directly.\n\n'
        '**1. Plain (recommended)**\n\n'
        '> I turn back to Roksana. I want to know if that\'s really her name.\n\n'
        '**2. Names the name**\n\n'
        '> I turn back to Roksana. I want to know if Roksana is really her name.\n\n'
        '**3. Real name versus work name**\n\n'
        '> I turn back to Roksana. I want to know if Roksana is her real name or just the one she uses here.\n\n'
        'Option 1 keeps the scene moving.'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(3)
    for number in (1, 2, 3):
        expect(pane.get_by_role('checkbox', name=f'Select item {number}:', exact=False)).to_be_visible()
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 1.')
    pane.locator('.edit-selection-count').click()
    review = pane.locator('.edit-selection-review')
    expect(review).to_contain_text('Proposed wording')
    expect(review).to_contain_text("I want to know if that's really her name.")
    review.get_by_role('button', name='Close selected items', exact=True).click()


def test_numbered_and_option_rewrites_still_register_when_item_matches_current_scene(page, server):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    ref = f'[line {line}](manuscript/{SCENE_REL}#L{line})'
    markdown = (
        '**1. Plain (recommended)**\n\n'
        f'> {OPENED_SENTENCE}\n\n{ref}\n\n'
        '**Option A** (shorter)\n\n'
        f'> {CHANGED_SENTENCE}\n\n{ref}\n\n'
        '**Tighter opening**\n\n'
        f'> She had reset the code in March.\n\n{ref}'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(3)
    expect(pane.get_by_role('checkbox', name='Select item 1: Plain (recommended)', exact=True)).to_be_visible()
    expect(pane.get_by_role('checkbox', name='Select item: Option A (shorter)', exact=True)).to_be_visible()
    tighter = pane.get_by_role('checkbox', name='Select item: Tighter opening', exact=True)
    tighter.check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item “Tighter opening”.')
    # Simulate applying Tighter opening to the scene and reloading: saved record stays wrapped.
    body = server.get_json('/data.json')['contents'][SCENE_REL]
    assert server.save_scene(body.replace(OPENED_SENTENCE, 'She had reset the code in March.')).json()['ok']
    page.evaluate('''() => {
        const scope = editSelectionGroupScope(_groupActiveSession), store = editSelectionStore(scope);
        Object.values(store.records).forEach(r => { if (r.title === 'Tighter opening') { r.requested = Date.now(); r.applied = true; r.selected = false; } });
        editSelectionSave(scope);
    }''')
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    expect(pane.locator('.edit-selection-item-heading', has_text='Tighter opening')).to_contain_text('Applied')


def test_curly_quote_verbatim_citation_does_not_get_checkbox(page, server):
    body = server.get_json('/data.json')['contents'][SCENE_REL]
    assert server.save_scene(body.replace(OPENED_SENTENCE, "She\u2019d used the same four digits since spring.")).json()['ok']
    source = server.scene_path().read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if "She\u2019d used" in text)
    ref = f'[line {line}](manuscript/{SCENE_REL}#L{line})'
    markdown = f"Look at this line:\n\n> She'd used the same four digits since spring.\n\n{ref}"
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(0)


def test_numbered_item_with_table_body_gets_item_checkbox(page, server):
    markdown = (
        '### 1. Cutting the hotel\n\n'
        '| What happens | Files |\n'
        '| --- | --- |\n'
        f'| Cut | [01-opening.md](manuscript/{SCENE_REL}) |\n'
        '| Salvage | Keep the quiet entrance. |\n\n'
        '### 2. Cuts that still apply\n\n'
        '| Line | Cut or change |\n'
        '| --- | --- |\n'
        f'| [18](manuscript/{SCENE_REL}#L18) | Trim the opening sentence. |\n'
        f'| [20](manuscript/{SCENE_REL}#L20) | Cut the apology line. |'
    )
    pane = show_reviews(page, server, [markdown])
    expect(pane.get_by_role('checkbox')).to_have_count(2)
    first = pane.get_by_role('checkbox', name='Select item 1: Cutting the hotel', exact=True)
    second = pane.get_by_role('checkbox', name='Select item 2: Cuts that still apply', exact=True)
    first.check()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 1.')
    second.check()
    expect(pane.locator('#groupInput')).to_have_value('Apply items 1, 2.')
    pane.locator('.edit-selection-count').click()
    review = pane.locator('.edit-selection-review')
    expect(review).to_contain_text('Salvage: Keep the quiet entrance.')
    expect(review).to_contain_text('18: Trim the opening sentence.')
