"""Selections use the review's item numbers without repeating available proposals."""
import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import CHANGED_SENTENCE, OPENED_SENTENCE, open_scene
from .test_btw_e2e import _open_discuss_agent
from .test_group_recap_e2e import edit_markdown
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def seed_selections(page, server, insertion=False):
    source = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(source, 1) if OPENED_SENTENCE in text)
    other = 'He carried two mugs and a look that had been his apology for months.'
    other_line = next(i for i, text in enumerate(source, 1) if other in text)
    markdown = ('## Agreed edits\n\n'
        + edit_markdown('1. Make the code change explicit', OPENED_SENTENCE, CHANGED_SENTENCE, line)
        + edit_markdown('2. Simplify the entrance', other, 'He carried two mugs and the same apologetic look.', other_line)
        + '## Choices for you\n\n'
        + edit_markdown('3. An alternative code detail', OPENED_SENTENCE, 'She had reset the code in March.', line))
    if insertion:
        markdown += f'\n\n### 4. Add the consequence\n\n**After:** Insert after [Opening · Line {line}](manuscript/{SCENE_REL}#L{line}):\n\n> It would not even be working off campus.'
    response = server.post_json('/api/discuss/group-history', {'action':'save', 'session': {
        'id':'selected-edits-demo', 'scene':SCENE_REL, 'title':'Choose revisions', 'turns':[
            {'role':'user', 'text':'Consider these revisions.'},
            {'role':'critic', 'seat':1, 'agent':'codex', 'tag':'Recap', 'text':markdown}]}})
    assert response.json()['ok']
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane=page.locator('#sceneGroupPane')
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).wait_for()
    return pane


@pytest.mark.parametrize('width', [1440, 800])
def test_selections_review_compare_and_prepare_do_not_send_or_apply_and_survive_reload(page, server, width, tmp_path):
    page.set_viewport_size({'width':width, 'height':1000})
    pane=seed_selections(page, server)
    before=server.scene_path().read_text()
    submissions=[]
    page.on('request', lambda r: submissions.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action')=='submit' else None)
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    pane.get_by_role('checkbox', name='Select item 2:', exact=False).check()
    tray=pane.locator('.edit-selection-composer')
    expect(tray.locator('.edit-selection-count')).to_contain_text('2 items selected')
    expect(pane.locator('#groupQuickSend')).to_be_hidden()
    tray.locator('.edit-selection-count').click()
    expect(tray.locator('.edit-selection-review')).to_be_visible()
    expect(tray.locator('.edit-selection-review-item').first.locator('p em')).to_have_text(OPENED_SENTENCE)
    expect(tray.locator('.edit-selection-review-item').first.locator('a')).to_contain_text('Line 18')
    tray.get_by_role('button', name='Compare passage', exact=True).first.click()
    expect(page.locator('#discussDiffModalContent td.diff_sub')).to_contain_text(OPENED_SENTENCE)
    page.keyboard.press('Escape')
    tray.get_by_role('button', name='Close selected items', exact=True).click()
    tray.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply items 1, 2.')
    expect(tray.locator('.edit-selection-included')).to_contain_text('2 items included')
    assert pane.locator('#groupTargetSelect').input_value()=='critic1'
    assert submissions==[]
    assert server.scene_path().read_text()==before
    page.screenshot(path=str(tmp_path/'selected-edits.png'))
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    expect(pane.get_by_role('checkbox', name='Select item 1:', exact=False)).to_be_checked()
    expect(pane.locator('#groupInput')).to_have_value('Apply items 1, 2.')
    tray.locator('.edit-selection-count').click()
    tray.get_by_role('button', name='Remove item 2', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply item 1.')
    tray.get_by_role('button', name='Clear', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('')
    expect(tray).to_be_hidden()
    expect(pane.locator('#groupQuickSend')).to_be_visible()


def test_group_custom_instructions_are_sent_without_repeating_proposals_in_shared_history(page, server):
    pane=seed_selections(page, server)
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    pane.get_by_role('checkbox', name='Select item 2:', exact=False).check()
    text='Apply 1 as proposed. For 2, keep the word apology and make it shorter.'
    pane.locator('#groupInput').fill(text)
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value(text)
    submitted=[]
    page.on('request', lambda r: submitted.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action')=='submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(submitted)==1
    request=submitted[0]
    assert request['authored']==text and request['text']==text
    assert len(request['seats'])==1
    assert 'proseview:selected-edits' not in request['text']
    expect(pane.locator('.edit-selection-receipt')).to_have_count(0)
    expect(pane.locator('.edit-selection-item-heading').first).to_contain_text('Requested')
    expect(pane.locator('.edit-selection-composer')).to_be_hidden()


def test_overlapping_wordings_require_a_choice_and_custom_draft_changes_are_not_rewritten(page, server):
    pane=seed_selections(page, server)
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    pane.get_by_role('checkbox', name='Select item 3:', exact=False).check()
    pane.get_by_role('button', name='Choose wording', exact=True).click()
    expect(pane.locator('.edit-selection-conflict')).to_contain_text('overlapping passages')
    submitted=[]
    page.on('request', lambda r: submitted.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action')=='submit' else None)
    pane.locator('#groupSendBtn').click()
    assert submitted==[]
    text='Apply 1 with a quieter ending. Discuss 3 before changing it.'
    pane.locator('#groupInput').fill(text)
    expect(pane.locator('#groupInput')).to_have_value(text)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(submitted)==1 and submitted[0]['text'].startswith(text)


def test_custom_notes_survive_removing_and_clearing_prepared_selections(page, server):
    pane=seed_selections(page,server)
    pane.get_by_role('checkbox',name='Select item 1:',exact=False).check()
    pane.get_by_role('checkbox',name='Select item 2:',exact=False).check()
    pane.get_by_role('button',name='Prepare request',exact=True).click()
    text='Apply 1 with a quieter ending. For 2, keep the word apology.'
    pane.locator('#groupInput').fill(text)
    pane.locator('.edit-selection-count').click()
    pane.get_by_role('button',name='Remove item 2',exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value(text)
    pane.get_by_role('button',name='Clear',exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value(text)


def test_requested_is_separate_from_a_verified_applied_replacement(page, server):
    pane=seed_selections(page, server)
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    pane.locator('#groupInput').fill('SELECT_FILE_CHANGE Apply 1.')
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    expect(pane.locator('.edit-selection-item-heading').first).to_contain_text('Applied')
    assert CHANGED_SENTENCE in server.scene_path().read_text()
    pane.locator('.group-tool-review').get_by_role('button', name='Undo all', exact=True).click()
    expect(pane.locator('.edit-selection-item-heading').first).to_contain_text('Requested')
    assert OPENED_SENTENCE in server.scene_path().read_text()


def test_individual_review_selections_transfer_to_group_and_the_individual_request_stays_editable(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, 'codex')
    page.locator('#discussInput').fill('SHOW_EDIT_SELECTIONS')
    page.locator('#discussSend').click()
    checkbox=page.locator('#discussLog').get_by_role('checkbox', name='Select item 3:', exact=False)
    checkbox.wait_for()
    checkbox.check()
    tray=page.locator('#discussComposerArea .edit-selection-composer')
    expect(tray.locator('.edit-selection-count')).to_contain_text('1 item selected')
    page.locator('#discussInput').fill('Apply 3, but retain the word same.')
    tray.get_by_role('button', name='Prepare request', exact=True).click()
    expect(page.locator('#discussInput')).to_have_value('Apply 3, but retain the word same.')
    page.locator('#discussGroupFork:not([disabled])').click()
    page.locator('#groupForkConfirm:not([disabled])').click()
    pane=page.locator('#sceneGroupPane')
    expect(pane.locator('.edit-selection-count')).to_contain_text('1 item selected')
    expect(pane.get_by_role('checkbox', name='Select item 3:', exact=False)).to_be_checked()
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-item p em')).to_have_text(OPENED_SENTENCE)
    with page.expect_response(lambda response: '/history/' in response.url and response.url.endswith('/open')) as restored:
        pane.get_by_role('button', name='Source chat ↗', exact=True).click()
    assert restored.value.ok and restored.value.json()['ok']
    page.wait_for_selector('#discussLog', state='visible')
    expect(checkbox).to_be_checked()
    expect(page.locator('#discussInput')).to_have_value('Apply 3, but retain the word same.')


def test_individual_send_uses_original_numbers_without_changing_the_writers_instruction(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, 'codex')
    page.locator('#discussInput').fill('SHOW_EDIT_SELECTIONS')
    page.locator('#discussSend').click()
    checkbox=page.locator('#discussLog').get_by_role('checkbox', name='Select item 3:', exact=False)
    checkbox.wait_for()
    checkbox.check()
    text='Apply item 3, but keep the word same. Explain item 5 before changing it.'
    page.locator('#discussInput').fill(text)
    page.locator('#discussComposerArea').get_by_role('button', name='Prepare request', exact=True).click()
    sent=[]
    page.on('request', lambda r: sent.append(r.post_data_json) if '/questions' in r.url and r.method=='POST' else None)
    page.locator('#discussSend').click()
    page.wait_for_function('() => !_discussSnapshot.active_request_id && !_discussSnapshot.active_turn_id && _discussSnapshot.messages.filter(m=>m.role==="user").length===2')
    assert len(sent)==1
    assert sent[0]['question']==text
    expect(page.locator('#discussLog .edit-selection-item-heading').first).to_contain_text('Requested')
    expect(page.locator('#discussLog .edit-selection-receipt')).to_have_count(0)


@pytest.mark.parametrize('operation', ['Insert after', 'Insert before', 'Replace', ''])
def test_explicit_edits_without_a_before_quote_are_selectable_and_keep_their_operation(page, server, operation, tmp_path):
    source=(server.root/'manuscript'/SCENE_REL).read_text().splitlines()
    line=next(i for i,text in enumerate(source,1) if OPENED_SENTENCE in text)
    replacement="It wouldn't even be working off campus."
    reference=f'[Opening · Line {line}](manuscript/{SCENE_REL}#L{line})'
    markdown=f'### 1. Anchor the explanation\n\n**After:** {operation} {reference}:\n\n> {replacement}'
    server.post_json('/api/discuss/group-history', {'action':'save','session':{
        'id':'standalone-selection','scene':SCENE_REL,'title':'Line-anchored edit', 'turns':[
            {'role':'critic','seat':1,'agent':'codex','text':markdown}]}})
    open_scene(page,server,SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane=page.locator('#sceneGroupPane')
    checkbox=pane.get_by_role('checkbox',name='Select item 1:',exact=False)
    expect(checkbox).to_be_visible()
    checkbox.check()
    prepare=pane.get_by_role('button',name='Prepare request',exact=True)
    expect(prepare).to_be_enabled()
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-item p em')).to_contain_text(OPENED_SENTENCE)
    pane.locator('.edit-selection-review-item').get_by_role('button',name='Compare passage',exact=True).click()
    expect(page.locator('#discussDiffModalContent')).to_contain_text(replacement)
    if operation.startswith('Insert'):
        assert page.locator('#discussDiffModalContent del.diff-delete').count()==0
    page.keyboard.press('Escape')
    pane.get_by_role('button',name='Close selected items',exact=True).click()
    prepare.click()
    if operation=='Insert after':
        page.screenshot(path=str(tmp_path/'selected-insertion.png'))
    sent=[]
    page.on('request',lambda r:sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action')=='submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(sent)==1
    assert sent[0]['text']=='Apply item 1.'


def test_a_missing_anchor_is_flagged_instead_of_sending_a_guessed_edit(page, server):
    markdown=f'### 1. Missing anchor\n\n**After:** Insert after [Opening · Line 999](manuscript/{SCENE_REL}#L999):\n\n> A proposed insertion.'
    server.post_json('/api/discuss/group-history',{'action':'save','session':{
        'id':'missing-selection-anchor','scene':SCENE_REL,'title':'Check the source','turns':[
            {'role':'critic','seat':1,'agent':'codex','text':markdown}]}})
    open_scene(page,server,SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane=page.locator('#sceneGroupPane')
    checkbox=pane.get_by_role('checkbox',name='Select item 1:',exact=False)
    checkbox.click()
    expect(pane.locator('.edit-selection-item-heading')).to_contain_text('Check source')
    expect(checkbox).not_to_be_checked()
    expect(pane.locator('.edit-selection-composer')).to_be_hidden()
    assert 'Could not locate' in pane.locator('.edit-selection-control').get_attribute('title')


def test_an_insertion_and_a_replacement_at_its_anchor_can_be_selected_together(page, server):
    pane=seed_selections(page,server,insertion=True)
    pane.get_by_role('checkbox',name='Select item 1:',exact=False).check()
    pane.get_by_role('checkbox',name='Select item 4:',exact=False).check()
    prepare=pane.get_by_role('button',name='Prepare request',exact=True)
    expect(prepare).to_be_enabled()
    prepare.click()
    expect(pane.locator('#groupInput')).to_have_value('Apply items 1, 4.')
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-conflict')).to_have_count(0)


def show_reviews(page, server, reviews):
    response = server.post_json('/api/discuss/group-history', {'action': 'save', 'session': {
        'id': 'original-item-numbers', 'scene': SCENE_REL, 'title': 'Original item numbers',
        'turns': [{'role': 'critic', 'seat': 1, 'agent': 'codex', 'text': text} for text in reviews]}})
    assert response.json()['ok']
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator('#sceneGroupPane')
    pane.locator('.group-turn-body').first.wait_for()
    return pane


@pytest.mark.parametrize('formatting', ['headings', 'ordered-list', 'bold', 'ordered-list-start-3'])
def test_original_numbers_survive_skipped_items_and_inserts_and_send_only_the_instruction(page, server, formatting):
    other = 'He carried two mugs and a look that had been his apology for months.'
    link = f'[Opening · Line 18](manuscript/{SCENE_REL}#L18)'
    blocks = [
        ('Make the code change explicit', f'**Type: Strengthen existing humor**\n\n**Before:**\n\n> *{OPENED_SENTENCE}*\n\n{link}\n\n**After:** Replace {link}:\n\n> {CHANGED_SENTENCE}'),
        ('Keep the hesitation', ''),
        ('Add the consequence', f'**Type: Comic opportunity**\n\n**After:** Insert after {link}:\n\n> It would not even be working off campus.'),
        ('Keep the silence', ''),
        ('Simplify the entrance', edit_markdown('Unused heading', other, 'He carried two mugs and the same apologetic look.', 20).split('\n\n', 1)[1]),
    ]
    parts = []
    start = 3 if formatting == 'ordered-list-start-3' else 1
    for number, (title, body) in enumerate(blocks, start):
        if formatting.startswith('ordered-list'):
            parts.append(f'{number}. **{title}**\n\n' + '\n'.join('   ' + line if line else '' for line in body.splitlines()))
        else:
            heading = f'### {number}. {title}' if formatting == 'headings' else f'**{number}. {title}**'
            parts.append(heading + '\n\n' + body)
    pane = show_reviews(page, server, ['\n\n'.join(parts)])
    expect(pane.get_by_role('checkbox')).to_have_count(3)
    for number in [start + 4, start, start + 2]:
        pane.get_by_role('checkbox', name=f'Select item {number}:', exact=False).check()
    prepare = pane.get_by_role('button', name='Prepare request', exact=True)
    expect(prepare).to_be_enabled()
    prepare.click()
    instruction = f'Apply items {start}, {start + 2}, {start + 4}.'
    expect(pane.locator('#groupInput')).to_have_value(instruction)
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-title').first).to_contain_text(f'{start}. Make the code change explicit')
    assert 'Type:' not in pane.locator('.edit-selection-review').inner_text()
    sent = []
    page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/api/discuss/group-run') and r.post_data_json.get('action') == 'submit' else None)
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    assert len(sent) == 1 and sent[0]['text'] == instruction


def test_unnumbered_suggestions_are_referred_to_by_title(page, server):
    pane = show_reviews(page, server, ['### 1. Keep the hesitation\n\nThis beat works.\n\n' + edit_markdown('Make the code change explicit', OPENED_SENTENCE, CHANGED_SENTENCE, 18)])
    pane.get_by_role('checkbox', name='Select item: Make the code change explicit', exact=True).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply item “Make the code change explicit”.')
    scope = page.evaluate('editSelectionGroupScope(_groupActiveSession)')
    outgoing = page.evaluate('(scope) => editSelectionOutgoing(scope, document.querySelector("#groupInput").value)', scope)
    assert outgoing['text'] == 'Apply item “Make the code change explicit”.'


def test_older_reviews_get_a_short_reference_when_item_numbers_repeat(page, server):
    other = 'He carried two mugs and a look that had been his apology for months.'
    pane = show_reviews(page, server, [
        edit_markdown('1. Make the code change explicit', OPENED_SENTENCE, CHANGED_SENTENCE, 18),
        edit_markdown('1. Simplify the entrance', other, 'He carried two mugs and the same apologetic look.', 26),
    ])
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).first.check()
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).last.check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    expect(pane.locator('#groupInput')).to_have_value('Apply items 1 (“Make the code change explicit”), 1 (“Simplify the entrance”).')
    outgoing = page.evaluate('editSelectionOutgoing(editSelectionGroupScope(_groupActiveSession), document.querySelector("#groupInput").value)')
    assert 'Selected items from earlier reviews:' in outgoing['text']
    assert 'item 1: Make the code change explicit' in outgoing['text']
    assert 'proseview:selected-edits' not in outgoing['text']
    assert CHANGED_SENTENCE not in outgoing['text']


def test_only_proposals_missing_from_the_receiving_history_are_included(page, server):
    pane = seed_selections(page, server)
    pane.get_by_role('checkbox', name='Select item 1:', exact=False).check()
    pane.get_by_role('checkbox', name='Select item 2:', exact=False).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    outgoing = page.evaluate('''replacement => {
        const scope = editSelectionGroupScope(_groupActiveSession);
        const component = _editSelectionComposers.get(scope);
        _groupTargetChoice = 'critic1';
        component.session = {...component.session, turns: [{role: 'critic', text: '### 1. Make the code change explicit\\n\\n' + replacement}]};
        return editSelectionOutgoing(scope, 'Apply items 1, 2.');
    }''', CHANGED_SENTENCE)
    assert outgoing['text'].startswith('Apply items 1, 2.')
    assert '### Edit 2: Simplify the entrance' in outgoing['text']
    assert '### Edit 1:' not in outgoing['text']
    assert CHANGED_SENTENCE not in outgoing['text']


@pytest.mark.parametrize('custom', [False, True])
def test_saved_selections_migrate_to_original_numbers_and_update_only_generated_drafts(page, server, custom):
    pane = show_reviews(page, server, [
        edit_markdown('1. Make the code change explicit', OPENED_SENTENCE, CHANGED_SENTENCE, 18)
        + edit_markdown('5. Add the code detail', OPENED_SENTENCE, 'She had reset the code in March.', 18)])
    pane.get_by_role('checkbox', name='Select item 5:', exact=False).check()
    pane.get_by_role('button', name='Prepare request', exact=True).click()
    page.evaluate('''() => {
        const scope = editSelectionGroupScope(_groupActiveSession), store = editSelectionStore(scope);
        Object.values(store.records).forEach((row, i) => { delete row.itemVersion; row.number = i + 1; row.title = 'Type: Comic opportunity'; });
        store.prepared.generated = 'Apply edit 2.';
        editSelectionSave(scope);
    }''')
    pane.locator('#groupInput').fill('Apply 5 with a quieter ending.' if custom else 'Apply edit 2.')
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    expect(pane.get_by_role('checkbox', name='Select item 5:', exact=False)).to_be_checked()
    expect(pane.locator('#groupInput')).to_have_value('Apply 5 with a quieter ending.' if custom else 'Apply item 5.')
    pane.locator('.edit-selection-count').click()
    expect(pane.locator('.edit-selection-review-title')).to_contain_text('5. Add the code detail')
