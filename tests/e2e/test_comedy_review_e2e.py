from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import wait_for_discuss_answer, wait_for_discuss_idle, wait_for_discuss_quiet  # noqa: E402
from .test_review_setup_e2e import customize_review, open_review  # noqa: E402

pytestmark = pytest.mark.e2e_browser

LANES = ['truth_pain', 'premise', 'character_status', 'deadpan_subtext', 'setup_surprise',
         'escalation_callbacks', 'specificity', 'timing_wording', 'tone_target', 'violation_distance']


def capture_questions(page):
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if '/api/discuss/conversations/' in request.url and request.url.endswith('/questions') else None)
    return requests


def test_comedy_styles_goal_and_lanes_survive_switching_and_reach_the_request(page: Page, server: ProseviewServer):
    requests = capture_questions(page)
    open_review(page, server, 'Comedy review')
    assert not requests
    expect(page.locator('.discuss-craft-focus-row')).to_have_css('height', '30px')
    assert page.locator('#discussSend').inner_text() == 'Run comedy review'
    assert not page.locator('#discussComedyStyle-dark').is_checked()
    # Both goals are on by default: tune the humor there and look for new chances.
    assert page.locator('#discussComedyGoal-strengthen').is_checked()
    assert page.locator('#discussComedyGoal-explore').is_checked()
    page.fill('#discussInput', 'Keep the narrator affectionate; the sarcasm belongs to the son.')
    page.locator('[data-scope="adjacent"]').click()
    page.locator('#discussReviewCheckPlan').check()
    page.locator('#discussComedyStyle-dark').check()
    page.locator('#discussComedyStyle-sarcastic').check()
    page.locator('#discussReviewFocusTrigger').click()
    page.locator('#discussReviewLanesClear').click()
    page.locator('#discussReviewLane-truth_pain').click()
    page.locator('#discussReviewLane-deadpan_subtext').click()
    page.keyboard.press('Escape')
    customize_review(page, 'Quick critique')
    assert not page.locator('.discuss-comedy-options').count()
    customize_review(page, 'Comedy review')
    assert page.locator('#discussComedyStyle-dark').is_checked()
    assert page.locator('#discussComedyStyle-sarcastic').is_checked()
    assert page.locator('#discussComedyGoal-explore').is_checked()
    assert page.locator('#discussComedyGoal-strengthen').is_checked()
    assert page.locator('[data-scope="adjacent"]').get_attribute('aria-pressed') == 'true'
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == '2 lanes selected'
    assert page.locator('#discussReviewCheckPlan').is_checked()
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    req = requests[-1]
    assert req['action_id'] == 'comedy_review'
    assert req['comedy_styles'] == ['dark', 'sarcastic']
    assert req['comedy_goals'] == ['strengthen', 'explore']
    assert 'comedy_goal' not in req
    assert req['review_lanes'] == ['truth_pain', 'deadpan_subtext']
    assert len(req['scenes']) == 2
    assert req['custom_instruction'] == 'Keep the narrator affectionate; the sarcasm belongs to the son.'
    receipt = page.locator('.discuss-craft-request-summary').last
    assert 'Comic styles: Dark comedy, Sarcasm' in receipt.inner_text()
    assert 'Review goals: Strengthen existing humor, Find comic opportunities' in receipt.inner_text()
    page.locator('.discuss-craft-prompt summary').click()
    assert 'Selected comic style: Dark comedy' in page.locator('.discuss-craft-prompt-body').inner_text()
    # The answer can be on screen before the snapshot that holds it settles.
    wait_for_discuss_idle(page)
    wait_for_discuss_quiet(page)
    page.evaluate("""() => {
        const answer = [..._discussSnapshot.messages].reverse().find(m => m.role === 'assistant');
        answer.text = '### 1. Let the request reveal the contradiction\\n\\n**Lane: Truth & pain — the need for approval undercuts the claim of independence.**';
        renderDiscussSnapshot();
    }""")
    page.get_by_role('button', name='Read about Truth & pain in Comedy review', exact=True).click()
    assert page.locator('#discussCraftInfoDialog [data-tab="truth_pain"]').get_attribute('aria-selected') == 'true'


@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}])
def test_every_comedy_lane_has_readable_examples_exercises_and_reachable_controls(page: Page, server: ProseviewServer, viewport):
    page.set_viewport_size(viewport)
    open_review(page, server, 'Comedy review')
    page.locator('#discussReviewFocusInfo').click()
    dialog = page.locator('#discussCraftInfoDialog')
    for lane in LANES:
        dialog.locator(f'[data-tab="{lane}"]').click()
        assert dialog.locator('.discuss-craft-example-card').count() == 2
        text = dialog.locator('#discussCraftInfoBody').inner_text()
        assert 'Why it works:' in text and 'Try it in your scene' in text and 'Use your judgment' in text
        assert len(text.split()) > 200
        another = dialog.locator('.discuss-craft-another-example')
        assert another.get_attribute('open') is None
        another.locator('summary').click()
        assert another.locator('blockquote').inner_text()
        assert dialog.locator('.discuss-craft-dialog-foot').bounding_box()['y'] < viewport['height']
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
    dialog.locator('[data-tab="overview"]').click()
    dialog.locator('.discuss-review-sources summary').click()
    assert dialog.locator('.discuss-review-source a').count() == 6
    assert 'Peter McGraw & Caleb Warren' in dialog.inner_text()
    assert 'Poking a Dead Frog' in dialog.inner_text()
    assert 'Strengthen existing humor' in dialog.inner_text()
    dialog.get_by_role('button', name='Close review guide', exact=True).click()
    expect(page.locator('#discussReviewFocusInfo')).to_be_focused()


def test_comic_style_info_opens_the_matching_guide_without_changing_lane_selection(page: Page, server: ProseviewServer):
    open_review(page, server, 'Comedy review')
    for style, lane in [('dark', 'violation_distance'), ('sarcastic', 'deadpan_subtext'), ('deadpan', 'deadpan_subtext')]:
        info = page.locator('#discussComedyStyleInfo-' + style)
        info.click()
        dialog = page.locator('#discussCraftInfoDialog')
        assert dialog.locator(f'[data-tab="{lane}"]').get_attribute('aria-selected') == 'true'
        dialog.get_by_role('button', name='Close review guide', exact=True).click()
        expect(info).to_be_focused()
        assert not page.locator('#discussComedyStyle-' + style).is_checked()
    assert page.locator('.discuss-craft-focus-trigger-text').inner_text() == 'All lanes'


def test_quick_critique_does_not_send_remembered_comedy_options(page: Page, server: ProseviewServer):
    requests = capture_questions(page)
    open_review(page, server, 'Comedy review')
    page.locator('#discussComedyStyle-dark').check()
    page.locator('#discussComedyGoal-explore').click()
    customize_review(page, 'Quick critique')
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['action_id'] == 'quick_critique'
    assert all(key not in requests[-1] for key in ('comedy_styles', 'comedy_goal', 'comedy_goals'))


@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}])
def test_comedy_goals_allow_both_or_either_and_require_at_least_one(page: Page, server: ProseviewServer, viewport):
    page.set_viewport_size(viewport)
    requests = capture_questions(page)
    open_review(page, server, 'Comedy review')
    strengthen = page.locator('#discussComedyGoal-strengthen')
    explore = page.locator('#discussComedyGoal-explore')
    assert strengthen.is_checked() and explore.is_checked()
    assert strengthen.is_checked() and explore.is_checked()
    assert 'two kinds of suggestion' in page.locator('#discussComedyGoalHelp').inner_text()
    strengthen.uncheck()
    assert not strengthen.is_checked() and explore.is_checked()
    explore.uncheck()
    assert page.locator('#discussSend').get_attribute('aria-disabled') == 'true'
    assert 'Choose at least one goal' in page.locator('#discussComedyGoalHelp').inner_text()
    assert not requests
    explore.check()
    assert page.locator('#discussSend').get_attribute('aria-disabled') == 'false'
    page.locator('#discussSend').click()
    wait_for_discuss_answer(page, 'Fake answer')
    assert requests[-1]['comedy_goals'] == ['explore']
