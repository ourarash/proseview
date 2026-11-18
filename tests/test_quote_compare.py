"""Passage comparisons resolve real text and preserve the writer's current version."""
import pytest

from proseview.quote_compare import compare_passage


SCENE = '---\ntitle: Opening\n---\n\n# Opening\n\nThe room was quiet. She kept the key. The door stayed shut.\n\nHe waited.\n'


def test_compares_only_the_exact_before_span_and_preserves_source_line_numbers():
    result = compare_passage(SCENE, 'She hid the key.', original='She kept the key.', line=7)
    assert result['before'] == 'She kept the key.'
    assert result['after'] == 'She hid the key.'
    assert result['line'] == 7
    assert '@@ -7 +7 @@' in result['patch']
    assert 'room' not in result['patch'] and 'door' not in result['patch']


def test_markdown_and_wrapping_do_not_create_false_changes():
    result = compare_passage('A **quiet** room.\nA locked door.\n', 'A quiet room. A locked door.', line=1)
    assert result['matches']
    assert not compare_passage('A quiet room.\n\nA locked door.\n', 'A quiet room. A locked door.', line=1)['matches']


def test_unsaved_changes_to_the_target_passage_are_compared_without_including_its_neighbours():
    live = SCENE.split('# Opening\n\n')[1].replace('She kept the key.', 'She dropped the key.')
    result = compare_passage(SCENE, 'She hid the key.', original='She kept the key.', line=7, live=live, live_line_offset=6)
    assert result['before'] == 'She dropped the key.'
    assert result['after'] == 'She hid the key.'
    assert result['line'] == 7


def test_line_citation_selects_the_whole_paragraph_for_a_standalone_rewrite():
    result = compare_passage(SCENE, 'A completely different paragraph.', line=7)
    assert result['before'] == 'The room was quiet. She kept the key. The door stayed shut.'


def test_duplicate_quotes_require_an_unambiguous_source_citation():
    scene = 'She waited.\n\nShe waited.\n'
    with pytest.raises(ValueError, match='more than once'):
        compare_passage(scene, 'She left.', original='She waited.')
    with pytest.raises(ValueError, match='more than once'):
        compare_passage(scene, 'She left.', original='She waited.', line=99)
    assert compare_passage(scene, 'She left.', original='She waited.', line=3)['line'] == 3


def test_missing_or_stale_sources_do_not_compare_an_unrelated_passage():
    with pytest.raises(ValueError, match='Could not locate'):
        compare_passage(SCENE, 'She hid the key.', line=500)
    with pytest.raises(ValueError, match='has changed'):
        compare_passage(SCENE, 'The ship sailed.', original='At sea, the captain watched the dawn.', line=7)


def test_insertions_keep_the_existing_passage_and_cuts_remove_it():
    result = compare_passage(SCENE, 'She listened.', original='He waited.', line=9, kind='insert-after')
    assert result['after'] == 'He waited.\n\nShe listened.'
    assert '-He waited.' not in result['patch']
    result = compare_passage(SCENE, '', original='He waited.', line=9)
    assert result['after'] == ''
    assert '-He waited.' in result['patch']
    already = SCENE + '\nShe listened.\n'
    assert compare_passage(already, 'She listened.', original='He waited.', line=9, kind='insert-after')['matches']
