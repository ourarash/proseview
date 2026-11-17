"""Hermetic Claude Agent SDK double for browser E2E subprocesses."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid
from types import SimpleNamespace

__version__ = "e2e-fake"

_sessions: dict[str, list[SimpleNamespace]] = {}
_held_claude_once = False


def _record_claude_event(payload: dict) -> None:
    home = os.environ.get("HOME")
    if not home:
        return
    record = pathlib.Path(home) / "fake-claude-received.jsonl"
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError:
        pass


class ClaudeAgentOptions:
    output_format: dict | None

    def __init__(self, **values):
        self.__dict__.update(values)


class HookMatcher:
    def __init__(self, **values):
        self.__dict__.update(values)


class PermissionResultAllow:
    def __init__(self, **values):
        self.behavior = "allow"
        self.__dict__.update(values)


class PermissionResultDeny:
    def __init__(self, message: str = "", **values):
        self.behavior = "deny"
        self.message = message
        self.__dict__.update(values)


class TextBlock:
    def __init__(self, text: str):
        self.text = text


class AssistantMessage:
    def __init__(self, text: str, session_id: str, error: str | None = None):
        self.content = [TextBlock(text)]
        self.session_id = session_id
        self.uuid = uuid.uuid4().hex
        self.error = error


class ResultMessage:
    def __init__(self, session_id: str, structured_output=None):
        self.session_id = session_id
        self.uuid = uuid.uuid4().hex
        self.is_error = False
        self.subtype = "success"
        self.terminal_reason = ""
        self.errors = []
        self.structured_output = structured_output
        self.result = ""


EXPIRED_LOGIN = "Failed to authenticate: OAuth session expired and could not be refreshed"


class ClaudeSDKClient:
    def __init__(self, *, options: ClaudeAgentOptions):
        self.options = options
        self.session_id = str(
            getattr(options, "resume", "") or getattr(options, "session_id", "") or uuid.uuid4()
        )
        self._response = []
        self._hold_event: asyncio.Event | None = None
        self._interrupted = False

    def _requested_kind(self):
        # A request with an output schema (a highlight suggestion) says what
        # it wants there, not in its prompt.
        schema = ((getattr(self.options, "output_format", None) or {}).get("schema") or {})
        return (((schema.get("properties") or {}).get("kind") or {}).get("enum") or [None])[0]

    def _is_persistent(self) -> bool:
        extra = getattr(self.options, "extra_args", None) or {}
        return "no-session-persistence" not in extra

    async def connect(self):
        if self._is_persistent():
            _sessions.setdefault(self.session_id, [])

    async def query(self, prompt: str):
        global _held_claude_once
        extra = getattr(self.options, "extra_args", None) or {}
        _record_claude_event({
            "method": "query",
            "session_id": self.session_id,
            "prompt": prompt,
            "fork_session": bool(getattr(self.options, "fork_session", False)),
            "resume": getattr(self.options, "resume", ""),
            "tools": list(getattr(self.options, "tools", None) or []),
            "ephemeral": "no-session-persistence" in extra,
        })
        self._hold_event = None
        self._interrupted = False
        if "HOLD_CLAUDE_ONCE" in prompt and not _held_claude_once:
            _held_claude_once = True
            self._hold_event = asyncio.Event()
        if "EXPIRED_CLAUDE_LOGIN" in prompt:
            # What Claude Code sends once its login can no longer be refreshed.
            result = ResultMessage(self.session_id)
            result.is_error = True
            result.result = EXPIRED_LOGIN
            self._response = [AssistantMessage(EXPIRED_LOGIN, self.session_id, "authentication_failed"), result]
            return
        rows = _sessions.setdefault(self.session_id, []) if self._is_persistent() else []
        rows.append(SimpleNamespace(
            type="user", uuid=uuid.uuid4().hex,
            message={"role": "user", "content": [{"type": "text", "text": prompt}]},
        ))
        structured = None
        answer = "Fake answer from Claude: the project conversation stayed with the writer."
        selection = ""
        if "BEGIN USER SELECTION\n" in prompt and "\nEND USER SELECTION" in prompt:
            selection = prompt.split("BEGIN USER SELECTION\n", 1)[1].split("\nEND USER SELECTION", 1)[0]
        if "Required result type: critique" in prompt:
            evidence = selection or "selected passage"
            if "dial turned with a dry clatter" in selection:
                evidence = "a pressure gauge that was never selected"
            structured = {
                "kind": "critique",
                "findings": [{
                    "observation": "The passage delays its strongest image.",
                    "evidence": evidence,
                    "why_it_matters": "The opening beat lands less sharply.",
                    "next_step": "Lead with the character's concrete action.",
                }],
            }
            answer = json.dumps(structured)
        elif "Required result type: alternatives" in prompt or self._requested_kind() == "alternatives":
            structured = {
                "kind": "alternatives",
                "summary": "A more direct version that preserves the scene beat.",
                "alternatives": [
                    {"text": "Rena pressed her thumb against the envelope seam.", "rationale": "Uses a direct physical action."},
                    {"text": "Rena held the sealed envelope to the window.", "rationale": "Keeps focus on the object."},
                    {"text": "Rena traced the envelope seam with one thumb.", "rationale": "Uses a quieter beat."},
                ],
            }
            answer = json.dumps(structured)
        elif "agreed" in (((getattr(self.options, "output_format", None) or {}).get("schema") or {}).get("properties") or {}):
            structured = {
                "agreed": [
                    {"title": "Cut the opening weather line", "line": "17", "original": "The weather was grey.", "replacement": "She had used the same four digits since spring.", "why": "Open on the safe.", "proposed_by": "Critic 1", "accepted": True},
                    {"title": "Keep the dialogue subtext clipped", "line": "", "original": "", "replacement": "", "why": "Let the pause carry the tension.", "proposed_by": "Critic 2", "accepted": False},
                ],
                "open": [{"issue": "When to reveal the safe code", "critic1": "In this scene, to raise the stakes.", "critic2": "In the next, to keep the subtext."}],
            }
            answer = json.dumps(structured)
        elif "in a Writers' Room on the manuscript scene" in prompt:
            answer = "**Agree:** Issue 1, and cut the weather outright.\n\n**Add:** a sharper pause before she speaks."
        elif "Visual Beat Map" in prompt:
            structured = {
                "overall_scene_summary": "Test scene dramatic progression.",
                "beats": [
                    {
                        "order": 1,
                        "title": "Opening tension",
                        "summary": "Initial confrontation begins.",
                        "start_paragraph": 0,
                        "end_paragraph": 1,
                        "estimated_tension": 30,
                        "is_turning_point": False,
                        "moments": [
                            {
                                "order": 1,
                                "type": "action",
                                "speaker": None,
                                "text": "The dial turned with a dry clatter.",
                                "source_ref": {
                                    "paragraph": 0,
                                    "exact_quote": "The dial turned with a dry clatter."
                                }
                            }
                        ]
                    },
                    {
                        "order": 2,
                        "title": "Rising conflict",
                        "summary": "Tension escalates between the characters.",
                        "start_paragraph": 2,
                        "end_paragraph": 3,
                        "estimated_tension": 75,
                        "is_turning_point": True,
                        "moments": [
                            {
                                "order": 2,
                                "type": "dialogue",
                                "speaker": "Rena",
                                "text": "What are you doing?",
                                "source_ref": {
                                    "paragraph": 2,
                                    "exact_quote": ""
                                }
                            }
                        ]
                    },
                    {
                        "order": 3,
                        "title": "Resolution",
                        "summary": "The conflict settles temporarily.",
                        "start_paragraph": 4,
                        "end_paragraph": 4,
                        "estimated_tension": 40,
                        "is_turning_point": False,
                        "moments": [
                            {
                                "order": 3,
                                "type": "interiority",
                                "speaker": None,
                                "text": "She looked away.",
                                "source_ref": {
                                    "paragraph": 4,
                                    "exact_quote": ""
                                }
                            }
                        ]
                    }
                ]
            }
            answer = json.dumps(structured)
        if "ROOM_PASS_CLAUDE" in prompt:
            answer = "[ROOM_PASS]"
        rows.append(SimpleNamespace(
            type="assistant", uuid=uuid.uuid4().hex,
            message={"role": "assistant", "content": [{"type": "text", "text": answer}]},
        ))
        self._response = [
            AssistantMessage(answer, self.session_id),
            ResultMessage(self.session_id, structured),
        ]

    async def receive_response(self):
        if self._hold_event is not None:
            try:
                await asyncio.wait_for(self._hold_event.wait(), timeout=15.0)
            except TimeoutError:
                pass
            if self._interrupted:
                aborted = ResultMessage(self.session_id)
                aborted.subtype = "error_during_execution"
                aborted.terminal_reason = "aborted_streaming"
                aborted.is_error = True
                self._response = []
                yield aborted
                return
        for message in self._response:
            yield message
        self._response = []

    async def interrupt(self):
        _record_claude_event({"method": "interrupt", "session_id": self.session_id})
        self._interrupted = True
        if self._hold_event is not None:
            self._hold_event.set()
        return None

    async def disconnect(self):
        return None


def get_session_messages(session_id: str, *, directory: str):
    return list(_sessions.get(session_id, []))


def list_sessions(*args, **kwargs):
    return [{"session_id": session_id} for session_id in _sessions]
