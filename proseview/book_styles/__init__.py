"""Book styles: how an exported book looks.

A style is a folder. ``epub.css`` styles the EPUB, ``pdf.typ`` lays out the
PDFs (see the comment at the top of ``classic/pdf.typ`` for what it must
define), and ``style.yaml`` holds the few choices neither can make on its
own: how chapters are numbered, what a scene break looks like, and whether
scene titles show. A style may have only one of the two designs; it then
offers only those formats. Adding a style is adding a folder here, or
pointing ``--style`` at a folder of your own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent
DEFAULT_STYLE = "classic"
CHAPTER_NUMBERING: tuple[str, ...] = ("words", "numerals", "number", "none")


class StyleError(ValueError):
    """A style that cannot be found or does not make sense."""


#: Every export format, in the order the dialog offers them.
FORMATS: tuple[str, ...] = ("epub", "pdf-print", "pdf-share")


@dataclass(frozen=True)
class BookStyle:
    name: str
    path: Path
    css: str | None
    chapter_numbering: str = "words"
    scene_break: str = "* * *"
    show_scene_titles: bool = False
    pdf_template: str | None = None
    description: str = ""
    #: Formats ``style.yaml`` limits the style to; empty means all it can make.
    declared_formats: tuple[str, ...] = ()
    #: Layout choices the shared PDF template reads (``pdf:`` in style.yaml).
    pdf_settings: tuple[tuple[str, object], ...] = ()

    @property
    def formats(self) -> tuple[str, ...]:
        """The formats this style makes: EPUB with a stylesheet, PDFs with a template."""
        return tuple(
            fmt for fmt in FORMATS
            if ((fmt == "epub" and self.css is not None) or (fmt != "epub" and self.pdf_template is not None))
            and (not self.declared_formats or fmt in self.declared_formats)
        )


#: What the shared PDF layout (classic/pdf.typ) can vary, with Classic's choices.
PDF_DEFAULTS: dict[str, object] = {
    "body_font": "Libertinus Serif",
    "heading_font": "Libertinus Serif",
    # classic: "Chapter One" in spaced capitals over an italic title.
    # modern: a large numeral over the title, both in the heading font.
    # romance: an italic numeral between ornaments over a large italic title.
    "opener": "classic",
    "drop_cap": True,
    "ornament": "",
}
PDF_OPENERS = ("classic", "modern", "romance")


def _is_style(folder: Path) -> bool:
    return (
        (folder / "epub.css").is_file() or (folder / "pdf.typ").is_file()
        or (folder / "style.yaml").is_file() and "extends:" in (folder / "style.yaml").read_text(encoding="utf-8")
    )


def available_styles() -> list[str]:
    """Names of the styles that ship with Proseview."""
    return sorted(
        entry.name for entry in STYLES_DIR.iterdir()
        if entry.is_dir() and entry.name != "fonts" and _is_style(entry)
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
        folder = next((c for c in candidates if _is_style(c)), None)
    if folder is None:
        raise StyleError(
            f"No book style called {wanted!r}. Built-in styles: {', '.join(available_styles())}; "
            "or pass a folder that holds an epub.css or a pdf.typ."
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
    declared = settings.get("formats") or []
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, list) or any(str(f) not in FORMATS for f in declared):
        raise StyleError(f"{settings_file}: formats must list some of {', '.join(FORMATS)}")
    css_file, pdf_file = folder / "epub.css", folder / "pdf.typ"
    css = css_file.read_text(encoding="utf-8") if css_file.is_file() else None
    pdf_template = pdf_file.read_text(encoding="utf-8") if pdf_file.is_file() else None
    pdf_settings = dict(PDF_DEFAULTS)

    # A style may build on another: its stylesheet is added after the base
    # one, and it lays out PDFs with the base template unless it has its own.
    parent = settings.get("extends")
    if parent:
        if str(parent).casefold() == folder.name.casefold():
            raise StyleError(f"{settings_file}: a style cannot extend itself")
        base_style = load_style(str(parent))
        if css is not None and base_style.css is not None:
            css = base_style.css + "\n\n/* ---- " + str(settings.get("name") or folder.name) + " ---- */\n\n" + css
        elif css is None:
            css = base_style.css
        pdf_template = pdf_template or base_style.pdf_template
        pdf_settings.update(dict(base_style.pdf_settings))
    own_pdf = settings.get("pdf") or {}
    if not isinstance(own_pdf, dict) or any(key not in PDF_DEFAULTS for key in own_pdf):
        raise StyleError(f"{settings_file}: pdf may set {', '.join(PDF_DEFAULTS)}")
    pdf_settings.update(own_pdf)
    if pdf_settings["opener"] not in PDF_OPENERS:
        raise StyleError(f"{settings_file}: pdf.opener must be one of {', '.join(PDF_OPENERS)}")
    return BookStyle(
        name=str(settings.get("name") or folder.name),
        path=folder,
        css=css,
        chapter_numbering=numbering,
        scene_break=str(settings.get("scene_break", "* * *")),
        show_scene_titles=show_titles,
        pdf_template=pdf_template,
        description=str(settings.get("description") or "").strip(),
        declared_formats=tuple(str(f) for f in declared),
        pdf_settings=tuple(pdf_settings.items()),
    )
