"""Tests for the theme layer.

Themes live in ``templates/assets/themes/*.css`` and are concatenated onto
``app.css`` at load time, so one can be added without touching the main
stylesheet. Covers:

- every theme file is picked up and inlined into the dashboard
- a theme defines the same token set as the stock themes it sits beside
- the graphite pair keeps readable contrast on its own surfaces
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.generator import _load_app_css, build_dashboard  # noqa: E402

FIXTURE = REPO_ROOT / "fixtures" / "demo-repo"
THEMES_DIR = REPO_ROOT / "proseview" / "templates" / "assets" / "themes"
GRAPHITE = ("graphite-light", "graphite-dark")


def _tokens(css: str, selector: str) -> dict[str, str]:
    body = css.split(selector + " {", 1)[1].split("\n        }", 1)[0]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


def _relative_luminance(hex_color: str) -> float:
    parts = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    parts = [p / 12.92 if p <= 0.03928 else ((p + 0.055) / 1.055) ** 2.4 for p in parts]
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_every_theme_file_is_concatenated_onto_the_stylesheet():
    css = _load_app_css()

    assert ".repo-tree" in css, "the base stylesheet must still be there"
    for path in THEMES_DIR.glob("*.css"):
        marker = path.read_text(encoding="utf-8").split("[data-theme=", 1)[1][:40]
        assert marker.split("]")[0] in css, f"{path.name} was not concatenated"


def test_themes_reach_the_rendered_dashboard():
    html = build_dashboard(FIXTURE, Config.load(FIXTURE))

    for name in GRAPHITE:
        assert f'[data-theme="{name}"]' in html, f"{name} is missing from the page"
        assert f'value="{name}"' in html, f"{name} is not offered in the theme picker"


@pytest.mark.parametrize("name", GRAPHITE)
def test_a_theme_overrides_everything_a_mode_switch_needs(name: str):
    """A partial theme leaves the previous theme's colours showing through.

    ``:root`` supplies the defaults and always applies, so the set a theme must
    override is exactly what the stock dark theme overrides — that is the
    proven list for flipping a page out of the light defaults and back.
    """
    css = _load_app_css()
    switchable = set(_tokens(css, '[data-theme="dark"]'))

    missing = switchable - set(_tokens(css, f'[data-theme="{name}"]'))

    assert not missing, f"{name} does not define: {sorted(missing)}"


@pytest.mark.parametrize("name", GRAPHITE)
def test_graphite_text_stays_readable_on_its_own_surfaces(name: str):
    tokens = _tokens(_load_app_css(), f'[data-theme="{name}"]')

    for fg, bg, floor in [
        ("--text-main", "--surface-card", 4.5),
        ("--text-main", "--bg-app", 4.5),
        ("--text-muted", "--surface-card", 4.5),
        ("--text-reading", "--surface-card", 4.5),
        ("--primary", "--surface-card", 3.0),
    ]:
        ratio = _contrast(tokens[fg], tokens[bg])
        assert ratio >= floor, f"{name}: {fg} on {bg} is {ratio:.2f}, needs {floor}"


@pytest.mark.parametrize("name", GRAPHITE)
def test_graphite_banner_text_is_readable_on_its_accent(name: str):
    """The hero banner paints --text-inverse on --primary.

    A theme whose accent is light needs dark banner text, the way Docsify's
    green banner already does. 3.0 is the WCAG floor for text this large.
    """
    tokens = _tokens(_load_app_css(), f'[data-theme="{name}"]')

    ratio = _contrast(tokens["--text-inverse"], tokens["--primary"])

    assert ratio >= 3.0, f"{name}: banner text is {ratio:.2f}:1 on the accent"


@pytest.mark.parametrize("name", GRAPHITE)
def test_graphite_declares_its_colour_scheme(name: str):
    """Without color-scheme the browser paints form controls for the wrong mode."""
    css = _load_app_css()
    body = css.split(f'[data-theme="{name}"] {{', 1)[1].split("\n        }", 1)[0]

    expected = "dark" if name.endswith("dark") else "light"
    assert f"color-scheme: {expected};" in body


def test_bootstrap_theme_allowlist_matches_theme_order():
    """The pre-paint bootstrap and THEME_ORDER must list the same themes.

    The bootstrap runs before the bundle, so it cannot read ``THEME_ORDER`` and
    keeps its own copy. When Graphite was added the copy was not updated, so
    picking it worked until the next reload and then silently reverted to light
    -- the theme was effectively unusable while looking like it worked.
    """
    import re

    template = (REPO_ROOT / "proseview" / "templates" / "index.html.j2").read_text(encoding="utf-8")
    state = (REPO_ROOT / "proseview" / "templates" / "assets" / "js" / "00-state.js").read_text(
        encoding="utf-8"
    )

    bootstrap = re.search(
        r"const allowed = \[([^\]]+)\];\s*\n\s*const stored = localStorage\.getItem\(storedKey\)",
        template,
    )
    assert bootstrap, "could not find the theme bootstrap allowlist"
    allowed = set(re.findall(r"'([^']+)'", bootstrap.group(1)))

    order = re.search(r"const THEME_ORDER = \[([^\]]+)\];", state)
    assert order, "could not find THEME_ORDER"
    themes = set(re.findall(r"'([^']+)'", order.group(1)))

    assert allowed == themes, (
        "bootstrap allowlist and THEME_ORDER have drifted; a theme missing from "
        f"the bootstrap resets to light on reload. Difference: {allowed ^ themes}"
    )


def test_every_theme_is_offered_in_the_toolbar_menu():
    """The toolbar picker must list what THEME_ORDER supports.

    Graphite shipped in THEME_ORDER and in both <select> menus but never in the
    toolbar list, so the main picker did not offer it.
    """
    import re

    template = (REPO_ROOT / "proseview" / "templates" / "index.html.j2").read_text(encoding="utf-8")
    state = (REPO_ROOT / "proseview" / "templates" / "assets" / "js" / "00-state.js").read_text(
        encoding="utf-8"
    )
    offered = set(re.findall(r'data-theme-value="([^"]+)"', template))
    order = set(re.findall(r"'([^']+)'", re.search(r"const THEME_ORDER = \[([^\]]+)\];", state).group(1)))
    assert offered == order, f"toolbar menu and THEME_ORDER differ: {offered ^ order}"


def test_theme_css_is_declared_as_package_data():
    """``templates/assets/*`` does not recurse, so themes need their own entry.

    Without it the wheel ships no theme CSS at all and an installed Proseview
    renders Graphite unstyled -- the same trap that hid ``vendor/pm/``.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"templates/assets/themes/*"' in pyproject, \
        "theme CSS would not ship in the wheel"


def test_chapter_tick_labels_ellipsize_rather_than_clip():
    """Twelve chapters with real titles used to run together.

    ``overflow: hidden`` with no ``text-overflow`` produced
    "I. Down the RabII. The Pool of TIII. A Caucus-Ra" under the shape chart.
    The span is the overflow context because a flex item cannot ellipsize its
    own text node.
    """
    css = (REPO_ROOT / "proseview" / "templates" / "assets" / "app.css").read_text(encoding="utf-8")
    assert ".story-tick > span" in css
    block = css.split(".story-tick > span")[1].split("}")[0]
    for rule in ("text-overflow: ellipsis", "overflow: hidden", "white-space: nowrap"):
        assert rule in block, f"tick label needs {rule}"
