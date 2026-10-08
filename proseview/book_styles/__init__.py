"""Book styles: how an exported book looks.

A style is a folder. ``epub.css`` styles the EPUB, and ``style.yaml`` holds
the few choices a stylesheet cannot make on its own: how chapters are
numbered, what a scene break looks like, and whether scene titles show.
Adding a style is adding a folder here, or pointing ``--style`` at a folder
of your own with the same two files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent
DEFAULT_STYLE = "classic"
CHAPTER_NUMBERING: tuple[str, ...] = ("words", "numerals", "none")


class StyleError(ValueError):
    """A style that cannot be found or does not make sense."""


@dataclass(frozen=True)
class BookStyle:
    name: str
    path: Path
    css: str
    chapter_numbering: str = "words"
    scene_break: str = "* * *"
    show_scene_titles: bool = False


def available_styles() -> list[str]:
    """Names of the styles that ship with Proseview."""
    return sorted(
        entry.name for entry in STYLES_DIR.iterdir()
        if entry.is_dir() and (entry / "epub.css").is_file()
    )


def load_style(spec: str = "", *, base: Path | None = None) -> BookStyle:
    """Load a built-in style by name, or a style folder by path.

    A relative path is tried against *base* (the novel's folder) first, so
    ``--style styles/mine`` means the folder inside the book.
    """
    import yaml

    wanted = (spec or DEFAULT_STYLE).strip()
    folder: Path | None = None
    if wanted.casefold() in {name.casefold() for name in available_styles()}:
        folder = STYLES_DIR / wanted.casefold()
    else:
        candidates = [Path(wanted).expanduser()]
        if base is not None and not Path(wanted).is_absolute():
            candidates.insert(0, base / wanted)
        folder = next((c for c in candidates if (c / "epub.css").is_file()), None)
    if folder is None:
        raise StyleError(
            f"No book style called {wanted!r}. Built-in styles: {', '.join(available_styles())}; "
            "or pass a folder that holds an epub.css."
        )

    settings: dict = {}
    settings_file = folder / "style.yaml"
    if settings_file.is_file():
        try:
            settings = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise StyleError(f"{settings_file} is not valid YAML: {exc}") from exc
        if not isinstance(settings, dict):
            raise StyleError(f"{settings_file} must be a mapping")
    numbering = str(settings.get("chapter_numbering", "words")).strip().lower()
    if numbering not in CHAPTER_NUMBERING:
        raise StyleError(
            f"{settings_file}: chapter_numbering must be one of {', '.join(CHAPTER_NUMBERING)}"
        )
    show_titles = settings.get("show_scene_titles", False)
    if not isinstance(show_titles, bool):
        raise StyleError(f"{settings_file}: show_scene_titles must be true or false")
    return BookStyle(
        name=str(settings.get("name") or folder.name),
        path=folder,
        css=(folder / "epub.css").read_text(encoding="utf-8"),
        chapter_numbering=numbering,
        scene_break=str(settings.get("scene_break", "* * *")),
        show_scene_titles=show_titles,
    )
