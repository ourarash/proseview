---
title: Agy (Antigravity CLI) Backend Proposal & Implementation Plan
status: proposal
date: 2026-11-17
---

# Agy (`agy`) Backend Proposal & Implementation Plan

## Goal

Add the Antigravity CLI (`agy`) as a third first-class agent provider in Proseview—alongside `codex` and `claude`—for both **single-agent Discuss** and **Group Room** sessions, while preserving the writer's native `agy` experience:

- **Existing `agy` OAuth auth** (no API key required).
- **`agy`'s own tools, MCP servers, skills, and workspace instructions** running natively.
- **Proseview's approval and review boundaries**: reading passes never edit files, write turns capture before-images via `_capture_before` for line-by-line diff review, and shell commands surface the approval card in the panel.

## Transport Choice: `agy acp --stdio`

Live probing against `agy 1.5.10` (`Antigravity ACP Server 1.5.10`) confirms that `agy acp --stdio` is the right transport—analogous to `codex app-server` (`proseview/codex_app_server.py`) and cleaner than either spawning `agy -p` per turn or adding the `google-antigravity` Python package as a dependency.

### Verified ACP Capabilities (`agy 1.5.10`)

| Capability | Observed behavior |
|---|---|
| Auth / tier | Uses existing `agy` OAuth login automatically; `session/new` returned `_meta.antigravity.tier` (`Google AI Pro` / `g1-pro-tier`) with no API key. |
| Model catalog & effort | `session/new` returns live `models.availableModels` and `configOptions` (`model`, `thought_level` in `low`/`medium`/`high`, `mode` in `default`/`accept-edits`/`auto`/`plan`); `session/set_model` succeeded. |
| System instructions | `initialize` advertises `_meta.antigravity.systemPrompt.append: true`; passing `_meta.antigravity.systemPrompt.append` in `session/new` reliably appends instructions. |
| Native tools & read-only tools | `read_file` ran without prompting, emitting `tool_call` (`in_progress`) and `tool_call_update` (`completed`). |
| Approval gating | In `default` mode, both `write_file` (`kind: "edit"`, with `locations`) and `run_command` (`kind: "execute"`, with `CommandLine`) paused and sent `session/request_permission` (`allow` / `deny`) before executing. |
| Streaming & history | `session/update` streams `agent_message_chunk` text deltas; `session/resume`, `session/load` (with history replay), `session/list`, `session/close`, and `additionalDirectories` are advertised and verified (`resume`/`load`). |

### Observed Model Catalog (`Google AI Pro` tier)

`agy models` and `agy acp` `session/new` currently report 7 model families (18 model/thinking-level IDs):

- **Gemini 4 Argon** *(default at Medium)*: `gemini-4-argon-{low,medium,high}` (`agy`'s current `pro`-tier equivalent)
- **Gemini 4 Hydrogen**: `gemini-4-hydrogen-{low,medium,high,xhigh}`
- **Orchestrator (Argon)**: `gemini-pro-orchestrator-g1-pro`
- **Gemini 3.8 Flash**: `gemini-3.8-flash-{low,medium,high}`
- **Claude Opus 5.5**: `claude-opus-5-5-{low,medium,high}`
- **Claude Sonnet 5.5**: `claude-sonnet-5-5-{low,medium,high}`
- **GPT-OSS 120B**: `gpt-oss-120b-medium`

*(Note: `Gemini 4 Carbon` is only exposed for Gemini Enterprise / `GEMINI_API_KEY` / `AGY_ADC_AUTH` sign-ins per `agy changelog`, not consumer `Google AI Pro` OAuth.)*

## Proseview Feature Fit: Free Chat vs. Structured JSON

### Works over ACP directly (free-form Markdown / text)
- Single-agent **Discuss** chat turns and **Craft reviews**
- **`A` (`Ask about selection`)** and **`P` (`Polish selection`)** shortcuts (`proseview/templates/assets/js/60-selection.js`, `68-discuss.js`) — neither sets `actionId` or `outputSchema`; both attach the selection and run a normal chat turn (or route to Group when the Group tab is open)
- **`/btw` side questions** (`proseview/discuss.py` falls back to an ephemeral seeded `thread/start` when `thread/fork` is absent)
- **Group Room critic turns** (`proseview/discuss.py`, `proseview/group_runtime.py`, including plain-text `STANCE | ...` lines for the positions table)
- **Beatmap** (`proseview/beatmap.py`) — does not pass `outputSchema`; prompts for JSON and parses/repairs it via `parse_agent_json`

### Requires `outputSchema` handling
Four features in `proseview/discuss.py` pass `outputSchema`:
1. **Highlight suggestions** (`suggest_for_highlight`, `alternatives` schema)
2. **Selection submenu actions** (`Rewrite ›` and `Critique ›` items in `60-selection.js`, `_action_task`)
3. **Repository continuity / canon refactor actions** (`_repository_action_task`, `continuity_report` schema)
4. **Group Moderator plan synthesis** (`GROUP_MODERATOR_SCHEMA`, parsed by `_parse_group_moderator_output`)

Since `agy acp` does not advertise native `outputSchema`, `AgyAcpClient` can handle these either by appending schema instructions to the turn prompt (stripping code fences before validation) or by shelling out to `agy -p --output-format json --json-schema` for ephemeral one-offs.

## Key Caveats to Verify Before/During Implementation

1. **Settings auto-approve vs. Proseview edit capture**: `agy acp --help` does not expose `--settings`. If `~/.gemini/antigravity-cli/settings.json` auto-approves edits or commands, `agy acp` could bypass `session/request_permission` (skipping `_capture_before` and reading-pass blocks). Test `session/set_mode` (`"plan"`) for reading passes and document expected permission behavior.
2. **Logged-out / expired auth**: Verify the exact JSON-RPC error returned by `agy acp` when unauthenticated so Proseview can surface a clear sign-in error without burning an LLM call.
3. **Cancel & thought-chunk suppression**: Confirm `session/cancel` cleanly stops an active `session/prompt` and verify the exact `sessionUpdate` type for thinking/reasoning chunks so raw reasoning is dropped (required by `tests/test_discuss_transport_conformance.py`).
4. **No `turn/steer` / `thread/fork` assumptions**: Like `claude`, `agy` uses Group Room's interrupt-and-queue fallback for mid-turn steering (`proseview/discuss.py`, `proseview/group_runtime.py`) and `/btw`'s seeded-thread fallback.

---

## Implementation Phases

### Phase 0 — `agy acp` Protocol Spike *(Complete — 2026-11-17)*

All four protocol checks passed against `agy 1.5.10` (`Antigravity ACP Server 1.5.10`):

| Check | Result | Design implication |
|---|---|---|
| **Unauthenticated `session/new`** | `initialize` succeeds; `session/new` returns JSON-RPC error `{"code": -32000, "message": "Authentication required"}`. | Detect `-32000` / `"Authentication required"` in `AgyAcpClient` and raise `AgyAuthError` (without burning an LLM call). |
| **`session/cancel`** | Sending notification `{"method": "session/cancel", "params": {"sessionId": ...}}` aborts an active `session/prompt`, which resolves with `{"stopReason": "cancelled"}`. | Maps cleanly to `turn/interrupt` (`stop` button) and must be treated as a clean user-initiated stop rather than a turn failure. |
| **`sessionUpdate` for thoughts vs. text** | Reasoning streams as `sessionUpdate: "agent_thought_chunk"` (`content.text`); visible answer streams as `sessionUpdate: "agent_message_chunk"`. | Drop `agent_thought_chunk` in `sanitize_agy_message` so raw reasoning never reaches Proseview's projection. |
| **Config switching (`set_config_option`)** | `session/set_config_option` works for both `configId: "model"` and `configId: "thought_level"` (`low`/`medium`/`high`), returning updated `configOptions`. | Use `session/set_config_option` for base model + effort changes (and `session/set_model` for exact IDs like `gemini-4-hydrogen-xhigh`). |
| **`plan` mode vs. `default` mode for reading passes** | `mode: "plan"` did not write `foo.txt`, **but** wrote an artifact plan (`write_file` with `ArtifactMetadata`) and asked the writer to click **Proceed**. In `mode: "default"`, `edit_file` paused on `session/request_permission` (`kind: "edit"`, `locations`, and `content: [{type: "diff", oldText, newText}]`). | **Keep sessions in `mode: "default"`** (explicitly calling `session/set_mode(..., "default")` on `session/new` in case user settings default elsewhere) and enforce reading passes by denying `session/request_permission` (`edit` / `execute`) when `not may_write`. |

### Phase 1 — `AgyAcpClient` Transport, Translator, and Conformance Suite
- Create `proseview/agy_acp_client.py` implementing the shared synchronous transport contract (`start`, `request`, `respond`, `respond_error`, `notify`, `close`, `inspect_capabilities`, `probe_capabilities`) and `sanitize_agy_message` translator.
- Map Proseview RPC methods to ACP:
  - `thread/start` → `session/new` (with `_meta.antigravity.systemPrompt.append`)
  - `thread/resume` → `session/resume`
  - `thread/read` → `session/load`
  - `turn/start` → `session/set_model` / `session/set_config_option` + threaded `session/prompt`
  - `turn/interrupt` → `session/cancel`
  - `model/list` → live `models` / `configOptions` from `session/new`
- Translate `session/request_permission`:
  - `kind == "edit"` → `item/fileChange/requestApproval` (preserves reading-pass denial and `_capture_before`)
  - `kind == "execute"` (and other non-read gated tools) → `item/commandExecution/requestApproval`
- Add an ACP test double in `tests/transport_fakes.py` and parametrize `tests/test_discuss_transport_conformance.py` across `("codex", "claude", "agy")`.

### Phase 2 — Single-Agent Discuss (`Agy` tab) + `/btw`
- **Backend**:
  - Add `"agy"` to `DISCUSS_AGENTS` in `proseview/config.py`.
  - Wire `"agy"` into `proseview/discuss.py` (`_probe_agent`, `_build_client`, `agents()`, `_instruction_files_for`, and `ask_side_question`).
  - Surface `AgyAuthError` / `AgyUnavailableError` cleanly in `proseview/server.py`.
- **Frontend**:
  - Add `utilityTabAgy` in `proseview/templates/index.html.j2`.
  - Generalize hardcoded `codex`/`claude` state maps, local caches, labels, and model catalogs in `proseview/templates/assets/js/68-discuss.js` and `69-btw.js`.
- **Outcome**: Full single-agent chat, `A`/`P` selection shortcuts, craft reviews, `/btw`, model/thinking-level selection, tool approvals, file edit diff review, and conversation restore.

### Phase 3 — Group Room Integration
- **Backend**:
  - Allow `"agy"` in `clean_profile` (`proseview/group.py`), `GroupSeatSettings` / `GroupHistoryStore` (`proseview/suggestions.py`), and `run_group_turn` / `chat_models` (`proseview/discuss.py`).
- **Frontend**:
  - Update participant selectors, saved-draft validation, and agent labels in `proseview/templates/assets/js/69-group-composer.js`, `69-group-fork.js`, `70-group-runtime.js`, and `68-discuss.js`.
- **Tests**: Extend Group unit and e2e coverage for 3-provider seats and restart recovery.

### Phase 4 — Structured JSON Actions & Peripheral Features (Follow-up)
- Support `outputSchema` turns in `AgyAcpClient` (schema-prompt injection + JSON extraction/validation, or `agy -p --output-format json --json-schema` for ephemeral one-offs) for selection `Rewrite ›` / `Critique ›` actions, continuity actions, highlight suggestions, and Group Moderator.
- Add `"agy"` to Beatmap (`proseview/beatmap.py`, `82-beatmap-settings.js`) and Settings › Suggestions (`proseview/suggestions.py`, `81-suggestion-settings.js`).
