from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import open_scene, open_discuss, wait_for_discuss_answer, wait_for_discuss_idle, wait_for_discuss_quiet  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def _open_craft(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_discuss(page)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.get_by_role('button', name='Customize Craft review', exact=True).click()


@pytest.mark.parametrize(('lens_id', 'lane_id', 'label'), [
    ('craft_mckee', 'subtext', 'Subtext'),
    ('craft_cron', 'handoff', 'What follows'),
    ('craft_coyne', 'genre', 'Genre expectations'),
    ('craft_snyder', 'conflict', 'Goal & obstacle'),
    ('craft_king', 'description', 'Description'),
    ('craft_lamott', 'character', 'Discover the person'),
])
def test_added_craft_topic_focus_sends_guide_lane_names(page: Page, server: ProseviewServer, lens_id: str, lane_id: str, label: str):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    _open_craft(page, server)
    page.fill('#discussInput', 'Keep the existing voice.')
    page.locator(f'.discuss-craft-lens[data-lens="{lens_id}"] .discuss-craft-info-btn').click()
    dialog = page.locator('#discussCraftInfoDialog')
    dialog.locator(f'.discuss-craft-dialog-tab[data-tab="{lane_id}"]').click()
    principle = dialog.locator('.discuss-craft-info-thesis').inner_text()
    dialog.get_by_role('button', name='Focus review on this topic').click()
    assert page.locator('#discussInput').input_value() == 'Keep the existing voice.'
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['action_id'] == lens_id
    assert requests[-1]['craft_focus'] == lane_id
    assert label in requests[-1]['craft_lanes']
    assert all(not name[0].isdigit() for name in requests[-1]['craft_lanes'])
    page.locator('.discuss-craft-prompt summary').click()
    assert 'Selected lanes: ' + label + '.' in page.locator('.discuss-craft-prompt-body').inner_text()
    assert label in page.locator('.discuss-craft-prompt-body').inner_text()
    assert principle in page.locator('.discuss-craft-prompt-body').inner_text()
    assert 'Principle:' in page.locator('.discuss-craft-prompt-body').inner_text()
    assert 'Look for:' not in page.locator('.discuss-craft-prompt-body').inner_text()


def test_optional_story_context_survives_render_lens_switch_and_reload(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    _open_craft(page, server)
    page.locator('.discuss-craft-lens[data-lens="craft_cron"] .discuss-craft-lens-pick').click()
    page.locator('.discuss-craft-story-context summary').click()
    context = 'Her known belief: asking for help makes her a burden. This is a tentative reconnection.'
    page.fill('#discussCraftContext', context)
    page.locator('#discussCraftContext').evaluate('el => el.setSelectionRange(6, 14)')
    page.evaluate('renderDiscussSnapshot()')
    assert page.locator('#discussCraftContext').input_value() == context
    assert page.locator('#discussCraftContext').evaluate('el => document.activeElement === el && el.selectionStart === 6 && el.selectionEnd === 14')
    page.locator('.discuss-craft-lens[data-lens="craft_coyne"] .discuss-craft-lens-pick').click()
    assert page.locator('#discussCraftContext').input_value() == context
    assert 'genre' in page.locator('#discussCraftContextHelp').inner_text()
    page.wait_for_function("() => document.querySelector('#discussCraftContextStatus').textContent.startsWith('Saved with')")
    page.evaluate('sessionStorage.clear()')
    page.reload(wait_until='load')
    open_discuss(page)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.get_by_role('button', name='Customize Craft review', exact=True).click()
    page.wait_for_function('value => document.querySelector("#discussCraftContext").value === value', arg=context)
    assert page.locator('#discussCraftContext').input_value() == context
    assert page.locator('#discussCraftContext').is_visible()
    page.locator('.discuss-craft-note-toggle', has_text='Scene frontmatter').locator('input').uncheck()
    page.locator('.discuss-craft-note-toggle', has_text='±1 scene excerpts').locator('input').uncheck()
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['review_contexts']['ch01/01-opening.md'] == context
    assert requests[-1]['include_frontmatter'] is False
    assert requests[-1]['include_adjacent'] is False
    assert context in page.locator('.discuss-craft-request-summary').inner_text()
    # Notes belong to the scene and are shared by providers.
    page.goto(server.base_url + '#/scene/ch01/02-walk.md', wait_until='load')
    page.wait_for_function("() => discussCraftActivePath() === 'ch01/02-walk.md'")
    page.locator('#discussCraftButton').click()
    page.get_by_role('button', name='Customize Craft review', exact=True).click()
    assert page.locator('#discussCraftContext').input_value() == ''


def test_focus_chips_and_result_lane_links_open_the_matching_guide(page: Page, server: ProseviewServer):
    _open_craft(page, server)
    assert page.get_by_role('button', name='Close review setup', exact=True).count() == 1
    assert page.locator('.discuss-craft-instruction-label').inner_text() == 'Instructions for this review (optional)'
    assert page.locator('#discussNewActivity').is_hidden()
    page.locator('#discussLog').evaluate('el => { el.scrollTop = 0; }')
    page.locator('.discuss-craft-lens[data-lens="craft_coyne"] .discuss-craft-lens-pick').click()
    assert page.locator('#discussNewActivity').is_hidden()
    page.locator('.discuss-craft-lens[data-lens="craft_mckee"] .discuss-craft-lens-pick').click()
    page.locator('.discuss-craft-focus-trigger').click()
    page.locator('#discussReviewLanesClear').click()
    popover = page.locator('.discuss-craft-focus-popover')
    assert popover.evaluate('el => getComputedStyle(el).backgroundColor') != 'rgba(0, 0, 0, 0)'
    tactics_opt = popover.locator('.discuss-craft-focus-option[data-focus="tactics"]')
    assert tactics_opt.locator('.discuss-craft-focus-option-brief').is_visible()
    tactics_opt.locator('.discuss-craft-focus-option-pick').click()
    page.keyboard.press('Escape')
    assert page.locator('#discussNewActivity').is_hidden()
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == 'Actions & reactions'
    assert page.locator('.discuss-craft-focus-clear').is_visible()
    assert page.locator('.discuss-craft-focus-row').bounding_box()['height'] == 30
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page)
    wait_for_discuss_idle(page)
    wait_for_discuss_quiet(page)
    page.evaluate(r"""() => {
        const answer = [..._discussSnapshot.messages].reverse().find(m => m.role === 'assistant');
        answer.text = '### Give the second request a new tactic\n\n**Lanes: Actions & reactions, Resistance — the second request repeats the first.**\n\nChange the response that makes the next action possible.';
        renderDiscussSnapshot();
    }""")
    link = page.get_by_role('button', name='Read about Actions & reactions in Story', exact=True)
    link.click()
    dialog = page.locator('#discussCraftInfoDialog')
    assert dialog.locator('[data-tab="tactics"]').get_attribute('aria-selected') == 'true'
    second_example = dialog.locator('.discuss-craft-another-example')
    assert second_example.get_attribute('open') is None
    second_example.locator('summary').click()
    assert second_example.get_attribute('open') is not None
    assert 'Use your judgment' in dialog.inner_text()
    dialog.get_by_role('button', name='Close review guide').click()
    assert link.evaluate('el => el === document.activeElement')


@pytest.mark.parametrize('line_suffix', ['#L26', ''])
def test_quote_uses_its_following_citation_instead_of_the_previous_quote(page: Page, server: ProseviewServer, line_suffix: str):
    open_scene(page, server)
    open_discuss(page)
    source = (server.root / 'manuscript/ch01/01-opening.md').read_text().splitlines()
    first, second = source[19], source[25]
    markdown = f'> {first}\n\n[Line 20](manuscript/ch01/01-opening.md#L20)\n\n> {second}\n\n[Line 26](manuscript/ch01/01-opening.md{line_suffix})'
    page.evaluate("""text => {
        const parent = document.createElement('div');
        parent.id = 'craftCitationCheck';
        renderDiscussMarkdown(parent, text, 'ch01/01-opening.md');
        document.getElementById('discussLog').appendChild(parent);
    }""", markdown)
    quotes = page.locator('#craftCitationCheck blockquote')
    assert quotes.nth(0).get_attribute('data-target-line') == '20'
    assert quotes.nth(1).get_attribute('data-target-line') == '26'
    assert quotes.nth(1).locator('.discuss-quote-line-tag').inner_text() == 'line 26'


def test_a_suggested_rewrite_points_at_the_passage_it_replaces(page: Page, server: ProseviewServer):
    # Reviews explain a finding between the quote and its rewrite, mentioning
    # other lines and scenes. Those mentions must not relabel the rewrite.
    open_scene(page, server)
    open_discuss(page)
    source = (server.root / 'manuscript/ch01/01-opening.md').read_text().splitlines()
    markdown = '\n'.join([
        '### 1. A finding',
        '',
        '**Type:** Comic opportunity',
        '**Lane:** Timing & wording. Why it belongs here.',
        '',
        f'> *{source[19]}*',
        '',
        '([Line 20](manuscript/ch01/01-opening.md#L20))',
        '',
        'It echoes [ch01/02 · Line 3](manuscript/ch01/02-walk.md#L3) and the beat at line 26.',
        '',
        '> "An invented rewrite that is not in the scene."',
        '',
        'In the opening, line 26:',
        '',
        '> "A passage the paragraph above introduces."',
    ])
    page.evaluate("""text => {
        const parent = document.createElement('div');
        parent.id = 'craftRewriteCheck';
        renderDiscussMarkdown(parent, text, 'ch01/01-opening.md');
        document.getElementById('discussLog').appendChild(parent);
    }""", markdown)
    labels = page.locator('#craftRewriteCheck p').first
    assert labels.inner_text().split('\n')[:2] == ['Type: Comic opportunity', 'Lane: Timing & wording. Why it belongs here.']
    quotes = page.locator('#craftRewriteCheck blockquote')
    assert quotes.nth(1).get_attribute('data-target-path') == 'ch01/01-opening.md'
    assert quotes.nth(1).locator('.discuss-quote-line-tag').inner_text() == 'line 20'
    assert quotes.nth(2).locator('.discuss-quote-line-tag').inner_text() == 'line 26'


def test_keep_citations_after_quotes_and_long_lead_ins_label_the_right_passage(page: Page, server: ProseviewServer):
    # From a chapter review: Keep items cite their quote at the start of the
    # reason below it, and a long explanation ending "Possibility:" links other
    # scenes in passing before a rewrite of the quoted passage.
    open_scene(page, server)
    open_discuss(page)
    source = (server.root / 'manuscript/ch01/01-opening.md').read_text().splitlines()
    markdown = '\n'.join([
        '**Keep**',
        '',
        f'> *{source[19]}*',
        '',
        '[01-opening.md · Line 20](manuscript/ch01/01-opening.md#L20). The comparison sets up the turn.',
        '',
        '> *A line from the next scene.*',
        '',
        '[02-walk.md · Line 3](manuscript/ch01/02-walk.md#L3). The cover story comes back reversed.',
        '',
        '### 1. A finding',
        '',
        f'> *{source[25]}*',
        '',
        '[01-opening.md · Line 26](manuscript/ch01/01-opening.md#L26)',
        '',
        'He never pushes back on what [02-walk.md · Line 3](manuscript/ch01/02-walk.md#L3) set up. '
        'Replace the duplicate with a push that gives her a reason of her own. Possibility:',
        '',
        '> "A rewrite of the passage quoted above."',
    ])
    page.evaluate("""text => {
        const parent = document.createElement('div');
        parent.id = 'keepCitationCheck';
        renderDiscussMarkdown(parent, text, 'ch01/01-opening.md');
        document.getElementById('discussLog').appendChild(parent);
    }""", markdown)
    quotes = page.locator('#keepCitationCheck blockquote')
    assert quotes.nth(0).get_attribute('data-target-line') == '20'
    assert quotes.nth(1).get_attribute('data-target-path') == 'ch01/02-walk.md'
    assert quotes.nth(1).get_attribute('data-target-line') == '3'
    assert quotes.nth(3).get_attribute('data-target-path') == 'ch01/01-opening.md'
    assert quotes.nth(3).get_attribute('data-target-line') == '26'


def test_update_from_scene_button_opens_discuss_sends_update_frontmatter_and_keeps_chat_open(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_scene(page, server)

    sync_btn = page.locator('#sceneFrontmatter .fm-sync-btn')
    assert sync_btn.is_visible()
    assert sync_btn.inner_text() == 'Update from scene'
    assert page.locator('#sceneFrontmatter .fm-age').is_visible()

    sync_btn.click()
    wait_for_discuss_answer(page, 'Fake answer')

    assert len(requests) >= 1
    req = requests[-1]
    assert req['action_id'] == 'update_frontmatter'
    assert req['action_scope'] == 'scene'
    assert req['include_frontmatter'] is False
    assert req['include_adjacent'] is False
    assert page.locator('#discussPanel').is_visible()
    assert page.locator('#discussInput').is_visible()
    assert 'Update frontmatter' in page.locator('.discuss-craft-request-summary').inner_text()
    page.locator('.discuss-craft-prompt summary', has_text='Update instructions').click()
    assert 'single source of truth' in page.locator('.discuss-craft-prompt-body').inner_text()
