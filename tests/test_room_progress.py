"""The Room exposes Markdown as it arrives, without leaking structured output."""
import pytest

from proseview.discuss import DiscussManager, _OneOff


@pytest.mark.parametrize("text", ["## Opening\n\nThe scene works.", 'A literal example: {"reply": "quoted text"}'])
def test_room_progress_returns_natural_markdown_before_completion(text):
    manager = DiscussManager.__new__(DiscussManager)
    pending = _OneOff()
    manager._room_runs = {"running": pending}
    pending.receive({"type": "response.delta", "text": text[:8]})
    assert manager.room_progress("running")["draft"] == text[:8]
    pending.receive({"type": "response.delta", "text": text[8:]})
    assert manager.room_progress("running")["draft"] == text
    assert not pending.done.is_set()


@pytest.mark.parametrize("text,expected", [('{"reply": "A partial\\nanswer', "A partial\nanswer"), ('{"agreed": [', "")])
def test_structured_room_progress_keeps_its_json_parser(text, expected):
    manager = DiscussManager.__new__(DiscussManager)
    pending = _OneOff()
    pending.structured_output = True
    pending.receive({"type": "response.delta", "text": text})
    manager._room_runs = {"running": pending}
    assert manager.room_progress("running")["draft"] == expected
