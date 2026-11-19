from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import ProseviewServer
from .test_browser_e2e import open_scene, open_discuss, wait_for_discuss_answer, wait_for_discuss_idle, wait_for_discuss_quiet

pytestmark = pytest.mark.e2e_browser


def open_review(page: Page, server: ProseviewServer, label='Quick critique'):
    open_scene(page, server)
    open_discuss(page)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    customize_review(page, label)


def customize_review(page: Page, label: str):
    if page.locator('.discuss-craft-setup').count():
        page.get_by_role('button', name='Close review setup', exact=True).click()
    page.get_by_role('button', name='Customize ' + label, exact=True).click()
    page.wait_for_selector('.discuss-craft-setup')


@pytest.mark.parametrize(('label', 'action', 'lane_count'), [
    ('Quick critique', 'quick_critique', 4),
    ('Deepen & layer', 'deepen_and_layer', 4),
    ('Craft review', 'craft_mckee', 5),
    ('Comedy review', 'comedy_review', 10),
])
def test_main_cards_run_immediately_with_all_lanes_and_book_defaults(page: Page, server: ProseviewServer, label, action, lane_count):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    # A cold quick run must read the book's settings without opening Customize.
    page.route('**/api/discuss/discuss-settings', lambda route: route.fulfill(json={
        'settings': {'book': {'include_frontmatter': False, 'include_adjacent_scenes': False}}
    }))
    open_scene(page, server)
    open_discuss(page)
    page.fill('#discussInput', 'Unsent question: does the ending work?')
    page.get_by_role('button', name='Run ' + label + ' with defaults', exact=True).click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert len(requests) == 1
    req = requests[0]
    assert req['action_id'] == action
    assert req['action_scope'] == 'scene'
    assert req['scenes'] == ['ch01/01-opening.md']
    assert len(set(req['review_lanes'])) == lane_count
    assert req['craft_focus'] == '' and req['custom_instruction'] == ''
    assert req['craft_check_plan'] is False
    assert req['include_frontmatter'] is False and req['include_adjacent'] is False
    assert req['attachments'] == [] and req['include_current_document'] is False
    assert not page.locator('.discuss-craft-setup').count()
    assert page.locator('#discussInput').input_value() == 'Unsent question: does the ending work?'
    if action == 'comedy_review':
        assert req['comedy_styles'] == [] and req['comedy_goals'] == ['strengthen', 'explore']
    else:
        assert 'comedy_styles' not in req and 'comedy_goals' not in req


@pytest.mark.parametrize(('label', 'lane_count'), [
    ('Quick critique', 4),
    ('Deepen & layer', 4),
    ('Craft review', 5),
    ('Comedy review', 10),
])
def test_all_lanes_toggles_every_lane_off_and_on_with_mouse_and_keyboard(page: Page, server: ProseviewServer, label, lane_count):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, label)
    page.locator('#discussReviewFocusTrigger').click()
    popover = page.locator('#discussReviewFocusPopover')
    all_lanes = popover.locator('#discussReviewLane-all')
    checked_lanes = popover.locator('.discuss-craft-focus-option-pick:not(#discussReviewLane-all)[aria-checked="true"]')
    expect(all_lanes).to_have_attribute('aria-checked', 'true')
    expect(checked_lanes).to_have_count(lane_count)

    all_lanes.click()
    expect(all_lanes).to_have_attribute('aria-checked', 'false')
    expect(checked_lanes).to_have_count(0)
    expect(page.locator('.discuss-craft-focus-trigger-text')).to_have_text('Choose at least one lane')
    expect(page.locator('#discussSend')).to_be_disabled()
    expect(all_lanes).to_be_focused()

    page.keyboard.press('Space')
    expect(all_lanes).to_have_attribute('aria-checked', 'true')
    expect(checked_lanes).to_have_count(lane_count)
    expect(page.locator('#discussSend')).to_be_enabled()

    checked_lanes.first.click()
    expect(all_lanes).to_have_attribute('aria-checked', 'false')
    expect(checked_lanes).to_have_count(lane_count - 1)
    all_lanes.click()
    expect(all_lanes).to_have_attribute('aria-checked', 'true')
    expect(checked_lanes).to_have_count(lane_count)
    page.keyboard.press('Escape')
    page.locator('#discussReviewFocusTrigger').click()
    expect(all_lanes).to_have_attribute('aria-checked', 'true')
    expect(checked_lanes).to_have_count(lane_count)
    assert requests == []


@pytest.mark.parametrize(('label', 'first_lane', 'lane_count'), [
    ('Quick critique', 'logic', 4),
    ('Deepen & layer', 'subtext', 4),
    ('Craft review', 'blind_spot', 5),
    ('Comedy review', 'truth_pain', 10),
])
def test_quick_runs_ignore_and_preserve_custom_choices(page: Page, server: ProseviewServer, label, first_lane, lane_count):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, label)
    if label == 'Craft review':
        page.locator('#discussReviewBook-craft_cron').click()
    page.locator('#discussReviewFrontmatter').uncheck()
    page.locator('#discussReviewAdjacent').uncheck()
    page.locator('[data-scope="adjacent"]').click()
    page.locator('#discussReviewCheckPlan').check()
    page.fill('#discussInput', 'Custom only: focus on the quiet ending.')
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    page.locator('#discussReviewLane-' + first_lane).click()
    page.keyboard.press('Escape')
    if label == 'Comedy review':
        page.locator('#discussComedyStyle-dark').check()
        page.locator('#discussComedyStyle-sarcastic').check()
        page.locator('#discussComedyGoal-explore').check()
    page.get_by_role('button', name='Close review setup', exact=True).click()
    assert page.locator('#discussInput').input_value() == ''
    if label == 'Craft review':
        assert 'Cron · Story Genius' in page.locator('.discuss-review-card-defaults').nth(2).inner_text()
    page.get_by_role('button', name='Run ' + label + ' with defaults', exact=True).click()
    wait_for_discuss_answer(page, 'Fake answer')
    req = requests[-1]
    assert req['scenes'] == ['ch01/01-opening.md']
    assert len(req['review_lanes']) == lane_count
    assert req['custom_instruction'] == '' and req['craft_check_plan'] is False
    assert req['include_frontmatter'] is True and req['include_adjacent'] is True
    if label == 'Craft review':
        assert req['action_id'] == 'craft_cron'
    if label == 'Comedy review':
        assert req['comedy_styles'] == [] and req['comedy_goals'] == ['strengthen', 'explore']
    wait_for_discuss_idle(page)
    page.locator('#discussCraftButton').click()
    customize_review(page, label)
    assert page.locator('[data-scope="adjacent"]').get_attribute('aria-pressed') == 'true'
    assert not page.locator('#discussReviewFrontmatter').is_checked()
    assert not page.locator('#discussReviewAdjacent').is_checked()
    assert page.locator('#discussReviewCheckPlan').is_checked()
    assert page.locator('#discussInput').input_value() == 'Custom only: focus on the quiet ending.'
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() != 'All lanes'
    if label == 'Comedy review':
        assert page.locator('#discussComedyStyle-dark').is_checked()
        assert page.locator('#discussComedyStyle-sarcastic').is_checked()
        assert page.locator('#discussComedyGoal-explore').is_checked()


def test_customize_keeps_an_unsent_chat_draft_separate_through_cancel_run_and_reload(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_scene(page, server)
    open_discuss(page)
    page.fill('#discussInput', 'Unsent chat draft.')
    customize_review(page, 'Quick critique')
    assert page.locator('#discussInput').input_value() == ''
    page.fill('#discussInput', 'Custom review instructions.')
    page.get_by_role('button', name='Close review setup', exact=True).click()
    assert page.locator('#discussInput').input_value() == 'Unsent chat draft.'
    customize_review(page, 'Quick critique')
    assert page.locator('#discussInput').input_value() == 'Custom review instructions.'
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['custom_instruction'] == 'Custom review instructions.'
    assert page.locator('#discussInput').input_value() == 'Unsent chat draft.'
    page.reload(wait_until='load')
    open_discuss(page)
    assert page.locator('#discussInput').input_value() == 'Unsent chat draft.'


def test_review_cards_can_run_another_review_in_the_same_chat(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_scene(page, server)
    open_discuss(page)
    page.get_by_role('button', name='Run Quick critique with defaults', exact=True).click()
    wait_for_discuss_answer(page, 'Fake answer')
    wait_for_discuss_idle(page)
    page.locator('#discussCraftButton').click()
    expect(page.locator('.discuss-review-card-picker')).to_be_visible()
    page.get_by_role('button', name='What gets sent with a quick review?', exact=True).click()
    expect(page.get_by_role('dialog', name='What this review receives', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    page.get_by_role('button', name='Run Comedy review with defaults', exact=True).click()
    expect(page.locator('.discuss-message.user')).to_have_count(2)
    assert [req['action_id'] for req in requests] == ['quick_critique', 'comedy_review']
    assert requests[1]['scenes'] == ['ch01/01-opening.md']
    assert not page.locator('.discuss-craft-setup').count()


def test_quick_run_waits_for_context_defaults_and_can_retry_if_they_fail_to_load(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    page.route('**/api/discuss/discuss-settings', lambda route: route.fulfill(status=422, json={'error': 'Could not load review settings.'}))
    open_scene(page, server)
    open_discuss(page)
    run = page.get_by_role('button', name='Run Quick critique with defaults', exact=True)
    run.click()
    expect(page.locator('#discussLog')).to_contain_text('Could not load review settings.')
    expect(run).to_be_enabled()
    assert not requests
    page.unroute('**/api/discuss/discuss-settings')
    run.click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert len(requests) == 1


@pytest.mark.parametrize('viewport', [{'width': 1500, 'height': 1000}, {'width': 390, 'height': 844}])
def test_cards_have_separate_keyboard_targets_and_fit_the_dock(page: Page, server: ProseviewServer, viewport):
    page.set_viewport_size(viewport)
    open_scene(page, server)
    open_discuss(page)
    run = page.get_by_role('button', name='Run Quick critique with defaults', exact=True)
    expect(run).to_be_enabled()
    assert 'What do you want to examine?' not in page.locator('#discussLog').inner_text()
    wait_for_discuss_quiet(page)
    run.focus()
    page.keyboard.press('Tab')
    customize = page.get_by_role('button', name='Customize Quick critique', exact=True)
    expect(customize).to_be_focused()
    page.evaluate('renderDiscussSnapshot()')
    expect(customize).to_be_focused()
    for card in page.locator('.discuss-review-card').all():
        assert not card.locator('button button').count()
        assert card.locator('.discuss-review-customize').inner_text() == 'Customize…'
        assert not card.locator('.discuss-review-customize svg').count()
        expect(card.locator('.discuss-review-customize')).to_have_css('border-top-width', '0px')
        expect(card.locator('.discuss-review-customize')).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
        assert card.locator('.discuss-review-customize').bounding_box()['height'] >= 32
        assert card.locator('.discuss-review-card-run').inner_text() == 'Run now →'
        assert card.evaluate('el => el.scrollWidth <= el.clientWidth')
        bounds = card.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= viewport['width']
    page.keyboard.press('Enter')
    expect(page.locator('.discuss-craft-setup')).to_be_visible()


@pytest.mark.parametrize('viewport', [{'width': 1500, 'height': 1000}, {'width': 390, 'height': 844}])
@pytest.mark.parametrize('include_context', [True, False])
def test_heading_info_shows_quick_run_defaults_without_starting_a_review(page: Page, server: ProseviewServer, viewport, include_context):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    page.set_viewport_size(viewport)
    page.route('**/api/discuss/discuss-settings', lambda route: route.fulfill(json={
        'settings': {'book': {'include_frontmatter': include_context, 'include_adjacent_scenes': include_context}}
    }))
    open_review(page, server)
    # These temporary choices must not be presented as the quick-run defaults.
    page.locator('#discussReviewFrontmatter').set_checked(not include_context)
    page.locator('#discussReviewAdjacent').set_checked(not include_context)
    page.locator('#discussReviewCheckPlan').check()
    page.get_by_role('button', name='Close review setup', exact=True).click()
    assert not page.locator('.discuss-review-defaults-help').count()
    trigger = page.get_by_role('button', name='What gets sent with a quick review?', exact=True)
    assert trigger.locator('..').locator('.discuss-story-group').inner_text().lower() == 'read this scene'
    trigger.click()
    popup = page.get_by_role('dialog', name='What this review receives', exact=True)
    expect(popup).to_be_visible()
    expected = 'Included' if include_context else 'Not included'
    for label in ('Scene details', 'Nearby scenes'):
        expect(popup.locator('.discuss-review-info-row', has_text=label).locator('dd')).to_contain_text(expected)
    assert popup.locator('.discuss-review-info-row', has_text='Check planned events').locator('dd').inner_text().startswith('Off')
    assert 'Every lane for the chosen review.' in popup.inner_text()
    assert 'Included when available.' in popup.inner_text()
    assert 'Settings → Discuss' in popup.inner_text()
    assert trigger.get_attribute('aria-expanded') == 'true'
    page.evaluate('renderDiscussSnapshot()')
    expect(popup).to_be_visible()
    bounds = popup.bounding_box()
    assert 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= viewport['width']
    assert 0 <= bounds['y'] and bounds['y'] + bounds['height'] <= viewport['height']
    assert popup.evaluate('el => el.scrollWidth <= el.clientWidth')
    page.keyboard.press('Escape')
    expect(popup).not_to_be_attached()
    expect(trigger).to_be_focused()
    trigger.press('Enter')
    expect(popup).to_be_visible()
    page.keyboard.press('Tab')
    expect(popup).not_to_be_attached()
    expect(page.get_by_role('button', name='Run Quick critique with defaults', exact=True)).to_be_focused()
    trigger.click()
    page.locator('#discussInput').click()
    expect(popup).not_to_be_attached()
    expect(page.locator('#discussInput')).to_be_focused()
    assert not requests


@pytest.mark.parametrize(('label', 'action', 'lane_ids'), [
    ('Quick critique', 'quick_critique', ['logic', 'motivation']),
    ('Deepen & layer', 'deepen_and_layer', ['subtext', 'emotion']),
    ('Craft review', 'craft_mckee', ['want', 'subtext']),
])
def test_shared_setup_sends_scenes_lanes_notes_and_plan_choice(page: Page, server: ProseviewServer, label, action, lane_ids):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, label)
    assert not requests  # Customize opens setup; Run sends the request.
    assert not page.locator('.discuss-review-modes').count()
    assert f'Customize {label.lower()}' in page.locator('.discuss-craft-head').inner_text()
    expect(page.locator('.discuss-craft-focus-row')).to_have_css('height', '30px')
    assert not page.locator('#discussReviewCheckPlan').is_checked()
    page.locator('#discussReviewCheckPlan').check()
    page.fill('#discussInput', 'Keep the quiet tone.')
    page.locator('[data-scope="custom"]').click()
    dialog = page.locator('#discussReviewSceneDialog')
    dialog.get_by_role('button', name='Clear selection', exact=True).click()
    assert dialog.locator('#discussReviewSceneApply').is_disabled()
    boxes = dialog.locator('input[type="checkbox"]')
    selected_paths = [boxes.nth(i).input_value() for i in (0, 1)]
    boxes.nth(0).check(); boxes.nth(1).check()
    dialog.locator('#discussReviewSceneApply').click()
    assert page.locator('#discussReviewAdjacent').is_disabled()
    page.locator('.discuss-craft-story-context summary').click()
    for index, path in enumerate(selected_paths):
        page.select_option('#discussReviewContextScene', path)
        page.fill('#discussCraftContext', f'Context belonging to scene {index + 1}.')
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    assert page.locator('#discussSend').get_attribute('aria-disabled') == 'true'
    for lane_id in lane_ids:
        page.locator(f'.discuss-craft-focus-option[data-focus="{lane_id}"] .discuss-craft-focus-option-pick').click()
    assert page.locator('#discussReviewFocusPopover').is_visible()
    page.locator(f'#discussReviewLaneInfo-{lane_ids[0]}').click()
    guide = page.locator('#discussCraftInfoDialog')
    assert guide.locator('.discuss-craft-example-card').count() == 2
    assert len(guide.locator('#discussCraftInfoBody').inner_text().split()) > 100
    guide.get_by_role('button', name='Close review guide', exact=True).click()
    assert page.locator('#discussReviewFocusTrigger').evaluate('el => el === document.activeElement')
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    req = requests[-1]
    assert req['action_id'] == action
    assert req['scenes'] == selected_paths
    assert req['review_lanes'] == lane_ids
    assert req['craft_check_plan'] is True
    assert req['include_adjacent'] is False
    assert req['custom_instruction'] == 'Keep the quiet tone.'
    assert req['review_contexts'] == {path: f'Context belonging to scene {i + 1}.' for i, path in enumerate(selected_paths)}
    receipt = page.locator('.discuss-craft-request-summary').last
    assert '2 scenes' in receipt.inner_text()
    assert 'Plan check:' in receipt.inner_text()
    assert 'Context belonging to scene 1.' in receipt.inner_text()
    assert 'Context belonging to scene 2.' in receipt.inner_text()


def test_switching_review_types_retains_shared_choices_and_each_types_lanes(page: Page, server: ProseviewServer):
    open_review(page, server)
    page.fill('#discussInput', 'Keep the ending understated.')
    page.locator('[data-scope="adjacent"]').click()
    page.locator('#discussReviewFrontmatter').uncheck()
    page.locator('#discussReviewCheckPlan').check()
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    page.locator('#discussReviewLane-motivation').click()
    page.keyboard.press('Escape')
    for label in ('Deepen & layer', 'Craft review', 'Quick critique'):
        customize_review(page, label)
        assert page.locator('[data-scope="adjacent"]').get_attribute('aria-pressed') == 'true'
        assert page.locator('#discussReviewCheckPlan').is_checked()
        assert not page.locator('#discussReviewFrontmatter').is_checked()
        assert page.locator('#discussInput').input_value() == 'Keep the ending understated.'
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == 'Character motivation'
    customize_review(page, 'Craft review')
    page.locator('.discuss-craft-lens[data-lens="craft_cron"] .discuss-craft-lens-pick').click()
    assert page.locator('[data-scope="adjacent"]').get_attribute('aria-pressed') == 'true'
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    page.locator('#discussReviewLane-blind_spot').click()
    page.locator('#discussReviewLane-handoff').click()
    page.keyboard.press('Escape')
    page.locator('.discuss-craft-lens[data-lens="craft_king"] .discuss-craft-lens-pick').click()
    page.locator('.discuss-craft-lens[data-lens="craft_cron"] .discuss-craft-lens-pick').click()
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == '2 lanes selected'
    page.locator('#discussReviewFocusTrigger').click()
    page.keyboard.press('End')
    page.keyboard.press('Space')
    page.keyboard.press('Escape')
    assert page.locator('#discussReviewFocusTrigger').evaluate('el => el === document.activeElement')
    page.locator('#discussReviewFocusReset').click()
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == 'All lanes'


def test_mobile_popover_and_scene_picker_keep_controls_reachable(page: Page, server: ProseviewServer):
    page.set_viewport_size({'width': 390, 'height': 844})
    open_review(page, server, 'Deepen & layer')
    page.locator('#discussReviewFocusTrigger').click()
    popover = page.locator('#discussReviewFocusPopover')
    box = popover.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    assert box['y'] >= 0 and box['y'] + box['height'] <= 844
    assert popover.locator('.discuss-craft-focus-option-brief').count() == 5
    page.keyboard.press('Escape')
    page.locator('[data-scope="custom"]').click()
    page.fill('#discussReviewSceneSearch', 'walk')
    assert page.locator('#discussReviewSceneChoices input[type="checkbox"]').count() == 1
    page.get_by_role('button', name='Cancel', exact=True).click()
    assert page.locator('[data-scope="this_scene"]').get_attribute('aria-pressed') == 'true'


def test_guide_returns_focus_to_its_info_button_after_close_and_escape(page: Page, server: ProseviewServer):
    open_review(page, server)
    info = page.locator('#discussReviewFocusInfo')
    for close_with_escape in (False, True):
        info.click()
        dialog = page.locator('#discussCraftInfoDialog')
        expect(dialog).to_be_visible()
        if close_with_escape:
            page.keyboard.press('Escape')
        else:
            dialog.get_by_role('button', name='Close review guide', exact=True).click()
        expect(info).to_be_focused()


@pytest.mark.parametrize(('label', 'noun'), [
    ('Quick critique', 'revision priorities'),
    ('Deepen & layer', 'opportunities'),
    ('Comedy review', 'revision priorities'),
])
def test_customize_changes_the_priority_cap_for_one_review_only(page: Page, server: ProseviewServer, label, noun):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, label)
    cap = page.locator('#discussReviewMaxFindings')
    assert cap.input_value() == '5'
    assert noun in page.locator('.discuss-review-limit-row').inner_text()
    cap.fill('12')
    cap.press('Tab')
    assert cap.input_value() == '12'
    cap.fill('25')
    cap.press('Tab')
    assert cap.input_value() == '20'  # The largest cap the prompt allows, and the writer is told.
    assert 'The most a review can give is 20' in page.locator('#discussReviewMaxFindingsHelp').inner_text()
    cap.fill('2')
    cap.press('Tab')
    assert 'Default 5' in page.locator('#discussReviewMaxFindingsHelp').inner_text()
    assert 'Up to 2' in page.locator('#discussTaskMode').inner_text()
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['review_max_findings'] == 2
    receipt = page.locator('.discuss-craft-request-summary').last.inner_text()
    assert ('Opportunities' if noun == 'opportunities' else 'Revision priorities') + ': up to 2' in receipt
    wait_for_discuss_idle(page)
    # The card's Run now keeps the shared default.
    page.locator('#discussCraftButton').click()
    page.get_by_role('button', name='Run ' + label + ' with defaults', exact=True).click()
    page.wait_for_function("n => document.querySelectorAll('.discuss-craft-request-summary').length >= n", arg=2)
    assert requests[-1]['review_max_findings'] == 5
    # The writer's cap survives a reload.
    wait_for_discuss_idle(page)
    page.reload()
    page.wait_for_function("() => typeof _discussCraftState === 'object'")
    assert page.evaluate('_discussCraftState.maxFindings') == 2


def test_show_what_to_keep_is_off_by_default_remembered_and_left_out_of_run_now(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, 'Deepen & layer')
    assert not page.locator('#discussReviewIncludeKeep').count()  # Deepen offers opportunities only.
    customize_review(page, 'Quick critique')
    keep = page.locator('#discussReviewIncludeKeep')
    assert not keep.is_checked()
    keep.check()
    assert 'Keep list' in page.locator('#discussTaskMode').inner_text()
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['review_include_keep'] is True
    assert 'Keep: list what to preserve' in page.locator('.discuss-craft-request-summary').last.inner_text()
    wait_for_discuss_idle(page)
    # The card's Run now keeps the default.
    page.locator('#discussCraftButton').click()
    page.get_by_role('button', name='Run Quick critique with defaults', exact=True).click()
    page.wait_for_function("n => document.querySelectorAll('.discuss-craft-request-summary').length >= n", arg=2)
    assert requests[-1]['review_include_keep'] is False
    assert 'Keep: off' in page.locator('.discuss-craft-request-summary').last.inner_text()
    wait_for_discuss_idle(page)
    page.reload()
    page.wait_for_function("() => typeof _discussCraftState === 'object'")
    assert page.evaluate('_discussCraftState.includeKeep') is True


def test_bird_by_bird_explains_it_has_no_priority_cap(page: Page, server: ProseviewServer):
    open_review(page, server, 'Craft review')
    page.locator('#discussReviewBook-craft_lamott').click()
    assert not page.locator('#discussReviewMaxFindings').count()
    assert 'one small drafting assignment' in page.locator('.discuss-review-limit').inner_text()


def test_open_critique_is_off_by_default_remembered_and_left_out_of_run_now(page: Page, server: ProseviewServer):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    open_review(page, server, 'Deepen & layer')
    assert not page.locator('#discussReviewOpenCritique').count()
    customize_review(page, 'Craft review')
    page.locator('#discussReviewBook-craft_mckee').click()
    oc = page.locator('#discussReviewOpenCritique')
    assert not oc.is_checked()
    page.locator('#discussReviewOpenCritiqueInfo').click()
    popover = page.locator('#discussReviewInfoPopover')
    expect(popover).to_be_visible()
    assert 'Rigid template and strict rules' in popover.inner_text()
    assert 'Model chooses level and structure' in popover.inner_text()
    assert not oc.is_checked()
    page.keyboard.press('Escape')
    expect(popover).not_to_be_attached()
    oc.check()
    assert 'Open critique' in page.locator('#discussTaskMode').inner_text()
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    page.locator('#discussReviewLane-want').click()
    page.locator('#discussReviewLane-subtext').click()
    page.keyboard.press('Escape')
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['review_open_critique'] is True
    assert requests[-1]['review_lanes'] == ['want', 'subtext']
    assert 'Format: open critique' in page.locator('.discuss-craft-request-summary').last.inner_text()
    wait_for_discuss_idle(page)
    # The card's Run now keeps the default.
    page.locator('#discussCraftButton').click()
    page.get_by_role('button', name='Run Craft review with defaults', exact=True).click()
    page.wait_for_function("n => document.querySelectorAll('.discuss-craft-request-summary').length >= n", arg=2)
    assert requests[-1]['review_open_critique'] is False
    assert 'Format: open critique' not in page.locator('.discuss-craft-request-summary').last.inner_text()
    wait_for_discuss_idle(page)
    page.reload()
    page.wait_for_function("() => typeof _discussCraftState === 'object'")
    assert page.evaluate('_discussCraftState.openCritique') is True
