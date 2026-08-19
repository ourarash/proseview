---
title: Claude Agent SDK Feasibility Spike
status: findings
date: 2026-08-18
---

# Claude Agent SDK feasibility spike

## Why this exists

Discuss currently talks to one agent, `codex app-server`, through
`proseview/codex_app_server.py`. The question was whether Claude could sit
beside it without redesigning Discuss. `discuss.py` already names the seam:
`sanitize_agent_message` is documented as the single point where a wire
protocol becomes Prosview's event vocabulary, and says a second agent belongs
behind a sibling translator rather than behind branches in the callers.

This spike tests the five assumptions that have to hold before committing to
that work. Run it with `scripts/spike_claude_agent_sdk.py`.

## Result

All five pass against `claude-agent-sdk` 0.2.139 and Claude Code 2.1.119.

| # | Assumption | Result |
|---|---|---|
| 1 | A session opens and reports capabilities | Pass — `get_server_info()` returns 47 commands |
| 2 | Structured output survives `validate_action_result` | Pass — Rephrase returned exactly 3 alternatives, accepted unmodified |
| 3 | Tool calls can be gated for the approval UI | Pass, but **not** the obvious way — see below |
| 4 | A running turn can be interrupted | Pass — `terminal_reason='aborted_streaming'` |
| 5 | A conversation can be read back for the history pane | Pass — `list_sessions` / `get_session_messages` |

## What the spike changed about the plan

### `can_use_tool` is not a safe approval gate

The intuitive mapping — Codex's `item/*/requestApproval` becomes the SDK's
`can_use_tool` callback — is wrong, and wrong in the direction that matters.
The SDK raises `CanUseToolShadowedWarning` and explains why: an `allowed_tools`
or `tools` entry that permits a whole tool auto-approves it *before* the
callback is consulted. The warning also notes that allow rules in the user's
settings files can shadow the callback and are not visible to it.

Probes A–D in `scripts/spike_permission_debug.py` confirm this empirically:
under four different option combinations, including `permission_mode="plan"`,
Bash ran to completion and `can_use_tool` never fired. An approval UI built on
that callback would silently not be an approval UI.

**A `PreToolUse` hook is the gate.** Probe E shows the hook firing for the same
call and the `deny` decision being enforced, with the model reporting that the
command was blocked. `PreToolUseHookInput` carries `tool_name`, `tool_input`,
`tool_use_id`, `permission_mode`, and `cwd` — enough to render the approval
card Prosview already has.

This sharpens the ambient-config concern rather than resolving it: the writer's
own settings can bypass `can_use_tool`, so `setting_sources=None` is
load-bearing, not merely tidy.

### Read-only tools never prompt

`Read` and `Glob` are auto-allowed under the default permission mode. The
approval a writer actually sees is an attempt to leave read-only — which fits
Prosview's posture, but means approval flows must be tested against `Bash`,
`Write`, and `Edit`, not against a read.

### Interrupt looks like an error unless you check the reason

An interrupted turn terminates with `subtype='error_during_execution'` and
`terminal_reason='aborted_streaming'`. `stop_reason` is `None`.
`_complete_stopped_turn` must treat that combination as a clean writer-initiated
stop, or every Stop press will surface as a failure in the UI.

### History is a supported API, not transcript scraping

`list_sessions()`, `get_session_info()`, `get_session_messages()`,
`rename_session()`, `delete_session()`, and `fork_session()` map onto
`list_conversations` / `open_conversation` / `rename_conversation` /
`remove_conversation` / `export_conversation` almost one-to-one. Nothing needs
to parse `~/.claude/projects/*.jsonl`, and `session_store` allows keeping
transcripts under `.proseview/` instead if that is preferred for privacy.

### Prefer `ResultMessage.structured_output`

The spike reads the JSON out of `ResultMessage.result`, which works. The real
implementation should use `ResultMessage.structured_output`, which is the field
intended for it.

## What the spike did not test

- Sustained reliability of structured output. One clean run is not a rate.
  Before relying on it, run the existing action suite repeatedly and measure
  how often `validate_action_result` rejects a response — the validator hard-
  fails on an exact count mismatch rather than truncating.
- Concurrency. Every check used a single `ClaudeSDKClient`. One client is one
  session, so the pooling design for many open scenes is still unvalidated.
- The asyncio/threading boundary. `DiscussManager` is threads and queues; the
  SDK is async. The bridge is unwritten and untested.
- Evidence-grounded critiques and continuity findings, which depend on model
  behaviour rather than on schema enforcement.

## Open question outside the code

Whether Anthropic's terms permit a distributed product to drive Claude Code
using an end user's personal subscription credentials. This is worth settling
before the implementation work, because it can invalidate the approach
independently of anything above.
