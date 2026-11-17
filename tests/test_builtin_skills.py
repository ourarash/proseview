from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from proseview import builtin_skills
from proseview.config import Config
from proseview.discuss import DiscussManager, DiscussStateStore, action_instruction, default_skill_body, DEFAULT_SKILLS_DIR
from proseview.scenes import split_frontmatter
from .transport_fakes import CodexFakeClient


def _book(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'book'
    (root / 'manuscript').mkdir(parents=True)
    (root / 'manuscript/one.md').write_text('# One\n\nShe waited.\n')
    return root


def _manager(root):
    return DiscussManager(root, client_factory=lambda callback, _agent=None: CodexFakeClient(callback))


@pytest.mark.parametrize('name', sorted(json.loads((DEFAULT_SKILLS_DIR / 'builtin_manifest.json').read_text())))
def test_untouched_builtins_are_removed_and_keep_using_packaged_prompt(tmp_path, monkeypatch, name):
    root = _book(tmp_path, monkeypatch)
    folder = root / '.proseview/skills' / name
    shutil.copytree(DEFAULT_SKILLS_DIR / name, folder)
    with_manager = _manager(root)
    try:
        assert not folder.exists()
        assert action_instruction(root, name) == default_skill_body(name)
        assert not (root / '.proseview.yaml').exists()
    finally:
        with_manager.close()


def test_old_defaults_and_edited_copies_migrate_once_preserving_yaml_comments(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    packaged = tmp_path / 'packaged'
    fm = '---\nname: quick_critique\ndescription: Read carefully.\n---\n\n'
    old = fm + 'Old shipped instructions.\n'
    current = fm + 'New shipped instructions.\n'
    package = packaged / 'quick_critique'
    package.mkdir(parents=True)
    (package / 'SKILL.md').write_text(current)
    (packaged / 'builtin_manifest.json').write_text(json.dumps({'quick_critique': {
        'SKILL.md': [hashlib.sha256(old.encode()).hexdigest()],
        'frontmatter': [split_frontmatter(old)[0]],
    }}))
    monkeypatch.setattr(builtin_skills, 'SKILLS_DIR', packaged)
    folder = root / '.proseview/skills/quick_critique'
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text(old)
    builtin_skills.migrate_builtin_copies(root, '.proseview/skills', ['quick_critique'])
    assert not folder.exists()
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text(fm + 'My exact editorial approach.\n')
    (root / '.proseview.yaml').write_text('# Keep this comment\ntarget_words: 90000\n')
    DiscussStateStore(root).record_offered_skills(['quick_critique'], '.proseview/skills')
    manager = _manager(root)
    assert not folder.exists()
    assert action_instruction(root, 'quick_critique') == 'My exact editorial approach.'
    assert '# Keep this comment' in (root / '.proseview.yaml').read_text()
    row = next(row for row in manager.discuss_settings()['skills'] if row['id'] == 'quick_critique')
    assert row['customized'] and row['source'] == 'yaml'
    manager.close()
    # A later, deliberately created folder is writer-owned, even if it starts
    # with a built-in's exact text.
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text(current)
    _manager(root).close()
    assert (folder / 'SKILL.md').read_text() == current


def test_edited_copy_becomes_override_without_losing_an_existing_override(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    folder = root / '.proseview/skills/quick_critique'
    shutil.copytree(DEFAULT_SKILLS_DIR / 'quick_critique', folder)
    with (folder / 'SKILL.md').open('a') as handle:
        handle.write('\nMy custom instruction.\n')
    manager = _manager(root)
    assert not folder.exists()
    assert 'My custom instruction.' in Config.load(root).discuss.skill_prompt('quick_critique')
    manager.close()
    shutil.copytree(DEFAULT_SKILLS_DIR / 'quick_critique', folder)
    with (folder / 'SKILL.md').open('a') as handle:
        handle.write('\nA different file customization.\n')
    builtin_skills.migrate_builtin_copies(root, '.proseview/skills', ['quick_critique'])
    assert folder.exists()
    assert 'My custom instruction.' in action_instruction(root, 'quick_critique')


@pytest.mark.parametrize('custom', ['resource', 'metadata', 'writer_created'])
def test_writer_owned_skills_are_kept(tmp_path, monkeypatch, custom):
    root = _book(tmp_path, monkeypatch)
    folder = root / '.proseview/skills/quick_critique'
    if custom == 'writer_created':
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: quick_critique\n---\n\nWriter-owned prompt.\n')
    else:
        shutil.copytree(DEFAULT_SKILLS_DIR / 'quick_critique', folder)
        if custom == 'resource':
            (folder / 'notes.txt').write_text('My supporting notes.')
        else:
            p = folder / 'agents/openai.yaml'
            p.write_text(p.read_text() + '\n# My interface change\n')
    before = (folder / 'SKILL.md').read_text()
    _manager(root).close()
    assert (folder / 'SKILL.md').read_text() == before


def test_lookup_precedence_and_packaged_defaults_in_settings(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    manager = _manager(root)
    folder = root / 'my-skills/quick_critique'
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text('---\nname: quick_critique\n---\n\nMy skill file.\n')
    (root / '.proseview.yaml').write_text('skills_path: my-skills\n')
    assert action_instruction(root, 'quick_critique') == 'My skill file.'
    cfg = Config.load(root)
    cfg.with_overrides(discuss=replace(cfg.discuss, skill_prompts=(('quick_critique', 'YAML wins.'),))).save(root)
    settings = manager.discuss_settings()
    assert settings['book']['skill_prompts']['quick_critique'] == 'YAML wins.'
    assert settings['defaults']['skill_prompts']['quick_critique'] == default_skill_body('quick_critique')
    assert action_instruction(root, 'quick_critique') == 'YAML wins.'
    manager.close()
