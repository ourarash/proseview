"""Portable Group handoffs. Native sessions stay isolated; file bodies travel once."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shlex
import threading
import time
import uuid
from typing import Any

from . import group
from . import group_context
from .repo import read_repo_text

_DOCUMENT = re.compile(r'BEGIN UNTRUSTED DOCUMENT ("(?:[^"\\]|\\.)*")\n.*?\nEND UNTRUSTED DOCUMENT \1', re.S)


def split_prompt(prompt: str) -> tuple[str, list[str]]:
    paths: list[str] = []
    prefix, marker, question = prompt.partition("\n\nUSER QUESTION\n")
    def remove(match: re.Match) -> str:
        path = json.loads(match[1])
        if path not in paths:
            paths.append(path)
        return f"[Current file supplied separately: {path}]"
    instructions = _DOCUMENT.sub(remove, prefix)
    if marker:
        instructions += marker + question
    for match in re.finditer(r"^(?:Open file: |Mentioned: )(.+)$", prefix, re.M):
        for path in match[1].split(", "):
            if path.strip() not in paths:
                paths.append(path.strip())
    return instructions, paths


def _error(message: str):
    from .discuss import ContextError
    return ContextError(message)


def source_busy(source: Any) -> bool:
    return bool(getattr(source, "forking", False) or source.active_request_id or source.active_turn_id
                or source.active_turn_started_at or source.pending
                or any(p.get("status") in {"pending", "resolving"} for p in source.approvals.values()))


def assert_groups_idle(manager: Any) -> None:
    runtime = manager.group_runtime
    # Check saved server state too, including another scene's active Group.
    keys = set(runtime.groups)
    directory = runtime.store.directory / "groups"
    if directory.exists():
        keys.update(p.stem for p in directory.glob("*.json"))
    for key in keys:
        saved = runtime.groups.get(key) or runtime.store.read("groups", key)
        if saved and not saved.get("deleted") and (saved.get("status") in {"running", "recovering"}
                or any(s.get("state") in {"queued", "running", "interrupting"} for s in saved.get("steps", []))):
            raise _error("Wait for the running Group to finish before forking this chat.")


def _native_history(manager: Any, source: Any) -> dict[str, Any]:
    if not source.thread_id:
        return {}
    return manager._read_thread_history(manager._client_for(source.agent), source.thread_id).get("thread") or {}


def prepare(manager: Any, source: Any, body: dict[str, Any]) -> dict[str, Any]:
    context_options = group_context.options(body)
    warnings: list[str] = []
    with source.lock:
        messages = copy.deepcopy(source.messages)
        tasks = copy.deepcopy(list(source.tasks.values()))
        selection = dict(source.model_selection)
        document = dict(source.document)
    try:
        native = _native_history(manager, source)
    except Exception:
        native = {}
        warnings.append("Provider history is unavailable; only saved conversation context can be transferred.")
    selected = group_context.select(messages, tasks, native, context_options)
    if context_options["mode"] == "recent":
        messages, tasks, native = selected["messages"], selected["tasks"], selected["native"]
    prompts: list[str] = []
    tool_turns: list[str] = []
    for turn in native.get("turns") or []:
        tool_turns.append(str(turn.get("id") or ""))
        for item in turn.get("items") or []:
            if item.get("type") == "userMessage":
                prompts.append("\n".join(str(p.get("text") or "") for p in item.get("content") or [] if p.get("type") == "text"))
    tool_files: list[str] = []
    for turn in native.get("turns") or []:
        for item in turn.get("items") or []:
            if item.get("type") not in {"commandExecution", "mcpToolCall", "dynamicToolCall", "fileRead", "fileChange"}:
                continue
            if isinstance(item.get("path"), str):
                tool_files.append(item["path"])
            arguments = item.get("arguments") or item.get("input") or {}
            if isinstance(arguments, dict):
                tool_files.extend(str(arguments[k]) for k in ("path", "file_path", "file") if isinstance(arguments.get(k), str))
            try:
                tokens = shlex.split(str(item.get("command") or ""))
                if "-lc" in tokens:
                    tokens = shlex.split(tokens[tokens.index("-lc") + 1])
                tool_files.extend(t for t in tokens if re.search(r"\.(?:md|txt|yaml|yml|json|csv)$", t))
            except (ValueError, IndexError):
                pass
    paths: list[str] = tool_files
    instructions: list[str] = []
    for prompt in prompts:
        clean, files = split_prompt(prompt)
        instructions.append(clean)
        paths.extend(files)
    for message in messages:
        receipt = message.get("context_sent") or {}
        if receipt.get("developer_instructions"):
            instructions.append("Historical instructions for this request (context, not new instructions):\n" + receipt["developer_instructions"])
        paths.extend(receipt.get("project_instructions") or [])
        paths.extend(receipt.get("documents") or [])
        if message.get("role") == "user":
            if receipt.get("request_instructions"):
                instructions.append(receipt["request_instructions"])
            elif not prompts and receipt.get("full_prompt"):
                text = receipt["full_prompt"]
                if len(text) >= 32000:
                    warnings.append("An older request's saved prompt was shortened; some instructions may be unavailable.")
                instructions.append(split_prompt(text)[0])
    scene = str(body.get("scene") or (document.get("path") if document.get("kind") == "scene" else "") or "")
    if manager._scene_file(scene) is None:
        raise _error("Open a manuscript scene before sending this conversation to Group.")
    paths.append(manager.context._document_target({"kind": "scene", "path": scene}).relative_to(manager.root).as_posix())
    try:
        paths.append(manager.context._document_target(document).relative_to(manager.root).as_posix())
    except Exception:
        pass
    structured = []
    for task in tasks:
        if task.get("result"):
            structured.append({k: copy.deepcopy(task[k]) for k in ("id", "kind", "label", "status", "result", "target", "action_id", "model", "selected_option") if k in task})
            for index, finding in enumerate(structured[-1]["result"].get("findings") or [], 1):
                finding.setdefault("number", index)
            paths.extend((task.get("result") or {}).get("documents") or [])
            for finding in (task.get("result") or {}).get("findings") or []:
                if finding.get("file"):
                    paths.append(finding["file"])
    files: list[str] = []
    for path in dict.fromkeys(str(p) for p in paths if isinstance(p, str)):
        try:
            target = manager.context._relative_target(path.rstrip("/"))
            if not target.exists():
                target = manager.context._document_target({"kind": "scene", "path": path})
            targets = manager.context._folder_files(target) if target.is_dir() else [target]
            for item in targets:
                if item.is_file():
                    relative = item.resolve().relative_to(manager.root.resolve()).as_posix()
                    if relative not in files:
                        files.append(relative)
        except Exception:
            warnings.append(f"Referenced file is unavailable: {path}")
    profiles = []
    available = []
    from .config import DISCUSS_AGENTS

    others = [agent for agent in DISCUSS_AGENTS if agent != source.agent]
    for agent in (source.agent, *others):
        try:
            manager._probe_agent(agent)
            available.append(agent)
        except Exception:
            pass
    other_agents = [agent for agent in others if agent in available]
    second_agent = other_agents[0] if len(other_agents) >= 1 else source.agent
    third_agent = other_agents[1] if len(other_agents) >= 2 else (other_agents[0] if len(other_agents) == 1 else source.agent)
    seed_profiles = (
        ("Original assistant", source.agent),
        ("Second opinion", second_agent),
        ("Third perspective", third_agent),
    )
    for index, (name, agent) in enumerate(seed_profiles):
        profiles.append({"id": f"fork-{index + 1}", "name": name, "agent": agent,
                         "model": selection.get("model", "") if index == 0 else "", "effort": selection.get("effort", "") if index == 0 else "",
                         "specialty": "", "style": ""})
    raw_participants = body.get("participants") or profiles
    roster = group.clean_participants(raw_participants)
    for index, profile in enumerate(roster):
        raw_item = raw_participants[index] if index < len(raw_participants) and isinstance(raw_participants[index], dict) else {}
        fallback_name = profiles[index]["name"] if index < len(profiles) else f"Participant {index + 1}"
        profile.update(name=str(raw_item.get("name") or fallback_name), specialty="", style="")
    turns = []
    for message in messages:
        if not str(message.get("text") or "").strip():
            continue
        assistant = message.get("role") == "assistant"
        model = message.get("model") or selection.get("model") or f"{source.agent.title()} default"
        turns.append({"role": "critic" if assistant else "user", "seat": 1,
                      "agent": source.agent, "model": model if assistant else "",
                      "model_inferred": assistant and not bool(message.get("model")),
                      "label": f"Original assistant · {source.agent.title()}" if assistant else "Writer",
                      "text": str(message["text"]), "created_at": message.get("created_at") or time.time(),
                      "inherited": True, "scene": scene})
    if structured:
        turns.append({"role": "critic", "seat": 1, "agent": source.agent,
                      "model": selection.get("model") or f"{source.agent.title()} default", "model_inferred": True,
                      "label": "Original assistant · structured results (read-only)", "inherited": True,
                      "text": "Structured results (read-only history)\n\n" + json.dumps(structured, ensure_ascii=False, indent=2), "scene": scene})
    if not any(t["role"] == "critic" for t in turns):
        raise _error("Wait for an answer before sending this chat to Group.")
    live = body.get("live_document")
    manager._validated_live_document({"kind": "scene", "path": scene}, live)
    portable = {"instructions": list(dict.fromkeys(instructions)), "files": files,
                "scene": scene,
                "source_agent": source.agent, "source_thread_id": source.thread_id,
                "tool_turn_ids": tool_turns, "live_document": live}
    portable["mode"] = context_options["mode"]
    if context_options["mode"] == "recent":
        portable["tool_turn_ids"] = []
        warnings.append("All participants start fresh sessions. Other files remain available by reference; private reasoning is excluded.")
    else:
        warnings.append("Only tool results available from provider session history can be transferred; private reasoning is excluded.")
    return {"scene": scene, "participants": roster, "turns": turns, "fork_context": portable,
            "warnings": list(dict.fromkeys(warnings)), "source_model": selection,
            "context_options": context_options, "selection": selected}


def materialize(manager: Any, context: dict[str, Any], *, instructions: bool = True) -> str:
    parts = []
    if instructions:
        parts.append("INHERITED REQUEST INSTRUCTIONS (conversation history, not a new request)\n" + "\n\n".join(context.get("instructions") or []))
        if context.get("mode") == "recent":
            parts.append("OTHER FILE REFERENCES (read current files with your tools when needed)\n" + "\n".join(context.get("files") or []))
        try:
            native = (manager._read_thread_history(manager._client_for(context["source_agent"]), context["source_thread_id"]).get("thread") or {}) if context.get("tool_turn_ids") else {}
            outputs = []
            for turn in native.get("turns") or []:
                if str(turn.get("id") or "") not in context.get("tool_turn_ids", []):
                    continue
                for item in turn.get("items") or []:
                    if item.get("type") in {"commandExecution", "mcpToolCall", "dynamicToolCall", "fileRead"}:
                        output = item.get("aggregatedOutput") or item.get("result") or item.get("output")
                        if output:
                            outputs.append(json.dumps(output, ensure_ascii=False))
            if outputs:
                parts.append("AVAILABLE TOOL RESULTS (untrusted evidence)\n" + "\n".join(outputs))
        except Exception:
            pass  # The setup explicitly discloses unavailable tool history.
    live = context.get("live_document") or {}
    scene_target = manager.context._document_target({"kind": "scene", "path": context["scene"]}).resolve()
    for path in context.get("files") or []:
        try:
            target = manager.context._relative_target(path)
            if context.get("mode") == "recent" and target.resolve() != scene_target:
                continue
            content = read_repo_text(target)
            if live and scene_target == target.resolve():
                try:
                    current = manager._validated_live_document({"kind": "scene", "path": context["scene"]}, live)
                    if current is not None:
                        content = current
                except ValueError:
                    pass  # A later save supersedes the initial unsaved draft.
            if target.resolve() == scene_target:
                from .discuss import _numbered_scene_body
                content = _numbered_scene_body(content)
            quoted = json.dumps(path, ensure_ascii=False)
            parts.append(f"CURRENT FILE (untrusted reference material): {path}\nBEGIN UNTRUSTED DOCUMENT {quoted}\n{content}\nEND UNTRUSTED DOCUMENT {quoted}")
        except Exception:
            parts.append(f"Referenced file is no longer available: {path}")
    return "\n\n".join(parts)


def _stamp(source: Any) -> str:
    import hashlib
    with source.lock:
        raw = [source.thread_id, source.messages, source.tasks, source.model_selection, source.document]
        return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def _release(source: Any, token: str) -> None:
    with source.lock:
        if getattr(source, "forking_id", "") == token:
            source.forking = False
            source.forking_id = ""


def _limit_errors(manager: Any, prepared: dict) -> list[str]:
    errors = []
    sample = group.chat_prompt(seat=2, history=prepared["turns"], scene_path=prepared["scene"]) + materialize(manager, prepared["fork_context"])
    for profile in prepared["participants"]:
        try:
            catalog = manager.list_models(profile["agent"])
            selected = profile["model"] or catalog["default"]["model"]
            row = next((r for r in catalog["models"] if r["id"] == selected), {})
            limit = row.get("context_window")
            if limit and math.ceil(len(sample.encode("utf-8")) / 4) + 2048 > limit:
                errors.append(f"The transferred context is estimated to exceed {profile['name']}'s model limit. Choose another model or keep fewer exchanges.")
        except Exception:
            pass
    return errors


def _job_public(job: dict) -> dict:
    return {"summary_id": job["id"], "status": job["status"], "context_counts": job["prepared"]["selection"]["counts"]}


def _summary_worker(manager: Any, source: Any, job: dict) -> None:
    prepared, one_off = job["prepared"], job["one_off"]
    try:
        client = manager._client_for(source.agent)
        params = {"threadId": source.thread_id, "cwd": str(manager.root), "ephemeral": True,
                  "approvalPolicy": "never", "sandbox": "read-only", "tools": [],
                  "settingSources": [], "mcpServers": {}, "allowWrite": False,
                  "developerInstructions": group_context.SUMMARY_INSTRUCTIONS}
        if source.agent == "codex":
            from .suggestions import codex_mcp_servers
            features = ("shell_tool", "unified_exec", "view_image", "multi_agent", "multi_agent_v2", "apps", "plugins",
                        "remote_plugin", "browser_use", "browser_use_external", "in_app_browser", "computer_use",
                        "image_generation", "memories", "sleep_tool", "goals", "code_mode_host", "request_permissions_tool")
            params["config"] = {"web_search": "disabled", "project_doc_max_bytes": 0,
                                **{f"features.{name}": False for name in features},
                                **{f"mcp_servers.{s['name']}.enabled": False for s in codex_mcp_servers()}}
        def no_tools(event: dict) -> None:
            if event.get("type") == "activity.updated":
                activity = event.get("activity") or {}
                if activity.get("kind") not in {"commentary", "reasoning"}:
                    one_off.tool_used = True
                    one_off.status, one_off.error = "failed", "The summary requested a tool; only conversation evidence is allowed."
                    one_off.done.set()
                    if one_off.interrupt:
                        one_off.interrupt()
        one_off.on_event = no_tools
        ok = bool(source.thread_id) and manager._run_ephemeral_attempt(
            client=client, one_off=one_off, agent=source.agent, method="thread/fork", thread_params=params,
            timeout=manager.SIDE_TIMEOUT,
            turn_params={"input": [{"type": "text", "text": group_context.summary_prompt(prepared)}],
                         "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                         "mayWrite": False, **{k: v for k, v in prepared["source_model"].items() if v}})
        if not ok:
            raise RuntimeError(one_off.error or "The source session could not provide a summary.")
        prepared["turns"].insert(0, {"role": "context", "label": "Generated conversation summary",
            "agent": source.agent, "model": prepared["source_model"].get("model") or source.agent.title() + " default",
            "text": one_off.text, "created_at": time.time(), "scene": prepared["scene"], "inherited": True})
    except Exception as exc:
        prepared["summary_missing"] = True
        counts = prepared["selection"]["counts"]
        prepared["warnings"].append(f"Summary missing. Only the latest {counts['kept']} exchanges and the current scene were transferred. {str(exc)[:300]}")
    finally:
        _release(source, job["id"])
        with manager._fork_lock:
            job["status"] = "cancelled" if one_off.cancelled else "ready"
            job["completed_at"] = time.monotonic()


def _summary_job(manager: Any, source: Any, body: dict) -> dict:
    key = str(body.get("summary_id") or "")
    with manager._fork_lock:
        job = manager._fork_jobs.get(key)
        if not job or job["conversation_id"] != source.id:
            raise _error("This summary is no longer available. Fork again to prepare a new one.")
        if body.get("action") == "cancel-summary":
            if job["status"] == "consumed":
                raise _error("This Group is already being created.")
            job["one_off"].cancelled = True
            job["status"] = "cancelled"
            job["one_off"].done.set()
            interrupt = job["one_off"].interrupt
        else:
            interrupt = None
        result = _job_public(job)
    if body.get("action") == "cancel-summary":
        if interrupt:
            interrupt()
        _release(source, key)
    return result


def fork_chat(manager: Any, conversation_id: str, body: dict[str, Any], *, create: bool = False) -> dict[str, Any]:
    source = manager._get(conversation_id)
    if getattr(source, "is_group", False):
        raise _error("Fork a single-agent chat to create a new Group.")
    action = body.get("action")
    if action == "links":
        return {"groups": [row for row in manager.group_runtime.history.list()
                           if (row.get("source") or {}).get("thread_id") == source.thread_id
                           and (row.get("source") or {}).get("agent") == source.agent]}
    if action in {"summary-state", "cancel-summary"}:
        return _summary_job(manager, source, body)
    token = uuid.uuid4().hex
    with source.lock:
        if source_busy(source):
            raise _error("Wait for this chat's running work and approvals before forking.")
        source.forking, source.forking_id = True, token
    runtime = manager.group_runtime
    keep_reserved = False
    try:
        with runtime.lock:
            assert_groups_idle(manager)
        if create and body.get("summary_id"):
            with manager._fork_lock:
                job = manager._fork_jobs.get(str(body["summary_id"]))
                if not job or job["conversation_id"] != source.id or job["status"] != "ready" or job["stamp"] != _stamp(source):
                    raise _error("The conversation or summary changed. Fork again to prepare the latest context.")
                prepared = job["prepared"]
                # The summarized snapshot and participant/workflow choices form one request.
                if job["choices"] != {k: body.get(k) for k in ("participants", "workflow", "positions_table", "scene", "live_document", "context_options")}:
                    raise _error("The fork choices changed. Prepare the summary again.")
                job["status"] = "consumed"
        else:
            prepared = prepare(manager, source, body)
        settings = manager.group_settings()
        workflows = [p for p in settings["library"]["presets"] if p.get("kind") == "workflow"]
        chosen = str(body.get("workflow") or "")
        workflow = next((p for p in workflows if p["id"] == chosen), None)
        if chosen and workflow is None:
            raise _error("Choose an available conversation workflow.")
        limit_errors = _limit_errors(manager, prepared)
        response = {"participants": prepared["participants"], "workflows": workflows,
                    "warnings": prepared["warnings"], "limit_errors": limit_errors,
                    "source_thread_id": source.thread_id, "scene": prepared["scene"],
                    "context_options": prepared["context_options"], "context_counts": prepared["selection"]["counts"]}
        if action == "summarize":
            from .discuss import _OneOff
            if prepared["context_options"]["mode"] != "recent" or not prepared["context_options"]["include_summary"] or not prepared["selection"]["counts"]["older"]:
                raise _error("No earlier exchanges need a summary.")
            if limit_errors:
                raise _error(" ".join(limit_errors))
            one_off = _OneOff()
            one_off.cancelled = False
            one_off.may_write = False
            job = {"id": token, "conversation_id": source.id, "prepared": prepared, "one_off": one_off,
                   "status": "summarizing", "stamp": _stamp(source), "created_at": time.monotonic(),
                   "choices": {k: body.get(k) for k in ("participants", "workflow", "positions_table", "scene", "live_document", "context_options")}}
            with manager._fork_lock:
                for old_key, old in list(manager._fork_jobs.items()):
                    if old["status"] != "summarizing" and time.monotonic() - old["created_at"] > 600:
                        manager._fork_jobs.pop(old_key, None)
                manager._fork_jobs[token] = job
            keep_reserved = True
            threading.Thread(target=_summary_worker, args=(manager, source, job), daemon=True, name="proseview-group-summary").start()
            return _job_public(job)
        if not create:
            return response
        needs_summary = prepared["context_options"]["mode"] == "recent" and prepared["context_options"]["include_summary"] and prepared["selection"]["counts"]["older"]
        if needs_summary and not body.get("summary_id"):
            raise _error("Prepare the selected summary before creating this Group.")
        for profile in prepared["participants"]:
            manager._probe_agent(profile["agent"])
        if limit_errors and (workflow or prepared["context_options"]["mode"] == "recent"):
            raise _error(" ".join(limit_errors))
        with runtime.lock:
            assert_groups_idle(manager)
            native_id = ""
            original = prepared["participants"][0]
            if prepared["context_options"]["mode"] == "recent":
                pass  # A native fork would retain the excluded history.
            elif original["agent"] == source.agent and original["model"] == prepared["source_model"].get("model", "") and source.thread_id:
                try:
                    result = manager._client_for(source.agent).request("thread/fork", {
                        "threadId": source.thread_id, "cwd": str(manager.root), "approvalPolicy": "on-request",
                        "developerInstructions": manager._effective_developer_instructions() + "\n\n" + group.GENERAL_CHAT_GUIDANCE,
                        "config": dict(manager.THREAD_CONFIG)})
                    native_id = str((result.get("thread") or {}).get("id") or "")
                    if not native_id:
                        raise ValueError("Provider did not return a child session")
                except Exception as exc:
                    response["warnings"].append(f"Original session could not be forked; using a fresh session with transferred context: {exc}")
            elif original["agent"] != source.agent or original["model"] != prepared["source_model"].get("model", ""):
                response["warnings"].append("Original assistant starts a fresh session because its provider or model changed.")
            else:
                response["warnings"].append("Original session is unavailable; using a fresh session with transferred context.")
            key = uuid.uuid4().hex
            raw = {"id": key, "scene": prepared["scene"], "title": "Fork of " + next((t["text"][:65] for t in prepared["turns"] if t["role"] == "user"), "conversation"),
                   "participants": prepared["participants"], "turns": prepared["turns"], "managed": True}
            saved = runtime._load(key, raw)
            saved["source"] = {"conversation_id": conversation_id, "thread_id": source.thread_id,
                               "agent": source.agent, "scene": prepared["scene"], "document": dict(source.document)}
            saved["fork_context"] = prepared["fork_context"]
            saved["context_options"] = prepared["context_options"]
            saved["context_counts"] = prepared["selection"]["counts"]
            saved["summary_missing"] = bool(prepared.get("summary_missing"))
            saved["notice"] = " ".join(response["warnings"])
            saved["handoff_warnings"] = list(response["warnings"])
            if native_id:
                saved["native_threads"]["1"] = {"thread_id": native_id, "seen": len(saved["turns"]), "scene": "", "signature": None, "forked": True,
                                                "guidance_hash": hashlib.sha256(group.GENERAL_CHAT_GUIDANCE.encode("utf-8")).hexdigest()}
            if workflow:
                runtime._preset(saved, {"append": True, "preset_id": workflow["id"], "kind": "workflow",
                                       "positions_table": body.get("positions_table", workflow.get("positions_table", True))})
            runtime._save(saved)
            if body.get("summary_id"):
                with manager._fork_lock:
                    manager._fork_jobs.pop(str(body["summary_id"]), None)
            source.group_forks.append({"id": key, "scene": saved["scene"], "title": saved["title"], "source_thread_id": source.thread_id})
            runtime._start_worker(key)
            return {**response, "group": runtime._public(saved)}
    finally:
        if not keep_reserved:
            _release(source, token)
