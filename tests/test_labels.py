"""Tests for calm Markdown scene labels, config validation, and server saves."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config, ConfigError  # noqa: E402
from proseview.generator import (  # noqa: E402
    _analysis_findings,
    _scene_table_body,
    build_dashboard,
    build_scene_data,
)
from proseview.scenes import collect_scene_stats, update_frontmatter_scalar  # noqa: E402
from proseview.server import (  # noqa: E402
    DiscussManager,
    _make_handler,
    _rewrite_manuscript_label,
    save_scene_content,
)
from proseview.story import resolve_label_catalog, story_payload  # noqa: E402


def _write_scene(
    root: Path,
    chapter: str,
    name: str,
    *,
    fm: str = "",
    body: str = "Quiet water against the pilings.\n",
) -> Path:
    path = root / "manuscript" / chapter / name
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f"---\n{fm}---\n\n" if fm else ""
    path.write_text(f"{front}{body}", encoding="utf-8")
    return path


def test_labels_config_accepts_named_colors_c0_aliases_hex_and_custom_label_field(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "story:\n"
        "  label_field: pov\n"
        "labels:\n"
        "  palette:\n"
        "    Mara: c0\n"
        "    Tomas: Red\n"
        "    Jules: orange\n"
        '    Flashback: "#3A7"\n',
        encoding="utf-8",
    )

    cfg = Config.load(tmp_path)

    assert cfg.story.label_field == "pov"
    assert cfg.labels.palette == (
        ("Mara", "blue"),
        ("Tomas", "red"),
        ("Jules", "orange"),
        ("Flashback", "#33aa77"),
    )
    assert cfg.labels.slot_for("Mara") == "blue"
    assert cfg.labels.slot_for("Tomas") == "red"
    assert cfg.labels.slot_for("Jules") == "orange"
    assert cfg.labels.slot_for("Flashback") == "#33aa77"
    assert cfg.labels.slot_for("Missing") is None


@pytest.mark.parametrize("bad_value", ["gold", "c8", "c-1", "0", "#12", "#gggggg", 123, True])
def test_labels_palette_rejects_invalid_values(tmp_path: Path, bad_value):
    yaml_val = f'"{bad_value}"' if isinstance(bad_value, str) else str(bad_value).lower()
    (tmp_path / ".proseview.yaml").write_text(
        f"labels:\n  palette:\n    Main Plot: {yaml_val}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="color name"):
        Config.load(tmp_path)


def test_custom_hex_label_does_not_consume_auto_slots_and_saves_to_yaml(tmp_path: Path):
    from proseview.config import LabelsConfig

    _write_scene(tmp_path, "ch01", "01-custom.md", fm="label: Custom\n")
    _write_scene(tmp_path, "ch01", "02-auto.md", fm="label: Auto\n")

    cfg = Config().with_overrides(labels=LabelsConfig(palette=(("Custom", "#4f7cac"),)))
    cfg.save(tmp_path)
    reloaded = Config.load(tmp_path)
    assert reloaded.labels.palette == (("Custom", "#4f7cac"),)

    scenes = collect_scene_stats(tmp_path, reloaded)
    slots, _ = resolve_label_catalog(scenes, reloaded)
    assert slots["Custom"] == "#4f7cac"
    assert slots["Auto"] == 0

    table_html = _scene_table_body(scenes, tmp_path, reloaded, "VS Code", analysis=False)
    assert "--label-color:#4f7cac" in table_html


def test_labels_config_rejects_unknown_subkeys_and_non_string_label_field(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text("labels:\n  mode: dense\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown key"):
        Config.load(tmp_path)

    (tmp_path / ".proseview.yaml").write_text("story:\n  label_field: 42\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="story.label_field"):
        Config.load(tmp_path)


def test_first_seen_order_and_configured_slots_with_overflow(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "labels:\n"
        "  palette:\n"
        "    Pinned: c0\n"
        "    Reserved: c2\n",
        encoding="utf-8",
    )
    # 9 distinct labels across scenes + 1 unused configured label ("Reserved" -> c2)
    labels = ["Alpha", "Pinned", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
    for i, lbl in enumerate(labels, start=1):
        _write_scene(tmp_path, "ch01", f"{i:02d}-scene.md", fm=f"label: {lbl}\n")
    _write_scene(tmp_path, "ch01", "10-plain.md")

    cfg = Config.load(tmp_path)
    scenes = collect_scene_stats(tmp_path, cfg)
    slots, catalog = resolve_label_catalog(scenes, cfg)

    # Configured c0 and c2 are reserved; unmapped labels take 1, 3, 4, 5, 6, 7 in first-seen order.
    assert slots["Pinned"] == 0
    assert slots["Reserved"] == 2
    assert slots["Alpha"] == 1
    assert slots["Beta"] == 3
    assert slots["Gamma"] == 4
    assert slots["Delta"] == 5
    assert slots["Epsilon"] == 6
    assert slots["Zeta"] == 7
    # 9th distinct label (Eta) and 10th (Theta) overflow to "other" instead of wrapping to 0.
    assert slots["Eta"] == "other"
    assert slots["Theta"] == "other"

    assert [entry["label"] for entry in catalog] == labels + ["Reserved"]
    assert catalog[-1]["count"] == 0
    assert catalog[-1]["configured"] is True

    payload = story_payload(scenes, cfg)
    assert payload["has_labels"] is True
    assert payload["label_field"] == "label"
    assert payload["scenes"][0]["label"] == "Alpha"
    assert payload["scenes"][0]["label_slot"] == 1
    assert payload["scenes"][-1]["label"] == ""
    assert payload["scenes"][-1]["label_slot"] is None


def test_list_valued_label_uses_first_item_and_emits_finding(tmp_path: Path):
    _write_scene(tmp_path, "ch01", "01-list.md", fm="label:\n  - Flashback\n  - Mara\n")
    _write_scene(tmp_path, "ch01", "02-scalar.md", fm="label: Main Plot\n")

    cfg = Config.load(tmp_path)
    scenes = collect_scene_stats(tmp_path, cfg)

    assert scenes[0].label == "Flashback"
    assert scenes[0].label_is_list is True
    assert scenes[1].label == "Main Plot"
    assert scenes[1].label_is_list is False

    findings = _analysis_findings(scenes, cfg, lambda p: p.relative_to("manuscript").as_posix())
    list_notes = [f for f in findings if "as a list" in str(f["text"])]
    assert len(list_notes) == 1
    assert list_notes[0]["text"] == "1 scene writes label: as a list."
    assert list_notes[0]["scenes"] == [{"title": "01 List", "path": "ch01/01-list.md"}]


def test_dashboard_and_table_emit_calm_label_markers(tmp_path: Path):
    _write_scene(tmp_path, "ch01", "01-a.md", fm="label: Subplot B\nstatus: revision\n")
    _write_scene(tmp_path, "ch01", "02-b.md")

    cfg = Config.load(tmp_path)
    scenes = collect_scene_stats(tmp_path, cfg)
    data = build_scene_data(scenes, tmp_path, cfg)

    assert set(data) == {"contents", "meta", "highlightsByPath", "medians"}
    assert data["meta"]["ch01/01-a.md"]["label"] == "Subplot B"
    assert data["meta"]["ch01/01-a.md"]["label_slot"] == 0
    assert data["meta"]["ch01/02-b.md"]["label"] == ""
    assert data["meta"]["ch01/02-b.md"]["label_slot"] is None

    table_html = _scene_table_body(scenes, tmp_path, cfg, "VS Code", analysis=False)
    assert 'data-label="Subplot B"' in table_html
    assert 'class="table-label-dot"' in table_html
    assert 'class="badge label-pill"' in table_html

    html = build_dashboard(tmp_path, cfg)
    assert 'value="label:Subplot B"' in html
    assert 'value="label:__none__"' in html
    assert 'id="setting_label_mode"' in html


def test_save_scene_content_frontmatter_only_preserves_heading_and_prose(tmp_path: Path):
    scene_path = _write_scene(
        tmp_path,
        "ch01",
        "01-bare.md",
        body="# The Pier\n\nEmpty stub or heading stays untouched.\n",
    )
    mtime = scene_path.stat().st_mtime

    # Add frontmatter via frontmatter-only save (content=None)
    save_scene_content(
        str(scene_path),
        None,
        mtime,
        str(tmp_path),
        frontmatter="label: Main Plot",
    )
    text = scene_path.read_text(encoding="utf-8")
    assert text == "---\nlabel: Main Plot\n---\n\n# The Pier\n\nEmpty stub or heading stays untouched.\n"

    # Clear frontmatter back to empty
    save_scene_content(
        str(scene_path),
        None,
        scene_path.stat().st_mtime,
        str(tmp_path),
        frontmatter="",
    )
    assert scene_path.read_text(encoding="utf-8") == "# The Pier\n\nEmpty stub or heading stays untouched.\n"


def test_update_frontmatter_scalar_renames_and_clears_cleanly():
    raw = "---\ntitle: Scene One\nlabel: Main Plot\nstatus: draft\n---\n\nBody text.\n"
    renamed = update_frontmatter_scalar(raw, "label", " Subplot: A ")
    assert renamed == '---\ntitle: Scene One\nlabel: "Subplot: A"\nstatus: draft\n---\n\nBody text.\n'

    cleared = update_frontmatter_scalar(raw, "label", "")
    assert cleared == "---\ntitle: Scene One\nstatus: draft\n---\n\nBody text.\n"

    only_label = "---\nlabel:\n  - Flashback\n  - Mara\n---\n\nBody text.\n"
    assert update_frontmatter_scalar(only_label, "label", "Main") == "---\nlabel: Main\n---\n\nBody text.\n"
    assert update_frontmatter_scalar(only_label, "label", "") == "Body text.\n"

    # Nested indented subkeys with the same name are left untouched.
    nested = "---\nmeta:\n  label: Nested\nlabel: Top\n---\n\nBody text.\n"
    assert update_frontmatter_scalar(nested, "label", "Next") == "---\nmeta:\n  label: Nested\nlabel: Next\n---\n\nBody text.\n"
    assert update_frontmatter_scalar(nested, "label", "") == "---\nmeta:\n  label: Nested\n---\n\nBody text.\n"


def test_rewrite_manuscript_label_updates_only_matching_scenes(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text("story:\n  label_field: thread\n", encoding="utf-8")
    p1 = _write_scene(tmp_path, "ch01", "01-a.md", fm="thread: Main\npov: Mara\n")
    p2 = _write_scene(tmp_path, "ch01", "02-b.md", fm="thread: Subplot\n")
    p3 = _write_scene(tmp_path, "ch01", "03-c.md", fm="thread: Main\n")

    cfg = Config.load(tmp_path)
    assert _rewrite_manuscript_label(tmp_path, cfg, "Main", "A-Plot") == 2
    assert "thread: A-Plot\npov: Mara" in p1.read_text(encoding="utf-8")
    assert "thread: Subplot" in p2.read_text(encoding="utf-8")
    assert "thread: A-Plot" in p3.read_text(encoding="utf-8")

    # Removing a label clears its field without touching other frontmatter or body.
    assert _rewrite_manuscript_label(tmp_path, cfg, "A-Plot", "") == 2
    assert p1.read_text(encoding="utf-8") == "---\npov: Mara\n---\n\nQuiet water against the pilings.\n"
    assert p3.read_text(encoding="utf-8") == "Quiet water against the pilings.\n"


def _patch_settings(port: int, token: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/settings",
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={
            "Content-Type": "application/json",
            "X-Proseview-Session": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_settings_api_label_add_rename_and_remove(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "labels:\n  palette:\n    Main Plot: c0\n",
        encoding="utf-8",
    )
    scene_a = _write_scene(tmp_path, "ch01", "01-a.md", fm="label: Main Plot\npov: Mara\n")
    scene_b = _write_scene(tmp_path, "ch01", "02-b.md", fm="label: Subplot\n")

    token = "test-session-token"
    handler_cls = _make_handler(
        get_html=lambda: "",
        get_analysis_json=lambda: b"{}",
        invalidate=lambda *_a, **_kw: None,
        subscribe=lambda: None,  # type: ignore[arg-type, return-value]
        unsubscribe=lambda _q: None,
        publish_event=lambda _ev: None,
        repo_root=str(tmp_path),
        discuss_manager=DiscussManager(tmp_path),
        session_token=token,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        # 1. Add a new label with no explicit color -> next unused slot after c0 and Subplot(c1) is slot 2.
        status, body = _patch_settings(port, token, {"label_add": {"name": "Climax"}})
        assert status == 200 and body["ok"] is True
        by_name = {entry["label"]: entry for entry in body["label_catalog"]}
        assert by_name["Climax"]["slot"] == 2
        assert by_name["Climax"]["configured"] is True

        # Duplicate add fails cleanly with 400.
        dup_status, dup_body = _patch_settings(port, token, {"label_add": {"name": "Subplot"}})
        assert dup_status == 400 and dup_body["ok"] is False

        # 2. Rename "Main Plot" -> "Hero Arc": keeps c0 in .proseview.yaml and rewrites scene_a.md.
        status, body = _patch_settings(port, token, {"label_rename": {"old": "Main Plot", "new": "Hero Arc"}})
        assert status == 200 and body["ok"] is True
        by_name = {entry["label"]: entry for entry in body["label_catalog"]}
        assert "Main Plot" not in by_name
        assert by_name["Hero Arc"]["slot"] == 0
        assert "label: Hero Arc" in scene_a.read_text(encoding="utf-8")

        # 3. Remove "Hero Arc": removes from .proseview.yaml and clears from scene_a.md (preserving pov: Mara).
        status, body = _patch_settings(port, token, {"label_remove": {"name": "Hero Arc"}})
        assert status == 200 and body["ok"] is True
        by_name = {entry["label"]: entry for entry in body["label_catalog"]}
        assert "Hero Arc" not in by_name
        assert scene_a.read_text(encoding="utf-8") == "---\npov: Mara\n---\n\nQuiet water against the pilings.\n"
        assert "label: Subplot" in scene_b.read_text(encoding="utf-8")

        cfg = Config.load(tmp_path)
        assert dict(cfg.labels.palette) == {"Climax": "teal"}
    finally:
        httpd.shutdown()
        httpd.server_close()
