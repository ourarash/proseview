"""Free-chat recap presentation and navigation, without a model output schema."""
import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import CHANGED_SENTENCE, OPENED_SENTENCE, open_scene
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def edit_markdown(title, original, replacement, line):
    link = f'[{SCENE_REL} · Line {line}](manuscript/{SCENE_REL}#L{line})'
    return (f'### {title}\n\n**Before:**\n\n> *{original}*\n\n{link}\n\n'
            f'**Why:** Make the action clearer.\n\n**After:** Replace {link}:\n\n> ' + replacement.replace('\n', '\n> ') + '\n\n')


def seed_recap(page, server, *, long=False):
    lines = (server.root / 'manuscript' / SCENE_REL).read_text().splitlines()
    line = next(i for i, text in enumerate(lines, 1) if OPENED_SENTENCE in text)
    replacement = CHANGED_SENTENCE + (' More of the complete replacement.' * 35 + '\n\nA second paragraph.' * 12 if long else '')
    recap = ('## Agreed edits\n\n' + edit_markdown('Clarify the safe combination', OPENED_SENTENCE, replacement, line)
             + '## Choices for you\n\n' + edit_markdown('Consider another wording', OPENED_SENTENCE, 'An alternative the agents have not agreed on.', line)
             + '## Withdrawn (1)\n\nKeep the original weather line; the proposed metaphor was withdrawn.')
    result = server.post_json('/api/discuss/group-history', {'action': 'save', 'session': {
        'id': 'recap-presentation', 'scene': SCENE_REL, 'title': 'Editing the opening',
        'turns': [{'role': 'user', 'text': 'Review the opening. ' * 90},
                  {'role': 'critic', 'seat': 1, 'agent': 'codex', 'text': 'Earlier discussion. ' * 100},
                  {'role': 'critic', 'seat': 2, 'agent': 'claude', 'tag': 'Recap', 'text': recap},
                  {'role': 'user', 'text': 'Keep these proposals ready for review.'}]}})
    assert result.json()['ok']
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    page.locator('.group-edit-card').first.wait_for()
    return page.locator('#sceneGroupPane'), replacement


@pytest.mark.parametrize('width', [1440, 800])
def test_markdown_recap_cards_keep_full_pasteable_text_and_collapse_withdrawals(page, server, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    pane, replacement = seed_recap(page, server, long=True)
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    cards = pane.locator('.group-edit-card')
    assert cards.count() == 2
    first = cards.first
    assert first.locator('blockquote em').first.inner_text() == OPENED_SENTENCE
    assert first.locator('.group-edit-status').inner_text() == 'Agreed'
    assert cards.nth(1).locator('.group-edit-status').inner_text() == 'Your choice'
    assert first.locator('.group-edit-source').get_attribute('data-prosview-path') == SCENE_REL
    assert not first.evaluate('el => el.classList.contains("is-edit-expanded")')
    first.get_by_role('button', name='Expand full edit', exact=True).click()
    assert first.evaluate('el => el.classList.contains("is-edit-expanded")')
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    first.get_by_role('button', name='Copy replacement', exact=True).click()
    assert page.evaluate('navigator.clipboard.readText()') == replacement
    assert not pane.locator('.is-withdrawn').evaluate('el => el.open')
    assert 'proposed metaphor was withdrawn' not in pane.inner_text()
    pane.locator('.is-withdrawn > summary').click()
    assert 'proposed metaphor was withdrawn' in pane.inner_text()
    assert first.evaluate('el => el.scrollWidth <= el.clientWidth + 1')


def test_group_message_collapsing_survives_rerenders_reload_and_latest_recap_navigation(page, server):
    pane, _ = seed_recap(page, server)
    earlier = pane.locator('.group-turn-card').nth(1)
    earlier.locator('.group-message-toggle').click()
    assert earlier.evaluate('el => el.classList.contains("is-message-collapsed")')
    assert earlier.locator('.group-message-preview').is_visible()
    page.evaluate('renderSceneGroupPane()')
    assert earlier.evaluate('el => el.classList.contains("is-message-collapsed")')
    pane.get_by_role('button', name='Collapse earlier messages', exact=True).click()
    assert pane.locator('.group-recap-message').evaluate('el => el.classList.contains("is-message-collapsed")')
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    assert not pane.locator('.group-recap-message').evaluate('el => el.classList.contains("is-message-collapsed")')
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane.locator('.group-recap-message').wait_for()
    assert earlier.evaluate('el => el.classList.contains("is-message-collapsed")')
    pane.get_by_role('button', name='Expand all', exact=True).click()
    assert pane.locator('.is-message-collapsed').count() == 0


def test_cross_scene_bare_line_links_use_nearby_explicit_source_and_leave_ambiguity_unlinked(page, server):
    seed_recap(page, server)
    page.evaluate('''() => {
        const box = document.createElement('div'); box.id = 'crossSceneRecap';
        renderDiscussMarkdown(box, '[Walk · Line 3](manuscript/ch01/02-walk.md#L3). Delete line 4.\\n\\n## Another edit\\n\\n[Opening · Line 20](manuscript/ch01/01-opening.md#L20). Keep line 21. Missing.md: line 88, then line 89.\\n\\n## No source\\n\\nConsider line 99.', 'ch01/01-opening.md');
        document.getElementById('groupBody').appendChild(box);
    }''')
    links = page.locator('#crossSceneRecap a')
    assert links.count() == 4
    assert links.nth(1).get_attribute('data-prosview-path') == 'ch01/02-walk.md'
    assert links.nth(1).get_attribute('data-prosview-line') == '4'
    assert links.nth(3).get_attribute('data-prosview-path') == SCENE_REL
    assert page.locator('#crossSceneRecap').get_by_role('link', name='line 89', exact=True).count() == 0
    assert page.locator('#crossSceneRecap').get_by_role('link', name='line 99', exact=True).count() == 0


@pytest.mark.parametrize('accept', [False, True])
def test_applied_edit_status_requires_matching_saved_diff_and_opens_existing_viewer(page, server, tmp_path, accept):
    page.set_viewport_size({'width': 1440, 'height': 1050})
    pane, _ = seed_recap(page, server)
    pane.locator('#groupInput').fill('@Codex SELECT_FILE_CHANGE apply these edits.')
    pane.locator('#groupSendBtn').click()
    _group_idle(page)
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    first = pane.locator('.group-edit-card').first
    first.locator('.group-edit-status').filter(has_text='Applied').wait_for()
    assert pane.locator('.group-edit-card').nth(1).locator('.group-edit-status').inner_text() == 'Your choice'
    page.screenshot(path=str(tmp_path / 'group-recap.png'))
    first.get_by_role('button', name='View changes', exact=True).click()
    page.locator('#discussDiffModalOverlay').wait_for(state='visible')
    assert page.locator('#discussDiffModalTitle').inner_text() == 'manuscript/' + SCENE_REL
    expect(page.locator('#discussDiffModalContent')).to_contain_text(CHANGED_SENTENCE)
    assert page.locator('#discussDiffModalContent input[type=checkbox]').count() == 0
    page.get_by_role('button', name='Close diff viewer', exact=True).click()
    pane.locator('.group-tool-review').get_by_role('button', name='Looks good' if accept else 'Undo all', exact=True).click()
    page.wait_for_function('() => !_groupActiveSession.turns.some(t => t.review_pending)')
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    first.locator('.group-edit-status').filter(has_text='Applied' if accept else 'Agreed').wait_for()
    if accept:
        first.get_by_role('button', name='View changes', exact=True).click()
        page.locator('#discussDiffModalOverlay').wait_for(state='visible')
        expect(page.locator('#discussDiffModalContent')).to_contain_text(CHANGED_SENTENCE)
        page.get_by_role('button', name='Close diff viewer', exact=True).click()


def test_linked_edit_replacements_are_never_copied_as_one_passage_and_unformatted_chat_stays_readable(page, server):
    pane, _ = seed_recap(page, server)
    page.evaluate('''() => {
        const turn = _groupActiveSession.turns.find(t => t.tag === 'Recap');
        turn.text = turn.text.replace('## Choices for you\\n\\n### Consider another wording', '**Linked change:**');
        renderSceneGroupPane();
    }''')
    card = pane.locator('.group-edit-card')
    assert card.count() == 1
    assert 'Copy each replacement separately.' in card.inner_text()
    assert card.get_by_role('button', name='Copy replacement', exact=True).count() == 0
    assert card.get_by_role('button', name='Copy quote', exact=True).count() == 4
    page.evaluate('''() => {
        _groupActiveSession.turns.find(t => t.tag === 'Recap').text = 'The original opening works. Keep the weather line and revisit the ending later.';
        renderSceneGroupPane();
    }''')
    assert pane.locator('.group-edit-card').count() == 0
    assert 'Keep the weather line' in pane.inner_text()


def test_group_reading_position_survives_reload_background_renders_and_history_switches(page, server):
    page.set_viewport_size({'width': 1440, 'height': 850})
    pane, _ = seed_recap(page, server, long=True)
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    card = pane.locator('.group-edit-card').first
    card.get_by_role('button', name='Expand full edit', exact=True).click()
    # Read the middle of a long message, rather than its beginning or bottom.
    card.locator('blockquote').nth(1).locator('p').nth(4).evaluate("el=>el.scrollIntoView({block:'start'})")
    page.wait_for_function("() => { const b=document.getElementById('groupBody'); return b._groupScrollState.anchor && !b._groupScrollState.atBottom && Math.abs(b._groupScrollState.top-b.scrollTop)<2; }")
    state = page.evaluate("document.getElementById('groupBody')._groupScrollState")
    assert state['top'] > 0
    page.evaluate("() => { _groupActiveSession.turns[0].text += 'More earlier discussion. '.repeat(300); renderSceneGroupPane(); }")
    page.wait_for_function("s => {const b=document.getElementById('groupBody'),a=Array.from(b.querySelectorAll('[data-group-reading-anchor]')).find(n=>n.dataset.groupReadingAnchor===s.anchor);return a && Math.abs(a.getBoundingClientRect().top-groupScrollViewportTop(b)-s.offset)<2;}", arg=state)
    page.reload()
    page.wait_for_function('() => !!window._PM')
    page.evaluate("showScenePanelTab('group')")
    page.wait_for_function("s => {const b=document.getElementById('groupBody');if(!b)return false;const a=Array.from(b.querySelectorAll('[data-group-reading-anchor]')).find(n=>n.dataset.groupReadingAnchor===s.anchor);return a && Math.abs(a.getBoundingClientRect().top-groupScrollViewportTop(b)-s.offset)<2;}", arg=state)
    # A second conversation on the same scene keeps its own reading position.
    other = {'id': 'other-reading-position', 'scene': SCENE_REL, 'title': 'Another discussion',
             'turns': [{'role': 'user', 'text': 'Different discussion. ' * 100},
                       {'role': 'critic', 'seat': 1, 'agent': 'codex', 'text': 'Another long reply. ' * 200}]}
    assert server.post_json('/api/discuss/group-history', {'action':'save', 'session':other}).json()['ok']
    page.evaluate("id=>openGroupHistorySession(_groupCurrentScenePath(),id)", other['id'])
    page.wait_for_function("id=>_groupActiveSession.id===id", arg=other['id'])
    pane.locator('#groupBody').evaluate('el=>el.scrollTop=50')
    page.wait_for_function("() => document.getElementById('groupBody')._groupScrollState.top===50")
    page.evaluate("() => openGroupHistorySession(_groupCurrentScenePath(),'recap-presentation')")
    page.wait_for_function("s => {const b=document.getElementById('groupBody'),a=Array.from(b.querySelectorAll('[data-group-reading-anchor]')).find(n=>n.dataset.groupReadingAnchor===s.anchor);return _groupActiveSession.id==='recap-presentation' && a && Math.abs(a.getBoundingClientRect().top-groupScrollViewportTop(b)-s.offset)<2;}", arg=state)


def test_group_follows_new_content_only_when_reading_at_the_bottom(page, server):
    pane, _ = seed_recap(page, server, long=True)
    body = pane.locator('#groupBody')
    body.evaluate('el=>el.scrollTop=el.scrollHeight')
    page.wait_for_function("() => document.getElementById('groupBody')._groupScrollState.atBottom")
    page.evaluate("() => { _groupActiveSession.turns.push({role:'critic',seat:1,agent:'codex',text:'A new long reply. '.repeat(150)});renderSceneGroupPane(); }")
    page.wait_for_function("() => {const b=document.getElementById('groupBody');return b.scrollHeight-b.scrollTop-b.clientHeight<2;}")
    body.evaluate('el=>el.scrollTop=80')
    page.wait_for_function("() => document.getElementById('groupBody')._groupScrollState.top===80")
    page.evaluate("() => { _groupActiveSession.turns.push({role:'critic',seat:2,agent:'claude',text:'More discussion. '.repeat(150)});renderSceneGroupPane(); }")
    page.wait_for_function("() => Math.abs(document.getElementById('groupBody').scrollTop-80)<2")


def test_collapsing_and_expanding_a_message_keeps_its_header_in_place(page, server):
    pane, _ = seed_recap(page, server, long=True)
    header = pane.locator('.group-turn-card').nth(1).locator('.group-turn-head')
    header.evaluate("el=>el.scrollIntoView({block:'center'})")
    top = header.bounding_box()['y']
    header.locator('.group-message-toggle').click()
    page.wait_for_function('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))')
    assert abs(header.bounding_box()['y'] - top) < 2
    header.locator('.group-message-toggle').click()
    page.wait_for_function('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))')
    assert abs(header.bounding_box()['y'] - top) < 2
