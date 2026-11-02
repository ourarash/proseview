"""Durable Room execution, separate from browser projections and agent prompts.

Only the server claims invitations. Browser commands are idempotent, and agent
I/O never holds the Room lock. A restart can recover a completed provider turn;
an interrupted turn is never silently repeated, especially when it edited files.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .room import PASS_MARKER, clean_participants
from .suggestions import RoomHistoryStore, _clean_room_session, _room_history_path


class RoomRuntimeError(ValueError):
    pass


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise RoomRuntimeError("invalid Room identifier")
    return value


class RoomDiskStore:
    """Private per-book records. Before images never come from the browser."""

    def __init__(self, root: Path, directory: Path | None = None) -> None:
        book = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
        self.directory = (directory or _room_history_path().parent / "room-runtime") / book
        self.lock = threading.RLock()

    def path(self, kind: str, key: str) -> Path:
        if kind not in ("rooms", "reviews"):
            raise RoomRuntimeError("invalid Room record type")
        return self.directory / kind / (identifier(key) + ".json")

    def read(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self.path(kind, key)
        with self.lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, ValueError) as exc:
                raise RoomRuntimeError(f"Cannot read the saved Room record: {exc}") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise RoomRuntimeError("The saved Room record has an unsupported format")
        return value

    def write(self, kind: str, key: str, value: dict[str, Any]) -> None:
        from .repo import atomic_write_text
        path = self.path(kind, key)
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps({**value, "version": 1}, ensure_ascii=False))


class RoomRuntime:
    def __init__(self, manager: Any, directory: Path | None = None) -> None:
        self.manager = manager
        self.store = RoomDiskStore(manager.root, directory)
        self.history = RoomHistoryStore(manager.root)
        self.generation = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.rooms: dict[str, dict[str, Any]] = {}
        self.workers: dict[str, threading.Thread] = {}
        self.context = threading.local()
        self.closing = False

    def _save(self, room: dict[str, Any]) -> None:
        room["revision"] = room.get("revision", 0) + 1
        room["updated_at"] = time.time()
        self.store.write("rooms", room["id"], room)
        if not room.get("deleted"):
            self.history.save({**room, "managed": True})

    def _load(self, key: str, initial: Any = None) -> dict[str, Any]:
        key = identifier(key)
        if key in self.rooms:
            return self.rooms[key]
        room = self.store.read("rooms", key)
        if room is None:
            saved = self.history.get(key) or initial
            if not isinstance(saved, dict):
                raise RoomRuntimeError("This Room has not been created")
            scene = str(saved.get("scene") or "")
            if self.manager._scene_file(scene) is None:
                raise RoomRuntimeError("Open a manuscript scene before starting the Room")
            participants = clean_participants(saved.get("participants") or (initial or {}).get("participants") or self.manager.room_settings()["participants"])
            raw = {**saved, "id": key, "participants": participants}
            # Persist even an empty managed Room, so an accepted first command
            # remains discoverable if the page closes before the worker starts.
            session = _clean_room_session(raw) if raw.get("turns") else {
                "id": key, "scene": scene, "participants": participants, "turns": [],
                "plans": [], "created_at": time.time(), "title": saved.get("title") or "Conversation",
                "badge": saved.get("badge") or "", "preset_id": saved.get("preset_id") or "", "question": "",
            }
            if session is None:
                raise RoomRuntimeError("Invalid saved Room")
            room = {**session, "managed": True, "revision": 0, "steps": [], "commands": {},
                    "native_threads": {}, "status": "idle", "active_step": "", "notice": "", "error": ""}
            self._restore_reviews(room)
            self.rooms[key] = room
            self._save(room)
            return room
        if room.get("deleted"):
            raise RoomRuntimeError("This Room was deleted")
        self.rooms[key] = room
        restored = self._restore_reviews(room)
        if room["status"] == "review":
            room["status"] = "idle"
            restored = True
        if restored:
            self._save(room)
        active = self._active(room)
        if room.get("status") in ("running", "recovering") or active and active["state"] in ("running", "interrupting"):
            room["recovery_was_paused"] = room.get("status") == "paused"
            # The previous worker cannot be trusted to have done nothing. First
            # try its saved completion/provider history, without executing it.
            room["status"] = "recovering"
            room["notice"] = "Checking the interrupted agent turn after a server restart…"
            self._save(room)
            self._start_recovery(key)
        elif room.get("status") == "idle":
            self._start_worker(key)
        return room

    def _restore_reviews(self, room: dict[str, Any]) -> bool:
        changed = False
        for turn in room["turns"]:
            if not turn.get("review_pending"):
                continue
            cid = turn.get("tool_conversation_id")
            try:
                available = cid and (self.manager._conversations.get(cid) or self.store.read("reviews", cid))
            except RoomRuntimeError:
                available = False
            if not available:
                turn["review_pending"] = False
                turn["review_unavailable"] = True
                room["notice"] = "An older review was lost when the server restarted. Your edits remain saved; use file history to inspect them. This no longer blocks messages."
                changed = True
        return changed

    @staticmethod
    def _review_pending(room: dict[str, Any]) -> bool:
        return any(turn.get("review_pending") for turn in room["turns"])

    def command(self, body: dict[str, Any]) -> dict[str, Any]:
        key = identifier(body.get("room_id"))
        action = body.get("action", "state")
        with self.lock:
            room = self._load(key, body.get("initial"))
            if action == "state":
                return self._public(room, unchanged=body.get("after_revision") == room.get("revision"))
            request_id = identifier(body.get("request_id"))
            previous = room["commands"].get(request_id)
            if previous:
                if previous != action:
                    raise RoomRuntimeError("A Room request id was reused for another action")
                return self._public(room)
            if action == "submit":
                self._submit(room, body)
            elif action == "preset":
                self._preset(room, body)
            elif action == "remove":
                target = identifier(body.get("message_id"))
                steps = [step for step in room["steps"] if step.get("message_id") == target]
                if not steps or any(step["state"] != "queued" for step in steps):
                    raise RoomRuntimeError("That message has already started")
                for step in steps:
                    step["state"] = "cancelled"
            elif action == "models":
                if room["status"] in ("running", "recovering"):
                    raise RoomRuntimeError("Wait for the current invitation before changing models")
                pair = clean_participants(body.get("participants"))
                # Only model/effort overrides can change in a running Room.
                for old, new in zip(room["participants"], pair):
                    if {k: v for k, v in old.items() if k not in ("model", "effort")} != {k: v for k, v in new.items() if k not in ("model", "effort")}:
                        raise RoomRuntimeError("Participants stay fixed after the Room starts")
                room["participants"] = pair
            elif action == "reviewed":
                cid = identifier(body.get("conversation_id"))
                outstanding = self.manager.turn_file_changes(cid)
                if outstanding["files"]:
                    raise RoomRuntimeError("Finish reviewing the outstanding changes first")
                for turn in room["turns"]:
                    if turn.get("tool_conversation_id") == cid:
                        turn["review_pending"] = False
                if room["status"] == "review":
                    room["status"] = "idle"
            elif action == "stop":
                room["status"] = "paused"
                room["notice"] = "Discussion stopped. Remaining invitations are saved."
                active = self._active(room)
                if active:
                    active["state"] = "interrupting"
                    # Calling the agent is kept outside the Room lock below.
            elif action in ("resume", "retry", "skip"):
                active = self._active(room)
                if active and active["state"] in ("running", "interrupting"):
                    raise RoomRuntimeError("Wait for the current agent to stop")
                if active and active["state"] == "interrupted":
                    if action == "resume":
                        raise RoomRuntimeError("Choose Retry or Skip for the interrupted invitation")
                    if action == "skip":
                        active["state"] = "cancelled"
                    else:
                        active["state"] = "queued"
                        active["attempt"] = active.get("attempt", 0) + 1
                        active["retry"] = True
                        if "review_choices" in body:
                            active["review_choices"] = self._review_choices(body)
                        active["previous_review_id"] = active.get("tool_conversation_id", "")
                        for field in ("native_reply", "native_status", "native_thread_id", "native_turn_id", "native_cache", "tool_conversation_id", "draft", "run_id"):
                            active.pop(field, None)
                        active.pop("live_document", None)
                        active.pop("live_content", None)
                        room["native_threads"].pop(str(active["seat"]), None)
                    room["active_step"] = ""
                room["status"] = "idle"
                room["notice"] = ""
                room["error"] = ""
            elif action == "preferences":
                # Legacy plan ticks/TODO/applied state do not own the transcript.
                raw = _clean_room_session({**room, "plans": body.get("plans", room.get("plans", []))})
                room["plans"] = raw["plans"] if raw else []
            else:
                raise RoomRuntimeError("Unknown Room action")
            room["commands"][request_id] = str(action)
            self._save(room)
            run_id = (self._active(room) or {}).get("run_id") if action == "stop" else None
            if action != "stop":
                self._start_worker(key)
            result = self._public(room)
        if run_id:
            self.manager.stop_room_turn(run_id)
        return result

    def _submit(self, room: dict[str, Any], body: dict[str, Any]) -> None:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RoomRuntimeError("A Room message cannot be empty")
        if len(text.encode()) > 128 * 1024:
            raise RoomRuntimeError("The Room message is too large")
        seats = body.get("seats")
        if not isinstance(seats, list) or not seats or any(type(s) is not int or s not in (1, 2) for s in seats) or len(set(seats)) != len(seats):
            raise RoomRuntimeError("Choose one or both participants")
        mid = identifier(body.get("message_id"))
        if any(step.get("message_id") == mid for step in room["steps"]):
            raise RoomRuntimeError("That message id is already in use")
        self.manager.context.build_mentions({"kind": "scene", "path": room["scene"]}, text, mentions=body.get("attachments") or [])
        live_document = body.get("live_document")
        self.manager._validated_live_document({"kind": "scene", "path": room["scene"]}, live_document)
        choices = self._review_choices(body)
        for index, seat in enumerate(seats):
            room["steps"].append({"id": uuid.uuid4().hex, "message_id": mid, "seat": seat,
                "state": "queued", "text": text, "authored": str(body.get("authored") or text.split("\n\nSelected passage:\n")[0]),
                "settle_reviews": index == 0, "review_choices": copy.deepcopy(choices) if index == 0 else [],
                "live_document": copy.deepcopy(live_document), "attachments": copy.deepcopy(body.get("attachments") or []), "kind": "message"})
        if room["status"] == "idle":
            room["error"] = ""

    @staticmethod
    def _review_choices(body: dict[str, Any]) -> list[dict[str, Any]]:
        choices = body.get("review_choices") or []
        if not isinstance(choices, list) or any(not isinstance(row, dict)
                or not isinstance(row.get("conversation_id"), str) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("fingerprint"), str) or not row["fingerprint"]
                or not isinstance(row.get("drop"), list)
                or any(type(block) is not int or block < 0 for block in row["drop"]) for row in choices):
            raise RoomRuntimeError("Reopen the change review before sending its choices")
        return choices

    def _settle_reviews(self, room: dict[str, Any], step: dict[str, Any]) -> None:
        """A new writer message keeps saved edits, honoring explicit unticks.

        Run only at the writer-message boundary, between agent calls. Agent
        replies and preset invitations never require a separate review action.
        Persist each completed review so recovery cannot apply an undo twice.
        """
        for turn in room["turns"]:
            if not turn.get("review_pending"):
                continue
            cid = turn.get("tool_conversation_id")
            changes = self.manager.turn_file_changes(cid)
            for file in changes["files"]:
                choice = next((row for row in step.get("review_choices", [])
                               if row["conversation_id"] == cid and row["path"] == file["path"]), None)
                drop = choice["drop"] if choice else []
                self.manager.apply_file_selection(cid, file["path"],
                    [block["id"] for block in file["blocks"] if block["id"] not in drop],
                    choice["fingerprint"] if choice else file["fingerprint"])
            turn["review_pending"] = False
            self._save(room)
        step["reviews_settled"] = True
        self._save(room)

    def _preset(self, room: dict[str, Any], body: dict[str, Any]) -> None:
        if room["turns"] or room["steps"]:
            raise RoomRuntimeError("Start a new Room before running a preset")
        invitations = body.get("invitations")
        if not isinstance(invitations, list) or not 2 <= len(invitations) <= 13:
            raise RoomRuntimeError("A preset needs 2–12 invitations plus its optional recap")
        for step in invitations:
            if not isinstance(step, dict) or type(step.get("seat")) is not int or step["seat"] not in (1, 2) or not isinstance(step.get("prompt"), str) or not step["prompt"].strip():
                raise RoomRuntimeError("Invalid preset invitation")
            room["steps"].append({"id": uuid.uuid4().hex, "seat": step["seat"], "state": "queued",
                "kind": "invitation", "prompt": step["prompt"], "recap": bool(step.get("recap")), "attachments": copy.deepcopy(step.get("attachments") or [])})

    def _active(self, room: dict[str, Any]) -> dict[str, Any] | None:
        return next((step for step in room["steps"] if step["id"] == room.get("active_step")), None)

    def _public(self, room: dict[str, Any], *, unchanged: bool = False) -> dict[str, Any]:
        if unchanged:
            active = self._active(room)
            return {"id": room["id"], "revision": room["revision"], "status": room["status"], "unchanged": True,
                    "live": self.manager.room_progress(active.get("run_id", "")) if active and room["status"] == "running" else None,
                    "partial_reply": (active or {}).get("draft", "")}
        result = {key: copy.deepcopy(value) for key, value in room.items() if key not in ("commands", "native_threads", "version")}
        result["acknowledged_requests"] = list(room["commands"])
        active = self._active(room)
        result["live"] = self.manager.room_progress(active.get("run_id", "")) if active and room["status"] == "running" else None
        # A disk checkpoint is also readable if the process died between a
        # streamed reply and committing its completed transcript entry.
        if active and not (result["live"] or {}).get("running"):
            result["partial_reply"] = active.get("draft", "")
        for step in result["steps"]:
            for key in ("live_content", "live_document", "native_reply", "native_status", "signature", "native_thread_id", "native_turn_id"):
                step.pop(key, None)
        return result

    def _start_worker(self, key: str) -> None:
        room = self.rooms[key]
        if self.closing or room["status"] != "idle" or not any(step["state"] == "queued" for step in room["steps"]):
            return
        old = self.workers.get(key)
        if old and old.is_alive():
            return
        worker = threading.Thread(target=self._work, args=(key,), daemon=True, name=f"room-{key}")
        self.workers[key] = worker
        worker.start()

    def _work(self, key: str) -> None:
        try:
            self._work_loop(key)
        finally:
            with self.lock:
                if self.workers.get(key) is threading.current_thread():
                    self.workers.pop(key, None)
                    self._start_worker(key)

    def _work_loop(self, key: str) -> None:
        while not self.closing:
            with self.lock:
                room = self.rooms[key]
                if room.get("deleted") or room["status"] != "idle":
                    return
                step = next((step for step in room["steps"] if step["state"] == "queued"), None)
                if step is None:
                    return
                step["state"] = "running"
                step["run_id"] = uuid.uuid4().hex
                room["active_step"] = step["id"]
                room["status"] = "running"
                room["owner"] = self.generation
                room["error"] = ""
                if step["kind"] == "message":
                    new_message = not any(turn.get("message_id") == step["message_id"] for turn in room["turns"])
                    step.setdefault("settle_reviews", new_message)
                    if new_message:
                        room["turns"].append({"role": "user", "label": "Me (Writer)", "text": step["text"], "message_id": step["message_id"], "attachments": copy.deepcopy(step.get("attachments") or [])})
                    authored = step["authored"]
                else:
                    if not any(turn.get("step_id") == step["id"] for turn in room["turns"]):
                        profile = room["participants"][step["seat"] - 1]
                        room["turns"].append({"role": "invitation", "label": "Preset", "seat": step["seat"],
                            "recap": step.get("recap", False), "step_id": step["id"], "text": f"@{profile['handle']}, {step['prompt']}", "attachments": copy.deepcopy(step.get("attachments") or [])})
                    authored = step["prompt"]
                if step.get("retry"):
                    recovery_id = step["id"] + "-retry-" + str(step.get("attempt", 0))
                    if not any(turn.get("step_id") == recovery_id for turn in room["turns"]):
                        room["turns"].append({"role": "invitation", "label": "Recovery", "step_id": recovery_id,
                            "text": "The previous attempt was interrupted. Check the current files before continuing this request. Preserve work already applied; do not repeat edits blindly."})
                self._save(room)
                history = copy.deepcopy(room["turns"])
                participants = copy.deepcopy(room["participants"])
                scene, run_id = room["scene"], step["run_id"]
                native = copy.deepcopy(room["native_threads"].get(str(step["seat"])))
            try:
                self.context.room_id, self.context.step_id = key, step["id"]
                self.context.previous_review_id = step.get("previous_review_id") or (native or {}).get("conversation_id", "")
                seat_key = f"{key}:{step['seat']}"
                if native:
                    self.manager._room_threads[seat_key] = native
                elif step.get("retry"):
                    self.manager._room_threads.pop(seat_key, None)
                skill = self.manager._room_skill_from_text(participants[step["seat"] - 1]["agent"], authored)
                attachments = self.manager._room_references(history)
                with self.lock:
                    if step["state"] != "running":
                        raise RoomRuntimeError("Stopped by writer")
                    if step.get("settle_reviews") and not step.get("reviews_settled"):
                        self._settle_reviews(room, step)
                live_content = self.manager._validated_live_document({"kind": "scene", "path": scene}, step.get("live_document"))
                result = self.manager.run_room_turn(scene=scene, live_content=live_content or "",
                    seat=step["seat"], turn_index=sum(t["role"] == "critic" for t in history) + 1,
                    history=history, participants=participants, attachments=attachments, skill=skill,
                    debate_id=key, run_id=run_id)
                with self.lock:
                    if self.closing or self.rooms[key].get("deleted"):
                        return
                    room = self.rooms[key]
                    self._finish(room, step, result)
                    native = self.manager._room_threads.get(seat_key)
                    if native:
                        room["native_threads"][str(step["seat"])] = copy.deepcopy(native)
                    self._save(room)
                    if room["status"] != "idle":
                        return
            except Exception as exc:
                with self.lock:
                    if self.closing:
                        return
                    room = self.rooms[key]
                    step["state"] = "interrupted"
                    # Failures are visible recovery choices, not an invitation
                    # that can disappear from an otherwise open conversation.
                    try:
                        self._attach_interrupted_review(room, step)
                    except Exception as review_error:
                        room["notice"] = "The interrupted review could not be restored: " + str(review_error)
                    room["status"] = "interrupted"
                    room["error"] = str(exc)
                    self._save(room)
                return
            finally:
                self.context.room_id = self.context.step_id = ""

    def _finish(self, room: dict[str, Any], step: dict[str, Any], result: dict[str, Any]) -> None:
        was_paused = room["status"] == "paused"
        step["state"] = "passed" if result.get("passed") else "completed"
        profile = room["participants"][step["seat"] - 1]
        if not any(turn.get("step_id") == step["id"] and turn["role"] == "critic" for turn in room["turns"]):
            room["turns"].append({"role": "critic", "step_id": step["id"], "seat": step["seat"],
                "agent": result["agent"], "model": result.get("model", ""), "label": profile["name"] + " · " + result["agent"].title(),
                "tag": "Recap" if step.get("recap") else "Reply", "text": result.get("reply", ""), "passed": bool(result.get("passed")),
                "changed_files": result.get("changed_files", []),
                "tool_conversation_id": result.get("tool_conversation_id", ""),
                "review_pending": bool(result.get("changed_files") or result.get("unreviewable"))})
        if step.get("native_cache"):
            room["native_threads"][str(step["seat"])] = step["native_cache"]
        room["active_step"] = ""
        room["status"] = "paused" if was_paused else "idle"
        room["notice"] = ""
        room["error"] = ""

    def _attach_interrupted_review(self, room: dict[str, Any], step: dict[str, Any]) -> None:
        cid = step.get("tool_conversation_id")
        if not cid or not self.store.read("reviews", cid):
            return
        changes = self.manager.turn_file_changes(cid)
        if not changes["files"] and not changes["unreviewable"]:
            return
        interrupted_id = step["id"] + "-interrupted-" + str(step.get("attempt", 0))
        if any(turn.get("step_id") == interrupted_id for turn in room["turns"]):
            return
        profile = room["participants"][step["seat"] - 1]
        room["turns"].append({"role": "critic", "step_id": interrupted_id, "seat": step["seat"], "agent": profile["agent"],
            "label": profile["name"] + " · " + profile["agent"].title() + " · interrupted reply (incomplete)", "text": step.get("draft") or "This invitation was interrupted. Review any saved changes before retrying or skipping it.",
            "tag": "Interrupted", "tool_conversation_id": cid, "review_pending": True})

    def checkpoint(self, room_id: str, step_id: str, fields: dict[str, Any]) -> None:
        with self.lock:
            room = self.rooms.get(room_id)
            if room is None:
                return
            step = next((step for step in room["steps"] if step["id"] == step_id), None)
            if not step or step["state"] not in ("running", "interrupting"):
                return
            if fields.get("run_id") and fields["run_id"] != step.get("run_id"):
                return
            step.update(fields)
            # Checkpoints do not cause the UI to redraw its composer on every token.
            self.store.write("rooms", room_id, room)

    def _start_recovery(self, key: str) -> None:
        worker = threading.Thread(target=self._recover, args=(key,), daemon=True, name=f"recover-room-{key}")
        self.workers[key] = worker
        worker.start()

    def _recover(self, key: str) -> None:
        with self.lock:
            room = self.rooms[key]
            step = self._active(room)
            saved = copy.deepcopy(step)
        result = None
        if saved:
            try:
                result = self.manager._recover_room_result(saved, room["participants"])
            except Exception:
                # Not knowing the result is an interruption, never permission
                # to repeat a potentially mutating invitation.
                result = None
        with self.lock:
            if self.closing:
                return
            room = self.rooms[key]
            if step is not None and result:
                self._finish(room, step, result)
                if room.pop("recovery_was_paused", False):
                    room["status"] = "paused"
                    room["notice"] = "The stopped invitation finished before the restart. Remaining invitations are saved until you resume."
            else:
                if step:
                    step["state"] = "interrupted"
                    try:
                        self._attach_interrupted_review(room, step)
                    except Exception as exc:
                        room["error"] = "The saved review could not be read: " + str(exc)
                room["status"] = "interrupted"
                room["notice"] = "The server restarted during an invitation. Any available partial reply and saved changes are preserved. Review changes, then choose Retry or Skip; nothing will be repeated automatically."
            self._save(room)
            # Completed recovery can safely run the remaining invitations.
            self.workers.pop(key, None)
            if result and room["status"] == "idle":
                self._start_worker(key)

    def delete(self, key: str) -> None:
        run_id = None
        with self.lock:
            record = self.rooms.get(key) or self.store.read("rooms", key)
            if record:
                record["deleted"] = True
                active = self._active(record)
                run_id = (active or {}).get("run_id")
                record["status"] = "paused"
                self._save(record)
        if run_id:
            self.manager.stop_room_turn(run_id)

    def close(self) -> None:
        with self.lock:
            self.closing = True
            for room in self.rooms.values():
                if room["status"] == "running":
                    room["notice"] = "The server stopped during this invitation. Its result will be checked when the Room reopens."
                    self._save(room)
