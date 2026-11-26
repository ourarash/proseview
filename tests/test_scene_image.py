"""Tests for one-click Scene Image generation, styles, chapter assets, and Discuss handoff."""

from __future__ import annotations

import base64
import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from proseview.agy_acp_client import AgyAcpClient
from proseview.config import Config, SceneImageConfig
from proseview.discuss import DiscussManager, _OneOff, sanitize_agent_message
from proseview.generator import TEMPLATE_DIR, _load_app_js
from proseview.scene_image import (
    BUILTIN_SCENE_IMAGE_STYLES,
    DEFAULT_SCENE_IMAGE_PROMPT,
    build_scene_image_prompt,
    capture_chat_image_from_event,
    detect_claude_image_mcp,
    detect_image_format,
    dismiss_scene_image_preview,
    generate_scene_image,
    get_scene_image_status,
    insert_scene_image,
    load_chat_image_bytes,
    load_preview_image_bytes,
    load_scene_image_preview,
    promote_chat_image_to_preview,
    remove_scene_image_from_scene,
    save_scene_image_preview,
    save_scene_image_settings_payload,
    scene_image_settings_payload,
    select_scene_image_take,
)
from http.server import ThreadingHTTPServer
from proseview.server import _make_handler

# Minimal valid 1x1 PNG bytes
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
# Minimal JPEG header bytes (enough for magic-byte sniffing)
_TINY_JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def _make_book(tmp_path: Path) -> Path:
    scene = tmp_path / "manuscript" / "ch01" / "01-opening-at-the-bar.md"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text(
        "---\n"
        "title: Opening at the Bar\n"
        "pov: Elena\n"
        "location: The Lantern Bar\n"
        "---\n\n"
        "The Lantern kept two hours past its license on Tuesdays.\n\n"
        "Elena sat three stools from the door.\n",
        encoding="utf-8",
    )
    chars = tmp_path / "story-bible" / "characters"
    chars.mkdir(parents=True, exist_ok=True)
    (chars / "elena.md").write_text("Elena wears a dark wool coat and carries a silver lighter.\n", encoding="utf-8")
    return tmp_path


class _FakeClient:
    """Minimal fake Discuss transport supporting Codex, Agy, and Claude image turns."""

    def __init__(self, *, agent: str, on_turn: Any) -> None:
        self.agent = agent
        self.on_turn = on_turn
        self.started_threads: list[dict[str, Any]] = []
        self.started_turns: list[dict[str, Any]] = []
        self.discarded: list[str] = []

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        params = params or {}
        if method == "thread/start":
            self.started_threads.append(dict(params))
            return {"thread": {"id": f"th-{self.agent}-1"}}
        if method == "turn/start":
            self.started_turns.append(dict(params))
            threading.Thread(target=self.on_turn, args=(params,), daemon=True).start()
            return {"turn": {"id": f"turn-{self.agent}-1"}}
        if method == "turn/interrupt":
            return {}
        return {}

    def discard_ephemeral_thread(self, thread_id: str) -> None:
        self.discarded.append(thread_id)


class _FakeDiscussManager:
    def __init__(self, root: Path, client: _FakeClient) -> None:
        self.root = root
        self.client = client
        self._one_offs: dict[str, _OneOff] = {}

    def _ensure_client(self, agent: str) -> _FakeClient:
        return self.client

    def _thread_key(self, agent: str, thread_id: str) -> str:
        return f"{agent}:{thread_id}"


def test_builtin_style_thumbnails_exist_and_are_valid_jpegs() -> None:
    styles_dir = TEMPLATE_DIR / "assets" / "scene-styles"
    assert len(BUILTIN_SCENE_IMAGE_STYLES) == 6
    for style in BUILTIN_SCENE_IMAGE_STYLES:
        thumb_name = style["thumb"].removeprefix("/assets/scene-styles/")
        thumb_path = styles_dir / thumb_name
        assert thumb_path.is_file(), f"Missing style thumbnail: {thumb_path}"
        fmt = detect_image_format(thumb_path.read_bytes())
        assert fmt == (".jpg", "image/jpeg")


def test_scene_image_config_round_trip(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    cfg = Config.load(book)
    assert cfg.scene_image == SceneImageConfig()
    assert cfg.scene_image.agent == "codex"
    assert cfg.scene_image.assets_dir == "assets"
    assert cfg.scene_image.style_preset == "ink_watercolor"

    saved = save_scene_image_settings_payload(
        book,
        {
            "book": {
                "agent": "agy",
                "model": "gemini-4-neon-high",
                "style_preset": "woodcut",
                "style": BUILTIN_SCENE_IMAGE_STYLES[1]["prompt"],
                "aspect_ratio": "3:2",
                "assets_dir": "art",
                "width": 480,
                "include_frontmatter": False,
                "include_characters": True,
                "instructions": False,
                "prompt": "Custom scene illustration instructions.",
            }
        },
    )
    assert saved["book"]["agent"] == "agy"
    assert saved["book"]["style_preset"] == "woodcut"
    assert saved["book"]["assets_dir"] == "art"
    assert saved["book"]["include_frontmatter"] is False

    reloaded = Config.load(book)
    assert reloaded.scene_image.agent == "agy"
    assert reloaded.scene_image.style_preset == "woodcut"
    assert reloaded.scene_image.style == ""  # matches preset, so no redundant override stored
    assert reloaded.scene_image.aspect_ratio == "3:2"
    assert reloaded.scene_image.assets_dir == "art"
    assert reloaded.scene_image.width == 480
    assert reloaded.scene_image.include_frontmatter is False
    assert reloaded.scene_image.instructions is False
    assert reloaded.scene_image.prompt == "Custom scene illustration instructions."

    # Rejects path traversal in assets_dir
    with pytest.raises(ValueError):
        save_scene_image_settings_payload(book, {"book": {"assets_dir": "../outside"}})


def test_preview_insert_into_per_scene_assets_and_remove(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    scene_file = book / "manuscript" / rel

    # Preview stays in .proseview/ without touching the manuscript or scene's assets/
    preview1 = save_scene_image_preview(
        book,
        rel,
        _TINY_PNG,
        ".png",
        "image/png",
        agent="codex",
        style_id="ink_watercolor",
        alt="Opening at the Bar — Take 1",
    )
    assert preview1["scene_path"] == rel
    assert preview1["take_index"] == 1
    assert preview1["take_count"] == 1
    assert not (book / "manuscript" / "ch01" / "assets").exists()
    assert load_preview_image_bytes(book, rel) == (_TINY_PNG, "image/png")

    # Generating a second take keeps Take 1 intact and supports switching between takes
    preview2 = save_scene_image_preview(
        book,
        rel,
        _TINY_JPG,
        ".jpg",
        "image/jpeg",
        agent="agy",
        style_id="woodcut",
        alt="Opening at the Bar — Take 2",
    )
    assert preview2["take_index"] == 2
    assert preview2["take_count"] == 2
    assert load_preview_image_bytes(book, rel) == (_TINY_JPG, "image/jpeg")

    # Switch back to Take 1 and insert it -> saves under ch01/assets/
    switched = select_scene_image_take(book, rel, preview1["take_id"])
    assert switched["preview"]["take_index"] == 1
    assert load_preview_image_bytes(book, rel) == (_TINY_PNG, "image/png")

    inserted = insert_scene_image(book, rel)
    assert inserted["ok"] is True
    expected_repo_path = "manuscript/ch01/assets/01-opening-at-the-bar.png"
    assert inserted["asset_repo_path"] == expected_repo_path
    assert inserted["markdown_src"] == "assets/01-opening-at-the-bar.png"
    assert inserted["width"] == 600
    assert (book / expected_repo_path).read_bytes() == _TINY_PNG

    updated_md = scene_file.read_text(encoding="utf-8")
    # Linked from the scene's folder, so Obsidian, VS Code and GitHub show it too.
    expected_tag = '<img src="assets/01-opening-at-the-bar.png" alt="Opening at the Bar — Take 1" width="600">'
    assert expected_tag in updated_md
    assert updated_md.startswith("---\ntitle: Opening at the Bar")
    # Preview cleared after insert so image isn't duplicated
    assert load_scene_image_preview(book, rel) is None

    # Status now reports embedded HTML image
    status = get_scene_image_status(book, rel)
    assert status["has_preview"] is False
    assert status["embedded"]["kind"] == "html"
    assert status["embedded"]["src"] == "assets/01-opening-at-the-bar.png"

    # Re-inserting with custom width replaces the leading <img> line cleanly
    save_scene_image_settings_payload(book, {"book": {"width": 480}})
    save_scene_image_preview(book, rel, _TINY_JPG, ".jpg", "image/jpeg", agent="agy", style_id="woodcut", alt="Woodcut bar")
    inserted2 = insert_scene_image(book, rel)
    expected_repo_path2 = "manuscript/ch01/assets/01-opening-at-the-bar.jpg"
    assert inserted2["asset_repo_path"] == expected_repo_path2
    assert inserted2["width"] == 480
    updated_md2 = scene_file.read_text(encoding="utf-8")
    assert updated_md2.count("<img ") == 1
    assert '<img src="assets/01-opening-at-the-bar.jpg" alt="Woodcut bar" width="480">' in updated_md2
    # The .png it replaced is gone, rather than left behind in assets/.
    assert not (book / expected_repo_path).exists()
    assert (book / expected_repo_path2).read_bytes() == _TINY_JPG

    # Removing restores clean prose without the image line
    removed = remove_scene_image_from_scene(book, rel)
    assert removed["removed"] is True
    after_remove = scene_file.read_text(encoding="utf-8")
    assert "<img" not in after_remove
    assert "The Lantern kept two hours past its license on Tuesdays." in after_remove


def test_codex_sanitize_and_generate_scene_image_with_refine(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    b64_png = base64.b64encode(_TINY_PNG).decode("ascii")

    # Verify sanitize_agent_message translates Codex ImageGenerationThreadItem
    events = sanitize_agent_message({
        "method": "item/completed",
        "params": {
            "threadId": "th-codex-1",
            "turnId": "turn-codex-1",
            "item": {
                "id": "ig-1",
                "type": "imageGeneration",
                "status": "completed",
                "result": b64_png,
                "revisedPrompt": "Moody corner bar with amber light",
            },
        },
    })
    assert len(events) == 1
    assert events[0]["type"] == "image.generated"
    assert events[0]["revised_prompt"] == "Moody corner bar with amber light"

    mgr_holder: dict[str, Any] = {}

    def _on_codex_turn(params: dict[str, Any]) -> None:
        mgr: _FakeDiscussManager = mgr_holder["mgr"]
        one_off = mgr._one_offs[mgr._thread_key("codex", params["threadId"])]
        one_off.receive(events[0])
        one_off.receive({
            "type": "response.completed",
            "phase": "final_answer",
            "text": json.dumps({"alt": "Warm amber bar at midnight", "revised_prompt": "Amber bar"}),
        })
        one_off.receive({"type": "turn.completed", "status": "completed"})

    client = _FakeClient(agent="codex", on_turn=_on_codex_turn)
    mgr = _FakeDiscussManager(book, client)
    mgr_holder["mgr"] = mgr

    res = generate_scene_image(book, rel, agent="codex", style_id="oil_painting", discuss_manager=mgr)
    assert res["ok"] is True
    assert res["preview"]["agent"] == "codex"
    assert res["preview"]["style_id"] == "oil_painting"
    assert res["preview"]["alt"] == "Warm amber bar at midnight"
    assert load_preview_image_bytes(book, rel) == (_TINY_PNG, "image/png")

    # Refinement passes localImage input to Codex!
    res2 = generate_scene_image(
        book, rel, agent="codex", note="Make the rain brighter", refine=True, discuss_manager=mgr
    )
    assert res2["ok"] is True
    last_input = client.started_turns[-1]["input"]
    assert any(item.get("type") == "localImage" for item in last_input)


def test_agy_generate_scene_image_and_auto_approve_subagent(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    generated_file = tmp_path / "agy_output_art.jpg"
    generated_file.write_bytes(_TINY_JPG)

    mgr_holder: dict[str, Any] = {}

    def _on_agy_turn(params: dict[str, Any]) -> None:
        mgr: _FakeDiscussManager = mgr_holder["mgr"]
        one_off = mgr._one_offs[mgr._thread_key("agy", params["threadId"])]
        one_off.receive({
            "type": "response.completed",
            "phase": "final_answer",
            "text": json.dumps({
                "image_path": str(generated_file),
                "alt": "Charcoal sketch of the bar",
                "revised_prompt": "Charcoal bar sketch",
            }),
        })
        one_off.receive({"type": "turn.completed", "status": "completed"})

    client = _FakeClient(agent="agy", on_turn=_on_agy_turn)
    mgr = _FakeDiscussManager(book, client)
    mgr_holder["mgr"] = mgr

    res = generate_scene_image(book, rel, agent="agy", style_id="charcoal", discuss_manager=mgr)
    assert res["ok"] is True
    assert res["preview"]["ext"] == ".jpg"
    assert client.started_turns[0]["autoApproveTools"] == ["invoke_subagent"]
    assert load_preview_image_bytes(book, rel) == (_TINY_JPG, "image/jpeg")

    # Verify AgyAcpClient auto-approves tools listed in session.auto_approve_tools
    sent: list[dict[str, Any]] = []
    acp = AgyAcpClient(cwd=book)
    acp._acp_respond = lambda acp_id, result: sent.append({"id": acp_id, "result": result})  # type: ignore[method-assign]
    from proseview.agy_acp_client import _Session
    sess = _Session("sess-1")
    sess.auto_approve_tools = {"invoke_subagent"}
    acp._sessions["sess-1"] = sess
    acp._handle_permission_request(
        42,
        {
            "sessionId": "sess-1",
            "toolCall": {"name": "invoke_subagent", "kind": "other", "toolCallId": "tc-1"},
            "options": [{"optionId": "allow_once_id", "kind": "allow_once"}],
        },
    )
    assert sent == [{"id": 42, "result": {"outcome": {"outcome": "selected", "optionId": "allow_once_id"}}}]


def test_claude_mcp_detection_and_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    mcp = detect_claude_image_mcp(book, force=True)
    assert mcp["available"] is False

    # Refuses cleanly when Claude has no image MCP
    with pytest.raises(RuntimeError, match="no built-in raster image generator"):
        generate_scene_image(book, rel, agent="claude", discuss_manager=object())

    # Detecting a project .mcp.json with an image server enables Claude
    (book / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"claude-imagine": {"url": "https://example.invalid/mcp"}}}),
        encoding="utf-8",
    )
    mcp2 = detect_claude_image_mcp(book, force=True)
    assert mcp2["available"] is True
    assert "claude-imagine" in mcp2["servers"]


def test_chat_image_capture_promote_and_insert(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    b64_png = base64.b64encode(_TINY_PNG).decode("ascii")

    captured = capture_chat_image_from_event(
        book,
        {"result": b64_png, "revised_prompt": "Rainy bar window"},
        agent="codex",
        scene_path=rel,
    )
    assert captured is not None
    assert load_chat_image_bytes(book, captured["image_id"]) == (_TINY_PNG, "image/png")

    promoted = promote_chat_image_to_preview(book, rel, captured["image_id"])
    assert promoted["ok"] is True
    assert load_preview_image_bytes(book, rel) == (_TINY_PNG, "image/png")

    dismiss_scene_image_preview(book, rel)
    inserted = insert_scene_image(book, rel, chat_image_id=captured["image_id"])
    assert inserted["asset_repo_path"] == "manuscript/ch01/assets/01-opening-at-the-bar.png"


def test_prompt_includes_character_and_frontmatter_context(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    cfg = Config.load(book)
    raw = (book / "manuscript" / "ch01" / "01-opening-at-the-bar.md").read_text(encoding="utf-8")
    prompt, meta = build_scene_image_prompt(
        book,
        cfg,
        "ch01/01-opening-at-the-bar.md",
        raw,
        agent="codex",
        style_id="gouache",
        note="Focus on the crimson streetlight reflection",
    )
    assert meta["style_name"] == "Minimalist Gouache"
    assert "Focus on the crimson streetlight reflection" in prompt
    assert "dark wool coat" in prompt  # from characters/elena.md
    assert "location: The Lantern Bar" in prompt  # from frontmatter


def test_http_scene_image_endpoints_and_style_thumbs(tmp_path: Path) -> None:
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    token = "test-session-token"
    mgr = DiscussManager(book)
    handler = _make_handler(
        get_html=lambda: "<html></html>",
        get_analysis_json=lambda: b"{}",
        invalidate=lambda *_a, **_kw: None,
        subscribe=lambda: None,  # type: ignore[arg-type,return-value]
        unsubscribe=lambda _q: None,
        publish_event=lambda _e: None,
        repo_root=str(book),
        discuss_manager=mgr,
        session_token=token,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    def _req(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[int, bytes, str]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-Proseview-Session": token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            return err.code, err.read(), err.headers.get("Content-Type", "")

    try:
        # 1. Built-in style thumbnails served cleanly
        code, raw, ctype = _req("/assets/scene-styles/woodcut.jpg")
        assert code == 200
        assert ctype == "image/jpeg"
        assert detect_image_format(raw) == (".jpg", "image/jpeg")

        code_bad, _, _ = _req("/assets/scene-styles/../app.css")
        assert code_bad == 404

        # 2. Settings GET & POST
        code, raw, _ = _req("/api/discuss/scene-image-settings")
        assert code == 200
        payload = json.loads(raw)
        assert payload["ok"] is True
        assert len(payload["settings"]["styles"]) == 6

        code, raw, _ = _req(
            "/api/discuss/scene-image-settings",
            method="POST",
            body={"save": True, "book": {"agent": "agy", "style_preset": "film_still", "assets_dir": "assets"}},
        )
        assert code == 200
        assert json.loads(raw)["settings"]["book"]["style_preset"] == "film_still"

        # 3. Multi-take preview, select, status, insert, remove round-trip
        p1 = save_scene_image_preview(book, rel, _TINY_PNG, ".png", "image/png", agent="codex", style_id="film_still")
        p2 = save_scene_image_preview(book, rel, _TINY_JPG, ".jpg", "image/jpeg", agent="agy", style_id="woodcut")
        code, raw, _ = _req(f"/api/scene/image/status?path={rel}")
        assert code == 200
        st_json = json.loads(raw)
        assert st_json["has_preview"] is True
        assert st_json["preview"]["take_count"] == 2
        assert st_json["preview"]["take_index"] == 2

        # Switch back to Take 1 via HTTP
        code, raw, _ = _req("/api/scene/image/select", method="POST", body={"path": rel, "take_id": p1["take_id"]})
        assert code == 200
        assert json.loads(raw)["preview"]["take_index"] == 1

        code, raw, ctype = _req(f"/api/scene/image/preview?path={rel}&take={p1['take_id']}")
        assert code == 200
        assert ctype == "image/png"
        assert raw == _TINY_PNG

        code, raw, _ = _req("/api/scene/image/insert", method="POST", body={"path": rel, "take_id": p1["take_id"]})
        assert code == 200
        ins = json.loads(raw)
        assert ins["asset_repo_path"] == "manuscript/ch01/assets/01-opening-at-the-bar.png"
        assert 'width="600"' in ins["image_line"]

        # Served via /repo-asset/
        code, raw, ctype = _req("/repo-asset/manuscript/ch01/assets/01-opening-at-the-bar.png")
        assert code == 200
        assert raw == _TINY_PNG

        code, raw, _ = _req("/api/scene/image/remove", method="POST", body={"path": rel})
        assert code == 200
        assert json.loads(raw)["removed"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_app_js_bundle_includes_scene_image_modules() -> None:
    bundle = _load_app_js()
    assert "handleSceneImageToolbarClick" in bundle
    assert "renderDiscussSceneImageCard" in bundle
    assert "loadSceneImageSettings" in bundle
    assert "createSceneImageNodeView" in bundle


def test_start_scene_image_job_runs_in_discuss_chat_and_updates_preview(tmp_path: Path) -> None:
    """1-click Scene Image jobs appear in the scene's Discuss chat and populate the calm preview."""
    import time
    from proseview.scene_image import start_scene_image_job

    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    b64_png = base64.b64encode(_TINY_PNG).decode("ascii")

    class _ChatFakeClient:
        alive = True
        capabilities = {"stable_discuss_protocol": True, "reasoning_summary": False}

        def __init__(self, on_message: Any) -> None:
            self.on_message = on_message

        def inspect_capabilities(self) -> dict[str, Any]:
            return dict(self.capabilities)

        def start(self) -> None:
            return None

        def close(self) -> None:
            return None

        def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
            params = params or {}
            if method == "thread/start":
                return {"thread": {"id": "th-chat-1"}}
            if method == "turn/start":
                tid = params["threadId"]
                def _emit() -> None:
                    self.on_message({"method": "turn/started", "params": {"threadId": tid, "turn": {"id": "turn-1"}}})
                    self.on_message({
                        "method": "item/completed",
                        "params": {
                            "threadId": tid,
                            "turnId": "turn-1",
                            "item": {
                                "id": "ig-chat-1",
                                "type": "imageGeneration",
                                "status": "completed",
                                "result": b64_png,
                                "revisedPrompt": "Amber bar counter at midnight",
                            },
                        },
                    })
                    self.on_message({
                        "method": "item/completed",
                        "params": {
                            "threadId": tid,
                            "turnId": "turn-1",
                            "item": {
                                "id": "msg-1",
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": json.dumps({"alt": "Amber bar counter", "revised_prompt": "Amber bar"}),
                            },
                        },
                    })
                    self.on_message({"method": "turn/completed", "params": {"threadId": tid, "turn": {"id": "turn-1", "status": "completed"}}})
                threading.Thread(target=_emit, daemon=True).start()
                return {"turn": {"id": "turn-1"}}
            if method == "model/list":
                return {"data": []}
            return {}

    mgr = DiscussManager(book, client_factory=lambda on_msg, _agent: _ChatFakeClient(on_msg))
    try:
        started = start_scene_image_job(
            book,
            rel,
            agent="codex",
            style_id="ink_watercolor",
            note="Warm lamp over the whiskey glass",
            discuss_manager=mgr,
        )
        assert started["ok"] is True
        assert started["active"] is True
        assert started["conversation_id"]

        # Wait briefly for the fake chat turn to finish
        for _ in range(50):
            st = get_scene_image_status(book, rel)
            if not st["active"]:
                break
            time.sleep(0.05)

        st = get_scene_image_status(book, rel)
        assert st["active"] is False
        assert st["has_preview"] is True
        assert st["preview"]["alt"] == "Amber bar counter"
        assert load_preview_image_bytes(book, rel) == (_TINY_PNG, "image/png")

        # Verify BOTH user request and assistant image card are visible in Discuss chat!
        snap = mgr.get_snapshot(started["conversation_id"])
        user_msgs = [m for m in snap["messages"] if m.get("role") == "user"]
        asst_msgs = [m for m in snap["messages"] if m.get("role") == "assistant"]
        assert any("Generate a scene illustration (Ink & Watercolor, 16:9): Warm lamp over the whiskey glass" in m["text"] for m in user_msgs)
        assert any("```proseview:scene-image" in m["text"] for m in asst_msgs)
        assert any("Amber bar counter" in m["text"] for m in asst_msgs)
    finally:
        mgr.close()


def test_codex_followup_chat_image_and_thread_history_restore(tmp_path: Path) -> None:
    """Follow-up chat turns and restored Codex threads render image cards without raw JSON."""
    from proseview.scene_image import capture_chat_image_from_text, format_scene_image_reply_text

    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"

    # 1. Codex prompt asks for natural prose, not raw JSON
    cfg = Config.load(book)
    raw = (book / "manuscript" / rel).read_text(encoding="utf-8")
    prompt, _meta = build_scene_image_prompt(book, cfg, rel, raw, agent="codex")
    assert "do NOT return JSON" in prompt

    # 2. Legacy JSON replies are cleanly unwrapped even without a new image
    clean, alt, rev = format_scene_image_reply_text(
        json.dumps({"alt": "Nima looks toward Roksana.", "revised_prompt": "Turned Nima's gaze."}),
        has_images=False,
    )
    assert clean == "Nima looks toward Roksana."
    assert alt == "Nima looks toward Roksana."
    assert rev == "Turned Nima's gaze."

    # 2b. Unrelated JSON replies with extra keys are NOT accidentally unwrapped
    unrelated_json = json.dumps({"schema": "v1", "alt": "fallback", "fields": [1, 2]})
    clean_unrelated, _, _ = format_scene_image_reply_text(unrelated_json, has_images=False)
    assert clean_unrelated == unrelated_json

    # 3. Codex linking a local generated_images file is captured and dead link stripped
    codex_saved = tmp_path / "generated_images" / "exec-123.png"
    codex_saved.parent.mkdir(parents=True, exist_ok=True)
    codex_saved.write_bytes(_TINY_PNG)
    reply_with_link = f"Yes, it's finished. Nima now looks directly at Roksana.\n\n[Open the finished image]({codex_saved})"
    captured = capture_chat_image_from_text(book, reply_with_link, agent="codex", scene_path=rel)
    assert captured is not None
    cleaned_link, _, _ = format_scene_image_reply_text(reply_with_link, has_images=True)
    assert "Open the finished image" not in cleaned_link
    assert "Nima now looks directly at Roksana." in cleaned_link

    # 4. Restoring Codex thread history restores imageGeneration items & unwraps legacy JSON
    mgr = DiscussManager(book)
    try:
        opened = mgr.open({"kind": "scene", "path": rel}, agent="codex")
        conv = mgr._get(opened["conversation_id"])
        conv.thread_id = "th-restore-1"
        thread_payload = {
            "id": "th-restore-1",
            "turns": [
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "userMessage",
                            "content": [{"type": "text", "text": "CTX\n\nUSER QUESTION\nGood, make Nima look at Roksana too"}],
                        },
                        {
                            "type": "imageGeneration",
                            "id": "ig-restore-1",
                            "status": "completed",
                            "savedPath": str(codex_saved),
                            "revisedPrompt": "Turned Nima's head toward Roksana",
                        },
                        {
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": json.dumps({"alt": "Nima and Roksana exchange a quiet look.", "revised_prompt": "Turned Nima's head"}),
                        },
                    ],
                }
            ],
        }
        mgr._restore_thread(conv, thread_payload, source_document=dict(conv.document))
        asst = [m for m in conv.messages if m.get("role") == "assistant"]
        assert len(asst) == 1
        assert "```proseview:scene-image" in asst[0]["text"]
        assert "Nima and Roksana exchange a quiet look." in asst[0]["text"]
        assert '{"alt"' not in asst[0]["text"]
    finally:
        mgr.close()


def test_agy_chat_image_capture_and_thread_restore(tmp_path: Path) -> None:
    """Agy JSON image_path replies are captured both live (without keyword hacks) and on thread restore."""
    from proseview.scene_image import capture_chat_image_from_text, format_scene_image_reply_text

    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    agy_img = tmp_path / "agy_brain" / "minimalist_woodcut_123.jpg"
    agy_img.parent.mkdir(parents=True, exist_ok=True)
    agy_img.write_bytes(_TINY_JPG)

    # 1. Explicit JSON image_path captured even when activities=None (e.g. on restore)
    agy_reply = json.dumps({
        "image_path": str(agy_img),
        "alt": "A monochrome woodcut engraving of the bar.",
        "revised_prompt": "Woodcut engraving of a dimly lit bar.",
    })
    captured = capture_chat_image_from_text(book, agy_reply, agent="agy", scene_path=rel, activities=None)
    assert captured is not None
    assert captured["alt"] == "A monochrome woodcut engraving of the bar."
    assert captured["ext"] == ".jpg"

    # 2. Agy replay combining pre-tool status text + JSON still unwraps cleanly
    replayed_text = "Waiting for the `image-generator` subagent to finish.\n\n" + agy_reply
    clean, alt, _rev = format_scene_image_reply_text(replayed_text, has_images=True)
    assert clean == "A monochrome woodcut engraving of the bar."
    assert '"image_path"' not in clean

    # 3. Restoring an Agy thread from replay produces a rendered card with zero unsafe-content notices
    mgr = DiscussManager(book)
    try:
        opened = mgr.open({"kind": "scene", "path": rel}, agent="agy")
        conv = mgr._get(opened["conversation_id"])
        conv.thread_id = "agy-sess-1"
        thread_payload = {
            "id": "agy-sess-1",
            "turns": [
                {
                    "id": "turn-1",
                    "items": [
                        {
                            "type": "userMessage",
                            "content": [{"type": "text", "text": "SCENE PROMPT\n\nUSER QUESTION\nGenerate a scene illustration (Woodcut & Engraving, 16:9)."}],
                        },
                        {
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": replayed_text,
                        },
                    ],
                }
            ],
        }
        mgr._restore_thread(conv, thread_payload, source_document=dict(conv.document))
        assert not any("could not be displayed safely" in str(n.get("message", "")) for n in conv.notices)
        asst = [m for m in conv.messages if m.get("role") == "assistant"]
        assert len(asst) == 1
        assert "```proseview:scene-image" in asst[0]["text"]
        assert "A monochrome woodcut engraving of the bar." in asst[0]["text"]
        assert '"image_path"' not in asst[0]["text"]
    finally:
        mgr.close()


def test_ordinary_chat_reply_linking_an_image_is_not_taken_as_an_illustration(tmp_path: Path) -> None:
    """Only an illustration request turns image paths in a reply into a generated image."""
    from proseview.scene_image import capture_chat_image_from_text, is_scene_image_prompt

    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    cover = book / "cover.png"
    cover.write_bytes(_TINY_PNG)
    reply = f"Your cover is here: [cover]({cover})"

    assert capture_chat_image_from_text(book, reply, agent="claude", scene_path=rel, explicit_only=True) is None
    # The JSON reply an illustration prompt asks for still counts.
    as_json = json.dumps({"image_path": str(cover), "alt": "Cover"})
    assert capture_chat_image_from_text(book, as_json, agent="claude", scene_path=rel, explicit_only=True) is not None

    assert is_scene_image_prompt("PROMPT\n\nUSER QUESTION\nGenerate a scene illustration (Woodcut, 16:9).")
    assert is_scene_image_prompt("PROMPT\n\nUSER QUESTION\nRefine the scene illustration (Woodcut, 16:9): warmer")
    assert not is_scene_image_prompt("CTX\n\nUSER QUESTION\nWhere is the cover image?")

    mgr = DiscussManager(book)
    try:
        opened = mgr.open({"kind": "scene", "path": rel}, agent="claude")
        conv = mgr._get(opened["conversation_id"])
        conv.thread_id = "th-plain-1"
        mgr._restore_thread(conv, {
            "id": "th-plain-1",
            "turns": [{
                "id": "turn-1",
                "items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": "CTX\n\nUSER QUESTION\nWhere is the cover image?"}]},
                    {"type": "agentMessage", "phase": "final_answer", "text": reply},
                ],
            }],
        }, source_document=dict(conv.document))
        asst = [m for m in conv.messages if m.get("role") == "assistant"]
        assert len(asst) == 1
        assert "proseview:scene-image" not in asst[0]["text"]
        assert get_scene_image_status(book, rel)["has_preview"] is False
    finally:
        mgr.close()


def test_replacing_an_illustration_keeps_pictures_the_writer_placed(tmp_path: Path) -> None:
    """Only the file Proseview wrote for this scene is removed when its type changes."""
    book = _make_book(tmp_path)
    rel = "ch01/01-opening-at-the-bar.md"
    scene_file = book / "manuscript" / rel
    own = book / "manuscript" / "ch01" / "map.png"
    own.write_bytes(_TINY_PNG)
    raw = scene_file.read_text(encoding="utf-8")
    fm_end = raw.index("---", 3) + 4
    scene_file.write_text(raw[:fm_end] + '\n<img src="map.png" alt="Map">\n\n' + raw[fm_end:].lstrip("\n"), encoding="utf-8")

    save_scene_image_preview(book, rel, _TINY_JPG, ".jpg", "image/jpeg", agent="agy", style_id="woodcut", alt="Bar")
    insert_scene_image(book, rel)
    assert own.read_bytes() == _TINY_PNG
    assert '<img src="assets/01-opening-at-the-bar.jpg"' in scene_file.read_text(encoding="utf-8")
