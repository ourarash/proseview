"""Shared harness for the Proseview end-to-end suite.

Unlike the rest of ``tests/``, these tests start the real application: a
``python -m proseview`` subprocess serving a throwaway copy of
``fixtures/demo-repo``. Nothing here imports ``proseview`` in-process, so the
suite exercises the same boot path a user gets from the CLI.

Everything in this module is stdlib-only. The browser tier layers Playwright on
top of these same fixtures.
"""

from __future__ import annotations

import json
import os
import queue
import random
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REPO = REPO_ROOT / "fixtures" / "demo-repo"

#: How long to wait for the server subprocess to answer its first request.
BOOT_TIMEOUT = 30.0
#: Watch interval handed to the server. Low so live-reload tests stay quick.
WATCH_INTERVAL = 0.5

#: Scene the mutating tests edit. Small, has frontmatter, no annotations.
SCENE_REL = "ch01/01-opening.md"
#: Scene carrying inline TODO/NOTE comments (created by ``_seed_annotated_scene``).
ANNOTATED_SCENE_REL = "ch01/03-annotated.md"
#: Generated ~10k-word scene used by the large-file cases.
LARGE_SCENE_REL = "ch03/01-long-haul.md"

#: Printed by every stub agent so tests can recognise a real spawn.
AGENT_MARKER = "PROSEVIEW_FAKE_AGENT"


# ── repo construction ───────────────────────────────────────────────────────


def _seed_skills(root: Path) -> None:
    """Give the repo a ``skills/`` tree.

    ``fixtures/demo-repo`` has none, and ``generator._load_skills`` returns ``[]``
    for a missing directory -- which makes the template omit the Skills button
    entirely. Without this the selection-menu tests would silently assert
    against a control that was never rendered.

    Three skills, chosen to cover every branch of ``_load_skills``. Note the
    selection menu lists only ``snippet-`` prefixed skills, so the one carrying
    ``agents/openai.yaml`` -- the display-name / default-prompt path -- has to
    be a snippet for that path to be observable in the browser.
    """
    skills = root / "skills"

    # Scene skill: no snippet prefix, so it is absent from the selection menu.
    tighten = skills / "tighten-prose"
    tighten.mkdir(parents=True, exist_ok=True)
    (tighten / "SKILL.md").write_text(
        "---\nname: tighten-prose\n---\n\nRemove filler from the selected passage.\n",
        encoding="utf-8",
    )

    # Snippet skill whose label comes from openai.yaml, not the directory name.
    continuity = skills / "snippet-continuity"
    (continuity / "agents").mkdir(parents=True, exist_ok=True)
    (continuity / "SKILL.md").write_text(
        "---\nname: snippet-continuity\n---\n\nCheck the passage against the story bible.\n",
        encoding="utf-8",
    )
    (continuity / "agents" / "openai.yaml").write_text(
        "interface:\n"
        '  display_name: "Continuity Check"\n'
        '  short_description: "Flag contradictions with the story bible"\n'
        '  default_prompt: "Check this passage for continuity errors."\n',
        encoding="utf-8",
    )

    # Snippet skill with no openai.yaml: display name falls back to the name.
    snippet = skills / "snippet-sensory"
    snippet.mkdir(parents=True, exist_ok=True)
    (snippet / "SKILL.md").write_text(
        "---\nname: snippet-sensory\n---\n\nAdd one concrete sensory detail.\n",
        encoding="utf-8",
    )


def _seed_annotated_scene(root: Path) -> None:
    """A scene that already contains inline TODO/NOTE comments.

    The editor round-trip tests need a document where annotations are parsed as
    ProseMirror atom nodes, so they can prove a save doesn't degrade them back
    into literal ``<!-- ... -->`` text.
    """
    path = root / "manuscript" / ANNOTATED_SCENE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "title: Annotated Ledger\n"
        "chapter: Chapter 1\n"
        "status: revision\n"
        "characters:\n"
        "  - Rena\n"
        "  - Patel\n"
        "todos:\n"
        "  - Verify the safe's brand against chapter three\n"
        "---\n"
        "\n"
        "# Annotated Ledger\n"
        "\n"
        "<!-- TODO: Tighten this opening beat -->\n"
        "\n"
        "Patel arrived with the ledger already open, thumb wedged at a column of "
        "numbers that refused to reconcile. He set it on the counter without a word.\n"
        "\n"
        "<!-- NOTE[continuity]: Patel should not know about the safe yet -->\n"
        "\n"
        "Rena read the column twice. The second reading did not improve it. She "
        "found a pencil, crossed out a figure, and wrote a smaller one above it.\n"
        "\n"
        "The shop stayed *quiet* in the way a held breath is quiet.\n",
        encoding="utf-8",
    )


def _seed_large_scene(root: Path) -> int:
    """Generate a ~10k-word scene and return its word count.

    Deterministically seeded, with a wide enough vocabulary that MATTR/MTLD land
    in a plausible range rather than degenerating on repeated filler.
    """
    rng = random.Random(20260802)
    subjects = [
        "Rena", "Lowe", "Patel", "the ledger", "the pier boy", "the harbour master",
        "the dockhand", "the auditor", "the clerk", "the tide", "the river",
    ]
    verbs = [
        "counted", "questioned", "abandoned", "recovered", "measured", "doubted",
        "annotated", "misplaced", "reconciled", "defended", "postponed", "revisited",
    ]
    objects = [
        "the weekly total", "a column of figures", "the safe's dial", "a torn receipt",
        "the morning delivery", "an unsigned invoice", "the shop's account",
        "a promise from spring", "the last honest number", "a stack of manifests",
    ]
    codas = [
        "and said nothing afterward", "before the kettle boiled", "against her better sense",
        "while the market woke", "with the patience of a creditor", "twice, then once more",
        "as though it were arithmetic", "under a grey and unhelpful sky",
    ]

    paragraphs: list[str] = []
    words = 0
    index = 0
    while words < 10_000:
        sentences = []
        for _ in range(rng.randint(4, 7)):
            sentences.append(
                f"{rng.choice(subjects)} {rng.choice(verbs)} {rng.choice(objects)} "
                f"{rng.choice(codas)}."
            )
        para = " ".join(sentences)
        paragraphs.append(para)
        words += len(para.split())
        index += 1
        # Sprinkle a few annotations so the large-file round-trip has atoms to
        # preserve, not just prose.
        if index % 40 == 0:
            paragraphs.append(f"<!-- NOTE[question]: Does beat {index} earn its place? -->")

    body = "\n\n".join(paragraphs)
    path = root / "manuscript" / LARGE_SCENE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "title: Long Haul\n"
        "chapter: Chapter 3\n"
        "status: draft\n"
        "characters:\n"
        "  - Rena\n"
        "  - Patel\n"
        "---\n"
        "\n"
        "# Long Haul\n"
        "\n" + body + "\n",
        encoding="utf-8",
    )
    return words


def _build_repo(dest: Path) -> Path:
    """Copy the committed fixture into *dest* and enrich it for E2E use."""
    shutil.copytree(FIXTURE_REPO, dest, dirs_exist_ok=True)
    # The committed fixture is gitignored but a stale .proseview/server.json can
    # linger from a local run. Leaving it would let `proseview propose` resolve
    # to a dead server instead of ours.
    shutil.rmtree(dest / ".proseview", ignore_errors=True)
    _seed_skills(dest)
    _seed_annotated_scene(dest)
    _seed_large_scene(dest)
    scripts = dest / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "check_continuity.py").write_text(
        "def check_continuity(scene):\n    return bool(scene)\n",
        encoding="utf-8",
    )
    (scripts / "hostile-preview.md").write_text(
        "# Safe heading\n\n"
        "<img src=x onerror=\"window.__previewPwned = true\">\n\n"
        "[Unsafe link](javascript:window.__previewPwned=true)\n",
        encoding="utf-8",
    )
    private = dest / ".private"
    private.mkdir(exist_ok=True)
    (private / "token.txt").write_text("fixture secret\n", encoding="utf-8")
    return dest


# ── agent stubs ─────────────────────────────────────────────────────────────


def _write_agent_stubs(bin_dir: Path) -> Path:
    """Create fake ``codex`` / ``claude`` / ``gemini`` executables.

    The real agent handoff sends ``command: ["codex"]`` to ``/terminal-spawn``
    and then types the prompt into the PTY as keystrokes. A stub that announces
    itself, echoes its argv, and then echoes stdin lets a test prove both halves
    of that contract without the real tools installed.

    The trailing read loop matters: an agent that exits immediately would tear
    the session down before the browser finished typing the prompt.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("claude", "gemini"):
        script = bin_dir / name
        script.write_text(
            "#!/bin/sh\n"
            f'echo "{AGENT_MARKER} {name} argv:$*"\n'
            "while IFS= read -r line; do\n"
            '  echo "STDIN:$line"\n'
            "done\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    codex = bin_dir / "codex"
    codex.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys

if len(sys.argv) >= 3 and sys.argv[1:3] == ['app-server', 'generate-json-schema']:
    out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1]) / 'v2'
    out.mkdir(parents=True, exist_ok=True)
    schemas = {
        'ThreadStartParams.json': '{}',
        'ThreadReadParams.json': '{"includeTurns":true}',
        'TurnStartParams.json': '{"summary":true,"readableRoots":true}',
        'TurnInterruptParams.json': '{}',
        'CommandExecutionRequestApproval.json': '{}',
        'CommandExecutionRequestApprovalResponse.json': '{"enum":["accept","acceptForSession","decline","cancel"]}',
        'FileChangeRequestApprovalResponse.json': '{"enum":["accept","acceptForSession","decline","cancel"]}',
        'PermissionsRequestApprovalResponse.json': '{"permissions":true}',
    }
    for name, body in schemas.items():
        (out / name).write_text(body, encoding='utf-8')
    raise SystemExit(0)

if len(sys.argv) < 2 or sys.argv[1] != 'app-server':
    print('PROSEVIEW_FAKE_AGENT codex argv:' + ' '.join(sys.argv[1:]), flush=True)
    for line in sys.stdin:
        print('STDIN:' + line.rstrip('\\n'), flush=True)
    raise SystemExit(0)

threads = {}
next_thread = 0
next_turn = 0
pending = {}
record = pathlib.Path(os.environ['HOME']) / 'fake-codex-received.jsonl'

def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}
    if method == 'initialize':
        emit({'id': request_id, 'result': {'userAgent': 'proseview-fake-codex/1', 'codexHome': '/isolated', 'platformFamily': 'unix', 'platformOs': 'test'}})
    elif method == 'initialized':
        continue
    elif method == 'account/read':
        emit({'id': request_id, 'result': {'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True}})
    elif method == 'thread/read':
        thread = threads.get(params.get('threadId'))
        if thread is None:
            emit({'id': request_id, 'error': {'code': -32004, 'message': 'thread not found'}})
        else:
            emit({'id': request_id, 'result': {'thread': thread}})
    elif method == 'thread/start':
        next_thread += 1
        thread_id = f'thread-{next_thread}'
        threads[thread_id] = {'id': thread_id, 'turns': []}
        emit({'id': request_id, 'result': {'thread': threads[thread_id]}})
    elif method == 'turn/start':
        next_turn += 1
        turn_id = f'turn-{next_turn}'
        thread_id = params['threadId']
        prompt = params['input'][0]['text']
        if thread_id not in threads:
            emit({'id': request_id, 'error': {'code': -32004, 'message': 'thread not found: ' + thread_id}})
            continue
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'threadId': thread_id, 'turnId': turn_id, 'params': params}) + '\\n')
        turn = {'id': turn_id, 'status': 'inProgress', 'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': prompt}]}]}
        threads.setdefault(thread_id, {'id': thread_id, 'turns': []})['turns'].append(turn)
        emit({'id': request_id, 'result': {'turn': {'id': turn_id, 'status': 'inProgress'}}})
        if 'CRASH_PROCESS' in prompt:
            os._exit(7)
        emit({'method': 'turn/started', 'params': {'threadId': thread_id, 'turn': {'id': turn_id, 'status': 'inProgress'}}})
        emit({'method': 'item/reasoning/textDelta', 'params': {'threadId': thread_id, 'turnId': turn_id, 'delta': 'PRIVATE RAW REASONING'}})
        emit({'method': 'item/reasoning/summaryTextDelta', 'params': {'threadId': thread_id, 'turnId': turn_id, 'delta': 'Reviewing the attached document'}})
        emit({'method': 'turn/plan/updated', 'params': {'threadId': thread_id, 'turnId': turn_id, 'plan': [{'step': 'Read context', 'status': 'completed'}, {'step': 'Answer question', 'status': 'inProgress'}]}})
        emit({'method': 'item/started', 'params': {'threadId': thread_id, 'turnId': turn_id, 'item': {'id': 'tool-' + turn_id, 'type': 'commandExecution', 'command': 'printf inspect', 'cwd': os.getcwd(), 'status': 'inProgress'}}})
        if 'HOLD_FOR_STOP' in prompt:
            continue
        if 'REQUEST_APPROVAL' in prompt:
            approval_id = 9000 + next_turn
            pending[approval_id] = (thread_id, turn_id, turn)
            emit({'id': approval_id, 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': thread_id, 'turnId': turn_id, 'itemId': 'tool-' + turn_id, 'command': 'printf approved', 'cwd': os.getcwd(), 'reason': 'Test approval', 'availableDecisions': ['accept', 'acceptForSession', 'decline', 'cancel']}})
            continue
        answer = 'Fake answer for ' + turn_id + ': **safe** [link](https://example.test) [unsafe](javascript:alert(1)) <script>hostile()</script>'
        emit({'method': 'item/agentMessage/delta', 'params': {'threadId': thread_id, 'turnId': turn_id, 'itemId': 'answer-' + turn_id, 'delta': answer[:24]}})
        emit({'method': 'item/completed', 'params': {'threadId': thread_id, 'turnId': turn_id, 'item': {'id': 'answer-' + turn_id, 'type': 'agentMessage', 'phase': 'final_answer', 'text': answer}}})
        turn.update({'status': 'completed', 'items': turn['items'] + [{'type': 'agentMessage', 'phase': 'final_answer', 'text': answer}]})
        emit({'method': 'turn/completed', 'params': {'threadId': thread_id, 'turn': {'id': turn_id, 'status': 'completed'}}})
        if 'FORGET_THREAD_AFTER_TURN' in prompt:
            threads.pop(thread_id, None)
    elif method == 'turn/interrupt':
        emit({'id': request_id, 'result': {}})
        emit({'method': 'turn/completed', 'params': {'threadId': params['threadId'], 'turn': {'id': params['turnId'], 'status': 'interrupted'}}})
    elif request_id in pending and ('result' in message or 'error' in message):
        thread_id, turn_id, turn = pending.pop(request_id)
        decision = (message.get('result') or {}).get('decision', 'decline')
        answer = 'Approval resolved: ' + decision
        emit({'method': 'item/completed', 'params': {'threadId': thread_id, 'turnId': turn_id, 'item': {'id': 'answer-' + turn_id, 'type': 'agentMessage', 'phase': 'final_answer', 'text': answer}}})
        turn.update({'status': 'completed', 'items': turn['items'] + [{'type': 'agentMessage', 'phase': 'final_answer', 'text': answer}]})
        emit({'method': 'turn/completed', 'params': {'threadId': thread_id, 'turn': {'id': turn_id, 'status': 'completed'}}})
""",
        encoding="utf-8",
    )
    codex.chmod(codex.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


# ── HTTP / SSE client ───────────────────────────────────────────────────────


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class SseStream:
    """Reader over a text/event-stream response.

    The server holds these connections open and emits heartbeats, so reads have
    to be pumped on a background thread to stay cancellable.
    """

    def __init__(self, resp: Any) -> None:
        self._resp = resp
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        event_type = "message"
        event_id: int | None = None
        event_data: list[str] = []
        try:
            for raw in self._resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("data: "):
                    data = line[len("data: "):]
                    event_data.append(data)
                    self._queue.put(data)
                elif line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("id: "):
                    try:
                        event_id = int(line[len("id: "):])
                    except ValueError:
                        event_id = None
                elif not line and event_data:
                    self._event_queue.put({"id": event_id, "type": event_type, "data": "\n".join(event_data)})
                    event_type = "message"
                    event_id = None
                    event_data = []
        except Exception:  # connection closed underneath us -- expected on teardown
            pass
        finally:
            self._queue.put(None)
            self._event_queue.put(None)

    def next(self, timeout: float = 5.0) -> str:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"no SSE frame within {timeout}s") from None
        if item is None:
            raise AssertionError("SSE stream closed")
        return item

    def wait_for(self, predicate: Callable[[str], bool], timeout: float = 10.0) -> str:
        """Return the first frame satisfying *predicate*, ignoring heartbeats."""
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                frame = self.next(timeout=remaining)
            except AssertionError:
                break
            seen.append(frame)
            if predicate(frame):
                return frame
        raise AssertionError(f"no matching SSE frame within {timeout}s; saw {seen!r}")

    def next_event(self, timeout: float = 5.0) -> dict[str, Any]:
        try:
            event = self._event_queue.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"no complete SSE event within {timeout}s") from None
        if event is None:
            raise AssertionError("SSE stream closed")
        return event

    def close(self) -> None:
        """Tear the stream down without waiting for the server.

        The pump thread is parked in a blocking ``readline`` and the server only
        writes again on its heartbeat -- 5s for terminal output, 15s for
        ``/events``. Plain ``close()`` would inherit that latency on every test.
        Shutting the socket down first makes the pending read fail immediately.
        """
        try:
            self._resp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self._resp.close()
        except Exception:
            pass


class ProseviewServer:
    """Handle on a running ``python -m proseview`` subprocess."""

    def __init__(self, root: Path, port: int, proc: subprocess.Popen, env: dict[str, str]):
        self.root = root
        self.port = port
        self.proc = proc
        self.env = env
        self.base_url = f"http://localhost:{port}"

    # -- paths -------------------------------------------------------------

    def scene_path(self, rel: str = SCENE_REL) -> Path:
        return self.root / "manuscript" / rel

    def url(self, path: str) -> str:
        return self.base_url + path

    # -- HTTP --------------------------------------------------------------

    def get(self, path: str, timeout: float = 30.0) -> Response:
        req = urllib.request.Request(self.url(path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read(), dict(exc.headers or {}))

    def get_json(self, path: str, timeout: float = 30.0) -> Any:
        return self.get(path, timeout=timeout).json()

    def post_json(self, path: str, payload: dict, timeout: float = 30.0, headers: dict[str, str] | None = None) -> Response:
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = urllib.request.Request(
            self.url(path),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read(), dict(exc.headers or {}))

    @contextmanager
    def sse(self, path: str = "/events", headers: dict[str, str] | None = None) -> Iterator[SseStream]:
        request = urllib.request.Request(self.url(path), headers=headers or {})
        resp = urllib.request.urlopen(request, timeout=30)
        stream = SseStream(resp)
        try:
            yield stream
        finally:
            stream.close()

    # -- CLI ---------------------------------------------------------------

    def cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run the real ``proseview`` CLI against this server's repo.

        The CLI locates the server itself through ``.proseview/server.json``, so
        this exercises the same discovery path an agent would use.
        """
        proc = subprocess.run(
            [sys.executable, "-m", "proseview", *args],
            cwd=str(self.root),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"proseview {' '.join(args)} failed ({proc.returncode})\n"
                f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
            )
        return proc

    # -- scene helpers -----------------------------------------------------

    def scene_meta(self, rel: str = SCENE_REL) -> dict:
        return self.get_json("/data.json")["meta"][rel]

    def save_scene(self, content: str, rel: str = SCENE_REL, mtime: float | None = None) -> Response:
        meta = self.scene_meta(rel)
        return self.post_json("/save-scene", {
            "abs_path": meta["abs_path"],
            "content": content,
            "open_mtime": meta["mtime"] if mtime is None else mtime,
        })


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        return int(sock.getsockname()[1])


def _server_env(bin_dir: Path, home: Path) -> dict[str, str]:
    """Environment for the server subprocess.

    Two entries carry real weight:

    ``SHELL`` -- ``spawn_terminal`` falls back to ``/bin/zsh`` when it is unset,
    which does not exist on the Ubuntu CI image.

    ``HOME`` -- terminal commands are wrapped in ``$SHELL -l -c``. A *login*
    shell sources the developer's real profile, which routinely rewrites PATH
    and would shadow our agent stubs with whatever is actually installed.
    Pointing HOME at an empty directory keeps the spawn hermetic.
    """
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(home)
    env["SHELL"] = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("PYTHONWARNINGS", None)
    return env


def _start_server(root: Path, bin_dir: Path, home: Path) -> ProseviewServer:
    port = _free_port()
    env = _server_env(bin_dir, home)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "proseview",
            "--root", str(root),
            "--port", str(port),
            "--interval", str(WATCH_INTERVAL),
            "--no-open",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    server = ProseviewServer(root, port, proc, env)

    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"server exited during boot ({proc.returncode}):\n{output}")
        try:
            if server.get("/", timeout=2).status == 200:
                return server
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError(f"server did not answer within {BOOT_TIMEOUT}s")


def _stop_server(server: ProseviewServer) -> None:
    """Stop the server the way a user does: Ctrl-C.

    ``serve()`` only unwinds on ``KeyboardInterrupt``; a bare ``SIGTERM`` skips
    the ``finally`` that removes ``.proseview/server.json``, leaving a runtime
    file pointing at a dead port. Sending SIGINT exercises the documented
    shutdown path and leaves the repo clean.
    """
    proc = server.proc
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def agent_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_agent_stubs(tmp_path_factory.mktemp("agent-bin"))


@pytest.fixture(scope="session")
def fake_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("fake-home")


@pytest.fixture(scope="session")
def shared_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One repo copy shared by read-only tests."""
    return _build_repo(tmp_path_factory.mktemp("shared-repo") / "novel")


@pytest.fixture(scope="session")
def shared_server(shared_repo: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    """Session-scoped server. Use only for tests that do not mutate the repo."""
    server = _start_server(shared_repo, agent_bin, fake_home)
    try:
        yield server
    finally:
        _stop_server(server)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh repo copy, isolated per test."""
    return _build_repo(tmp_path / "novel")


@pytest.fixture
def server(repo: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    """Function-scoped server for tests that write to the repo."""
    srv = _start_server(repo, agent_bin, fake_home)
    try:
        yield srv
    finally:
        _stop_server(srv)
        # serve() removes its runtime file on clean shutdown; a leftover file
        # means teardown did not run and later CLI calls could target a corpse.
        assert not (repo / ".proseview" / "server.json").exists(), \
            "server.json survived shutdown"
