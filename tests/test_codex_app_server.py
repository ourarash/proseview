from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from proseview.codex_app_server import CodexAppServer, CodexAuthError, CodexProtocolError


def _runnable(path: Path) -> Path:
    """Return the path that will actually launch *path* on this platform.

    The stubs are Python scripts with a shebang, which POSIX honours once the
    execute bit is set. Windows honours neither and refuses them outright with
    "not a valid Win32 application", so there it gets a .cmd wrapper naming the
    running interpreter, and that is what the client is pointed at.
    """
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    if os.name != "nt":
        return path
    wrapper = path.with_suffix(".cmd")
    wrapper.write_text(
        f'@echo off\r\n"{sys.executable}" "{path}" %*\r\n', encoding="utf-8"
    )
    return wrapper


def _fake_codex(tmp_path: Path, *, authenticated: bool = True, malformed: bool = False) -> Path:
    path = tmp_path / "codex"
    script = f"""#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get('method')
    if method == 'initialize':
        print(json.dumps({{'id': msg['id'], 'result': {{'userAgent': 'fake/1', 'codexHome': '/fake', 'platformFamily': 'unix', 'platformOs': 'macos'}}}}), flush=True)
    elif method == 'initialized':
        pass
    elif method == 'account/read':
        account = {{'type': 'chatgpt', 'email': 'fake@example.test'}} if {authenticated!r} else None
        print(json.dumps({{'id': msg['id'], 'result': {{'account': account, 'requiresOpenaiAuth': True}}}}), flush=True)
    elif method == 'thread/start':
        print(json.dumps({{'id': msg['id'], 'result': {{'thread': {{'id': 'thread-1'}}}}}}), flush=True)
    elif method == 'turn/start':
        print(json.dumps({{'id': msg['id'], 'result': {{'turn': {{'id': 'turn-1', 'status': 'inProgress'}}}}}}), flush=True)
        if {malformed!r}:
            print('not json', flush=True)
        else:
            print(json.dumps({{'method': 'item/reasoning/summaryTextDelta', 'params': {{'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': 'Checking'}}}}), flush=True)
            print(json.dumps({{'method': 'turn/completed', 'params': {{'threadId': 'thread-1', 'turn': {{'id': 'turn-1', 'status': 'completed'}}}}}}), flush=True)
"""
    path.write_text(script, encoding="utf-8")
    return _runnable(path)


def test_client_initializes_checks_auth_and_dispatches_notifications(tmp_path: Path):
    executable = _fake_codex(tmp_path)
    received: list[dict] = []
    client = CodexAppServer(executable=str(executable), cwd=tmp_path, on_message=received.append)
    try:
        client.start()
        thread = client.request("thread/start", {"cwd": str(tmp_path)})
        turn = client.request("turn/start", {"threadId": thread["thread"]["id"], "input": []})
        deadline = time.monotonic() + 2
        while not any(m.get("method") == "turn/completed" for m in received) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.user_agent == "fake/1"
        assert turn["turn"]["id"] == "turn-1"
        assert [m["method"] for m in received] == [
            "item/reasoning/summaryTextDelta",
            "turn/completed",
        ]
    finally:
        client.close()
    assert client.alive is False


def test_client_rejects_missing_authentication(tmp_path: Path):
    client = CodexAppServer(executable=str(_fake_codex(tmp_path, authenticated=False)), cwd=tmp_path)
    with pytest.raises(CodexAuthError, match="sign in"):
        client.start()
    client.close()


def test_malformed_protocol_fails_pending_and_future_requests(tmp_path: Path):
    client = CodexAppServer(executable=str(_fake_codex(tmp_path, malformed=True)), cwd=tmp_path)
    client.start()
    client.request("thread/start", {"cwd": str(tmp_path)})
    client.request("turn/start", {"threadId": "thread-1", "input": []})
    deadline = time.monotonic() + 2
    while client.alive and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(CodexProtocolError, match="invalid JSON"):
        client.request("thread/start", {})
    client.close()


def test_server_requests_are_exposed_and_can_be_answered(tmp_path: Path):
    executable = tmp_path / "codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get('method')
    if method == 'initialize':
        print(json.dumps({'id': msg['id'], 'result': {'userAgent':'fake','codexHome':'/fake','platformFamily':'unix','platformOs':'linux'}}), flush=True)
    elif method == 'account/read':
        print(json.dumps({'id': msg['id'], 'result': {'account': {'type':'apiKey'}, 'requiresOpenaiAuth': True}}), flush=True)
    elif method == 'thread/start':
        print(json.dumps({'id': msg['id'], 'result': {'thread': {'id':'thread-1'}}}), flush=True)
        print(json.dumps({'id': 900, 'method':'item/fileChange/requestApproval', 'params': {'threadId':'thread-1','turnId':'turn-1','itemId':'item-1'}}), flush=True)
    elif msg.get('id') == 900 and 'result' in msg:
        print(json.dumps({'method':'serverRequest/resolved','params':{'threadId':'thread-1','requestId':900}}), flush=True)
""",
        encoding="utf-8",
    )
    executable = _runnable(executable)
    seen: list[dict] = []
    client = CodexAppServer(executable=str(executable), cwd=tmp_path, on_message=seen.append)
    try:
        client.start()
        client.request("thread/start", {})
        deadline = time.monotonic() + 2
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert seen[0]["method"] == "item/fileChange/requestApproval"
        client.respond(900, {"decision": "decline"})
    finally:
        client.close()


def test_generated_schema_capability_detection_requires_stable_discuss_protocol(tmp_path: Path):
    executable = tmp_path / "codex-schema"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1]) / 'v2'
out.mkdir(parents=True)
for name, body in {
    'ThreadStartParams.json': '{}',
    'ThreadReadParams.json': '{"includeTurns":true}',
    'TurnStartParams.json': '{"summary":true,"readableRoots":true}',
    'TurnInterruptParams.json': '{}',
    'CommandRequestApproval.json': '{}',
}.items():
    (out / name).write_text(body)
""",
        encoding="utf-8",
    )
    executable = _runnable(executable)
    client = CodexAppServer(executable=str(executable), cwd=tmp_path)
    capabilities = client.inspect_capabilities()
    assert capabilities["stable_discuss_protocol"] is True
    assert capabilities["reasoning_summary"] is True


def test_generated_schema_rejects_missing_required_capabilities(tmp_path: Path):
    executable = tmp_path / "codex-schema-old"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1]) / 'v2'
out.mkdir(parents=True)
(out / 'TurnStartParams.json').write_text('{}')
""",
        encoding="utf-8",
    )
    executable = _runnable(executable)
    client = CodexAppServer(executable=str(executable), cwd=tmp_path)
    with pytest.raises(CodexProtocolError, match="unsupported"):
        client.inspect_capabilities()


def test_stderr_diagnostics_never_retain_document_or_reasoning_text(tmp_path: Path):
    launcher = _fake_codex(tmp_path)
    # Patch the script, not the launcher: on Windows those are different files
    # and rewriting the wrapper leaves the stub silent.
    script = tmp_path / "codex"
    raw = script.read_text(encoding="utf-8")
    script.write_text(
        raw.replace("import json, sys", "import json, sys\nprint('PRIVATE DOCUMENT BODY AND RAW REASONING', file=sys.stderr, flush=True)"),
        encoding="utf-8",
    )
    client = CodexAppServer(executable=str(launcher), cwd=tmp_path)
    try:
        client.start()
        # Process startup is slower on Windows than the second this allowed.
        deadline = time.monotonic() + 10
        while not client._stderr and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client._stderr
        assert "PRIVATE DOCUMENT" not in str(client._stderr)
        assert "RAW REASONING" not in str(client._stderr)
    finally:
        client.close()
