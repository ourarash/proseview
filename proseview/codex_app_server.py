"""Small synchronous JSON-RPC client for ``codex app-server``.

The app-server protocol is newline-delimited JSON over stdio.  Prosview keeps
the transport private to the local server and exposes only sanitized domain
events from :mod:`proseview.discuss` to browsers.
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable


class CodexError(RuntimeError):
    pass


class CodexUnavailableError(CodexError):
    pass


class CodexAuthError(CodexError):
    pass


class CodexProtocolError(CodexError):
    pass


class CodexRequestError(CodexError):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CodexAppServer:
    def __init__(
        self,
        *,
        executable: str | None = None,
        cwd: Path | str,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_failure: Callable[[BaseException], None] | None = None,
        request_timeout: float = 15.0,
    ) -> None:
        self.executable = executable
        self.cwd = str(Path(cwd).resolve())
        self.on_message = on_message or (lambda _message: None)
        self.on_failure = on_failure or (lambda _error: None)
        self.request_timeout = request_timeout
        self.user_agent = ""
        self.capabilities: dict[str, Any] = {}
        self._proc: subprocess.Popen[str] | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._next_id = 1
        self._fatal: BaseException | None = None
        self._stderr: deque[str] = deque(maxlen=50)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._fatal is None

    def start(self) -> None:
        with self._start_lock:
            if self.alive:
                return
            self.close()
            executable = self.executable or shutil.which("codex")
            if not executable:
                raise CodexUnavailableError("Codex CLI is not installed or is not on PATH")
            self._fatal = None
            try:
                self._proc = subprocess.Popen(
                    [executable, "app-server"],
                    cwd=self.cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                )
            except OSError as exc:
                raise CodexUnavailableError(f"Could not start Codex app-server: {exc}") from exc
            self._reader = threading.Thread(target=self._read_loop, name="proseview-codex-reader", daemon=True)
            self._stderr_reader = threading.Thread(target=self._stderr_loop, name="proseview-codex-stderr", daemon=True)
            self._reader.start()
            self._stderr_reader.start()
            try:
                initialized = self.request(
                    "initialize",
                    {
                        "clientInfo": {"name": "proseview", "title": "Prosview", "version": "0.1.0"},
                        "capabilities": {"experimentalApi": False},
                    },
                )
                self.user_agent = str(initialized.get("userAgent") or "")
                self.notify("initialized", {})
                account = self.request("account/read", {"refreshToken": False})
                if account.get("requiresOpenaiAuth") and not account.get("account"):
                    raise CodexAuthError("Codex is not authenticated; sign in with `codex login` and try again")
            except BaseException:
                self.close()
                raise

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if method != "initialize" and not self.alive:
            if self._fatal is not None:
                raise self._fatal
            raise CodexUnavailableError("Codex app-server is not running")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                response = response_queue.get(timeout=self.request_timeout if timeout is None else timeout)
            except queue.Empty as exc:
                raise CodexProtocolError(f"Codex request timed out: {method}") from exc
            if isinstance(response, BaseException):
                raise response
            if isinstance(response.get("error"), dict):
                error = response["error"]
                raise CodexRequestError(str(error.get("message") or "Codex request failed"), code=error.get("code"))
            result = response.get("result")
            if result is None:
                return {}
            if not isinstance(result, dict):
                raise CodexProtocolError(f"Codex returned an invalid result for {method}")
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"method": method, "params": params or {}})

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        self._send({"id": request_id, "result": result})

    def respond_error(self, request_id: int | str, message: str, code: int = -32601) -> None:
        self._send({"id": request_id, "error": {"code": code, "message": message}})

    def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            if self._fatal is not None:
                raise self._fatal
            raise CodexUnavailableError("Codex app-server is not running")
        line = json.dumps(message, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(line)
                proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            error = CodexProtocolError("Codex app-server connection closed")
            self._fail(error)
            raise error from exc

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError) as exc:
                    self._fail(CodexProtocolError("Codex app-server emitted invalid JSON"))
                    return
                if not isinstance(message, dict):
                    self._fail(CodexProtocolError("Codex app-server emitted an invalid message"))
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
                try:
                    self.on_message(message)
                except Exception:
                    # A browser/domain consumer cannot be allowed to kill the
                    # transport. Its own boundary reports the failure.
                    continue
        finally:
            if self._fatal is None and self._proc is proc:
                detail = "exited unexpectedly" if proc.poll() is not None else "connection closed unexpectedly"
                self._fail(CodexProtocolError(f"Codex app-server {detail}"))

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            # Diagnostics are deliberately bounded and never forwarded to the
            # browser. App-server must not write document bodies here, but we
            # still avoid persistent logging.
            self._stderr.append("Codex emitted stderr; content suppressed by Prosview")

    def _fail(self, error: BaseException) -> None:
        first_failure = self._fatal is None
        self._fatal = error
        with self._pending_lock:
            queues = list(self._pending.values())
        for pending in queues:
            try:
                pending.put_nowait(error)
            except queue.Full:
                pass
        if first_failure:
            try:
                self.on_failure(error)
            except Exception:
                pass

    def inspect_capabilities(self) -> dict[str, Any]:
        """Best-effort exact schema inspection for the installed CLI.

        Missing schema generation is not fatal: the stable methods are probed
        through normal requests. The result is diagnostics/capability data,
        never a version comparison.
        """
        executable = self.executable or shutil.which("codex")
        if not executable:
            return {}
        with tempfile.TemporaryDirectory(prefix="proseview-codex-schema-") as tmp:
            try:
                completed = subprocess.run(
                    [executable, "app-server", "generate-json-schema", "--out", tmp],
                    cwd=self.cwd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return {}
            if completed.returncode != 0:
                return {}
            schema_files = list(Path(tmp).rglob("*.json"))
            if not schema_files:
                return {}
            schema_names = " ".join(path.name.lower() for path in schema_files)
            schema_chunks: list[str] = []
            remaining = 8 * 1024 * 1024
            for path in schema_files:
                if remaining <= 0:
                    break
                try:
                    chunk = path.read_text(encoding="utf-8")[:remaining]
                except OSError:
                    continue
                schema_chunks.append(chunk)
                remaining -= len(chunk.encode("utf-8"))
            schema_text = "".join(schema_chunks)
            normalized_text = schema_text.lower().replace("/", "").replace("_", "")
            required = {
                "thread start": ("threadstartparams", "threadstart"),
                "thread history": ("threadreadparams", "threadread"),
                "turn start": ("turnstartparams", "turnstart"),
                "turn interruption": ("turninterruptparams", "turninterrupt"),
                "approvals": ("requestapproval", "approvalrequest"),
            }
            missing = [
                label for label, signals in required.items()
                if not any(signal in schema_names.replace("_", "") or signal in normalized_text for signal in signals)
            ]
            if "includeturns" not in normalized_text:
                missing.append("thread history includeTurns")
            if missing:
                raise CodexProtocolError("Codex app-server protocol is unsupported (missing " + ", ".join(missing) + ")")

            allowed_decisions = {"accept", "acceptForSession", "decline", "cancel"}

            def response_decisions(filename: str) -> list[str]:
                target = next((path for path in schema_files if path.name == filename), None)
                if target is None:
                    return []
                try:
                    payload = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    return []
                found: set[str] = set()

                def visit(value: Any) -> None:
                    if isinstance(value, dict):
                        enum = value.get("enum")
                        if isinstance(enum, list):
                            found.update(str(item) for item in enum if str(item) in allowed_decisions)
                        for child in value.values():
                            visit(child)
                    elif isinstance(value, list):
                        for child in value:
                            visit(child)

                visit(payload)
                return [item for item in ("accept", "acceptForSession", "decline", "cancel") if item in found]

            command_decisions = response_decisions("CommandExecutionRequestApprovalResponse.json")
            file_decisions = response_decisions("FileChangeRequestApprovalResponse.json")
            permissions_supported = any(path.name == "PermissionsRequestApprovalResponse.json" for path in schema_files)
            self.capabilities = {
                "schema_generation": True,
                "reasoning_summary": '"summary"' in schema_text,
                "restricted_read_access": '"readableRoots"' in schema_text,
                "stable_discuss_protocol": True,
                "approval_decisions": {
                    "command": command_decisions,
                    "network": command_decisions,
                    "fileChange": file_decisions,
                    "permissions": ["accept", "acceptForSession", "decline", "cancel"] if permissions_supported else [],
                },
            }
            return dict(self.capabilities)

    def probe_capabilities(self) -> dict[str, Any]:
        """Probe non-mutating stable methods when schema generation is absent.

        A not-found/invalid-params response proves the method exists. A JSON-RPC
        method-not-found response proves this CLI cannot safely host Discuss.
        Turn start and approvals are then exercised by normal user actions.
        """
        probes = (
            ("thread/read", {"threadId": "proseview-capability-probe", "includeTurns": True}),
            ("turn/interrupt", {"threadId": "proseview-capability-probe", "turnId": "proseview-capability-probe"}),
        )
        for method, params in probes:
            try:
                self.request(method, params)
            except CodexRequestError as exc:
                if exc.code == -32601 or "method not found" in str(exc).lower():
                    raise CodexProtocolError(f"Codex app-server protocol is unsupported (missing {method})") from exc
            except CodexProtocolError:
                raise
        self.capabilities["stable_discuss_protocol"] = True
        self.capabilities["schema_generation"] = False
        return dict(self.capabilities)

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
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
        self._fail(CodexUnavailableError("Codex app-server stopped"))
