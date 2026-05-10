"""Configuration loader for ``.proseview.yaml``.

Holds the v1 config surface defined in the implementation plan: manuscript
path, target word count and daily cadence, lexical goal bands, chapter glob,
character and location overrides, and editor handoff settings. Every key has
a default so a repo without ``.proseview.yaml`` still produces a dashboard.

The loader implements a narrow subset of YAML sufficient for the v1 config
shape (scalars, inline arrays, block lists, one level of nested mapping).
Adopting PyYAML is an option tracked in the plan's Open Questions; for now
the stdlib-only parser keeps v1 single-file-ish.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


DEFAULT_EDITOR_SCHEME = "vscode"
BUILTIN_EDITOR_SCHEMES = {"vscode", "cursor", "zed", "positron", "custom"}

# These defaults are conventions, not hard requirements. A novel repo that
# uses different folder names sets `characters_path`, `skills_path`, and
# `repo_tab.folders` in its `.proseview.yaml`; missing folders are simply
# skipped at render time.
DEFAULT_CHARACTERS_PATH = "story-bible/characters"
DEFAULT_SKILLS_PATH = "skills"
DEFAULT_REPO_TAB_FOLDERS: tuple[str, ...] = (
    "plans", "continuity", "outline", "story-bible", "docs", "templates",
)
DEFAULT_REPO_TAB_PREVIEW_MAX_BYTES = 512 * 1024


@dataclass(frozen=True)
class EditorConfig:
    scheme: str = DEFAULT_EDITOR_SCHEME
    url_template: str | None = None


@dataclass(frozen=True)
class RepoTabConfig:
    folders: tuple[str, ...] = DEFAULT_REPO_TAB_FOLDERS
    preview_max_bytes: int = DEFAULT_REPO_TAB_PREVIEW_MAX_BYTES


@dataclass(frozen=True)
class Config:
    manuscript_path: str = "manuscript/"
    characters_path: str = DEFAULT_CHARACTERS_PATH
    skills_path: str = DEFAULT_SKILLS_PATH
    target_words: int = 80000
    daily_target: int = 500
    mattr_band: tuple[float, float] = (0.74, 0.77)
    mtld_band: tuple[float, float] = (105.0, 130.0)
    chapter_pattern: str = "ch*"
    characters: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    editor: EditorConfig = field(default_factory=EditorConfig)
    repo_tab: RepoTabConfig = field(default_factory=RepoTabConfig)

    @property
    def manuscript_subdir(self) -> str:
        return self.manuscript_path.rstrip("/")

    @property
    def characters_dir(self) -> str:
        return self.characters_path.rstrip("/")

    @property
    def skills_dir(self) -> str:
        return self.skills_path.rstrip("/")

    @classmethod
    def load(cls, repo_root: Path) -> "Config":
        """Load ``.proseview.yaml`` from ``repo_root``, falling back to defaults.

        Missing file: silently returns defaults. Unknown top-level keys: warned
        once but the rest of the config still loads. Invalid values for known
        keys raise ``ConfigError`` so the CLI fails loudly rather than silently
        rendering wrong numbers.
        """
        path = repo_root / ".proseview.yaml"
        if not path.exists():
            return cls()
        raw = _parse_yaml(path.read_text(encoding="utf-8"))
        return cls._from_raw(raw, source=path)

    @classmethod
    def _from_raw(cls, raw: dict[str, Any], *, source: Path | None = None) -> "Config":
        defaults = cls()
        known = set(_config_field_names())
        for key in raw:
            if key not in known:
                import warnings
                origin = f" ({source})" if source else ""
                warnings.warn(f"proseview: unknown config key {key!r}{origin}; ignoring",
                              stacklevel=2)

        manuscript_path = _coerce_str(raw.get("manuscript_path", defaults.manuscript_path),
                                      "manuscript_path")
        if not manuscript_path.endswith("/"):
            manuscript_path = manuscript_path + "/"

        return cls(
            manuscript_path=manuscript_path,
            characters_path=_coerce_str(raw.get("characters_path", defaults.characters_path),
                                        "characters_path"),
            skills_path=_coerce_str(raw.get("skills_path", defaults.skills_path),
                                    "skills_path"),
            target_words=_coerce_int(raw.get("target_words", defaults.target_words),
                                     "target_words"),
            daily_target=_coerce_int(raw.get("daily_target", defaults.daily_target),
                                     "daily_target"),
            mattr_band=_coerce_band(raw.get("mattr_band", defaults.mattr_band),
                                    "mattr_band"),
            mtld_band=_coerce_band(raw.get("mtld_band", defaults.mtld_band),
                                   "mtld_band"),
            chapter_pattern=_coerce_str(raw.get("chapter_pattern", defaults.chapter_pattern),
                                        "chapter_pattern"),
            characters=_coerce_str_tuple(raw.get("characters", ()), "characters"),
            locations=_coerce_str_tuple(raw.get("locations", ()), "locations"),
            editor=_coerce_editor(raw.get("editor")),
            repo_tab=_coerce_repo_tab(raw.get("repo_tab")),
        )

    def with_overrides(self, **kwargs: Any) -> "Config":
        """Return a new ``Config`` with the given fields replaced. Convenience
        for tests and the upcoming ``--config`` CLI overrides.
        """
        return replace(self, **kwargs)


class ConfigError(ValueError):
    """Raised when ``.proseview.yaml`` contains an invalid value for a known key."""


def _config_field_names() -> tuple[str, ...]:
    return (
        "manuscript_path", "characters_path", "skills_path",
        "target_words", "daily_target",
        "mattr_band", "mtld_band", "chapter_pattern",
        "characters", "locations", "editor", "repo_tab",
    )


def _coerce_str(v: Any, key: str) -> str:
    if isinstance(v, str):
        return v
    raise ConfigError(f"{key!r} must be a string, got {type(v).__name__}: {v!r}")


def _coerce_int(v: Any, key: str) -> int:
    if isinstance(v, bool):
        raise ConfigError(f"{key!r} must be an integer, got bool")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ConfigError(f"{key!r} must be an integer, got {type(v).__name__}: {v!r}")


def _coerce_float(v: Any, key: str) -> float:
    if isinstance(v, bool):
        raise ConfigError(f"{key!r} entries must be numbers, got bool")
    if isinstance(v, (int, float)):
        return float(v)
    raise ConfigError(f"{key!r} entries must be numbers, got {type(v).__name__}: {v!r}")


def _coerce_band(v: Any, key: str) -> tuple[float, float]:
    if isinstance(v, tuple) and len(v) == 2:
        return (_coerce_float(v[0], key), _coerce_float(v[1], key))
    if isinstance(v, list):
        if len(v) != 2:
            raise ConfigError(f"{key!r} must be a 2-element list, got {len(v)} elements")
        return (_coerce_float(v[0], key), _coerce_float(v[1], key))
    raise ConfigError(f"{key!r} must be a 2-element list, got {type(v).__name__}: {v!r}")


def _coerce_str_tuple(v: Any, key: str) -> tuple[str, ...]:
    if isinstance(v, tuple):
        return tuple(_coerce_str(x, key) for x in v)
    if isinstance(v, list):
        return tuple(_coerce_str(x, key) for x in v)
    if v is None:
        return ()
    raise ConfigError(f"{key!r} must be a list of strings, got {type(v).__name__}: {v!r}")


def _coerce_editor(v: Any) -> EditorConfig:
    defaults = EditorConfig()
    if v is None:
        return defaults
    if not isinstance(v, dict):
        raise ConfigError(f"'editor' must be a mapping, got {type(v).__name__}: {v!r}")
    scheme = v.get("scheme", defaults.scheme)
    if not isinstance(scheme, str):
        raise ConfigError(f"'editor.scheme' must be a string, got {type(scheme).__name__}")
    if scheme not in BUILTIN_EDITOR_SCHEMES:
        allowed = ", ".join(sorted(BUILTIN_EDITOR_SCHEMES))
        raise ConfigError(f"'editor.scheme' must be one of {{{allowed}}}; got {scheme!r}")
    url_template = v.get("url_template", defaults.url_template)
    if url_template is not None and not isinstance(url_template, str):
        raise ConfigError("'editor.url_template' must be a string or null")
    if scheme == "custom" and not url_template:
        raise ConfigError("'editor.scheme: custom' requires 'editor.url_template'")
    return EditorConfig(scheme=scheme, url_template=url_template)


def _coerce_repo_tab(v: Any) -> RepoTabConfig:
    defaults = RepoTabConfig()
    if v is None:
        return defaults
    if not isinstance(v, dict):
        raise ConfigError(f"'repo_tab' must be a mapping, got {type(v).__name__}: {v!r}")
    folders_raw = v.get("folders", defaults.folders)
    folders = _coerce_str_tuple(folders_raw, "repo_tab.folders") if folders_raw else defaults.folders
    preview_raw = v.get("preview_max_bytes", defaults.preview_max_bytes)
    preview_max_bytes = _coerce_int(preview_raw, "repo_tab.preview_max_bytes")
    if preview_max_bytes <= 0:
        raise ConfigError("'repo_tab.preview_max_bytes' must be a positive integer")
    return RepoTabConfig(folders=folders, preview_max_bytes=preview_max_bytes)


def _parse_scalar(v: str) -> Any:
    v = v.strip()
    if v == "" or v.lower() == "null" or v == "~":
        return None
    low = v.lower()
    if low in {"true", "yes"}:
        return True
    if low in {"false", "no"}:
        return False
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_inline_list(v: str) -> list[Any]:
    inner = v[1:-1].strip()
    if not inner:
        return []
    parts, depth, buf = [], 0, ""
    for ch in inner:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [_parse_scalar(p) for p in parts]


def _parse_value(v: str) -> Any:
    if v.startswith("[") and v.endswith("]"):
        return _parse_inline_list(v)
    return _parse_scalar(v)


def _parse_yaml(text: str) -> dict[str, Any]:
    """Parse the v1 ``.proseview.yaml`` shape: top-level scalars, inline arrays,
    bulleted block lists, and a single level of nested mapping under ``editor``.

    Not a general YAML parser. If more sophistication is needed later we can
    swap in PyYAML behind the same signature.
    """
    root: dict[str, Any] = {}
    mapping_stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    pending_list: tuple[int, dict[str, Any], str] | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip()

        while len(mapping_stack) > 1 and mapping_stack[-1][0] >= indent:
            mapping_stack.pop()
        if pending_list and pending_list[0] >= indent and not content.startswith("- "):
            pending_list = None

        if content.startswith("- "):
            if not pending_list:
                raise ConfigError(
                    f"unexpected list item at top level: {line!r}"
                )
            _, container, key = pending_list
            if not isinstance(container.get(key), list):
                container[key] = []
            container[key].append(_parse_scalar(content[2:]))
            continue

        if ":" not in content:
            raise ConfigError(f"unrecognized config line: {line!r}")
        key, value = content.split(":", 1)
        key = key.strip()
        value = value.strip()

        parent_indent, parent = mapping_stack[-1]
        if not value:
            parent[key] = {}
            mapping_stack.append((indent, parent[key]))
            pending_list = (indent, parent, key)
        else:
            parent[key] = _parse_value(value)
            pending_list = None
    return root
