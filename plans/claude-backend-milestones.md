---
title: Claude Backend for Discuss
status: milestones 1-5 complete
date: 2026-08-19
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

## Milestone 4 — two agent tabs

Codex and Claude each have a dock tab. Selecting one opens that agent's own
conversation for the current document; the other keeps running on the server
and its state is restored from its snapshot on return. Both tabs are always
present, and one that cannot start says why rather than disappearing.

`discuss.agent` no longer selects an agent — it decides which tab the dock
opens on.

Verified in a browser, not only in tests: a Codex turn stays live while you
switch to Claude, ask it something, and switch back, with each answer landing
only in its own tab.

## Milestone 5 — one behaviour suite, both transports

`tests/test_discuss_transport_conformance.py` runs the same forty-odd
assertions against both agents: questions, queueing, structured selection
actions and their schemas, stop, approvals, history scoping, failure handling,
and the rule that raw reasoning never reaches the projection.

The doubles live in `tests/transport_fakes.py` and deliberately speak
different protocols — sharing the emitting code would test nothing, and a test
guards that too. `test_discuss_manager.py` keeps the Codex-specific depth
(continuity reports, proposal staleness, thread recovery) and now imports the
same Codex double instead of defining its own.

Checked by sabotage: making the Claude translator forward raw thinking fails
`test_raw_reasoning_never_reaches_the_projection[claude]` and nothing else.

## Structured-output reliability, so far

Eight selection actions run against the live agent: seven accepted by
`validate_action_result`, one rejected with "the agent returned the wrong
result type", meaning the `kind` field came back as something other than the
single value its schema enum permits. The failing payload was not captured, so
the cause is not yet known.

Six consecutive runs afterwards were clean. One failure in eight is not a rate
worth quoting, but it is enough to say the concern is real rather than
theoretical: the validator hard-fails where it could truncate or retry, so a
rare malformed result becomes a visible error for the writer. Capturing the
failing payload is the next step, not loosening the validator.

## The history gap, closed

`thread/read` returned only the user's message, so reopening a Claude
conversation blanked it. Two causes, both fixed while driving the real UI:

* The thread id Prosview persisted was a locally generated value that meant
  nothing to a new process. A thread id is now the SDK session id, so a
  conversation survives a restart and resumes rather than warning that it is
  no longer available.
* The transport returned its own turn shape. `DiscussManager` has a strict
  restore parser, so `thread/read` now returns the structure that parser
  expects.

## Not built

Skills still return an empty list for Claude: the SDK has no `skills/list`
equivalent, so the picker needs to scan `SKILL.md` frontmatter instead.

Still unvalidated, and not resolvable by more unit tests:

* Structured-output reliability as a *rate*. Eight runs is a signal, not a
  measurement — see above.
* Pool behaviour under a writer moving between many scenes for an extended
  period.

## Open question outside the code

Whether Anthropic's terms permit a distributed product to drive Claude Code
using an end user's personal subscription credentials.
