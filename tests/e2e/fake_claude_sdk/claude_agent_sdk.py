"""Hermetic Claude Agent SDK double for browser E2E subprocesses."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

__version__ = "e2e-fake"

_sessions: dict[str, list[SimpleNamespace]] = {}


class ClaudeAgentOptions:
    output_format: dict | None

    def __init__(self, **values):
        self.__dict__.update(values)


class HookMatcher:
    def __init__(self, **values):
        self.__dict__.update(values)


class TextBlock:
    def __init__(self, text: str):
        self.text = text


class AssistantMessage:
    def __init__(self, text: str, session_id: str):
        self.content = [TextBlock(text)]
        self.session_id = session_id
        self.uuid = uuid.uuid4().hex


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


class ClaudeSDKClient:
    def __init__(self, *, options: ClaudeAgentOptions):
        self.options = options
        self.session_id = str(
            getattr(options, "resume", "") or getattr(options, "session_id", "") or uuid.uuid4()
        )
        self._response = []

    async def connect(self):
        _sessions.setdefault(self.session_id, [])

    async def query(self, prompt: str):
        rows = _sessions.setdefault(self.session_id, [])
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
        elif "Required result type: alternatives" in prompt:
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
        rows.append(SimpleNamespace(
            type="assistant", uuid=uuid.uuid4().hex,
            message={"role": "assistant", "content": [{"type": "text", "text": answer}]},
        ))
        self._response = [
            AssistantMessage(answer, self.session_id),
            ResultMessage(self.session_id, structured),
        ]

    async def receive_response(self):
        for message in self._response:
            yield message
        self._response = []

    async def interrupt(self):
        return None

    async def disconnect(self):
        return None


def get_session_messages(session_id: str, *, directory: str):
    return list(_sessions.get(session_id, []))


def list_sessions(*args, **kwargs):
    return [{"session_id": session_id} for session_id in _sessions]
