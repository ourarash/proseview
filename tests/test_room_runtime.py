"""Durable Room queues and review snapshots, independent of a browser lifetime."""
import copy
import threading
import time

import pytest

from proseview.discuss import ContextError
from tests.test_highlight_suggestions import _manager, _repo


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Room did not reach the expected state")


def initial(manager, key="durable-room"):
    return {"id": key, "scene": "one.md", "participants": manager.room_settings()["participants"], "turns": [], "title": "Conversation"}


def command(manager, action="state", key="durable-room", **kw):
    return manager.room_command({"action": action, "room_id": key, "request_id": kw.pop("request_id", f"request-{time.monotonic_ns()}"), **kw})


def reply(kwargs, text="A useful reply."):
    profile = kwargs["participants"][kwargs["seat"] - 1]
    return {"seat": kwargs["seat"], "agent": profile["agent"], "reply": text, "passed": not text, "model": "", "changed_files": [], "unreviewable": []}


def test_room_review_survives_restart_and_undo_remains_available(tmp_path):
    root = _repo(tmp_path)
    first = _manager(root, [])
    try:
        result = first.run_room_turn(scene="one.md", participants=first.room_settings()["participants"])
        cid = result["tool_conversation_id"]
        conversation = first._get(cid)
        scene = root / "manuscript" / "one.md"
        original = scene.read_text()
        first._capture_before(conversation, [{"path": "manuscript/one.md"}])
        scene.write_text(original.replace("First document.", "A revised opening."))
    finally:
        first.close()
    second = _manager(root, [])
    try:
        changes = second.turn_file_changes(cid)
        assert changes["files"][0]["before"] == original
        assert "A revised opening." in changes["files"][0]["after"]
        second.apply_file_selection(cid, "manuscript/one.md", [], changes["files"][0]["fingerprint"])
        assert scene.read_text() == original
    finally:
        second.close()
    third = _manager(root, [])
    try:
        assert third.turn_file_changes(cid)["files"] == []
        assert third._get(cid).agent_notes, "review corrections must survive another restart"
    finally:
        third.close()


def test_legacy_missing_review_does_not_block_messages(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        session = initial(manager)
        session["turns"] = [{"role": "critic", "seat": 1, "agent": "codex", "text": "Edited the file.", "review_pending": True, "tool_conversation_id": "lost-proxy"}]
        manager.room_history({"action": "save", "session": session})
        state = command(manager)
        assert state["status"] == "idle" and not state["turns"][0]["review_pending"]
        assert state["turns"][0]["review_unavailable"] and "no longer blocks" in state["notice"]
        assert clients == [], "reading recovery state must not resend any agent request"
    finally:
        manager.close()


def test_server_finishes_all_invitations_without_an_attached_browser_and_deduplicates_submit(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    started, release = threading.Event(), threading.Event()
    calls = []
    def run(**kw):
        calls.append(copy.deepcopy(kw))
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return reply(kw)
    monkeypatch.setattr(manager, "run_room_turn", run)
    try:
        body = dict(initial=initial(manager), request_id="send-once", message_id="message-one", text="First question", seats=[1, 2])
        command(manager, "submit", **body)
        assert started.wait(5)
        command(manager, "submit", **body)
        command(manager, "submit", message_id="message-two", text="Next question", seats=[2])
        assert not any(t.get("text") == "Next question" for t in command(manager)["turns"])
        release.set()
        state = wait_for(lambda: (s := command(manager))["status"] == "idle" and len([t for t in s["turns"] if t["role"] == "critic"]) == 3 and s)
        assert [kw["seat"] for kw in calls] == [1, 2, 2]
        assert len([t for t in state["turns"] if t["role"] == "user"]) == 2
        assert len(state["steps"]) == 3
    finally:
        release.set()
        manager.close()


def test_preset_continues_after_a_pass_without_a_browser(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    calls = []
    def run(**kw):
        calls.append(kw["seat"])
        return reply(kw, "" if len(calls) == 1 else "Second perspective.")
    monkeypatch.setattr(manager, "run_room_turn", run)
    try:
        command(manager, "preset", initial=initial(manager), invitations=[{"seat": 1, "prompt": "Your view?"}, {"seat": 2, "prompt": "Your view?"}])
        state = wait_for(lambda: len((s := command(manager))["turns"]) == 4 and s["status"] == "idle" and s)
        assert calls == [1, 2]
        assert state["turns"][1]["passed"] is True
    finally:
        manager.close()


def test_restart_recovers_a_completed_reply_without_repeating_it(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    first = _manager(root, [])
    saved = {**initial(first), "managed": True, "version": 1, "revision": 1, "commands": {}, "native_threads": {}, "status": "running", "active_step": "step-one", "notice": "", "error": "", "plans": [],
        "turns": [{"role": "user", "label": "Writer", "text": "Discuss."}], "steps": [
            {"id": "step-one", "seat": 1, "kind": "message", "state": "running", "native_status": "completed", "native_reply": "Already completed.", "text": "Discuss.", "authored": "Discuss.", "message_id": "message"},
            {"id": "step-two", "seat": 2, "kind": "message", "state": "queued", "text": "Discuss.", "authored": "Discuss.", "message_id": "message"}]}
    first.room_runtime.store.write("rooms", saved["id"], saved)
    first.close()
    second = _manager(root, [])
    calls = []
    def run(**kw):
        calls.append(kw["seat"])
        return reply(kw)
    monkeypatch.setattr(second, "run_room_turn", run)
    try:
        command(second)
        state = wait_for(lambda: (s := command(second))["status"] == "idle" and len([t for t in s["turns"] if t["role"] == "critic"]) == 2 and s)
        assert calls == [2]
        assert sum(t["text"] == "Already completed." for t in state["turns"]) == 1
    finally:
        second.close()


def test_restart_preserves_an_unfinished_reply_and_never_repeats_it_automatically(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    first = _manager(root, [])
    saved = {**initial(first), "managed": True, "version": 1, "revision": 1, "commands": {}, "native_threads": {}, "status": "running", "active_step": "step-one", "notice": "", "error": "", "plans": [],
        "turns": [{"role": "user", "label": "Writer", "text": "Edit this."}], "steps": [
            {"id": "step-one", "seat": 1, "kind": "message", "state": "running", "draft": "A partial reply", "text": "Edit this.", "authored": "Edit this.", "message_id": "message"}]}
    first.room_runtime.store.write("rooms", saved["id"], saved)
    first.close()
    second = _manager(root, [])
    calls = []
    monkeypatch.setattr(second, "run_room_turn", lambda **kw: calls.append(kw))
    try:
        command(second)
        state = wait_for(lambda: (s := command(second))["status"] == "interrupted" and s)
        assert state["partial_reply"] == "A partial reply" and calls == []
        with pytest.raises(ContextError, match="Retry or Skip"):
            command(second, "resume")
        command(second, "skip")
        assert command(second)["status"] == "idle" and calls == []
    finally:
        second.close()


def test_saved_managed_room_with_a_missing_review_is_usable(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    first = _manager(root, [])
    saved = command(first, initial=initial(first))
    saved.update(status="review", commands={}, native_threads={}, turns=[{
        "role": "critic", "seat": 1, "agent": "codex", "text": "Saved changes.",
        "tool_conversation_id": "missing-review", "review_pending": True}])
    first.room_runtime.store.write("rooms", saved["id"], saved)
    first.close()
    second = _manager(root, [])
    monkeypatch.setattr(second, "run_room_turn", lambda **kw: reply(kw))
    try:
        state = command(second)
        assert state["status"] == "idle" and state["turns"][0]["review_unavailable"]
        command(second, "submit", message_id="followup", text="Continue talking.", seats=[1])
        wait_for(lambda: len(command(second)["turns"]) == 3)
    finally:
        second.close()


def test_a_late_checkpoint_cannot_overwrite_a_retried_attempt(tmp_path):
    manager = _manager(_repo(tmp_path), [])
    try:
        command(manager, initial=initial(manager))
        room = manager.room_runtime.rooms["durable-room"]
        room["steps"] = [{"id": "step", "seat": 1, "state": "running", "run_id": "new-attempt"}]
        manager.room_runtime.checkpoint(room["id"], "step", {"run_id": "old-attempt", "native_status": "completed", "native_reply": "Old reply"})
        assert "native_status" not in room["steps"][0]
        manager.room_runtime.checkpoint(room["id"], "step", {"run_id": "new-attempt", "draft": "Current reply"})
        assert room["steps"][0]["draft"] == "Current reply"
    finally:
        manager.close()


def test_stopped_completed_turn_stays_paused_after_restart(tmp_path, monkeypatch):
    first = _manager(root := _repo(tmp_path), [])
    saved = command(first, initial=initial(first))
    saved.update(status="paused", active_step="step", commands={}, native_threads={}, steps=[{
        "id": "step", "seat": 1, "state": "interrupting", "kind": "invitation", "prompt": "Your view?",
        "native_status": "completed", "native_reply": "Finished before stopping."}, {
        "id": "next", "seat": 2, "state": "queued", "kind": "invitation", "prompt": "Your view?"}])
    first.room_runtime.store.write("rooms", saved["id"], saved)
    first.close()
    second = _manager(root, [])
    calls = []
    monkeypatch.setattr(second, "run_room_turn", lambda **kw: calls.append(kw) or reply(kw))
    try:
        command(second)
        state = wait_for(lambda: (s := command(second))["status"] == "paused" and s)
        assert calls == [] and state["steps"][0]["state"] == "completed"
        command(second, "resume")
        wait_for(lambda: (s := command(second))["status"] == "idle" and len(s["turns"]) == 3)
        assert [call["seat"] for call in calls] == [2]
    finally:
        second.close()


def test_queued_unsaved_draft_conflict_needs_explicit_retry_using_current_files(tmp_path, monkeypatch):
    manager = _manager(root := _repo(tmp_path), [])
    scene = root / "manuscript" / "one.md"
    calls = []
    monkeypatch.setattr(manager, "run_room_turn", lambda **kw: calls.append(kw) or reply(kw))
    try:
        command(manager, initial=initial(manager))
        command(manager, "stop")
        command(manager, "submit", message_id="draft", text="Use this draft.", seats=[1],
            live_document={"content": "Unsaved author's draft.", "base_mtime": scene.stat().st_mtime})
        scene.write_text("An earlier agent edited this scene.")
        import os
        os.utime(scene, (scene.stat().st_atime, scene.stat().st_mtime + 2))
        command(manager, "resume")
        state = wait_for(lambda: (s := command(manager))["status"] == "interrupted" and s)
        assert "changed externally" in state["error"] and calls == []
        command(manager, "retry")
        wait_for(lambda: (s := command(manager))["status"] == "idle" and len(s["turns"]) == 3)
        assert calls[0]["live_content"] == ""
        assert "Check the current files" in calls[0]["history"][-1]["text"]
    finally:
        manager.close()


def test_provider_conversation_link_resumes_after_restart(tmp_path):
    first = _manager(root := _repo(tmp_path), first_clients := [])
    try:
        command(first, "submit", initial=initial(first), message_id="first", text="First question.", seats=[1])
        wait_for(lambda: (s := command(first))["status"] == "idle" and len(s["turns"]) == 2)
        native = copy.deepcopy(first.room_runtime.rooms["durable-room"]["native_threads"]["1"])
        threads = copy.deepcopy(first_clients[0].threads)
    finally:
        first.close()
    second = _manager(root, [])
    try:
        client = second._client_for("codex")
        client.threads = threads
        client.unloaded = set(threads)
        command(second, "submit", message_id="second", text="Follow-up question.", seats=[1])
        wait_for(lambda: (s := command(second))["status"] == "idle" and len(s["turns"]) == 4)
        assert client.resumes == [native["thread_id"]]
        assert client.turn_params[0]["threadId"] == native["thread_id"]
        assert "Follow-up question." in client.prompts[0]
        assert "First question." not in client.prompts[0], "a restored native link receives only the new shared turns"
    finally:
        second.close()


def test_stale_browser_save_cannot_replace_server_transcript(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    monkeypatch.setattr(manager, "run_room_turn", lambda **kw: reply(kw))
    try:
        command(manager, "submit", initial=initial(manager), message_id="first", text="Saved on the server.", seats=[1])
        wait_for(lambda: len(command(manager)["turns"]) == 2)
        manager.room_history({"action": "save", "session": {**initial(manager), "turns": [{"role": "user", "text": "Outdated browser copy"}]}})
        assert command(manager)["turns"][0]["text"] == "Saved on the server."
    finally:
        manager.close()


def test_edit_review_does_not_pause_the_next_agent(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    calls = []
    def run(**kw):
        calls.append(kw["seat"])
        result = reply(kw)
        if len(calls) == 1:
            result.update(tool_conversation_id="saved-review", changed_files=["manuscript/one.md"])
        return result
    monkeypatch.setattr(manager, "run_room_turn", run)
    try:
        command(manager, "submit", initial=initial(manager), message_id="both", text="Discuss together.", seats=[1, 2])
        state = wait_for(lambda: (s := command(manager))["status"] == "idle" and len(s["turns"]) == 3 and s)
        assert calls == [1, 2]
        assert state["turns"][1]["review_pending"], "review remains available without stopping the discussion"
    finally:
        manager.close()


def saved_edit(manager, root):
    command(manager, "submit", initial=initial(manager), message_id="edit", text="Make this edit.", seats=[1])
    state = wait_for(lambda: (s := command(manager))["status"] == "idle" and len(s["turns"]) == 2 and s)
    cid = state["turns"][-1]["tool_conversation_id"]
    scene = root / "manuscript" / "one.md"
    original = scene.read_text()
    manager._capture_before(manager._get(cid), [{"path": "manuscript/one.md"}])
    scene.write_text(original.replace("First document.", "Revised opening."))
    with manager.room_runtime.lock:
        room = manager.room_runtime.rooms[state["id"]]
        room["turns"][-1]["review_pending"] = True
        manager.room_runtime._save(room)
    return cid, scene, original, manager.turn_file_changes(cid)["files"][0]


@pytest.mark.parametrize("undo", [False, True])
def test_next_writer_message_settles_optional_review_and_honors_unticks(tmp_path, undo):
    manager = _manager(root := _repo(tmp_path), [])
    try:
        cid, scene, original, offer = saved_edit(manager, root)
        choice = [{"conversation_id": cid, "path": offer["path"], "drop": [block["id"] for block in offer["blocks"]], "fingerprint": offer["fingerprint"]}] if undo else []
        command(manager, "submit", message_id="followup", text="What do you think now?", seats=[2], review_choices=choice)
        state = wait_for(lambda: (s := command(manager))["status"] == "idle" and len(s["turns"]) == 4 and s)
        assert not state["turns"][1]["review_pending"]
        assert manager.turn_file_changes(cid)["files"] == []
        assert (scene.read_text() == original) is undo
    finally:
        manager.close()


def test_optional_review_never_applies_stale_unticks_and_can_retry_with_refreshed_choices(tmp_path, monkeypatch):
    manager = _manager(root := _repo(tmp_path), [])
    try:
        cid, scene, original, offer = saved_edit(manager, root)
        scene.write_text(scene.read_text() + "\nAn external edit that must survive.\n")
        latest = scene.read_text()
        calls = []
        monkeypatch.setattr(manager, "run_room_turn", lambda **kw: calls.append(kw) or reply(kw))
        command(manager, "submit", message_id="followup", text="What next?", seats=[2], review_choices=[{
            "conversation_id": cid, "path": offer["path"], "drop": [offer["blocks"][0]["id"]], "fingerprint": offer["fingerprint"]}])
        state = wait_for(lambda: (s := command(manager))["status"] == "interrupted" and s)
        assert "changed since you looked" in state["error"]
        assert scene.read_text() == latest and calls == []
        command(manager, "retry", review_choices=[])
        wait_for(lambda: (s := command(manager))["status"] == "idle" and len(s["turns"]) == 5)
        assert scene.read_text() == latest and len(calls) == 1
    finally:
        manager.close()


def test_existing_review_paused_room_resumes_its_pending_agent_after_upgrade(tmp_path, monkeypatch):
    first = _manager(root := _repo(tmp_path), [])
    try:
        cid, scene, original, offer = saved_edit(first, root)
        with first.room_runtime.lock:
            room = first.room_runtime.rooms["durable-room"]
            room["status"] = "review"
            room["steps"].append({"id": "waiting-agent", "seat": 2, "state": "queued", "kind": "invitation", "prompt": "Give your view."})
            first.room_runtime._save(room)
    finally:
        first.close()
    second = _manager(root, [])
    calls = []
    monkeypatch.setattr(second, "run_room_turn", lambda **kw: calls.append(kw["seat"]) or reply(kw))
    try:
        command(second)
        state = wait_for(lambda: (s := command(second))["status"] == "idle" and len(s["turns"]) == 4 and s)
        assert calls == [2] and state["turns"][1]["review_pending"]
        assert second.turn_file_changes(cid)["files"][0]["after"] == scene.read_text()
    finally:
        second.close()
