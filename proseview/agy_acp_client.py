"""Synchronous ACP (Agent Client Protocol) client for ``agy acp --stdio``.

This is the sibling of :mod:`proseview.codex_app_server` and
:mod:`proseview.claude_agent_client`. It presents the same synchronous surface
that :class:`~proseview.discuss.DiscussManager` already drives — ``start``,
``request``, ``respond``, ``respond_error``, ``notify``, ``close``,
``inspect_capabilities``, ``probe_capabilities`` — and carries its own
translator :func:`sanitize_agy_message` into Prosview's event vocabulary.

Structurally, ``agy acp --stdio`` behaves much like ``codex app-server``:

* **Multiplexed sessions over one stdio process.** ``session/new`` creates a
  persistent session ID (which maps 1:1 to Prosview's ``threadId``), while
  ``session/prompt`` runs as a blocking JSON-RPC request per turn on a worker
  thread so ``turn/start`` can return immediately.
* **Out-of-band permission gating.** In ``default`` mode, ``agy acp`` asks
  ``session/request_permission`` before mutating files or running commands.
  This client translates ``edit`` permissions into Prosview's
  ``item/fileChange/requestApproval`` (so reading passes stay blocked and
  writable turns capture before-images for diff review) and ``execute``/other
  gated tools into ``item/commandExecution/requestApproval``.
* **Raw reasoning dropped at the seam.** ``agent_thought_chunk`` updates are
  never forwarded; only safe progress and visible answer chunks pass through.
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

APPROVAL_DECISIONS = ["accept", "acceptForSession", "decline", "cancel"]
APPROVAL_METHODS = {
    "command": "item/commandExecution/requestApproval",
    "fileChange": "item/fileChange/requestApproval",
}

WRITE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "replace_file_content",
    "multi_replace_file_content",
})
WEB_TOOLS = frozenset({"search_web", "read_url_content", "fetch_url", "web_search", "web_fetch"})
EFFORT_LADDER = ("low", "medium", "high", "xhigh", "max", "ultra")
EFFORT_DESCRIPTIONS = {
    "low": "Fast answers with little deliberation",
    "medium": "Balanced speed and reasoning depth",
    "high": "Deeper reasoning for tangled questions",
    "xhigh": "Extended reasoning for hard problems",
    "max": "Maximum reasoning depth",
    "ultra": "Maximum reasoning depth",
}

LOGIN_COMMAND = "agy"
LOGIN_EXPIRED = "Your Agy login has expired or is missing. Sign in with `agy`, then ask again."
_AUTH_FAILURE_MARKERS = (
    "authentication required",
    "not authenticated",
    "oauth",
    "login required",
    "please sign in",
)

DEFAULT_REQUEST_TIMEOUT = 20.0
TURN_START_TIMEOUT = 60.0
SESSION_NEW_TIMEOUT = 30.0
SESSION_LOAD_TIMEOUT = 60.0
MODEL_DEFAULT_SOURCE = "Agy CLI settings (~/.gemini/antigravity-cli/settings.json)"

_DEFAULT_TIMEOUT = object()
_VARIANT_SUFFIX_RE = re.compile(r"^(?P<base>.+)-(?P<effort>low|medium|high|xhigh|max|ultra)$")


class AgyError(RuntimeError):
    pass


class AgyUnavailableError(AgyError):
    pass


class AgyAuthError(AgyError):
    pass


class AgyProtocolError(AgyError):
    pass


class AgyRequestError(AgyError):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _bounded(value: Any, limit: int = 524_288) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "\n… output truncated by Prosview …"


def _extract_json_text(raw: str) -> str:
    """Best-effort extraction of a JSON object from a structured-turn reply."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        json.loads(text)
        return text
    except ValueError:
        pass
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE):
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            pass
    decoder = json.JSONDecoder()
    idx = 0
    while (pos := text.find("{", idx)) != -1:
        try:
            obj, end = decoder.raw_decode(text, pos)
            if isinstance(obj, dict):
                return text[pos:end]
        except ValueError:
            pass
        idx = pos + 1
    return text


def _is_auth_error(message: Any, code: int | None = None) -> bool:
    lowered = str(message or "").lower()
    if any(marker in lowered for marker in _AUTH_FAILURE_MARKERS):
        return True
    return code == -32000 and "auth" in lowered


def _is_missing_session_error(message: Any, code: int | None = None) -> bool:
    lowered = str(message or "").lower()
    return code == -32004 or "not found" in lowered or "unknown session" in lowered


def _extract_tool_paths(tool_call: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        val = str(raw or "").strip()
        if val and val not in seen:
            seen.add(val)
            paths.append(val)

    for loc in tool_call.get("locations") or []:
        if isinstance(loc, dict):
            add(loc.get("path"))
    for item in tool_call.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "diff":
            add(item.get("path"))
    for key in ("args", "rawInput"):
        args = tool_call.get(key)
        if isinstance(args, dict):
            for field in ("Path", "TargetFile", "path", "file_path", "DirectoryPath"):
                add(args.get(field))
    return paths


def _extract_tool_output(update: dict[str, Any]) -> str:
    raw = update.get("rawOutput")
    if isinstance(raw, str) and raw:
        return _bounded(raw)
    if isinstance(raw, dict):
        for key in ("output", "stdout", "text", "content", "error"):
            if raw.get(key):
                return _bounded(raw[key])
    parts: list[str] = []
    for item in update.get("content") or []:
        if isinstance(item, dict):
            if item.get("type") == "content" and isinstance(item.get("content"), dict):
                text = item["content"].get("text")
                if text:
                    parts.append(str(text))
            elif item.get("text"):
                parts.append(str(item["text"]))
    return _bounded("\n".join(parts)) if parts else ""


def _acp_activity_kind(tool_name: str, acp_kind: str) -> str:
    if acp_kind == "execute" or tool_name == "run_command":
        return "commandExecution"
    if acp_kind == "edit" or tool_name in WRITE_TOOLS:
        return "fileChange"
    if tool_name in WEB_TOOLS or acp_kind == "fetch":
        return "webSearch"
    if tool_name.startswith("mcp__"):
        return "mcpToolCall"
    return "dynamicToolCall"


def _acp_activity_status(status: Any, default: str = "inProgress") -> str:
    lowered = str(status or "").strip().lower()
    if lowered in {"completed", "done"}:
        return "completed"
    if lowered in {"failed", "error", "cancelled", "denied"}:
        return "failed"
    if lowered in {"pending", "in_progress", "inprogress", "running"}:
        return "inProgress"
    return default


def _tool_command_detail(tool_name: str, args: dict[str, Any], title: str = "") -> str:
    return (
        str(args.get("CommandLine") or args.get("command") or "").strip()
        or (f"Search the web for “{args.get('query')}”" if args.get("query") else "")
        or (f"Open {args.get('Url') or args.get('url')}" if (args.get("Url") or args.get("url")) else "")
        or title
        or tool_name
    )


def sanitize_agy_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate one ACP notification into Prosview's event vocabulary.

    The sibling of :func:`proseview.discuss.sanitize_agent_message` and
    :func:`proseview.claude_agent_client.sanitize_claude_message`, emitting
    the exact same vocabulary:

        progress.delta, response.delta, response.completed, plan.updated,
        turn.started, turn.completed, activity.updated, warning, error

    Raw reasoning (``agent_thought_chunk``) is dropped unconditionally so it
    never reaches the browser projection.
    """
    method = str(message.get("method") or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    thread_id = params.get("threadId") or params.get("sessionId")
    common = {"thread_id": thread_id, "turn_id": params.get("turnId")}

    if method == "session/update":
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        kind = str(update.get("sessionUpdate") or "")
        if kind == "agent_thought_chunk":
            return []
        if kind == "agent_message_chunk":
            content = update.get("content") if isinstance(update.get("content"), dict) else {}
            if content.get("type") == "text" or "text" in content:
                return [{
                    "type": "response.delta",
                    **common,
                    "item_id": update.get("itemId"),
                    "text": _bounded(content.get("text"), 65_536),
                }]
            return []
        if kind in {"tool_call", "tool_call_update"}:
            tool_name = str(update.get("name") or "")
            acp_kind = str(update.get("kind") or "")
            args = update.get("args") if isinstance(update.get("args"), dict) else (
                update.get("rawInput") if isinstance(update.get("rawInput"), dict) else {}
            )
            activity_kind = _acp_activity_kind(tool_name, acp_kind)
            activity: dict[str, Any] = {
                "id": update.get("toolCallId"),
                "kind": activity_kind,
                "status": _acp_activity_status(update.get("status")),
            }
            output = _extract_tool_output(update)
            if activity_kind == "commandExecution":
                activity.update(
                    command=_bounded(_tool_command_detail(tool_name, args, str(update.get("title") or "")), 4000),
                    cwd=_bounded(args.get("Cwd") or args.get("cwd") or "", 2000),
                    output=output,
                )
            elif activity_kind == "fileChange":
                activity["changes"] = [
                    {"path": _bounded(path, 2000), "kind": "modify"}
                    for path in _extract_tool_paths(update)
                ]
            elif activity_kind == "webSearch":
                activity["query"] = _bounded(args.get("query") or args.get("Url") or args.get("url") or "", 4000)
            else:
                paths = _extract_tool_paths(update)
                activity.update(
                    tool=_bounded(tool_name, 1000),
                    path=_bounded(paths[0] if paths else "", 2000),
                    pattern=_bounded(args.get("Query") or args.get("Pattern") or args.get("pattern") or "", 1000),
                    output=output,
                )
            return [{"type": "activity.updated", **common, "activity": activity}]
        if kind == "plan":
            plan = []
            for row in update.get("entries") or []:
                if isinstance(row, dict):
                    plan.append({
                        "step": _bounded(row.get("content") or row.get("step"), 2000),
                        "status": row.get("status"),
                    })
            return [{"type": "plan.updated", **common, "plan": plan, "explanation": ""}]
        return []

    if method == "session/progress":
        return [{"type": "progress.delta", **common, "text": _bounded(params.get("text"))}]
    if method == "session/assistant_message":
        return [{
            "type": "response.completed",
            **common,
            "item_id": params.get("itemId"),
            "phase": params.get("phase") or "final_answer",
            "text": _bounded(params.get("text"), 524_288),
        }]
    if method == "session/prompt/started":
        return [{"type": "turn.started", **common, "status": "inProgress", "error": ""}]
    if method in {"session/prompt/completed", "turn/completed"}:
        return [{
            "type": "turn.completed",
            **common,
            "status": params.get("status") or "completed",
            "error": _bounded(params.get("error")),
        }]
    if method == "session/warning":
        return [{"type": "warning", **common, "message": _bounded(params.get("message"))}]
    if method == "session/error":
        event = {"type": "error", **common, "message": _bounded(params.get("message"))}
        if params.get("command"):
            event["command"] = _bounded(params.get("command"), 1000)
        return [event]
    return []


class _Session:
    """One ACP session, standing in for one Discuss thread."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.thread_params: dict[str, Any] = {}
        self.turn_id: str = ""
        self.may_write: bool = False
        self.busy: bool = False
        self.cancel_requested: bool = False
        self.model: str = ""
        self.effort: str = ""
        self.session_grants: set[str] = set()
        self.text_parts: list[str] = []
        self.had_tool_since_text: bool = False
        self.expects_structured: bool = False
        self.item_seq: int = 0

    def next_item_id(self) -> str:
        self.item_seq += 1
        return f"agy-item-{self.turn_id}-{self.item_seq}"


class AgyAcpClient:
    """Synchronous JSON-RPC client for ``agy acp --stdio``."""

    translate = staticmethod(sanitize_agy_message)

    def __init__(
        self,
        *,
        executable: str | None = None,
        cwd: Path | str,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_failure: Callable[[BaseException], None] | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.executable = executable
        self.cwd = str(Path(cwd).resolve())
        self.on_message = on_message or (lambda _message: None)
        self.on_failure = on_failure or (lambda _error: None)
        self.request_timeout = request_timeout
        self.user_agent = ""
        self.capabilities: dict[str, Any] = {}
        self._agent_capabilities: dict[str, Any] = {}
        self._supports_system_prompt_append = False

        self._proc: subprocess.Popen[str] | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._next_id = 1
        self._fatal: BaseException | None = None
        self._closed = False
        self._stderr: deque[str] = deque(maxlen=50)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._outbound: queue.Queue[dict[str, Any] | None] = queue.Queue()

        self._sessions: dict[str, _Session] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._replay_buffers: dict[str, list[dict[str, Any]]] = {}

        # Cached model metadata populated from session/new or session/resume.
        self._raw_models: list[dict[str, Any]] = []
        self._raw_config_options: list[dict[str, Any]] = []
        self._current_model_id: str = ""
        self._variant_ids: set[str] = set()

    @property
    def alive(self) -> bool:
        return (
            not self._closed
            and self._proc is not None
            and self._proc.poll() is None
            and self._fatal is None
        )

    # --- capabilities & lifecycle ------------------------------------------

    def inspect_capabilities(self) -> dict[str, Any]:
        """Verify that ``agy`` is installed and advertise transport capabilities."""
        executable = self.executable or shutil.which("agy")
        if not executable:
            raise AgyUnavailableError("Agy CLI is not installed or is not on PATH")
        self.capabilities = {
            "schema_generation": False,
            "reasoning_summary": False,
            "restricted_read_access": True,
            "thread_fork": False,
            "stable_discuss_protocol": True,
            "approval_decisions": {
                "command": list(APPROVAL_DECISIONS),
                "network": list(APPROVAL_DECISIONS),
                "fileChange": list(APPROVAL_DECISIONS),
                "permissions": [],
            },
        }
        return dict(self.capabilities)

    def probe_capabilities(self) -> dict[str, Any]:
        self.capabilities.setdefault("stable_discuss_protocol", True)
        return dict(self.capabilities)

    def start(self) -> None:
        with self._start_lock:
            if self.alive:
                return
            if self._closed:
                raise AgyUnavailableError("Agy client is closed")
            executable = self.executable or shutil.which("agy")
            if not executable:
                raise AgyUnavailableError("Agy CLI is not installed or is not on PATH")
            self._fatal = None
            try:
                self._proc = subprocess.Popen(
                    [executable, "acp", "--stdio"],
                    cwd=self.cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )
            except OSError as exc:
                raise AgyUnavailableError(f"Could not start Agy ACP server: {exc}") from exc

            self._outbound = queue.Queue()
            self._reader = threading.Thread(target=self._read_loop, name="proseview-agy-reader", daemon=True)
            self._stderr_reader = threading.Thread(target=self._stderr_loop, name="proseview-agy-stderr", daemon=True)
            self._dispatch_thread = threading.Thread(
                target=self._dispatch_loop, name="proseview-agy-dispatch", daemon=True
            )
            self._reader.start()
            self._stderr_reader.start()
            self._dispatch_thread.start()

            try:
                initialized = self._acp_request(
                    "initialize",
                    {
                        "protocolVersion": 1,
                        "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}},
                    },
                    allow_during_init=True,
                )
                info = initialized.get("agentInfo") if isinstance(initialized.get("agentInfo"), dict) else {}
                name = str(info.get("name") or "Antigravity ACP Server")
                version = str(info.get("version") or "").strip()
                self.user_agent = f"{name}/{version}" if version else name
                caps = initialized.get("agentCapabilities")
                self._agent_capabilities = caps if isinstance(caps, dict) else {}
                meta = self._agent_capabilities.get("_meta")
                antigravity_meta = meta.get("antigravity") if isinstance(meta, dict) else {}
                sys_prompt_meta = antigravity_meta.get("systemPrompt") if isinstance(antigravity_meta, dict) else {}
                self._supports_system_prompt_append = bool(
                    isinstance(sys_prompt_meta, dict) and sys_prompt_meta.get("append")
                )
                # Verify existing agy auth without creating an empty session.
                try:
                    self._acp_request("session/list", {"cwd": self.cwd})
                except AgyRequestError as exc:
                    if _is_auth_error(exc, exc.code):
                        raise AgyAuthError(
                            "Agy is not authenticated; sign in with `agy` in a terminal and try again"
                        ) from exc
                    if exc.code == -32601:
                        # Older/fake server without session/list: let session/new check auth.
                        pass
                    else:
                        raise
            except BaseException:
                self.close()
                raise

    # --- low-level ACP JSON-RPC --------------------------------------------

    def _acp_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: Any = _DEFAULT_TIMEOUT,
        allow_during_init: bool = False,
    ) -> dict[str, Any]:
        if not allow_during_init and not self.alive:
            if self._fatal is not None:
                raise self._fatal
            raise AgyUnavailableError("Agy ACP server is not running")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            wait_budget = self.request_timeout if timeout is _DEFAULT_TIMEOUT else timeout
            try:
                response = response_queue.get(timeout=wait_budget)
            except queue.Empty as exc:
                raise AgyProtocolError(f"Agy ACP request timed out: {method}") from exc
            if isinstance(response, BaseException):
                raise response
            if isinstance(response.get("error"), dict):
                error = response["error"]
                code = error.get("code")
                msg = str(error.get("message") or "Agy ACP request failed")
                raise AgyRequestError(msg, code=code if isinstance(code, int) else None)
            result = response.get("result")
            if result is None:
                return {}
            if not isinstance(result, dict):
                raise AgyProtocolError(f"Agy ACP returned an invalid result for {method}")
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _acp_notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _acp_respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            if self._fatal is not None:
                raise self._fatal
            raise AgyUnavailableError("Agy ACP server is not running")
        line = json.dumps(message, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(line)
                proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            error = AgyProtocolError("Agy ACP connection closed")
            self._fail(error)
            raise error from exc

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    message = json.loads(stripped)
                except (ValueError, TypeError):
                    self._fail(AgyProtocolError("Agy ACP server emitted invalid JSON"))
                    return
                if not isinstance(message, dict):
                    self._fail(AgyProtocolError("Agy ACP server emitted an invalid message"))
                    return
                request_id = message.get("id")
                if request_id is not None and "method" not in message:
                    with self._pending_lock:
                        pending = self._pending.get(request_id)
                    if pending is not None:
                        try:
                            pending.put_nowait(message)
                        except queue.Full:
                            pass
                    continue
                self._handle_inbound(message)
        finally:
            if self._fatal is None and self._proc is proc and not self._closed:
                detail = "exited unexpectedly" if proc.poll() is not None else "connection closed unexpectedly"
                self._fail(AgyProtocolError(f"Agy ACP server {detail}"))

    def _dispatch_loop(self) -> None:
        while True:
            message = self._outbound.get()
            if message is None:
                return
            try:
                self.on_message(message)
            except Exception:
                continue

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        self._outbound.put({"method": method, "params": params})

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for _raw in proc.stderr:
            self._stderr.append("Agy emitted stderr; content suppressed by Prosview")

    def _fail(self, error: BaseException) -> None:
        first = self._fatal is None
        self._fatal = error
        with self._pending_lock:
            queues = list(self._pending.values())
        for pending in queues:
            try:
                pending.put_nowait(error)
            except queue.Full:
                pass
        if first:
            try:
                self.on_failure(error)
            except Exception:
                pass

    # --- inbound ACP routing -----------------------------------------------

    def _handle_inbound(self, message: dict[str, Any]) -> None:
        method = str(message.get("method") or "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}

        if message.get("id") is not None and method == "session/request_permission":
            self._handle_permission_request(message["id"], params)
            return
        if message.get("id") is not None and method:
            # Unknown server->client RPC request; reject cleanly so ACP never hangs.
            try:
                self._send({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"Unsupported ACP client method: {method}"},
                })
            except AgyError:
                pass
            return

        if method == "session/update":
            session_id = str(params.get("sessionId") or "")
            with self._state_lock:
                replay_buf = self._replay_buffers.get(session_id)
                if replay_buf is not None:
                    replay_buf.append(message)
                    return
                session = self._sessions.get(session_id)
                turn_id = session.turn_id if session else ""
                suppress_chunk = False
                update = params.get("update") if isinstance(params.get("update"), dict) else {}
                ut = str(update.get("sessionUpdate") or "")
                if session and turn_id:
                    if ut == "agent_message_chunk":
                        content = update.get("content") if isinstance(update.get("content"), dict) else {}
                        chunk = str(content.get("text") or "")
                        if chunk:
                            if session.had_tool_since_text and session.text_parts:
                                commentary = "".join(session.text_parts).strip()
                                session.text_parts.clear()
                                session.had_tool_since_text = False
                                if commentary and not session.expects_structured:
                                    self._emit("session/assistant_message", {
                                        "sessionId": session_id,
                                        "threadId": session_id,
                                        "turnId": turn_id,
                                        "itemId": session.next_item_id(),
                                        "phase": "thought",
                                        "text": commentary,
                                    })
                            session.text_parts.append(chunk)
                        suppress_chunk = session.expects_structured
                    elif ut == "tool_call":
                        session.had_tool_since_text = True
            if suppress_chunk:
                return
            enriched_params = {**params, "threadId": session_id, "turnId": turn_id}
            self._outbound.put({"method": "session/update", "params": enriched_params})
            return

        self._outbound.put(message)

    def _handle_permission_request(self, acp_id: Any, params: dict[str, Any]) -> None:
        session_id = str(params.get("sessionId") or "")
        tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        tool_name = str(tool_call.get("name") or "")
        acp_kind = str(tool_call.get("kind") or "")
        options = params.get("options") if isinstance(params.get("options"), list) else []

        allow_id = "allow"
        deny_id = "deny"
        for opt in options:
            if not isinstance(opt, dict):
                continue
            kind = str(opt.get("kind") or "")
            if kind in {"allow_once", "allow_always"} and allow_id == "allow":
                allow_id = str(opt.get("optionId") or "allow")
            elif kind in {"reject_once", "reject_always"} and deny_id == "deny":
                deny_id = str(opt.get("optionId") or "deny")

        with self._state_lock:
            session = self._sessions.get(session_id)
            turn_id = session.turn_id if session else ""
            if session and acp_kind != "edit" and tool_name not in WRITE_TOOLS and tool_name in session.session_grants:
                try:
                    self._acp_respond(acp_id, {"outcome": {"outcome": "selected", "optionId": allow_id}})
                except AgyError:
                    pass
                return

        is_edit = acp_kind == "edit" or tool_name in WRITE_TOOLS
        approval_kind = "fileChange" if is_edit else "command"
        proxy_id = f"agy-perm-{uuid.uuid4().hex}"
        args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else (
            tool_call.get("rawInput") if isinstance(tool_call.get("rawInput"), dict) else {}
        )

        out_params: dict[str, Any] = {
            "threadId": session_id,
            "turnId": turn_id,
            "itemId": tool_call.get("toolCallId"),
            "reason": f"Agy wants to use {tool_name or approval_kind}.",
            "tool": tool_name,
            "cwd": str(args.get("Cwd") or args.get("cwd") or self.cwd),
            "availableDecisions": list(APPROVAL_DECISIONS),
        }
        if is_edit:
            paths = _extract_tool_paths(tool_call)
            out_params["changes"] = [{"path": path, "kind": "modify"} for path in paths]
            out_params["command"] = _bounded(
                f"{tool_name} {paths[0]}".strip() if paths else tool_name, 4000
            )
        else:
            out_params["command"] = _bounded(
                _tool_command_detail(tool_name, args, str(tool_call.get("title") or "")), 4000
            )

        with self._state_lock:
            self._pending_permissions[proxy_id] = {
                "acp_id": acp_id,
                "session_id": session_id,
                "tool": tool_name,
                "kind": approval_kind,
                "allow_id": allow_id,
                "deny_id": deny_id,
            }
        self._outbound.put({"id": proxy_id, "method": APPROVAL_METHODS[approval_kind], "params": out_params})

    # --- DiscussManager synchronous request surface ------------------------

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self.alive:
            if self._fatal is not None:
                raise self._fatal
            raise AgyUnavailableError("Agy ACP server is not running")
        params = params or {}
        handlers = {
            "thread/start": self._handle_thread_start,
            "thread/resume": self._handle_thread_resume,
            "thread/read": self._handle_thread_read,
            "turn/start": self._handle_turn_start,
            "turn/interrupt": self._handle_turn_interrupt,
            "model/list": self._handle_model_list,
            "skills/list": self._handle_skills_list,
        }
        handler = handlers.get(method)
        if handler is None:
            raise AgyRequestError(f"method not found: {method}", code=-32601)
        budget = timeout if timeout is not None else self.request_timeout
        if method == "turn/start":
            budget = max(budget, TURN_START_TIMEOUT)
        return handler(params, budget)

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        key = str(request_id)
        with self._state_lock:
            pending = self._pending_permissions.pop(key, None)
        if pending is None:
            raise AgyRequestError("approval is no longer pending")
        decision = str((result or {}).get("decision") or "decline")
        if decision == "acceptForSession" and pending["kind"] != "fileChange" and pending["tool"]:
            with self._state_lock:
                session = self._sessions.get(pending["session_id"])
                if session is not None:
                    session.session_grants.add(pending["tool"])
        option_id = pending["allow_id"] if decision in {"accept", "acceptForSession"} else pending["deny_id"]
        self._acp_respond(pending["acp_id"], {"outcome": {"outcome": "selected", "optionId": option_id}})

    def respond_error(self, request_id: int | str, message: str, code: int = -32601) -> None:
        key = str(request_id)
        with self._state_lock:
            pending = self._pending_permissions.pop(key, None)
        if pending is None:
            return
        try:
            self._acp_respond(pending["acp_id"], {"outcome": {"outcome": "selected", "optionId": pending["deny_id"]}})
        except AgyError:
            pass

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        return None

    def discard_ephemeral_thread(self, thread_id: str) -> None:
        session_id = str(thread_id or "").strip()
        if not session_id:
            return
        with self._state_lock:
            self._sessions.pop(session_id, None)
        try:
            if self.alive:
                self._acp_request("session/close", {"sessionId": session_id}, timeout=5.0)
        except AgyError:
            pass

    # --- handlers ----------------------------------------------------------

    def _record_session_metadata(self, result: dict[str, Any]) -> None:
        models = result.get("models") if isinstance(result.get("models"), dict) else {}
        available = models.get("availableModels") if isinstance(models.get("availableModels"), list) else []
        config_options = result.get("configOptions") if isinstance(result.get("configOptions"), list) else []
        current_id = str(models.get("currentModelId") or "").strip()
        with self._state_lock:
            if available:
                self._raw_models = [row for row in available if isinstance(row, dict)]
                self._variant_ids = {str(row.get("modelId") or "") for row in self._raw_models if row.get("modelId")}
            if config_options:
                self._raw_config_options = [row for row in config_options if isinstance(row, dict)]
            if current_id:
                self._current_model_id = current_id

    def _ensure_default_mode(self, session_id: str, result: dict[str, Any]) -> None:
        modes = result.get("modes") if isinstance(result.get("modes"), dict) else {}
        current = str(modes.get("currentModeId") or "").strip()
        available = {
            str(m.get("id") or "") for m in (modes.get("availableModes") or []) if isinstance(m, dict)
        }
        if current != "default" and (not available or "default" in available):
            try:
                self._acp_request("session/set_mode", {"sessionId": session_id, "modeId": "default"}, timeout=5.0)
            except AgyError:
                pass

    def _handle_thread_start(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        cwd = str(params.get("cwd") or self.cwd)
        acp_params: dict[str, Any] = {"cwd": cwd, "mcpServers": []}
        instructions = str(params.get("developerInstructions") or "").strip()
        if instructions and self._supports_system_prompt_append:
            acp_params["_meta"] = {"antigravity": {"systemPrompt": {"append": instructions}}}
        try:
            result = self._acp_request("session/new", acp_params, timeout=max(timeout, SESSION_NEW_TIMEOUT))
        except AgyRequestError as exc:
            if _is_auth_error(exc, exc.code):
                raise AgyAuthError(LOGIN_EXPIRED) from exc
            raise
        session_id = str(result.get("sessionId") or "").strip()
        if not session_id:
            raise AgyProtocolError("Agy ACP server did not return a sessionId")
        self._record_session_metadata(result)
        self._ensure_default_mode(session_id, result)
        session = _Session(session_id)
        session.thread_params = dict(params)
        with self._state_lock:
            self._sessions[session_id] = session
        return {"thread": {"id": session_id}}

    def _handle_thread_resume(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        session_id = str(params.get("threadId") or "").strip()
        if not session_id:
            raise AgyRequestError("thread not found", code=-32004)
        with self._state_lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                existing.thread_params.update(params)
                return {"thread": {"id": session_id}}
        cwd = str(params.get("cwd") or self.cwd)
        try:
            result = self._acp_request(
                "session/resume", {"sessionId": session_id, "cwd": cwd, "mcpServers": []}, timeout=timeout
            )
        except AgyRequestError as exc:
            if _is_auth_error(exc, exc.code):
                raise AgyAuthError(LOGIN_EXPIRED) from exc
            if _is_missing_session_error(exc, exc.code):
                raise AgyRequestError(f"thread not found: {session_id}", code=-32004) from exc
            raise
        self._record_session_metadata(result)
        self._ensure_default_mode(session_id, result)
        session = _Session(session_id)
        session.thread_params = dict(params)
        with self._state_lock:
            self._sessions[session_id] = session
        return {"thread": {"id": session_id}}

    def _handle_thread_read(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        session_id = str(params.get("threadId") or "").strip()
        if not session_id:
            raise AgyRequestError("thread not found", code=-32004)
        cwd = str(params.get("cwd") or self.cwd)
        with self._state_lock:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.busy:
                raise AgyRequestError(
                    "Agy session is busy; cannot reload while a turn is running",
                    code=-32002,
                )
            self._replay_buffers[session_id] = []
        try:
            result = self._acp_request(
                "session/load",
                {"sessionId": session_id, "cwd": cwd, "mcpServers": []},
                timeout=max(timeout, SESSION_LOAD_TIMEOUT),
            )
        except AgyRequestError as exc:
            if _is_auth_error(exc, exc.code):
                raise AgyAuthError(LOGIN_EXPIRED) from exc
            if _is_missing_session_error(exc, exc.code):
                raise AgyRequestError(f"thread not found: {session_id}", code=-32004) from exc
            raise
        finally:
            with self._state_lock:
                replayed = self._replay_buffers.pop(session_id, [])
        self._record_session_metadata(result)
        turns = self._turns_from_replay(replayed)
        if not turns:
            raise AgyRequestError(f"thread not found: {session_id}", code=-32004)
        with self._state_lock:
            if session_id not in self._sessions:
                session = _Session(session_id)
                session.thread_params = dict(params)
                self._sessions[session_id] = session
        return {"thread": {"id": session_id, "turns": turns}, "turns": turns}

    @staticmethod
    def _turns_from_replay(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        agent_chunks: list[str] = []

        def flush_agent() -> None:
            if current is not None and agent_chunks:
                text = "".join(agent_chunks)
                agent_chunks.clear()
                current["items"].append({
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": _bounded(text, 524_288),
                })

        for msg in messages:
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            update = params.get("update") if isinstance(params.get("update"), dict) else {}
            ut = str(update.get("sessionUpdate") or "")
            content = update.get("content") if isinstance(update.get("content"), dict) else {}
            text = str(content.get("text") or "")
            if ut == "user_message_chunk" and text:
                flush_agent()
                if current is not None and len(current["items"]) == 1:
                    # Consecutive user chunks belong to the same user turn.
                    current["items"][0]["content"][0]["text"] += text
                else:
                    current = {
                        "id": f"turn-{len(turns) + 1}",
                        "items": [{"type": "userMessage", "content": [{"type": "text", "text": text}]}],
                    }
                    turns.append(current)
            elif ut == "agent_message_chunk" and text and current is not None:
                agent_chunks.append(text)
        flush_agent()
        return turns

    def _handle_turn_start(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        session_id = str(params.get("threadId") or "").strip()
        with self._state_lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise AgyRequestError("thread not found", code=-32004)
        prompt_parts = [
            str(item.get("text") or "")
            for item in (params.get("input") or [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        prompt = "\n\n".join(part for part in prompt_parts if part)
        if not prompt:
            raise AgyRequestError("turn input is empty", code=-32602)

        self._apply_model_selection(session, params, timeout=timeout)

        schema = params.get("outputSchema")
        expects_structured = bool(schema)
        if schema:
            prompt = (
                f"{prompt}\n\n"
                "REQUIRED JSON OUTPUT SCHEMA:\n"
                "Return ONLY a single valid JSON object matching this schema (no markdown fences or extra text):\n"
                f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
            )

        turn_id = uuid.uuid4().hex
        with self._state_lock:
            session.turn_id = turn_id
            session.may_write = bool(params.get("mayWrite"))
            session.busy = True
            session.cancel_requested = False
            session.text_parts = []
            session.had_tool_since_text = False
            session.expects_structured = expects_structured

        self._emit("session/prompt/started", {
            "sessionId": session_id,
            "threadId": session_id,
            "turnId": turn_id,
        })
        worker = threading.Thread(
            target=self._run_prompt_turn,
            args=(session, turn_id, prompt, expects_structured),
            name=f"proseview-agy-turn-{turn_id[:8]}",
            daemon=True,
        )
        worker.start()
        return {"turn": {"id": turn_id, "status": "inProgress"}}

    def _apply_model_selection(self, session: _Session, params: dict[str, Any], *, timeout: float) -> None:
        req_model = str(params.get("model") or "").strip()
        req_effort = str(params.get("effort") or "").strip().lower()
        if not req_model and not req_effort:
            return
        if req_model == session.model and req_effort == session.effort:
            return

        with self._state_lock:
            variant_ids = set(self._variant_ids)
            default_base = self._split_variant(self._current_model_id)[0]

        combined = f"{req_model}-{req_effort}" if (req_model and req_effort) else ""
        if combined and combined in variant_ids:
            self._acp_request("session/set_model", {"sessionId": session.session_id, "modelId": combined}, timeout=timeout)
        elif req_model and req_model in variant_ids and not req_effort:
            self._acp_request("session/set_model", {"sessionId": session.session_id, "modelId": req_model}, timeout=timeout)
        elif not req_model and req_effort and default_base and f"{default_base}-{req_effort}" in variant_ids:
            self._acp_request(
                "session/set_model",
                {"sessionId": session.session_id, "modelId": f"{default_base}-{req_effort}"},
                timeout=timeout,
            )
        else:
            if req_model:
                self._acp_request(
                    "session/set_config_option",
                    {"sessionId": session.session_id, "configId": "model", "value": req_model},
                    timeout=timeout,
                )
            if req_effort:
                self._acp_request(
                    "session/set_config_option",
                    {"sessionId": session.session_id, "configId": "thought_level", "value": req_effort},
                    timeout=timeout,
                )
        session.model = req_model
        session.effort = req_effort

    def _run_prompt_turn(
        self, session: _Session, turn_id: str, prompt: str, expects_structured: bool = False
    ) -> None:
        session_id = session.session_id
        common = {"sessionId": session_id, "threadId": session_id, "turnId": turn_id}
        status = "completed"
        error_text = ""
        try:
            # Wait indefinitely (until turn completes, is cancelled, or transport stops)
            result = self._acp_request(
                "session/prompt",
                {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
                timeout=None,
            )
            stop_reason = str(result.get("stopReason") or "end_turn")
            if stop_reason == "cancelled":
                with self._state_lock:
                    user_cancelled = session.cancel_requested
                if user_cancelled:
                    status = "interrupted"
                else:
                    status = "failed"
                    error_text = "Agy cancelled the turn before finishing."
                    self._emit("session/error", {**common, "message": error_text})
            else:
                with self._state_lock:
                    final_text = "".join(session.text_parts).strip()
                    session.text_parts.clear()
                if expects_structured and final_text:
                    final_text = _extract_json_text(final_text)
                if final_text:
                    self._emit("session/assistant_message", {
                        **common,
                        "itemId": session.next_item_id(),
                        "phase": "final_answer",
                        "text": final_text,
                    })
        except AgyRequestError as exc:
            status = "failed"
            if _is_auth_error(exc, exc.code):
                error_text = LOGIN_EXPIRED
                self._emit("session/error", {**common, "message": LOGIN_EXPIRED, "command": LOGIN_COMMAND})
            else:
                error_text = _bounded(str(exc), 4000)
                self._emit("session/error", {**common, "message": error_text})
        except BaseException as exc:  # noqa: BLE001
            status = "failed"
            error_text = _bounded(str(exc), 4000)
            self._emit("session/error", {**common, "message": error_text})
        finally:
            with self._state_lock:
                session.busy = False
                session.turn_id = ""
                session.cancel_requested = False
                session.text_parts.clear()
            self._emit("session/prompt/completed", {**common, "status": status, "error": error_text})

    def _handle_turn_interrupt(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        session_id = str(params.get("threadId") or "").strip()
        if not session_id:
            raise AgyRequestError("thread not found", code=-32004)
        with self._state_lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise AgyRequestError("thread not found", code=-32004)
            session.cancel_requested = True
        self._acp_notify("session/cancel", {"sessionId": session_id})
        return {}

    def _handle_skills_list(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        return {"skills": []}

    def _handle_model_list(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        with self._state_lock:
            have_catalog = bool(self._raw_models or self._raw_config_options)
        if not have_catalog:
            # Open and close a short probe session to read the live model catalog
            # before the writer starts their first conversation.
            try:
                result = self._acp_request(
                    "session/new", {"cwd": self.cwd, "mcpServers": []}, timeout=max(timeout, SESSION_NEW_TIMEOUT)
                )
            except AgyRequestError as exc:
                if _is_auth_error(exc, exc.code):
                    raise AgyAuthError(LOGIN_EXPIRED) from exc
                raise
            self._record_session_metadata(result)
            probe_id = str(result.get("sessionId") or "").strip()
            if probe_id:
                try:
                    self._acp_request("session/close", {"sessionId": probe_id}, timeout=5.0)
                except AgyError:
                    pass

        with self._state_lock:
            raw_models = list(self._raw_models)
            config_options = list(self._raw_config_options)
            current_id = self._current_model_id

        return self._build_model_catalog(raw_models, config_options, current_id)

    @staticmethod
    def _split_variant(model_id: str) -> tuple[str, str]:
        match = _VARIANT_SUFFIX_RE.match(str(model_id or "").strip())
        if match:
            return match.group("base"), match.group("effort")
        return str(model_id or "").strip(), ""

    @classmethod
    def _build_model_catalog(
        cls,
        raw_models: list[dict[str, Any]],
        config_options: list[dict[str, Any]],
        current_model_id: str,
    ) -> dict[str, Any]:
        model_opt = next((opt for opt in config_options if opt.get("id") == "model"), None)
        thought_opt = next((opt for opt in config_options if opt.get("id") == "thought_level"), None)

        default_model = str((model_opt or {}).get("currentValue") or "").strip()
        default_effort = str((thought_opt or {}).get("currentValue") or "").strip().lower()
        if not default_model and current_model_id:
            default_model, suffix_effort = cls._split_variant(current_model_id)
            if not default_effort:
                default_effort = suffix_effort

        variant_efforts: dict[str, list[str]] = {}
        variant_names: dict[str, str] = {}
        for row in raw_models:
            mid = str(row.get("modelId") or "").strip()
            if not mid:
                continue
            base, effort = cls._split_variant(mid)
            if effort and (not model_opt or any(
                isinstance(opt, dict) and opt.get("value") == base
                for opt in (model_opt.get("options") or [])
            )):
                variant_efforts.setdefault(base, [])
                if effort not in variant_efforts[base]:
                    variant_efforts[base].append(effort)
                variant_names.setdefault(base, re.sub(r"\s*\([^)]+\)\s*$", "", str(row.get("name") or base)).strip())
            else:
                variant_efforts.setdefault(mid, [])
                variant_names.setdefault(mid, str(row.get("name") or mid).strip())

        base_entries: list[tuple[str, str]] = []
        if model_opt and isinstance(model_opt.get("options"), list):
            for opt in model_opt["options"]:
                if isinstance(opt, dict) and opt.get("value"):
                    base_entries.append((str(opt["value"]), str(opt.get("name") or opt["value"])))
        else:
            for base, name in variant_names.items():
                base_entries.append((base, name))

        thought_values = [
            str(opt.get("value") or "").strip().lower()
            for opt in ((thought_opt or {}).get("options") or [])
            if isinstance(opt, dict) and opt.get("value")
        ]

        rows: list[dict[str, Any]] = []
        for base_id, display_name in base_entries:
            efforts = list(variant_efforts.get(base_id) or [])
            if not efforts:
                _, suffix = cls._split_variant(base_id)
                efforts = [suffix] if suffix else (thought_values or ["medium"])
            efforts_sorted = [e for e in EFFORT_LADDER if e in efforts] or efforts
            rows.append({
                "id": base_id,
                "displayName": display_name,
                "description": "",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": eff, "description": EFFORT_DESCRIPTIONS.get(eff, f"{eff} reasoning")}
                    for eff in efforts_sorted
                ],
                "defaultReasoningEffort": default_effort if default_effort in efforts_sorted else efforts_sorted[0],
                "isDefault": base_id == default_model,
            })

        return {
            "data": rows,
            "default": {
                "model": default_model,
                "effort": default_effort or "medium",
                "source": MODEL_DEFAULT_SOURCE,
            },
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._state_lock:
            pending = list(self._pending_permissions.items())
            self._pending_permissions.clear()
        for _proxy_id, info in pending:
            try:
                self._acp_respond(info["acp_id"], {"outcome": {"outcome": "selected", "optionId": info["deny_id"]}})
            except AgyError:
                pass
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        self._outbound.put(None)
        self._fail(AgyUnavailableError("Agy ACP server stopped"))
