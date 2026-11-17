"""Retire auto-installed prompt copies without replacing writer-owned skills."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from .config import Config, DISCUSS_PROMPT_MAX
from .scenes import split_frontmatter


SKILLS_DIR = Path(__file__).parent / "skills"


def migrate_builtin_copies(root: Path, skills_path: str, offered: list[str]) -> None:
    """Migrate one legacy directory. Callers record completion outside the book.

    Known shipped copies are removed. A body-only edit becomes a YAML override
    before its old files are removed. Extra resources, customized metadata,
    symlinks, or a conflicting YAML override identify a writer-owned folder.
    """
    if (root / skills_path).is_symlink():
        return
    directory = (root / skills_path).resolve()
    if not directory.is_relative_to(root.resolve()) or directory == root.resolve():
        return
    manifest = json.loads((SKILLS_DIR / "builtin_manifest.json").read_text(encoding="utf-8"))
    cfg = Config.load(root)
    overrides = dict(cfg.discuss.skill_prompts)
    remove: list[list[Path]] = []
    changed = False
    for name, known in manifest.items():
        target = directory / name
        prompt = target / "SKILL.md"
        if target.is_symlink() or not prompt.is_file() or prompt.is_symlink():
            continue
        if any(p.is_dir() and p.relative_to(target).as_posix() != "agents" for p in target.rglob("*")):
            continue
        files = [p for p in target.rglob("*") if not p.is_dir() or p.is_symlink()]
        if any(p.is_symlink() or p.relative_to(target).as_posix() not in ("SKILL.md", "agents/openai.yaml") for p in files):
            continue
        companion = target / "agents/openai.yaml"
        if companion.is_file() and hashlib.sha256(companion.read_bytes()).hexdigest() not in known.get("agents/openai.yaml", []):
            continue
        raw = prompt.read_bytes()
        current = SKILLS_DIR / name / "SKILL.md"
        untouched = hashlib.sha256(raw).hexdigest() in known["SKILL.md"] or raw == current.read_bytes()
        if not untouched:
            # An unrecorded SKILL.md without the shipped companion is a skill
            # the writer created, rather than evidence of automatic installation.
            if name not in offered and not companion.is_file():
                continue
            frontmatter, body = split_frontmatter(raw.decode("utf-8"))
            body = body.strip()
            if frontmatter not in known.get("frontmatter", []) or not body or len(body) > DISCUSS_PROMPT_MAX:
                continue
            existing = overrides.get(name)
            if existing is not None and existing.strip() != body:
                continue
            if existing is None:
                overrides[name] = body
                changed = True
        remove.append(files)
    # Persist the complete edited text before deleting any copy that owns it.
    if changed:
        cfg.with_overrides(discuss=replace(cfg.discuss, skill_prompts=tuple(sorted(overrides.items())))).save(root)
    for files in remove:
        for path in files:
            path.unlink()
        target = next(p.parent for p in files if p.name == "SKILL.md")
        for path in (target / "agents", target):
            if path.is_dir():
                path.rmdir()
    if directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
