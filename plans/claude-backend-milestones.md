---
title: Claude Backend for Discuss — Milestones 1-3
status: in progress
date: 2026-08-18
---

# Claude backend for Discuss

Follows `plans/claude-agent-sdk-spike.md`, which established feasibility. This
records what is built, what is deliberately not, and what was learned by
running it against the live agent rather than against fakes.

## What is built

**Milestone 1 — transport and translator.** `proseview/claude_agent_client.py`
presents the same surface as `codex_app_server.py` (`start`, `request`,
`respond`, `close`, `inspect_capabilities`) and carries its own translator,
`sanitize_claude_message`, emitting exactly the vocabulary
`sanitize_agent_message` does. `DiscussManager` picks a transport in
`_build_client` and takes the translator from it, so no caller branches on
which agent answered.

**Milestone 2 — session pool and async bridge.** One `ClaudeSDKClient` is one
session, so the client owns a pool keyed by thread id, bounded at
`MAX_SESSIONS` with least-recently-used eviction of idle sessions. A private
event loop runs on its own thread; every public method bridges to it, and
inbound notifications are handed to a separate dispatcher thread so manager
callbacks can safely re-enter the client — an approval decision calls
`respond` from inside `on_message`.

**Milestone 3 — approvals and the read-only suite.** Tool calls are gated by a
`PreToolUse` hook rather than `can_use_tool`, for the reasons in the spike
document. `tests/test_claude_read_only.py` asserts the property rather than the
spelling: no tool that can modify anything, reach the network, or run code gets
through without the writer being asked — including a tool that does not exist
yet.

Agent selection is `discuss.agent` in `.proseview.yaml`, default `codex`.

## What running it live changed

Both of these passed the fake-backed tests and failed against the real agent.

**`StructuredOutput` is not a writer-facing tool.** When an output schema is
set, the CLI returns the JSON through an internal `StructuredOutput` tool call.
The first live run stalled: the gate asked the writer to approve it, and the
turn hung behind an approval nobody could explain. Internal tools are now
allowed unconditionally and never shown as activity.

**With a schema, the prose is not the answer.** The same run published the
model's commentary as the final message while the JSON sat in the tool call.
That fails `validate_action_result` on every selection action. A schema-bound
turn now takes its answer from `ResultMessage.structured_output`, and assistant
prose and text deltas are suppressed for that turn.

A third bug came out of the test run itself: pending approvals were abandoned
on `close`, stranding the gate coroutine and the turn it held.

## Known gap

`thread/read` currently returns only the user's message. The assistant reply
does not appear in the session store immediately after the turn — most likely
`session_store_flush` batching rather than absence. Worth settling with
`flush="eager"` or a read retry when the history pane is wired up in milestone
4; it is not yet proven either way.

## Not built

Milestones 4 and 5: skills, agent selection in the UI, the writer-facing
history pane, and the wider test coverage mirroring `test_discuss_manager.py`
across both transports.

Still unvalidated, and not resolvable by more unit tests:

- Structured-output reliability as a *rate*. Every live run so far has been
  clean, but a handful of runs is not a measurement, and the manager's
  validator hard-fails on an exact count mismatch rather than truncating.
- Pool behaviour under a writer moving between many scenes for an extended
  period.

## Open question outside the code

Whether Anthropic's terms permit a distributed product to drive Claude Code
using an end user's personal subscription credentials.
