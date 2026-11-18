"""Quote previews use the existing diff viewer without modifying the scene."""
import pytest

expect = pytest.importorskip('playwright.sync_api').expect
from .conftest import SCENE_REL
from .test_browser_e2e import CHANGED_SENTENCE, OPENED_SENTENCE, enter_edit_mode
from .test_group_recap_e2e import seed_recap

pytestmark = pytest.mark.e2e_browser


@pytest.mark.parametrize('width', [1440, 800])
def test_quote_comparison_shows_only_changed_words_and_preserves_chat_position(page, server, tmp_path, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    pane, _ = seed_recap(page, server)
    saved = server.scene_path().read_text()
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    card = pane.locator('.group-edit-card').first
    controls = card.locator('.discuss-quote-actions')
    button = controls.nth(1).get_by_role('button', name='Compare', exact=True)
    button.scroll_into_view_if_needed()
    top = pane.locator('#groupBody').evaluate('el=>el.scrollTop')
    page.screenshot(path=str(tmp_path / 'quote-compare-entry.png'))
    button.click()
    overlay = page.locator('#discussDiffModalOverlay')
    expect(overlay).to_be_visible()
    expect(overlay.locator('#discussDiffModalTitle')).to_have_text('Compare passage')
    expect(overlay.locator('.discuss-quote-comparison-labels')).to_contain_text('Current scene')
    expect(overlay.locator('.discuss-quote-comparison-labels')).to_contain_text('Suggested text')
    expect(overlay.locator('td.diff_sub')).to_contain_text(OPENED_SENTENCE)
    expect(overlay.locator('td.diff_add')).to_contain_text(CHANGED_SENTENCE)
    assert overlay.locator('del.diff-delete').count() > 0
    assert overlay.locator('ins.diff-insert').count() > 0
    assert 'The loft smelled' not in overlay.locator('#discussDiffModalContent').inner_text()
    assert overlay.locator('input[type=checkbox]').count() == 0
    assert overlay.locator('.diff-modal').evaluate('el=>el.scrollWidth<=el.clientWidth+1')
    page.screenshot(path=str(tmp_path / 'quote-compare.png'))
    overlay.get_by_role('slider', name='Aa', exact=True).focus()
    page.keyboard.press('ArrowRight')
    expect(overlay.locator('td.diff_sub')).to_have_css('font-size', '19px')
    overlay.get_by_role('button', name='Inline', exact=True).click()
    expect(overlay.locator('table.diff-inline')).to_be_visible()
    page.keyboard.press('Escape')
    expect(overlay).to_be_hidden()
    expect(button).to_be_focused()
    assert abs(pane.locator('#groupBody').evaluate('el=>el.scrollTop') - top) < 2
    assert server.scene_path().read_text() == saved
    controls.nth(0).get_by_role('button', name='Compare', exact=True).click()
    expect(overlay.locator('#discussDiffModalContent')).to_have_text('Matches the current scene.')
    page.keyboard.press('Escape')
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    controls.nth(1).get_by_role('button', name='Copy quote', exact=True).click()
    assert page.evaluate('navigator.clipboard.readText()') == CHANGED_SENTENCE


def test_quote_comparison_uses_unsaved_target_text_without_saving_it(page, server):
    pane, _ = seed_recap(page, server)
    saved = server.scene_path().read_text()
    enter_edit_mode(page)
    current = 'She had changed the code yesterday.'
    page.evaluate('''({before, after}) => {
        let change = null;
        _pmView.state.doc.descendants((node, pos) => {
            if (node.isText && node.text.includes(before)) change = {from:pos+node.text.indexOf(before), to:pos+node.text.indexOf(before)+before.length};
        });
        _pmView.dispatch(_pmView.state.tr.insertText(after, change.from, change.to));
    }''', {'before': OPENED_SENTENCE, 'after': current})
    pane.get_by_role('button', name='Latest recap', exact=True).click()
    pane.locator('.group-edit-card').first.locator('.discuss-quote-actions').nth(1).get_by_role('button', name='Compare', exact=True).click()
    overlay = page.locator('#discussDiffModalOverlay')
    expect(overlay.locator('td.diff_sub')).to_contain_text(current)
    expect(overlay.locator('#discussDiffModalNote')).to_contain_text('unsaved edits')
    expect(overlay.locator('td.diff_add')).to_contain_text(CHANGED_SENTENCE)
    assert server.scene_path().read_text() == saved
    page.keyboard.press('Escape')
    assert page.evaluate('_pmDirty')


def test_source_linked_quotes_in_normal_chat_compare_other_files_and_report_missing_passages(page, server):
    target = server.root / 'plans' / 'structure-notes.md'
    target.write_text('The lamp was **green**.\n\nA quiet room.\n')
    pane, _ = seed_recap(page, server)
    page.evaluate('''() => {
        const node = document.createElement('div'); node.className='discuss-message'; node.id='normalCompare';
        renderDiscussMarkdown(node, '**Before:**\\n\\n> *The lamp was green.*\\n\\n[structure-notes.md · Line 1](plans/structure-notes.md#L1)\\n\\n**After:** Replace [structure-notes.md · Line 1](plans/structure-notes.md#L1):\\n\\n> The lamp was blue.');
        document.getElementById('groupBody').appendChild(node);
    }''')
    block = page.locator('#normalCompare')
    block.locator('.discuss-quote-actions').nth(1).get_by_role('button', name='Compare', exact=True).click()
    overlay = page.locator('#discussDiffModalOverlay')
    expect(overlay.locator('.discuss-quote-comparison-labels')).to_contain_text('Current file')
    expect(overlay.locator('td.diff_sub')).to_have_text('The lamp was green.')
    expect(overlay.locator('td.diff_add')).to_have_text('The lamp was blue.')
    assert page.evaluate('paths[curIdx]') == SCENE_REL
    page.keyboard.press('Escape')
    block.locator('blockquote').nth(1).evaluate("el=>{el.dataset.targetLine='99';el.dataset.targetEndLine='99';el._discussCompareOriginal='A nonexistent original passage.';}")
    block.locator('.discuss-quote-actions').nth(1).get_by_role('button', name='Compare', exact=True).click()
    expect(overlay.locator('#discussDiffModalContent')).to_contain_text('Could not locate this passage')
    page.keyboard.press('Escape')
