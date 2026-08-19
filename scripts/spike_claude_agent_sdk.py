"""Feasibility spike: can `claude-agent-sdk` back Prosview's Discuss feature?

This is a throwaway probe, not product code. It answers five questions that
must all be "yes" before committing to a Claude implementation alongside the
existing Codex one:

  1. A session opens against a repository and reports its capabilities.
  2. Structured output survives Prosview's own ``validate_action_result``.
  3. A tool-permission request reaches us with enough detail to render the
     four approval decisions Prosview already exposes.
  4. A running turn can be interrupted.
  5. A finished conversation can be read back for the history pane.

Each check is independent and failure-isolated: one broken assumption should
still leave the other four measured. Run with the SDK importable and the
`claude` CLI on PATH.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import claude_agent_sdk as sdk  # noqa: E402
from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from proseview.discuss import (  # noqa: E402
    ACTION_DEFINITIONS,
    ContextBuilder,
    DiscussManager,
    action_output_schema,
    validate_action_result,
)

# A real manuscript scene, so the selection and context envelope are the ones
# Prosview would actually send rather than a synthetic string.
SCENE_ROOT = REPO_ROOT / "fixtures" / "demo-repo"
# A scene path is relative to the configured manuscript subdir, not the root.
SCENE_DOC = {"kind": "scene", "path": "ch01/01-opening.md"}
SCENE_FILE = SCENE_ROOT / "manuscript" / SCENE_DOC["path"]
CHECK_TIMEOUT = 240.0

results: list[dict[str, Any]] = []


def record(name: str, passed: bool, detail: str, **extra: Any) -> None:
    results.append({"check": name, "passed": passed, "detail": detail, **extra})
    print(f"  {'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)


def base_options(**overrides: Any) -> ClaudeAgentOptions:
    """The lockdown Prosview would ship: no ambient config, no MCP, no plugins.

    `setting_sources=None` is the load-bearing part — it stops the writer's own
    CLAUDE.md, hooks, and settings from entering a session Prosview believes it
    has bounded. It also stops settings-file allow rules from silently
    shadowing the permission gate (see check 3).
    """
    options: dict[str, Any] = {
        "cwd": str(SCENE_ROOT),
        "setting_sources": None,
        "strict_mcp_config": True,
        "mcp_servers": {},
        "permission_mode": "default",
        "max_turns": 6,
    }
    options.update(overrides)
    return ClaudeAgentOptions(**options)


def text_of(message: Any) -> str:
    if not isinstance(message, AssistantMessage):
        return ""
    return "".join(b.text for b in message.content if isinstance(b, TextBlock))


async def maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def selection_from_scene() -> tuple[str, str]:
    """Pick a unique paragraph from the scene to act on."""
    raw = SCENE_FILE.read_text(encoding="utf-8")
    body = raw.split("---", 2)[-1] if raw.startswith("---") else raw
    for para in (p.strip() for p in body.split("\n\n")):
        # Prosview requires the selection to appear exactly once in the file.
        if len(para) > 80 and not para.startswith("#") and raw.count(para) == 1:
            return raw, para
    raise SystemExit("no unique paragraph found in the fixture scene")


# --- 1. session opens -------------------------------------------------------

async def check_session_opens() -> str | None:
    async with ClaudeSDKClient(options=base_options(tools=[])) as client:
        await client.query("Reply with exactly: ready")
        session_id = None
        async for message in client.receive_response():
            session_id = getattr(message, "session_id", None) or session_id
        info = await maybe_await(client.get_server_info())
        commands = len((info or {}).get("commands") or [])
        record(
            "1. session opens",
            bool(session_id),
            f"session_id={session_id}, server_info={'yes' if info else 'no'}, commands={commands}",
            session_id=session_id,
        )
        return session_id


# --- 2. structured output through the real validator ------------------------

async def check_structured_output() -> None:
    action_id = "rephrase"
    spec = ACTION_DEFINITIONS[action_id]
    schema = action_output_schema(spec["kind"], spec["count"])
    _, selection = selection_from_scene()

    # Build the prompt with Prosview's real context builder so the untrusted
    # -material envelope and the BEGIN USER SELECTION markers are identical.
    builder = ContextBuilder(SCENE_ROOT)
    instruction = spec["instruction"]
    question = (
        "SELECTION ACTION\n"
        f"Action: {spec['label']} ({action_id})\n"
        f"Required result type: {spec['kind']}\n"
        f"Constraints: {instruction}\n"
        "Return only the JSON object required by the supplied output schema."
    )
    bundle = builder.build(SCENE_DOC, question, selection=selection)

    options = base_options(
        tools=[],
        system_prompt=DiscussManager.DEVELOPER_INSTRUCTIONS,
        output_format={"type": "json_schema", "schema": schema},
    )

    raw = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(bundle.prompt)
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                # NOTE: ResultMessage.structured_output is the field intended
                # for this; .result is read here only to keep the spike's
                # parsing path explicit.
                raw = getattr(message, "result", None) or raw
            else:
                raw += text_of(message)

    task = {
        "id": uuid.uuid4().hex,
        "action_id": action_id,
        "kind": spec["kind"],
        "max_results": spec["count"],
        "target": {"document": dict(SCENE_DOC), "selection": selection},
    }

    Path(REPO_ROOT / "spike-structured-output.json").write_text(raw, encoding="utf-8")

    # Two separate questions: is it well-formed JSON matching the schema, and
    # does Prosview's stricter validator (exact counts, no duplicates, no
    # echoing the selection) also accept it?
    try:
        parsed = json.loads(raw)
        shape = f"keys={sorted(parsed)}, alternatives={len(parsed.get('alternatives', []))}"
    except Exception as exc:  # noqa: BLE001
        record("2a. json parses", False, f"{type(exc).__name__}: {exc}", raw=raw[:400])
        return
    record("2a. json parses", True, shape)

    try:
        validated = validate_action_result(raw, task)
        record(
            "2b. Prosview validator accepts",
            True,
            f"{len(validated['alternatives'])} alternatives accepted",
        )
    except Exception as exc:  # noqa: BLE001
        record(
            "2b. Prosview validator accepts",
            False,
            f"{type(exc).__name__}: {exc}",
            note="expected failure mode if the model ignores minItems/maxItems",
        )


# --- 3. permission request detail -------------------------------------------

async def check_permission_request() -> None:
    """Gate tool calls the way Prosview must: with a PreToolUse hook.

    The obvious-looking option, ``can_use_tool``, is NOT a reliable gate. Any
    ``allowed_tools``/``tools`` entry that allows a whole tool auto-approves it
    before the callback runs, and — per the SDK's own warning — allow rules in
    the user's settings files can shadow it invisibly. A hook is consulted
    either way, so it is the only safe place to hang an approval UI.
    See scripts/spike_permission_debug.py for the evidence.
    """
    from claude_agent_sdk import HookMatcher

    seen: list[dict[str, Any]] = []
    attempted: list[str] = []

    async def pre_tool_use(input_data: dict[str, Any], tool_use_id: Any, context: Any):
        seen.append(
            {
                "tool": input_data.get("tool_name"),
                "input_keys": sorted(input_data.get("tool_input") or {})[:6],
                "tool_use_id": input_data.get("tool_use_id"),
                "permission_mode": input_data.get("permission_mode"),
                "cwd": input_data.get("cwd"),
            }
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Prosview spike: denied by policy.",
            }
        }

    options = base_options(
        tools=["Bash", "Read"],
        max_turns=3,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]},
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "Run the shell command `wc -l manuscript/ch01/01-opening.md` "
            "using the Bash tool and report the number."
        )
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                attempted.extend(
                    b.name for b in message.content if isinstance(b, ToolUseBlock)
                )

    if not seen:
        record(
            "3. permission gate (hook)",
            False,
            f"hook never fired; tools attempted={attempted or 'none'}",
        )
        return
    first = seen[0]
    record(
        "3. permission gate (hook)",
        True,
        f"tool={first['tool']}, input_keys={first['input_keys']}, "
        f"tool_use_id={'yes' if first['tool_use_id'] else 'no'}, deny enforced",
        payload=seen,
    )


# --- 4. interrupt -----------------------------------------------------------

async def check_interrupt() -> None:
    """Interrupt a turn that is genuinely still running.

    A turn that finishes on its own before the interrupt lands would look like
    a pass while proving nothing, so this asserts on the terminating
    ResultMessage rather than on timing alone.
    """
    options = base_options(tools=[], max_turns=2)
    async with ClaudeSDKClient(options=options) as client:
        # Long enough that it cannot plausibly finish inside the sleep below.
        await client.query(
            "Write the numbers 1 to 3000, one per line, with no other text. "
            "Do not summarise or abbreviate."
        )

        chunks = 0
        finished = False
        final: Any = None

        async def drain() -> None:
            nonlocal chunks, finished, final
            async for message in client.receive_response():
                if text_of(message):
                    chunks += 1
                if isinstance(message, ResultMessage):
                    final = message
            finished = True

        task = asyncio.create_task(drain())
        await asyncio.sleep(4)
        already_done = finished
        started = time.monotonic()
        await client.interrupt()
        try:
            await asyncio.wait_for(task, timeout=45)
        except asyncio.TimeoutError:
            task.cancel()
            record("4. interrupt", False, "turn did not end within 45s of interrupt")
            return

        elapsed = time.monotonic() - started
        stop_reason = getattr(final, "stop_reason", None)
        terminal = getattr(final, "terminal_reason", None)
        subtype = getattr(final, "subtype", None)
        detail = (
            f"ended {elapsed:.1f}s after interrupt, chunks={chunks}, "
            f"subtype={subtype!r}, stop_reason={stop_reason!r}, terminal_reason={terminal!r}"
        )
        if already_done:
            # The turn completed before we interrupted, so this run proves
            # nothing about interruption. Report that honestly.
            record("4. interrupt", False, "INCONCLUSIVE — turn finished before interrupt; " + detail)
        else:
            record("4. interrupt", True, detail)


# --- 5. history read-back ---------------------------------------------------

async def check_history(session_id: str | None) -> None:
    if not session_id:
        record("5. history read-back", False, "no session_id captured in check 1")
        return

    listed = await maybe_await(sdk.list_sessions(directory=str(SCENE_ROOT)))
    info = await maybe_await(sdk.get_session_info(session_id, directory=str(SCENE_ROOT)))
    messages = await maybe_await(
        sdk.get_session_messages(session_id, directory=str(SCENE_ROOT))
    )

    ids = {getattr(s, "session_id", None) for s in (listed or [])}
    roles = [getattr(m, "type", "?") for m in (messages or [])]
    record(
        "5. history read-back",
        bool(messages) and session_id in ids,
        f"{len(listed or [])} sessions listed, target_listed={session_id in ids}, "
        f"{len(messages or [])} messages, types={roles[:6]}, "
        f"summary={getattr(info, 'summary', None)!r}",
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, nargs="*", help="run only these checks")
    args = parser.parse_args()
    wanted = set(args.only or [1, 2, 3, 4, 5])

    print(f"claude-agent-sdk {sdk.__version__}  root={SCENE_ROOT}\n")

    session_id = None
    plan = [
        (1, "session opens", lambda: check_session_opens()),
        (2, "structured output", lambda: check_structured_output()),
        (3, "permission request", lambda: check_permission_request()),
        (4, "interrupt", lambda: check_interrupt()),
        (5, "history read-back", lambda: check_history(session_id)),
    ]

    for number, label, run in plan:
        if number not in wanted:
            continue
        print(f"[{number}] {label} ...", flush=True)
        try:
            outcome = await asyncio.wait_for(run(), timeout=CHECK_TIMEOUT)
            if number == 1:
                session_id = outcome
        except asyncio.TimeoutError:
            record(f"{number}. {label}", False, f"timed out after {CHECK_TIMEOUT:.0f}s")
        except Exception as exc:  # noqa: BLE001
            record(f"{number}. {label}", False, f"{type(exc).__name__}: {exc}")

    print("\n--- summary ---")
    for row in results:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['check']}: {row['detail']}")
    Path(REPO_ROOT / "spike-report.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"\nreport: {REPO_ROOT / 'spike-report.json'}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
