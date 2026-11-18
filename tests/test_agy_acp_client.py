from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from proseview.agy_acp_client import (
    AgyAcpClient,
    AgyAuthError,
    AgyProtocolError,
    AgyRequestError,
    AgyUnavailableError,
    _extract_json_text,
    sanitize_agy_message,
)


def _runnable(path: Path) -> Path:
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    if os.name != "nt":
        return path
    wrapper = path.with_suffix(".cmd")
    wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{path}" %*\r\n', encoding="utf-8")
    return wrapper


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def _fake_agy(
    tmp_path: Path,
    *,
    authenticated: bool = True,
    malformed: bool = False,
    cancel_on_prompt: bool = False,
    structured_fence: bool = False,
    prompt_delay: float = 0.0,
) -> Path:
    path = tmp_path / "agy"
    log_path = tmp_path / "acp_calls.jsonl"
    script = f"""#!/usr/bin/env python3
import json, sys, pathlib, time

log_path = pathlib.Path({str(log_path)!r})
def log(entry):
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\\n")

sessions = {{}}
next_sid = 0
active_prompt = None

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    log(msg)
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {{}}

    if method == "initialize":
        print(json.dumps({{
            "jsonrpc": "2.0",
            "id": rid,
            "result": {{
                "protocolVersion": 1,
                "agentInfo": {{"name": "Antigravity ACP Server", "version": "1.5.10"}},
                "agentCapabilities": {{
                    "loadSession": True,
                    "sessionCapabilities": {{"resume": {{}}, "load": {{}}, "list": {{}}, "close": {{}}}},
                    "_meta": {{"antigravity": {{"systemPrompt": {{"append": True}}}}}},
                }},
            }},
        }}), flush=True)
    elif method == "session/list":
        if not {authenticated!r}:
            print(json.dumps({{
                "jsonrpc": "2.0",
                "id": rid,
                "error": {{"code": -32000, "message": "Authentication required"}},
            }}), flush=True)
        else:
            print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{"sessions": []}}}}), flush=True)
    elif method == "session/new":
        if not {authenticated!r}:
            print(json.dumps({{
                "jsonrpc": "2.0",
                "id": rid,
                "error": {{"code": -32000, "message": "Authentication required"}},
            }}), flush=True)
            continue
        next_sid += 1
        sid = f"acp-sess-{{next_sid}}"
        sessions[sid] = {{"history": [], "mode": "accept-edits", "model": "gemini-4-argon-medium"}}
        print(json.dumps({{
            "jsonrpc": "2.0",
            "id": rid,
            "result": {{
                "sessionId": sid,
                "modes": {{
                    "currentModeId": "accept-edits",
                    "availableModes": [{{"id": "default"}}, {{"id": "accept-edits"}}, {{"id": "plan"}}],
                }},
                "models": {{
                    "currentModelId": "gemini-4-argon-medium",
                    "availableModels": [
                        {{"modelId": "gemini-4-argon-low", "name": "Gemini 4 Argon (Low)"}},
                        {{"modelId": "gemini-4-argon-medium", "name": "Gemini 4 Argon (Medium)"}},
                        {{"modelId": "gemini-4-argon-high", "name": "Gemini 4 Argon (High)"}},
                        {{"modelId": "gemini-4-hydrogen-xhigh", "name": "Gemini 4 Hydrogen (XHigh)"}},
                    ],
                }},
                "configOptions": [
                    {{
                        "id": "model",
                        "currentValue": "gemini-4-argon",
                        "options": [
                            {{"value": "gemini-4-argon", "name": "Gemini 4 Argon"}},
                            {{"value": "gemini-4-hydrogen", "name": "Gemini 4 Hydrogen"}},
                        ],
                    }},
                    {{
                        "id": "thought_level",
                        "currentValue": "medium",
                        "options": [{{"value": "low"}}, {{"value": "medium"}}, {{"value": "high"}}],
                    }},
                ],
            }},
        }}), flush=True)
    elif method == "session/set_mode":
        sid = params.get("sessionId")
        if sid in sessions:
            sessions[sid]["mode"] = params.get("modeId")
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{}}}}), flush=True)
    elif method in ("session/set_model", "session/set_config_option", "session/close"):
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{}}}}), flush=True)
    elif method == "session/resume":
        sid = params.get("sessionId")
        if sid not in sessions and sid != "persisted-session":
            print(json.dumps({{
                "jsonrpc": "2.0",
                "id": rid,
                "error": {{"code": -32004, "message": "session not found"}},
            }}), flush=True)
        else:
            sessions.setdefault(sid, {{"history": [], "mode": "default"}})
            print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{"sessionId": sid}}}}), flush=True)
    elif method == "session/load":
        sid = params.get("sessionId")
        if sid != "persisted-session" and sid not in sessions:
            print(json.dumps({{
                "jsonrpc": "2.0",
                "id": rid,
                "error": {{"code": -32004, "message": "session not found"}},
            }}), flush=True)
            continue
        print(json.dumps({{
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {{"sessionId": sid, "update": {{"sessionUpdate": "user_message_chunk", "content": {{"type": "text", "text": "Saved question"}}}}}},
        }}), flush=True)
        print(json.dumps({{
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {{"sessionId": sid, "update": {{"sessionUpdate": "agent_message_chunk", "content": {{"type": "text", "text": "Saved answer"}}}}}},
        }}), flush=True)
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{"sessionId": sid}}}}), flush=True)
    elif method == "session/prompt":
        if {malformed!r}:
            print("not json", flush=True)
            continue
        sid = params["sessionId"]
        if {cancel_on_prompt!r}:
            active_prompt = (rid, sid)
            print(json.dumps({{
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {{"sessionId": sid, "update": {{"sessionUpdate": "agent_thought_chunk", "content": {{"type": "text", "text": "RAW SECRET"}}}}}},
            }}), flush=True)
            continue
        if {prompt_delay!r} > 0:
            time.sleep({prompt_delay!r})
        text = "```json\\n{{\\"ok\\": true}}\\n```" if {structured_fence!r} else "Visible reply"
        print(json.dumps({{
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {{"sessionId": sid, "update": {{"sessionUpdate": "agent_thought_chunk", "content": {{"type": "text", "text": "RAW SECRET"}}}}}},
        }}), flush=True)
        print(json.dumps({{
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {{"sessionId": sid, "update": {{"sessionUpdate": "agent_message_chunk", "content": {{"type": "text", "text": text}}}}}},
        }}), flush=True)
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{"stopReason": "end_turn"}}}}), flush=True)
    elif method == "session/cancel":
        if active_prompt is not None:
            prid, psid = active_prompt
            active_prompt = None
            print(json.dumps({{"jsonrpc": "2.0", "id": prid, "result": {{"stopReason": "cancelled"}}}}), flush=True)
"""
    path.write_text(script, encoding="utf-8")
    return _runnable(path)


# --- translator unit tests --------------------------------------------------


def test_translator_drops_raw_thought_chunks():
    assert sanitize_agy_message({
        "method": "session/update",
        "params": {
            "sessionId": "s1",
            "turnId": "t1",
            "update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "RAW SECRET"}},
        },
    }) == []


def test_translator_maps_text_delta_and_metadata_updates():
    events = sanitize_agy_message({
        "method": "session/update",
        "params": {
            "sessionId": "s1",
            "turnId": "t1",
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hello"}},
        },
    })
    assert events == [{
        "type": "response.delta",
        "thread_id": "s1",
        "turn_id": "t1",
        "item_id": None,
        "text": "Hello",
    }]
    assert sanitize_agy_message({
        "method": "session/update",
        "params": {"sessionId": "s1", "update": {"sessionUpdate": "usage_update", "used": 100}},
    }) == []


def test_translator_maps_execute_edit_and_read_tool_calls():
    cmd = sanitize_agy_message({
        "method": "session/update",
        "params": {
            "sessionId": "s1",
            "turnId": "t1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "c1",
                "name": "run_command",
                "kind": "execute",
                "status": "in_progress",
                "args": {"CommandLine": "git status", "Cwd": "/repo"},
            },
        },
    })
    assert cmd == [{
        "type": "activity.updated",
        "thread_id": "s1",
        "turn_id": "t1",
        "activity": {
            "id": "c1",
            "kind": "commandExecution",
            "status": "inProgress",
            "command": "git status",
            "cwd": "/repo",
            "output": "",
        },
    }]

    edit = sanitize_agy_message({
        "method": "session/update",
        "params": {
            "sessionId": "s1",
            "turnId": "t1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "c2",
                "name": "edit_file",
                "kind": "edit",
                "status": "completed",
                "locations": [{"path": "/repo/manuscript/one.md"}],
            },
        },
    })
    assert edit == [{
        "type": "activity.updated",
        "thread_id": "s1",
        "turn_id": "t1",
        "activity": {
            "id": "c2",
            "kind": "fileChange",
            "status": "completed",
            "changes": [{"path": "/repo/manuscript/one.md", "kind": "modify"}],
        },
    }]

    read = sanitize_agy_message({
        "method": "session/update",
        "params": {
            "sessionId": "s1",
            "turnId": "t1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "c3",
                "name": "read_file",
                "kind": "read",
                "status": "completed",
                "args": {"Path": "/repo/manuscript/one.md"},
            },
        },
    })
    assert read[0]["activity"]["kind"] == "dynamicToolCall"
    assert read[0]["activity"]["tool"] == "read_file"
    assert read[0]["activity"]["path"] == "/repo/manuscript/one.md"


# --- client subprocess protocol tests ---------------------------------------


def test_missing_executable_fails_capability_inspection(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    client = AgyAcpClient(cwd=tmp_path)
    with pytest.raises(AgyUnavailableError, match="not installed"):
        client.inspect_capabilities()


def test_client_starts_enforces_default_mode_and_appends_instructions(tmp_path: Path):
    exe = _fake_agy(tmp_path)
    received: list[dict] = []
    client = AgyAcpClient(executable=str(exe), cwd=tmp_path, on_message=received.append)
    try:
        client.start()
        assert client.user_agent == "Antigravity ACP Server/1.5.10"
        thread = client.request("thread/start", {"cwd": str(tmp_path), "developerInstructions": "Rule one."})
        sid = thread["thread"]["id"]
        assert sid == "acp-sess-1"
        turn = client.request("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "Hi"}]})
        assert turn["turn"]["id"]
        _wait_until(lambda: any(m.get("method") == "session/prompt/completed" for m in received))

        events = [ev for msg in received for ev in sanitize_agy_message(msg)]
        assert not any("RAW SECRET" in repr(ev) for ev in events)
        assert any(ev["type"] == "response.completed" and ev["text"] == "Visible reply" for ev in events)

        calls = [json.loads(line) for line in (tmp_path / "acp_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        new_call = next(c for c in calls if c.get("method") == "session/new")
        assert new_call["params"]["_meta"]["antigravity"]["systemPrompt"]["append"] == "Rule one."
        set_mode = next(c for c in calls if c.get("method") == "session/set_mode")
        assert set_mode["params"]["modeId"] == "default"
    finally:
        client.close()
    assert client.alive is False


def test_unauthenticated_start_raises_auth_error(tmp_path: Path):
    client = AgyAcpClient(executable=str(_fake_agy(tmp_path, authenticated=False)), cwd=tmp_path)
    with pytest.raises(AgyAuthError, match="sign in"):
        client.start()
    client.close()


def test_malformed_json_fails_client_and_future_requests(tmp_path: Path):
    failures: list[BaseException] = []
    client = AgyAcpClient(
        executable=str(_fake_agy(tmp_path, malformed=True)),
        cwd=tmp_path,
        on_failure=failures.append,
    )
    try:
        client.start()
        sid = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "Hi"}]})
        _wait_until(lambda: not client.alive)
        assert failures and isinstance(failures[0], AgyProtocolError)
        with pytest.raises(AgyProtocolError, match="invalid JSON"):
            client.request("thread/start", {})
    finally:
        client.close()


def test_thread_read_buffers_replay_and_reconstructs_turns(tmp_path: Path):
    received: list[dict] = []
    client = AgyAcpClient(executable=str(_fake_agy(tmp_path)), cwd=tmp_path, on_message=received.append)
    try:
        client.start()
        res = client.request("thread/read", {"threadId": "persisted-session"})
        assert len(res["turns"]) == 1
        assert res["turns"][0]["items"][0]["content"][0]["text"] == "Saved question"
        assert res["turns"][0]["items"][1]["text"] == "Saved answer"
        # Replayed chunks must not leak as live notifications.
        assert received == []
    finally:
        client.close()


def test_missing_thread_resume_raises_not_found(tmp_path: Path):
    client = AgyAcpClient(executable=str(_fake_agy(tmp_path)), cwd=tmp_path)
    try:
        client.start()
        with pytest.raises(AgyRequestError) as exc:
            client.request("thread/resume", {"threadId": "does-not-exist"})
        assert exc.value.code == -32004
    finally:
        client.close()


def test_turn_interrupt_sends_session_cancel_and_completes_as_interrupted(tmp_path: Path):
    received: list[dict] = []
    client = AgyAcpClient(
        executable=str(_fake_agy(tmp_path, cancel_on_prompt=True)),
        cwd=tmp_path,
        on_message=received.append,
    )
    try:
        client.start()
        sid = client.request("thread/start", {})["thread"]["id"]
        turn_id = client.request("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "Long"}]})["turn"]["id"]
        time.sleep(0.05)
        client.request("turn/interrupt", {"threadId": sid, "turnId": turn_id})
        _wait_until(lambda: any(m.get("method") == "session/prompt/completed" for m in received))
        completed = next(m for m in received if m.get("method") == "session/prompt/completed")
        assert completed["params"]["status"] == "interrupted"
    finally:
        client.close()


def test_long_prompt_does_not_time_out_on_request_timeout(tmp_path: Path):
    received: list[dict] = []
    client = AgyAcpClient(
        executable=str(_fake_agy(tmp_path, prompt_delay=0.8)),
        cwd=tmp_path,
        on_message=received.append,
        request_timeout=0.5,
    )
    try:
        client.start()
        sid = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "Take your time"}]})
        _wait_until(lambda: any(m.get("method") == "session/prompt/completed" for m in received))
        completed = next(m for m in received if m.get("method") == "session/prompt/completed")
        assert completed["params"]["status"] == "completed"
        assert not any(m.get("method") == "session/error" for m in received)
    finally:
        client.close()


def test_structured_turn_suppresses_raw_chunks_and_strips_fences(tmp_path: Path):
    received: list[dict] = []
    client = AgyAcpClient(
        executable=str(_fake_agy(tmp_path, structured_fence=True)),
        cwd=tmp_path,
        on_message=received.append,
    )
    try:
        client.start()
        sid = client.request("thread/start", {})["thread"]["id"]
        client.request(
            "turn/start",
            {
                "threadId": sid,
                "input": [{"type": "text", "text": "Check"}],
                "outputSchema": {"type": "object"},
            },
        )
        _wait_until(lambda: any(m.get("method") == "session/prompt/completed" for m in received))
        events = [ev for msg in received for ev in sanitize_agy_message(msg)]
        assert not any(ev["type"] == "response.delta" for ev in events)
        final = next(ev for ev in events if ev["type"] == "response.completed")
        assert json.loads(final["text"]) == {"ok": True}
    finally:
        client.close()


def test_model_list_probes_session_closes_it_and_groups_efforts(tmp_path: Path):
    client = AgyAcpClient(executable=str(_fake_agy(tmp_path)), cwd=tmp_path)
    try:
        client.start()
        catalog = client.request("model/list", {})
        by_id = {row["id"]: row for row in catalog["data"]}
        assert [e["reasoningEffort"] for e in by_id["gemini-4-argon"]["supportedReasoningEfforts"]] == [
            "low", "medium", "high"
        ]
        assert [e["reasoningEffort"] for e in by_id["gemini-4-hydrogen"]["supportedReasoningEfforts"]] == ["xhigh"]
        assert catalog["default"]["model"] == "gemini-4-argon"
        assert catalog["default"]["effort"] == "medium"

        calls = [json.loads(line) for line in (tmp_path / "acp_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any(c.get("method") == "session/close" for c in calls)
    finally:
        client.close()


def test_permission_requests_translate_and_cache_command_grants_not_edits(tmp_path: Path):
    exe = tmp_path / "agy"
    log_path = tmp_path / "perm_answers.jsonl"
    exe.write_text(
        f"""#!/usr/bin/env python3
import json, sys, pathlib
log_path = pathlib.Path({str(log_path)!r})
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    msg = json.loads(line)
    m = msg.get("method")
    rid = msg.get("id")
    if m == "initialize":
        print(json.dumps({{"jsonrpc":"2.0","id":rid,"result":{{"protocolVersion":1,"agentInfo":{{"name":"Agy","version":"1"}}}}}}), flush=True)
    elif m == "session/list":
        print(json.dumps({{"jsonrpc":"2.0","id":rid,"result":{{"sessions":[]}}}}), flush=True)
    elif m == "session/new":
        print(json.dumps({{"jsonrpc":"2.0","id":rid,"result":{{"sessionId":"s1","modes":{{"currentModeId":"default"}}}}}}), flush=True)
    elif m == "session/prompt":
        # 1) command permission
        print(json.dumps({{"jsonrpc":"2.0","id":"acp-1","method":"session/request_permission","params":{{"sessionId":"s1","toolCall":{{"toolCallId":"tc1","name":"run_command","kind":"execute","args":{{"CommandLine":"ls"}}}},"options":[{{"optionId":"allow","kind":"allow_once"}},{{"optionId":"deny","kind":"reject_once"}}]}}}}), flush=True)
        # Wait for answer to acp-1 before asking edit
    elif rid == "acp-1" and "result" in msg:
        with log_path.open("a") as fh: fh.write(json.dumps(msg) + "\\n")
        # 2) same command again -> should be auto-answered by acceptForSession
        print(json.dumps({{"jsonrpc":"2.0","id":"acp-2","method":"session/request_permission","params":{{"sessionId":"s1","toolCall":{{"toolCallId":"tc2","name":"run_command","kind":"execute","args":{{"CommandLine":"pwd"}}}},"options":[{{"optionId":"allow","kind":"allow_once"}},{{"optionId":"deny","kind":"reject_once"}}]}}}}), flush=True)
    elif rid == "acp-2" and "result" in msg:
        with log_path.open("a") as fh: fh.write(json.dumps(msg) + "\\n")
        # 3) edit permission -> never cached, forwarded as fileChange
        print(json.dumps({{"jsonrpc":"2.0","id":"acp-3","method":"session/request_permission","params":{{"sessionId":"s1","toolCall":{{"toolCallId":"tc3","name":"edit_file","kind":"edit","locations":[{{"path":"/repo/one.md"}}]}},"options":[{{"optionId":"allow","kind":"allow_once"}},{{"optionId":"deny","kind":"reject_once"}}]}}}}), flush=True)
    elif rid == "acp-3" and "result" in msg:
        with log_path.open("a") as fh: fh.write(json.dumps(msg) + "\\n")
        print(json.dumps({{"jsonrpc":"2.0","id":100,"result":{{"stopReason":"end_turn"}}}}), flush=True)
""",
        encoding="utf-8",
    )
    # Fix prompt rid tracking in stub: echo prompt rid back at end
    exe.write_text(
        exe.read_text(encoding="utf-8").replace(
            'elif m == "session/prompt":',
            'elif m == "session/prompt":\n        prompt_rid = rid',
        ).replace(
            '"id":100,"result"',
            '"id":prompt_rid,"result"',
        ),
        encoding="utf-8",
    )
    _runnable(exe)

    received: list[dict] = []
    client = AgyAcpClient(executable=str(exe), cwd=tmp_path, on_message=received.append)
    try:
        client.start()
        sid = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "Go"}], "mayWrite": True})

        _wait_until(lambda: any(m.get("method") == "item/commandExecution/requestApproval" for m in received))
        cmd_req = next(m for m in received if m.get("method") == "item/commandExecution/requestApproval")
        assert cmd_req["params"]["command"] == "ls"
        client.respond(cmd_req["id"], {"decision": "acceptForSession"})

        # acp-2 was auto-granted without another item/commandExecution/requestApproval;
        # next forwarded request must be acp-3 as fileChange.
        _wait_until(lambda: any(m.get("method") == "item/fileChange/requestApproval" for m in received))
        edit_req = next(m for m in received if m.get("method") == "item/fileChange/requestApproval")
        assert edit_req["params"]["changes"] == [{"path": "/repo/one.md", "kind": "modify"}]
        client.respond(edit_req["id"], {"decision": "decline"})

        _wait_until(lambda: any(m.get("method") == "session/prompt/completed" for m in received))
        assert len([m for m in received if m.get("method") == "item/commandExecution/requestApproval"]) == 1

        answers = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert [a["result"]["outcome"]["optionId"] for a in answers] == ["allow", "allow", "deny"]
    finally:
        client.close()


def test_extract_json_text_handles_prose_wrappers_and_fences():
    fenced = 'Here are the alternatives:\n\n```json\n{"alternatives": [{"text": "Clean"}]}\n```\nHope this helps!'
    assert json.loads(_extract_json_text(fenced)) == {"alternatives": [{"text": "Clean"}]}

    bare_with_prose = 'Sure — {"ok": true, "count": 2} — done.'
    assert json.loads(_extract_json_text(bare_with_prose)) == {"ok": True, "count": 2}

    trailing_braces = 'Result: {"ok": true}\nNote: {placeholder} is optional.'
    assert json.loads(_extract_json_text(trailing_braces)) == {"ok": True}

    leading_braces = 'Use {template} -> {"alternatives": [{"text": "Fixed"}]}'
    assert json.loads(_extract_json_text(leading_braces)) == {"alternatives": [{"text": "Fixed"}]}

    raw_json = '{"ok": true}'
    assert _extract_json_text(raw_json) == '{"ok": true}'
