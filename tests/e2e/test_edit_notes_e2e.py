"""Per-item instructions remain visible, editable, and part of the chat request."""
import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import CHANGED_SENTENCE, OPENED_SENTENCE, open_scene
from .test_btw_e2e import _open_discuss_agent
from .test_edit_selection_e2e import seed_selections, show_reviews
from .test_group_recap_e2e import edit_markdown
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def item_for(checkbox):
    return checkbox.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " edit-selection-item ")][1]')


def note_host(quote):
    return quote.locator(':scope > .edit-selection-note-host')


def add_note(quote, text):
    quote.get_by_role('button', name='Add note', exact=True).click()
    host = note_host(quote)
    host.get_by_role('textbox').fill(text)
    host.get_by_role('button', name='Done', exact=True).click()
    return host


def test_notes_update_the_request_preserve_other_writing_and_stay_out_of_quote_comparisons(page, server, tmp_path):
    pane = seed_selections(page, server)
    first = pane.get_by_role('checkbox', name='Select item 1:', exact=False)
    first.check()
    pane.get_by_role('checkbox', name='Select item 2:', exact=False).check()
    quote = item_for(first)
    note = 'Keep “same” before “four digits”.'
    host = add_note(quote, note)
    expect(quote.get_by_role('button', name='Add note', exact=True)).to_be_hidden()
    expect(host.get_by_role('button', name='Change note for item 1', exact=True)).to_have_text('Your note' + note)
    expect(host.get_by_role('button', name='Edit', exact=True)).to_have_count(0)
    expect(pane.locator('.edit-selection-ids .has-note')).to_have_count(1)

    quote.get_by_role('button', name='Compare', exact=True).last.click()
    expect(page.locator('#discussDiffModalContent')).to_contain_text(CHANGED_SENTENCE)
    expect(page.locator('#discussDiffModalContent')).not_to_contain_text(note)
    page.keyboard.press('Escape')
    initial = 'Apply items 1, 2.\n\nFor item 1: ' + note
    expect(pane.locator('#groupInput')).to_have_value(initial)
    pane.locator('#groupInput').fill('Keep the quiet tone.\n\n' + initial)

    host.get_by_role('button', name='Change note for item 1', exact=True).click()
    revised = 'Keep “same” and use “spring” instead of “March”.'
    host.get_by_role('textbox').fill(revised)
    host.get_by_role('button', name='Done', exact=True).click()
    expected = 'Keep the quiet tone.\n\nApply items 1, 2.\n\nFor item 1: ' + revised
    expect(pane.locator('#groupInput')).to_have_value(expected)
    page.screenshot(path=str(tmp_path / 'edit-notes-implemented.png'))

    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action') == 'submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(sent) == 1 and sent[0]['text'] == expected and sent[0]['authored'] == expected
    assert 'proseview:selected-edits' not in sent[0]['text']


def test_notes_survive_deselection_clearing_refresh_and_keyboard_editing(page, server):
    pane = seed_selections(page, server)
    checkbox = pane.get_by_role('checkbox', name='Select item 1:', exact=False)
    checkbox.check()
    host = add_note(item_for(checkbox), 'Use <home> & keep the first person.')
    preview = host.get_by_role('button', name='Change note for item 1', exact=True)
    preview.focus()
    page.keyboard.press('Enter')
    field = host.get_by_role('textbox')
    expect(field).to_be_focused()
    field.press('End')
    field.press_sequentially(' Keep it short.')
    page.keyboard.press('Escape')
    expect(preview).to_be_focused()
    checkbox.uncheck()
    expect(host).to_be_hidden()
    checkbox.check()
    expect(preview).to_contain_text('Keep it short.')
    pane.get_by_role('button', name='Clear', exact=True).click()
    checkbox.check()
    expect(preview).to_contain_text('Keep it short.')
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    checkbox = pane.get_by_role('checkbox', name='Select item 1:', exact=False)
    expect(checkbox).to_be_checked()
    host = note_host(item_for(checkbox))
    host.get_by_role('button', name='Change note for item 1', exact=True).click()
    expect(host.get_by_role('textbox')).to_have_value('Use <home> & keep the first person. Keep it short.')
    page.evaluate('renderSceneGroupPane()')
    expect(note_host(item_for(checkbox)).get_by_role('textbox')).to_have_value('Use <home> & keep the first person. Keep it short.')


def test_notes_can_be_changed_and_removed_directly_in_the_selection_review(page, server):
    pane = seed_selections(page, server)
    checkbox = pane.get_by_role('checkbox', name='Select item 2:', exact=False)
    checkbox.check()
    add_note(item_for(checkbox), 'Use “my home” instead of “my house”.')
    pane.locator('.edit-selection-count').click()
    review = pane.locator('.edit-selection-review')
    review.get_by_role('button', name='Change note for item 2', exact=True).click()
    review.get_by_role('textbox').fill('Keep the word apology.')
    review.get_by_role('button', name='Done', exact=True).click()
    expect(review.get_by_role('button', name='Change note for item 2', exact=True)).to_contain_text('Keep the word apology.')
    expect(pane.locator('#groupInput')).to_have_value('Apply item 2.\n\nFor item 2: Keep the word apology.')
    review.get_by_role('button', name='Change note for item 2', exact=True).click()
    review.get_by_role('button', name='Remove note', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 2.')
    expect(item_for(checkbox).get_by_role('button', name='Add note', exact=True)).to_be_visible()
    expect(pane.locator('.edit-selection-ids .has-note')).to_have_count(0)


def test_updating_notes_preserves_a_note_line_rewritten_directly_in_chat(page, server):
    pane = seed_selections(page, server)
    checkbox = pane.get_by_role('checkbox', name='Select item 1:', exact=False)
    checkbox.check()
    host = add_note(item_for(checkbox), 'Keep the original wording of the first clause.')
    text = 'Apply item 1 with my revised ending.\n\nFor item 1: Discuss the ending before changing it.'
    pane.locator('#groupInput').fill(text)
    host.get_by_role('button', name='Change note for item 1', exact=True).click()
    host.get_by_role('textbox').fill('Make the first clause shorter.')
    host.get_by_role('button', name='Done', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value(text)
    pane.get_by_role('button', name='Clear', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value(text)


def test_notes_are_sent_even_when_the_writer_does_not_click_update_request_again(page, server):
    pane = seed_selections(page, server)
    checkbox = pane.get_by_role('checkbox', name='Select item 1:', exact=False)
    checkbox.check()
    host = add_note(item_for(checkbox), 'Keep the first clause.')
    host.get_by_role('button', name='Change note for item 1', exact=True).click()
    host.get_by_role('textbox').fill('Discuss this item before applying it.')
    host.get_by_role('button', name='Done', exact=True).click()
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action') == 'submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    expected = 'Apply item 1.\n\nFor item 1: Discuss this item before applying it.'
    assert len(sent) == 1 and sent[0]['text'] == expected and sent[0]['authored'] == expected


def test_individual_notes_survive_rerenders_transfer_to_group_and_send_with_a_custom_request(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, 'codex')
    page.locator('#discussInput').fill('SHOW_EDIT_SELECTIONS')
    page.locator('#discussSend').click()
    checkbox = page.locator('#discussLog').get_by_role('checkbox', name='Select item 3:', exact=False)
    checkbox.check()
    host = add_note(item_for(checkbox), 'Keep the word same.')
    page.evaluate('renderDiscussSnapshot()')
    expect(note_host(item_for(checkbox)).get_by_role('button', name='Change note for item 3', exact=True)).to_contain_text('Keep the word same.')
    page.locator('#discussGroupFork:not([disabled])').wait_for(state='attached')
    page.locator('#discussSendMoreBtn').click()
    page.locator('#discussGroupFork:not([disabled])').click()
    page.locator('#groupForkConfirm:not([disabled])').click()
    pane = page.locator('#sceneGroupPane')
    group_checkbox = pane.get_by_role('checkbox', name='Select item 3:', exact=False)
    expect(group_checkbox).to_be_checked()
    expect(note_host(item_for(group_checkbox)).get_by_role('button', name='Change note for item 3', exact=True)).to_contain_text('Keep the word same.')
    pane.locator('#groupTargetSelect').select_option('critic1')
    pane.locator('#groupInput').fill('Apply 3 with a quieter ending.')
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action') == 'submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(sent) == 1 and sent[0]['text'] == 'Apply 3 with a quieter ending.\n\nFor item 3: Keep the word same.'
    assert 'proseview:selected-edits' not in sent[0]['text']


def test_individual_chat_sends_the_note_with_a_custom_request_without_preparing_again(page, server, tmp_path):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, 'codex')
    page.locator('#discussInput').fill('SHOW_EDIT_SELECTIONS')
    page.locator('#discussSend').click()
    checkbox = page.locator('#discussLog').get_by_role('checkbox', name='Select item 3:', exact=False)
    checkbox.check()
    quote = item_for(checkbox)
    host = add_note(quote, 'Keep the word same.')
    host.get_by_role('button', name='Change note for item 3', exact=True).click()
    host.get_by_role('textbox').fill('Keep the word same.\nUse spring instead of March.')
    page.screenshot(path=str(tmp_path / 'edit-note-editor-implemented.png'))
    host.get_by_role('button', name='Done', exact=True).click()
    page.locator('#discussInput').fill('Apply 3 with a quieter ending.')
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if '/questions' in r.url and r.method == 'POST' else None)
    page.locator('#discussSend').click()
    page.wait_for_function('() => !_discussSnapshot.active_request_id && !_discussSnapshot.active_turn_id && _discussSnapshot.messages.filter(m => m.role === "user").length === 2')
    expected = 'Apply 3 with a quieter ending.\n\nFor item 3: Keep the word same.\nUse spring instead of March.'
    assert len(sent) == 1 and sent[0]['question'] == expected
    expect(page.locator('#discussLog .user').last).to_contain_text('Use spring instead of March.')
    expect(page.locator('#discussLog .edit-selection-receipt')).to_have_count(0)


@pytest.mark.parametrize(('width', 'repeated_item'), [(1440, 16), (390, 1)])
def test_overflow_counts_items_once_and_connected_edits_share_one_note(page, server, width, repeated_item, tmp_path):
    page.set_viewport_size({'width': width, 'height': 1000})
    numbers = [1, 4, 5, 6, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19]
    blocks = []
    for number in numbers:
        for index in range(3 if number == repeated_item else 1):
            block = edit_markdown(f'{number}. A detail for item {number}', OPENED_SENTENCE, f'An extra beat for item {number}, change {index + 1}.', 18).replace('**After:** Replace', '**After:** Insert after')
            blocks.append(block if not index else block.split('\n\n', 1)[1])
    pane = show_reviews(page, server, [''.join(blocks)])
    checkboxes = pane.get_by_role('checkbox')
    expect(checkboxes).to_have_count(14)
    for checkbox in checkboxes.all():
        checkbox.check()
    expect(pane.locator('.edit-selection-count')).to_contain_text('14 items selected')
    assert pane.locator('.edit-selection-ids button[data-selection-key]').all_text_contents() == ['1', '4', '5', '6', '9']
    more = pane.get_by_role('button', name='+9 more', exact=True)
    expect(more).to_be_visible()
    add_note(item_for(pane.get_by_role('checkbox', name=f'Select item {repeated_item}:', exact=False).first), 'Keep these changes together.')
    for checkbox in pane.get_by_role('checkbox', name=f'Select item {repeated_item}:', exact=False).all():
        expect(note_host(item_for(checkbox)).get_by_role('button', name=f'Change note for item {repeated_item}', exact=True)).to_contain_text('Keep these changes together.')
    more.click()
    panel = pane.locator('.edit-selection-review')
    expect(panel).to_be_visible()
    expect(panel.locator('.edit-selection-review-head')).to_contain_text('14 items · 16 edits')
    expect(panel.locator('.edit-selection-review-item')).to_have_count(14)
    expect(panel.locator('.edit-selection-review-edit')).to_have_count(16)
    expect(panel.get_by_role('button', name=f'Change note for item {repeated_item}', exact=True)).to_have_count(1)
    panel.get_by_role('button', name='Close selected items', exact=True).click()
    draft = pane.locator('#groupInput').input_value()
    assert draft.startswith('Apply items ' + ', '.join(map(str, numbers)) + '.')
    assert draft.count('For item ' + str(repeated_item) + ': Keep these changes together.') == 1
    assert pane.locator('.edit-selection-composer').evaluate('element => element.getBoundingClientRect().right <= innerWidth + 1')
    page.screenshot(path=str(tmp_path / 'selected-items-with-notes.png'))


def test_equal_numbers_in_different_reviews_have_separate_notes_and_counts(page, server):
    other = 'He carried two mugs and a look that had been his apology for months.'
    pane = show_reviews(page, server, [
        edit_markdown('1. Make the code change explicit', OPENED_SENTENCE, CHANGED_SENTENCE, 18),
        edit_markdown('1. Simplify the entrance', other, 'He carried two mugs and the same apologetic look.', 20),
    ])
    first, second = pane.get_by_role('checkbox', name='Select item 1:', exact=False).all()
    first.check()
    second.check()
    add_note(item_for(first), 'Keep same.')
    expect(item_for(second).get_by_role('button', name='Add note', exact=True)).to_be_visible()
    add_note(item_for(second), 'Keep apology.')
    expect(pane.locator('.edit-selection-count')).to_contain_text('2 items selected')
    draft = pane.locator('#groupInput').input_value()
    assert 'For item 1 (“Make the code change explicit”): Keep same.' in draft
    assert 'For item 1 (“Simplify the entrance”): Keep apology.' in draft
