"""Durable Group execution, separate from browser projections and agent prompts.

Only the server claims invitations. Browser commands are idempotent, and agent
I/O never holds the Group lock. A restart can recover a completed provider turn;
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

from .group import PASS_MARKER, SECOND_OPINION_RECAP, clean_participants, extract_stances, visible_reply, positions_table
from .suggestions import GroupHistoryStore, _clean_group_session, _group_history_path, group_title


class GroupRuntimeError(ValueError):
    pass


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise GroupRuntimeError("invalid Group identifier")
    return value


class GroupDiskStore:
    """Private per-book records. Before images never come from the browser."""

    def __init__(self, root: Path, directory: Path | None = None) -> None:
        book = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
        self.directory = (directory or _group_history_path().parent / "group-runtime") / book
        self.lock = threading.RLock()

    def path(self, kind: str, key: str) -> Path:
        if kind not in ("groups", "reviews"):
            raise GroupRuntimeError("invalid Group record type")
        return self.directory / kind / (identifier(key) + ".json")

    def read(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self.path(kind, key)
        with self.lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, ValueError) as exc:
                raise GroupRuntimeError(f"Cannot read the saved Group record: {exc}") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise GroupRuntimeError("The saved Group record has an unsupported format")
        return value

    def write(self, kind: str, key: str, value: dict[str, Any]) -> None:
        from .repo import atomic_write_text
        path = self.path(kind, key)
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps({**value, "version": 1}, ensure_ascii=False))


class GroupRuntime:
    def __init__(self, manager: Any, directory: Path | None = None) -> None:
        self.manager = manager
        self.store = GroupDiskStore(manager.root, directory)
        self.history = GroupHistoryStore(manager.root)
        self.generation = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.groups: dict[str, dict[str, Any]] = {}
        self.workers: dict[str, threading.Thread] = {}
        self.context = threading.local()
        self.closing = False

    def _save(self, group: dict[str, Any]) -> None:
        group["title"] = group_title(group)
        group["revision"] = group.get("revision", 0) + 1
        group["updated_at"] = time.time()
        self.store.write("groups", group["id"], group)
        if not group.get("deleted"):
            self.history.save({**group, "managed": True})

    def _load(self, key: str, initial: Any = None) -> dict[str, Any]:
        key = identifier(key)
        if key in self.groups:
            return self.groups[key]
        group = self.store.read("groups", key)
        if group is None:
            saved_history = self.history.get(key)
            saved = saved_history or initial
            if not isinstance(saved, dict):
                raise GroupRuntimeError("This Group has not been created")
            scene = str(saved.get("scene") or "")
            if not saved_history and self.manager._scene_file(scene) is None:
                raise GroupRuntimeError("Open a manuscript scene before starting the Group")
            participants = clean_participants(saved.get("participants") or (initial or {}).get("participants") or self.manager.group_settings()["participants"])
            raw = {**saved, "id": key, "participants": participants}
            # Persist even an empty managed Group, so an accepted first command
            # remains discoverable if the page closes before the worker starts.
            session = _clean_group_session(raw) if raw.get("turns") else {
                "id": key, "scene": scene, "participants": participants, "turns": [],
                "plans": [], "created_at": time.time(), "title": saved.get("title") or "Conversation",
                "badge": saved.get("badge") or "", "preset_id": saved.get("preset_id") or "", "question": "",
            }
            if session is None:
                raise GroupRuntimeError("Invalid saved Group")
            group = {**session, "managed": True, "revision": 0, "steps": [], "commands": {},
                    "native_threads": {}, "status": "idle", "active_step": "", "notice": "", "error": ""}
            self._restore_reviews(group)
            self.groups[key] = group
            self._save(group)
            return group
        if group.get("deleted"):
            raise GroupRuntimeError("This Group was deleted")
        group.setdefault("status", "idle")
        group.setdefault("steps", [])
        group.setdefault("commands", {})
        group.setdefault("native_threads", {})
        cleaned = _clean_group_session(group)
        if cleaned:
            group["turns"] = cleaned["turns"]
        session_created = float(group.get("created_at") or time.time())
        session_updated = float(group.get("updated_at") or session_created)
        turns = group.get("turns") or []
        n_turns = len(turns)
        for i, t in enumerate(turns):
            if not t.get("created_at"):
                if n_turns <= 1 or session_updated <= session_created:
                    t["created_at"] = session_created
                else:
                    t["created_at"] = session_created + (session_updated - session_created) * (i / (n_turns - 1))
        self.groups[key] = group
        restored = self._restore_reviews(group)
        if group["status"] == "review":
            group["status"] = "idle"
            restored = True
        if restored:
            self._save(group)
        active = self._active(group)
        if group.get("status") in ("running", "recovering") or active and active["state"] in ("running", "interrupting"):
            group["recovery_was_paused"] = group.get("status") == "paused"
            # The previous worker cannot be trusted to have done nothing. First
            # try its saved completion/provider history, without executing it.
            group["status"] = "recovering"
            group["notice"] = "Checking the interrupted agent turn after a server restart…"
            self._save(group)
            self._start_recovery(key)
        elif group.get("status") == "idle":
            self._start_worker(key)
        return group

    def _restore_reviews(self, group: dict[str, Any]) -> bool:
        changed = False
        for turn in group["turns"]:
            if not turn.get("review_pending"):
                continue
            cid = turn.get("tool_conversation_id")
            try:
                available = cid and (self.manager._conversations.get(cid) or self.store.read("reviews", cid))
            except GroupRuntimeError:
                available = False
            if not available:
                turn["review_pending"] = False
                turn["review_unavailable"] = True
                group["notice"] = "An older review was lost when the server restarted. Your edits remain saved; use file history to inspect them. This no longer blocks messages."
                changed = True
        return changed

    @staticmethod
    def _review_pending(group: dict[str, Any]) -> bool:
        return any(turn.get("review_pending") for turn in group["turns"])

    def command(self, body: dict[str, Any]) -> dict[str, Any]:
        key = identifier(body.get("group_id"))
        action = body.get("action", "state")
        with self.lock:
            group = self._load(key, body.get("initial"))
            if action == "state":
                return self._public(group, unchanged=body.get("after_revision") == group.get("revision"))
            request_id = identifier(body.get("request_id"))
            previous = group["commands"].get(request_id)
            if previous:
                if previous != action:
                    raise GroupRuntimeError("A Group request id was reused for another action")
                return self._public(group)
            steer_request: dict[str, Any] | None = None
            stop_run_id: str | None = None
            if action == "submit":
                steer_request, stop_run_id = self._submit(group, body)
            elif action == "preset":
                self._preset(group, body)
            elif action == "remove":
                target = identifier(body.get("message_id"))
                steps = [step for step in group["steps"] if step.get("message_id") == target]
                if not steps or any(step["state"] != "queued" for step in steps):
                    raise GroupRuntimeError("That message has already started")
                for step in steps:
                    step["state"] = "cancelled"
            elif action == "models":
                if group["status"] in ("running", "recovering"):
                    raise GroupRuntimeError("Wait for the current invitation before changing models")
                pair = clean_participants(body.get("participants"))
                # Only model/effort overrides can change in a running Group.
                for old, new in zip(group["participants"], pair):
                    if {k: v for k, v in old.items() if k not in ("model", "effort")} != {k: v for k, v in new.items() if k not in ("model", "effort")}:
                        raise GroupRuntimeError("Participants stay fixed after the Group starts")
                group["participants"] = pair
            elif action == "reviewed":
                cid = identifier(body.get("conversation_id"))
                outstanding = self.manager.turn_file_changes(cid)
                if outstanding["files"]:
                    raise GroupRuntimeError("Finish reviewing the outstanding changes first")
                for turn in group["turns"]:
                    if turn.get("tool_conversation_id") == cid:
                        turn["review_pending"] = False
                if group["status"] == "review":
                    group["status"] = "idle"
            elif action == "stop":
                group["status"] = "paused"
                group["notice"] = "Discussion stopped. Remaining invitations are saved."
                active = self._active(group)
                if active:
                    active["state"] = "interrupting"
                    # Calling the agent is kept outside the Group lock below.
            elif action in ("resume", "retry", "skip"):
                active = self._active(group)
                if active and active["state"] in ("running", "interrupting"):
                    raise GroupRuntimeError("Wait for the current agent to stop")
                if active and active["state"] == "interrupted":
                    if action == "resume":
                        raise GroupRuntimeError("Choose Retry or Skip for the interrupted invitation")
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
                        group["native_threads"].pop(str(active["seat"]), None)
                    group["active_step"] = ""
                group["status"] = "idle"
                group["notice"] = ""
                group["error"] = ""
            elif action == "preferences":
                # Legacy plan ticks/TODO/applied state do not own the transcript.
                raw = _clean_group_session({**group, "plans": body.get("plans", group.get("plans", []))})
                group["plans"] = raw["plans"] if raw else []
            else:
                raise GroupRuntimeError("Unknown Group action")
            group["commands"][request_id] = str(action)
            self._save(group)
            run_id = (self._active(group) or {}).get("run_id") if action == "stop" else stop_run_id
            if action != "stop":
                self._start_worker(key)
            result = self._public(group)
        if steer_request is not None:
            fallback_stop_id = self._execute_steer(key, steer_request)
            with self.lock:
                group = self.groups[key]
                result = self._public(group)
            if fallback_stop_id:
                run_id = fallback_stop_id
        if run_id:
            self.manager.stop_group_turn(run_id)
        return result

    def _submit(self, group: dict[str, Any], body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise GroupRuntimeError("A Group message cannot be empty")
        if len(text.encode()) > 128 * 1024:
            raise GroupRuntimeError("The Group message is too large")
        seats = body.get("seats")
        if seats is None:
            text_str = str(text or "")
            if re.search(r"(?:^|[\s(])@(all|everyone)(?=$|[\s.,!?:;)\]'’])", text_str, re.IGNORECASE):
                seats = [1, 2]
            else:
                last_seat = next((turn["seat"] for turn in reversed(group.get("turns", [])) if turn.get("role") == "critic" and turn.get("seat") in (1, 2)), None)
                seats = [last_seat] if last_seat in (1, 2) else [1, 2]
        if not isinstance(seats, list) or not seats or any(type(s) is not int or s not in (1, 2) for s in seats) or len(set(seats)) != len(seats):
            raise GroupRuntimeError("Choose one or both participants")
        mid = identifier(body.get("message_id"))
        if any(step.get("message_id") == mid for step in group["steps"]):
            raise GroupRuntimeError("That message id is already in use")
        scene = body.get("scene") or group["scene"]
        if not isinstance(scene, str) or self.manager._scene_file(scene) is None:
            raise GroupRuntimeError("Open a manuscript scene before sending to the Group")
        self.manager.context.build_mentions({"kind": "scene", "path": scene}, text, mentions=body.get("attachments") or [])
        live_document = body.get("live_document")
        self.manager._validated_live_document({"kind": "scene", "path": scene}, live_document)
        choices = self._review_choices(body)
        authored = str(body.get("authored") or re.split(r"\n\nSelected passage(?:\s*\([^)\n]*\))?:\n", text, maxsplit=1)[0])
        attachments = copy.deepcopy(body.get("attachments") or [])
        created_at = body.get("created_at") or time.time()
        steps = [
            {"id": uuid.uuid4().hex, "message_id": mid, "seat": seat,
             "state": "queued", "scene": scene, "text": text, "authored": authored,
             "settle_reviews": index == 0, "review_choices": copy.deepcopy(choices) if index == 0 else [],
             "live_document": copy.deepcopy(live_document), "attachments": copy.deepcopy(attachments),
             "created_at": created_at, "kind": "message"}
            for index, seat in enumerate(seats)
        ]
        immediate = bool(body.get("immediate")) or body.get("mode") == "now"
        if not immediate:
            group["steps"].extend(steps)
            if group["status"] == "idle":
                group["error"] = ""
            return None, None

        active = self._active(group)
        if active and active["state"] in ("running", "interrupting"):
            if active.get("kind") == "message" and active.get("message_id"):
                for queued in group["steps"]:
                    if queued["state"] == "queued" and queued.get("message_id") == active["message_id"]:
                        queued["state"] = "cancelled"
            insert_at = group["steps"].index(active) + 1
            active_agent = group["participants"][active["seat"] - 1]["agent"]
            can_steer = active["state"] == "running" and active_agent == "codex" and seats[0] == active["seat"]
            if can_steer:
                # Steer injects into the active Codex turn: show the writer's
                # message immediately and queue any second tagged seat right behind.
                active["steered"] = True
                group["turns"].append({
                    "role": "user", "label": "Me (Writer)", "scene": scene, "text": text,
                    "message_id": mid, "attachments": copy.deepcopy(attachments), "created_at": created_at,
                })
                group["steps"][insert_at:insert_at] = steps[1:]
                return {
                    "active_id": active["id"],
                    "run_id": active.get("run_id") or "",
                    "seat": active["seat"],
                    "scene": scene,
                    "text": text,
                    "authored": authored,
                    "attachments": copy.deepcopy(attachments),
                    "message_id": mid,
                    "fallback_step": steps[0],
                }, None
            active["superseded"] = True
            group["steps"][insert_at:insert_at] = steps
            stop_run_id = None
            if active["state"] == "running":
                active["state"] = "interrupting"
                stop_run_id = active.get("run_id") or None
            group["error"] = ""
            group["notice"] = ""
            return None, stop_run_id

        if active and active["state"] == "interrupted":
            active["state"] = "cancelled"
            group["active_step"] = ""
        first_queued = next((i for i, queued in enumerate(group["steps"]) if queued["state"] == "queued"), len(group["steps"]))
        group["steps"][first_queued:first_queued] = steps
        group["status"] = "idle"
        group["error"] = ""
        group["notice"] = ""
        return None, None

    def _execute_steer(self, key: str, steer_request: dict[str, Any]) -> str | None:
        ok = self.manager.steer_group_turn(
            steer_request["run_id"],
            scene=steer_request["scene"],
            text=steer_request["text"],
            authored=steer_request["authored"],
            seat=steer_request["seat"],
            attachments=steer_request["attachments"],
            message_id=steer_request["message_id"],
        )
        if ok:
            return None
        fallback_stop_id: str | None = None
        with self.lock:
            group = self.groups.get(key)
            if group is None:
                return None
            mid = steer_request["message_id"]
            # Undo optimistic user turn so the fallback step emits it in true turn order.
            group["turns"] = [turn for turn in group["turns"] if turn.get("message_id") != mid]
            active = next((step for step in group["steps"] if step["id"] == steer_request["active_id"]), None)
            follow_idx = next((i for i, step in enumerate(group["steps"]) if step.get("message_id") == mid), None)
            if active is not None and active["state"] == "running" and active.get("run_id") == steer_request["run_id"]:
                active.pop("steered", None)
                active["superseded"] = True
                active["state"] = "interrupting"
                insert_at = follow_idx if follow_idx is not None else group["steps"].index(active) + 1
                group["steps"].insert(insert_at, steer_request["fallback_step"])
                fallback_stop_id = steer_request["run_id"] or None
            else:
                insert_at = follow_idx if follow_idx is not None else next(
                    (i for i, step in enumerate(group["steps"]) if step["state"] == "queued"),
                    len(group["steps"]),
                )
                group["steps"].insert(insert_at, steer_request["fallback_step"])
                self._start_worker(key)
            self._save(group)
        return fallback_stop_id

    @staticmethod
    def _review_choices(body: dict[str, Any]) -> list[dict[str, Any]]:
        choices = body.get("review_choices") or []
        if not isinstance(choices, list) or any(not isinstance(row, dict)
                or not isinstance(row.get("conversation_id"), str) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("fingerprint"), str) or not row["fingerprint"]
                or not isinstance(row.get("drop"), list)
                or any(type(block) is not int or block < 0 for block in row["drop"]) for row in choices):
            raise GroupRuntimeError("Reopen the change review before sending its choices")
        return choices

    def _settle_reviews(self, group: dict[str, Any], step: dict[str, Any]) -> None:
        """A new writer message keeps saved edits, honoring explicit unticks.

        Run only at the writer-message boundary, between agent calls. Agent
        replies and preset invitations never require a separate review action.
        Persist each completed review so recovery cannot apply an undo twice.
        """
        for turn in group["turns"]:
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
            self._save(group)
        step["reviews_settled"] = True
        self._save(group)

    def _preset(self, group: dict[str, Any], body: dict[str, Any]) -> None:
        preset_id = str(body.get("preset_id") or "")
        preset = next((p for p in self.manager.group_settings()["library"]["presets"] if p["id"] == preset_id), {})
        workflow = preset.get("kind") == "workflow"
        if workflow and not any(t.get("role") == "critic" and not t.get("passed") for t in group["turns"]):
            raise GroupRuntimeError("Ask for an answer before starting Second opinion & recap")
        append = bool(body.get("append"))
        if not append and (group["turns"] or group["steps"]):
            raise GroupRuntimeError("Start a new Group before running a preset")
        if append and (group["status"] != "idle" or any(s["state"] in ("queued", "running", "interrupting") for s in group["steps"])):
            raise GroupRuntimeError("Wait for the current invitations to finish before continuing")
        invitations = body.get("invitations")
        if workflow:
            # Both entry points execute the shared definition, including its recap.
            invitations = copy.deepcopy(preset["invitations"])
            if preset.get("recap"):
                invitations.append({"seat": preset["recap"], "recap": True, "prompt": SECOND_OPINION_RECAP})
        min_steps = 1 if append else 2
        if not isinstance(invitations, list) or not min_steps <= len(invitations) <= 13:
            raise GroupRuntimeError("A preset needs 2–12 invitations plus its optional recap")
        for step in invitations:
            if not isinstance(step, dict) or type(step.get("seat")) is not int or step["seat"] not in (1, 2) or not isinstance(step.get("prompt"), str) or not step["prompt"].strip():
                raise GroupRuntimeError("Invalid preset invitation")
        for agent in {group["participants"][step["seat"] - 1]["agent"] for step in invitations}:
            try:
                self.manager._probe_agent(agent)
            except Exception as exc:
                raise GroupRuntimeError(f"{agent.title()} is unavailable: {exc}") from exc
        for step in invitations:
            group["steps"].append({"id": uuid.uuid4().hex, "seat": step["seat"], "state": "queued",
                "kind": "invitation", "prompt": step["prompt"], "recap": bool(step.get("recap")),
                "positions_table": bool(body.get("positions_table", preset.get("positions_table", False))),
                "preset_kind": preset.get("kind", "task"),
                "attachments": copy.deepcopy(step.get("attachments") or [])})
        if preset_id:
            group["preset_id"] = preset_id
            group["preset_kind"] = preset.get("kind", "task")
        if append:
            total_invitations = sum(1 for s in group["steps"] if s.get("kind") == "invitation" and not s.get("recap") and s.get("state") != "cancelled")
            has_recap = any(s.get("recap") for s in invitations)
            group["badge"] = f"{total_invitations} invitations" + (" + recap" if has_recap else "")

    def _active(self, group: dict[str, Any]) -> dict[str, Any] | None:
        return next((step for step in group["steps"] if step["id"] == group.get("active_step")), None)

    def _public(self, group: dict[str, Any], *, unchanged: bool = False) -> dict[str, Any]:
        def public_live(value):
            if value:
                value = copy.deepcopy(value)
                value["draft"] = visible_reply(str(value.get("draft") or ""), streaming=True)
            return value
        if unchanged:
            active = self._active(group)
            return {"id": group["id"], "revision": group["revision"], "status": group["status"], "unchanged": True,
                    "live": public_live(self.manager.group_progress(active.get("run_id", ""))) if active and group["status"] == "running" else None,
                    "partial_reply": visible_reply((active or {}).get("draft", ""), streaming=True)}
        result = {key: copy.deepcopy(value) for key, value in group.items() if key not in ("commands", "native_threads", "version", "fork_context")}
        result["acknowledged_requests"] = list(group["commands"])
        result["title"] = group_title(group)
        active = self._active(group)
        result["live"] = public_live(self.manager.group_progress(active.get("run_id", ""))) if active and group["status"] == "running" else None
        # A disk checkpoint is also readable if the process died between a
        # streamed reply and committing its completed transcript entry.
        if active and not (result["live"] or {}).get("running"):
            result["partial_reply"] = visible_reply(active.get("draft", ""), streaming=True)
        for step in result["steps"]:
            if step.get("draft"):
                step["draft"] = visible_reply(step["draft"], streaming=True)
            for key in ("live_content", "live_document", "native_reply", "native_status", "signature", "native_thread_id", "native_turn_id"):
                step.pop(key, None)
        return result

    def _start_worker(self, key: str) -> None:
        group = self.groups[key]
        if self.closing or group["status"] != "idle" or not any(step["state"] == "queued" for step in group["steps"]):
            return
        old = self.workers.get(key)
        if old and old.is_alive():
            return
        worker = threading.Thread(target=self._work, args=(key,), daemon=True, name=f"group-{key}")
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
                group = self.groups[key]
                if group.get("deleted") or group["status"] != "idle":
                    return
                step = next((step for step in group["steps"] if step["state"] == "queued"), None)
                if step is None:
                    return
                step["state"] = "running"
                step["run_id"] = uuid.uuid4().hex
                group["active_step"] = step["id"]
                group["status"] = "running"
                group["owner"] = self.generation
                group["error"] = ""
                if step["kind"] == "message":
                    new_message = not any(turn.get("message_id") == step["message_id"] for turn in group["turns"])
                    step.setdefault("settle_reviews", new_message)
                    if new_message:
                        group["turns"].append({"role": "user", "label": "Me (Writer)", "scene": step.get("scene") or group["scene"], "text": step["text"], "message_id": step["message_id"], "attachments": copy.deepcopy(step.get("attachments") or []), "created_at": step.get("created_at") or time.time()})
                    authored = step["authored"]
                else:
                    if not any(turn.get("step_id") == step["id"] for turn in group["turns"]):
                        profile = group["participants"][step["seat"] - 1]
                        group["turns"].append({"role": "invitation", "label": "Preset", "seat": step["seat"],
                            "recap": step.get("recap", False), "step_id": step["id"], "text": f"@{profile['handle']}, {step['prompt']}", "attachments": copy.deepcopy(step.get("attachments") or []),
                            "created_at": step.get("created_at") or time.time()})
                    authored = step["prompt"]
                if step.get("retry"):
                    recovery_id = step["id"] + "-retry-" + str(step.get("attempt", 0))
                    if not any(turn.get("step_id") == recovery_id for turn in group["turns"]):
                        group["turns"].append({"role": "invitation", "label": "Recovery", "step_id": recovery_id,
                            "text": "The previous attempt was interrupted. Check the current files before continuing this request. Preserve work already applied; do not repeat edits blindly.",
                            "created_at": time.time()})
                self._save(group)
                history = copy.deepcopy(group["turns"])
                participants = copy.deepcopy(group["participants"])
                scene, run_id = step.get("scene") or group["scene"], step["run_id"]
                native = copy.deepcopy(group["native_threads"].get(str(step["seat"])))
            try:
                self.context.group_id, self.context.step_id = key, step["id"]
                self.context.fork_context = copy.deepcopy(group.get("fork_context"))
                if self.context.fork_context:
                    current = self.manager.context._document_target({"kind": "scene", "path": scene}).relative_to(self.manager.root).as_posix()
                    if current not in self.context.fork_context["files"]:
                        self.context.fork_context["files"].append(current)
                    if step.get("live_document") is not None:
                        self.context.fork_context["scene"] = scene
                        self.context.fork_context["live_document"] = step["live_document"]
                self.context.positions_table = bool(step.get("positions_table"))
                self.context.previous_review_id = step.get("previous_review_id") or (native or {}).get("conversation_id", "")
                seat_key = f"{key}:{step['seat']}"
                if native:
                    self.manager._group_threads[seat_key] = native
                elif step.get("retry"):
                    self.manager._group_threads.pop(seat_key, None)
                skill = self.manager._group_skill_from_text(participants[step["seat"] - 1]["agent"], authored)
                attachments = self.manager._group_references(history)
                with self.lock:
                    if step["state"] != "running":
                        raise GroupRuntimeError("Stopped by writer")
                    if step.get("settle_reviews") and not step.get("reviews_settled"):
                        self._settle_reviews(group, step)
                live_content = self.manager._validated_live_document({"kind": "scene", "path": scene}, step.get("live_document"))
                result = self.manager.run_group_turn(scene=scene, live_content=live_content or "",
                    seat=step["seat"], turn_index=sum(t["role"] == "critic" for t in history) + 1,
                    history=history, participants=participants, attachments=attachments, skill=skill,
                    debate_id=key, run_id=run_id, preset_id=group.get("preset_id", ""))
                with self.lock:
                    if self.closing or self.groups[key].get("deleted"):
                        return
                    group = self.groups[key]
                    self._finish(group, step, result)
                    native = self.manager._group_threads.get(seat_key)
                    if native:
                        if step.get("steered"):
                            native["seen"] = len(group["turns"])
                        group["native_threads"][str(step["seat"])] = copy.deepcopy(native)
                    self._save(group)
                    if group["status"] != "idle":
                        return
            except Exception as exc:
                with self.lock:
                    if self.closing:
                        return
                    group = self.groups[key]
                    if step.get("superseded"):
                        step["state"] = "cancelled"
                        try:
                            self._attach_interrupted_review(group, step)
                        except Exception as review_error:
                            group["notice"] = "The interrupted review could not be restored: " + str(review_error)
                        group["active_step"] = ""
                        group["status"] = "idle"
                        group["notice"] = ""
                        group["error"] = ""
                        self._save(group)
                        continue
                    step["state"] = "interrupted"
                    # Failures are visible recovery choices, not an invitation
                    # that can disappear from an otherwise open conversation.
                    try:
                        self._attach_interrupted_review(group, step)
                    except Exception as review_error:
                        group["notice"] = "The interrupted review could not be restored: " + str(review_error)
                    group["status"] = "interrupted"
                    group["error"] = str(exc)
                    self._save(group)
                return
            finally:
                self.context.group_id = self.context.step_id = ""
                self.context.fork_context = None
                self.context.positions_table = False

    def _finish(self, group: dict[str, Any], step: dict[str, Any], result: dict[str, Any]) -> None:
        was_paused = group["status"] == "paused" and not step.get("superseded")
        step["state"] = "passed" if result.get("passed") else "completed"
        profile = group["participants"][step["seat"] - 1]
        if not any(turn.get("step_id") == step["id"] and turn["role"] == "critic" for turn in group["turns"]):
            group["turns"].append({"role": "critic", "step_id": step["id"], "seat": step["seat"], "scene": step.get("scene") or group["scene"],
                "agent": result["agent"], "model": result.get("model", ""), "label": profile["name"] + " · " + result["agent"].title(),
                "tag": "Recap" if step.get("recap") else "Reply", "text": visible_reply(result.get("reply", "")), "passed": bool(result.get("passed")),
                "stances": extract_stances(result.get("reply", "")),
                "preset_kind": step.get("preset_kind", "task"),
                "changed_files": result.get("changed_files", []),
                "tool_conversation_id": result.get("tool_conversation_id", ""),
                "review_pending": bool(result.get("changed_files") or result.get("unreviewable")),
                "created_at": result.get("created_at") or time.time(),
                "duration_ms": result.get("duration_ms"),
                **({"context_sent": result["context_sent"]} if result.get("context_sent") else {})})
            if step.get("recap") and step.get("positions_table"):
                group["turns"][-1]["positions"] = positions_table(group["turns"])
        if step.get("native_cache"):
            group["native_threads"][str(step["seat"])] = step["native_cache"]
        group["active_step"] = ""
        group["status"] = "paused" if was_paused else "idle"
        group["notice"] = ""
        group["error"] = ""

    def _attach_interrupted_review(self, group: dict[str, Any], step: dict[str, Any]) -> None:
        cid = step.get("tool_conversation_id")
        if not cid or not self.store.read("reviews", cid):
            return
        changes = self.manager.turn_file_changes(cid)
        if not changes["files"] and not changes["unreviewable"]:
            return
        interrupted_id = step["id"] + "-interrupted-" + str(step.get("attempt", 0))
        if any(turn.get("step_id") == interrupted_id for turn in group["turns"]):
            return
        profile = group["participants"][step["seat"] - 1]
        group["turns"].append({"role": "critic", "step_id": interrupted_id, "seat": step["seat"], "agent": profile["agent"],
            "label": profile["name"] + " · " + profile["agent"].title() + " · interrupted reply (incomplete)", "text": step.get("draft") or "This invitation was interrupted. Review any saved changes before retrying or skipping it.",
            "tag": "Interrupted", "tool_conversation_id": cid, "review_pending": True, "created_at": time.time()})

    def checkpoint(self, group_id: str, step_id: str, fields: dict[str, Any]) -> None:
        with self.lock:
            group = self.groups.get(group_id)
            if group is None:
                return
            step = next((step for step in group["steps"] if step["id"] == step_id), None)
            if not step or step["state"] not in ("running", "interrupting"):
                return
            if fields.get("run_id") and fields["run_id"] != step.get("run_id"):
                return
            step.update(fields)
            # Checkpoints do not cause the UI to redraw its composer on every token.
            self.store.write("groups", group_id, group)

    def _start_recovery(self, key: str) -> None:
        worker = threading.Thread(target=self._recover, args=(key,), daemon=True, name=f"recover-group-{key}")
        self.workers[key] = worker
        worker.start()

    def _recover(self, key: str) -> None:
        with self.lock:
            group = self.groups[key]
            step = self._active(group)
            saved = copy.deepcopy(step)
        result = None
        if saved:
            try:
                result = self.manager._recover_group_result(saved, group["participants"])
            except Exception:
                # Not knowing the result is an interruption, never permission
                # to repeat a potentially mutating invitation.
                result = None
        with self.lock:
            if self.closing:
                return
            group = self.groups[key]
            if step is not None and result:
                self._finish(group, step, result)
                if group.pop("recovery_was_paused", False):
                    group["status"] = "paused"
                    group["notice"] = "The stopped invitation finished before the restart. Remaining invitations are saved until you resume."
            else:
                if step:
                    step["state"] = "interrupted"
                    try:
                        self._attach_interrupted_review(group, step)
                    except Exception as exc:
                        group["error"] = "The saved review could not be read: " + str(exc)
                group["status"] = "interrupted"
                group["notice"] = "The server restarted during an invitation. Any available partial reply and saved changes are preserved. Review changes, then choose Retry or Skip; nothing will be repeated automatically."
            self._save(group)
            # Completed recovery can safely run the remaining invitations.
            self.workers.pop(key, None)
            if result and group["status"] == "idle":
                self._start_worker(key)

    def delete(self, key: str) -> None:
        run_id = None
        with self.lock:
            record = self.groups.get(key) or self.store.read("groups", key)
            if record:
                record["deleted"] = True
                active = self._active(record)
                run_id = (active or {}).get("run_id")
                record["status"] = "paused"
                self._save(record)
        if run_id:
            self.manager.stop_group_turn(run_id)

    def close(self) -> None:
        with self.lock:
            self.closing = True
            for group in self.groups.values():
                if group["status"] == "running":
                    group["notice"] = "The server stopped during this invitation. Its result will be checked when the Group reopens."
                    self._save(group)
