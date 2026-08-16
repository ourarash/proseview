"""Image serving and the ``images`` setting.

``/repo-asset/`` is the only route that hands back arbitrary repository bytes,
so its containment is worth testing as carefully as the mutation endpoints':
a path that escapes the repo here leaks any file the user can read.

The setting exists because rendering an image is a network request. A remote
``<img>`` reports the reader's IP and the fact that they opened a document to
whoever hosts it, and in Discuss the URL is chosen by a model rather than by
the reader -- hence the separate ``remote_in_agent_output`` gate.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config, ConfigError, ImagesConfig, _coerce_images  # noqa: E402

#: Smallest valid PNG, so the fixtures are real image bytes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ── The setting ──────────────────────────────────────────────────────────────

def test_images_render_by_default_but_agent_remote_images_require_opt_in():
    """Authored images render while model-chosen remote requests stay quiet."""
    images = Config().images
    assert images.mode == "all"
    assert images.remote_in_agent_output is False


@pytest.mark.parametrize("raw,expected", [
    ("off", ImagesConfig(mode="off")),
    ("local", ImagesConfig(mode="local")),
    ("all", ImagesConfig(mode="all")),
    (False, ImagesConfig(mode="off")),
    (True, ImagesConfig(mode="all")),
    (None, ImagesConfig()),
    ({"remote_in_agent_output": False}, ImagesConfig(remote_in_agent_output=False)),
    ({"mode": "local"}, ImagesConfig(mode="local")),
    ({"mode": "all", "remote_in_agent_output": True},
     ImagesConfig(mode="all", remote_in_agent_output=True)),
])
def test_images_setting_accepts_its_documented_forms(raw, expected):
    assert _coerce_images(raw) == expected


@pytest.mark.parametrize("raw", ["bogus", {"mode": "sometimes"}, 3, {"mode": "all", "remote_in_agent_output": "yes"}])
def test_invalid_images_setting_fails_loudly(raw):
    with pytest.raises(ConfigError):
        _coerce_images(raw)


def test_setting_reaches_the_page(tmp_path: Path):
    from proseview.generator import build_dashboard

    (tmp_path / "one.md").write_text("# One\n\nProse.\n", encoding="utf-8")
    (tmp_path / ".proseview.yaml").write_text("images: off\n", encoding="utf-8")

    html = build_dashboard(tmp_path, Config.load(tmp_path))

    assert '"mode": "off"' in html


# ── The route ────────────────────────────────────────────────────────────────

@pytest.fixture()
def served(tmp_path: Path):
    """A repo with an image, plus a secret next to it and one outside."""
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "cover.png").write_bytes(PNG)
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (tmp_path / "secret.env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    outside = tmp_path.parent / "outside-secret.png"
    outside.write_bytes(PNG)
    return tmp_path, outside


def _fetch(server_root: Path, url_path: str):
    """Drive ``_handle_repo_asset`` without a socket."""
    from proseview.server import _Handler

    class _Probe(_Handler):
        def __init__(self):  # noqa: D107 - no socket setup wanted
            self.path = url_path
            self.repo_root = str(server_root)
            self.status = None
            self.headers_sent = {}
            self.body = b""

        def send_response(self, code, message=None):
            self.status = code

        def send_header(self, key, value):
            self.headers_sent[key] = value

        def end_headers(self):
            pass

        @property
        def wfile(self):
            probe = self

            class _W:
                def write(self, data):
                    probe.body += data
            return _W()

    probe = _Probe()
    probe._handle_repo_asset()
    return probe


def test_an_image_inside_the_repo_is_served(served):
    root, _ = served
    probe = _fetch(root, "/repo-asset/img/cover.png")

    assert probe.status == 200
    assert probe.headers_sent["Content-Type"] == "image/png"
    assert probe.body == PNG
    # Type confusion and SVG script execution are both closed off.
    assert probe.headers_sent["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in probe.headers_sent["Content-Security-Policy"]


@pytest.mark.parametrize("url_path", [
    "/repo-asset/secret.env",                    # not an image type
    "/repo-asset/notes.md",                      # not an image type
    "/repo-asset/../outside-secret.png",         # traversal
    "/repo-asset/img/../../outside-secret.png",  # traversal through a real dir
    "/repo-asset/%2e%2e/outside-secret.png",     # percent-encoded traversal
    "/repo-asset//etc/hosts",                    # absolute path
    "/repo-asset/img/missing.png",               # not there
    "/repo-asset/",                              # empty
])
def test_everything_outside_the_contract_is_refused(served, url_path):
    root, _ = served
    probe = _fetch(root, url_path)

    assert probe.status == 404, f"{url_path} should not be served"
    assert probe.body == b""


def test_a_symlink_pointing_out_of_the_repo_is_refused(served):
    root, outside = served
    link = root / "img" / "escape.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    probe = _fetch(root, "/repo-asset/img/escape.png")

    assert probe.status == 404, "a symlink must not be followed out of the repo"
    assert probe.body == b""


def test_a_symlink_staying_inside_the_repo_is_also_refused(served):
    """Conservative on purpose: matching ``_contained_abs_path``.

    Symlinks are refused outright rather than resolved and re-checked, so the
    rule stays easy to reason about.
    """
    root, _ = served
    link = root / "img" / "alias.png"
    try:
        link.symlink_to(root / "img" / "cover.png")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    assert _fetch(root, "/repo-asset/img/alias.png").status == 404
