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

### Phase 1 — `AgyAcpClient` Transport, Translator, and Conformance Suite *(Complete — 2026-11-17)*
- Created [agy_acp_client.py](file:///Users/ari/github/proseview/proseview/agy_acp_client.py) implementing the shared synchronous transport contract (`start`, `request`, `respond`, `respond_error`, `notify`, `close`, `inspect_capabilities`, `probe_capabilities`) and `sanitize_agy_message` translator.
- Mapped Proseview RPC methods to ACP (`thread/start`, `thread/resume`, `thread/read`, `turn/start`, `turn/interrupt`, `model/list`, `skills/list`), including replay-buffering during `session/load`, `mode: "default"` enforcement, `_meta.antigravity.systemPrompt.append`, and schema-prompt fallback with fence stripping when `outputSchema` is supplied.
- Translated `session/request_permission` (`edit` → `item/fileChange/requestApproval`, `execute`/other → `item/commandExecution/requestApproval`) with per-session `acceptForSession` caching for non-edit tools only.
- Wired `"agy"` into [discuss.py](file:///Users/ari/github/proseview/proseview/discuss.py) transport dispatch (`_is_thread_unavailable`, `_probe_agent`, `_build_client`, `_model_default_source`) without prematurely changing `DISCUSS_AGENTS` before Phase 2 UI work.
- Added `AgyFakeClient` in [transport_fakes.py](file:///Users/ari/github/proseview/tests/transport_fakes.py), parametrized [test_discuss_transport_conformance.py](file:///Users/ari/github/proseview/tests/test_discuss_transport_conformance.py) across `("codex", "claude", "agy")` (85 passed), added subprocess unit tests in [test_agy_acp_client.py](file:///Users/ari/github/proseview/tests/test_agy_acp_client.py) (13 passed), and verified end-to-end against live `agy 1.5.10`.

### Phase 2 — Single-Agent Discuss (`Agy` tab) + `/btw` *(Complete — 2026-11-17)*
- **Backend**:
  - Added `"agy"` to `DISCUSS_AGENTS` in [config.py](file:///Users/ari/github/proseview/proseview/config.py).
  - Added `agy_instruction_files` (`GEMINI.md`, `.gemini/GEMINI.md`, `AGENTS.md`) in [suggestions.py](file:///Users/ari/github/proseview/proseview/suggestions.py).
  - Wired `"agy"` into `agents()`, `ask_side_question`, `_side_thread_params`, `_run_side_question` (skipping `thread/fork` cleanly when `capabilities["thread_fork"]` is `False` so `/btw` runs straight in `seeded` mode), `_instruction_files_for`, and `discuss_settings()` in [discuss.py](file:///Users/ari/github/proseview/proseview/discuss.py).
  - Mapped `AgyAuthError` (401) and `AgyUnavailableError` / `AgyProtocolError` (503) in [server.py](file:///Users/ari/github/proseview/proseview/server.py).
- **Frontend**:
  - Added `utilityTabAgy` in [index.html.j2](file:///Users/ari/github/proseview/proseview/templates/index.html.j2) and hid it in static snapshots in [app.css](file:///Users/ari/github/proseview/proseview/templates/assets/app.css).
  - Added `"agy"` across `DISCUSS_AGENTS`, `DISCUSS_AGENT_LABELS`, `SCENE_PANEL_TABS`, `UTILITY_TAB_IDS`, `_chatHistoryState`, model catalog state, unavailable/not-connected guidance, and `Stop <agent>` labels in [68-discuss.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/68-discuss.js).
  - Generalized `/btw` agent checks and labels for `"agy"` in [69-btw.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/69-btw.js), and added `"agy"` to the Settings › Discuss default-agent picker and instruction summary in [81-suggestion-settings.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/81-suggestion-settings.js).

### Phase 3 — Group Room Integration *(Complete — 2026-11-17)*
- **Backend**:
  - Allowed `"agy"` in `clean_profile` ([group.py](file:///Users/ari/github/proseview/proseview/group.py)), `GroupSeatSettings.from_json` and `_clean_group_session` ([suggestions.py](file:///Users/ari/github/proseview/proseview/suggestions.py)), and `group_settings` / `_run_group_call` ([discuss.py](file:///Users/ari/github/proseview/proseview/discuss.py), including `AgyRequestError` → `_GroupThreadGone` thread recovery).
  - Updated `prepare_group_fork` and `_summary_worker` in [group_fork.py](file:///Users/ari/github/proseview/proseview/group_fork.py) to pair `agy` cleanly with another available provider and skip `thread/fork` when `capabilities["thread_fork"]` is `False`.
- **Frontend**:
  - Updated Group provider pickers, apply-plan target selector, saved-draft validation, duplicate `_groupAgentDisplay` cleanup, Send-to-Group fork dialog, and Settings › Group profiles/catalogs in [68-discuss.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/68-discuss.js), [69-group-composer.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/69-group-composer.js), [69-group-fork.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/69-group-fork.js), and [81-suggestion-settings.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/81-suggestion-settings.js).
- **Tests**: Parametrized Group model/skill tests across `("codex", "claude", "agy")` and added `agy` Group profile persistence, lost-thread recovery, and Send-to-Group fallback tests in [test_group.py](file:///Users/ari/github/proseview/tests/test_group.py) and [test_group_fork.py](file:///Users/ari/github/proseview/tests/test_group_fork.py).

### Phase 4 — Beatmap, Highlight Suggestions, and Structured JSON Hardening *(Complete — 2026-11-17)*
- **Structured JSON hardening**: Updated [agy_acp_client.py](file:///Users/ari/github/proseview/proseview/agy_acp_client.py) with `_extract_json_text` so `outputSchema` ACP turns cleanly extract raw JSON, fenced ```` ```json ```` blocks wrapped in explanatory prose, or outermost `{...}` JSON objects.
- **Highlight Suggestions & Settings › Suggestions**:
  - Updated [discuss.py](file:///Users/ari/github/proseview/proseview/discuss.py) (`suggest_for_highlight`, `suggestion_settings`, `save_suggestion_settings`), [suggestions.py](file:///Users/ari/github/proseview/proseview/suggestions.py) (`SuggestionAppSettings`), and [server.py](file:///Users/ari/github/proseview/proseview/server.py) (`_suggestion_save_source`) to support `"agy"` alongside `"codex"` and `"claude"`.
  - Updated [67-highlight-card.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/67-highlight-card.js), [68-discuss.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/68-discuss.js), [81-suggestion-settings.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/81-suggestion-settings.js), and [index.html.j2](file:///Users/ari/github/proseview/proseview/templates/index.html.j2).
- **Beatmap & Settings › Beat Map**:
  - Updated `_coerce_beatmap` in [config.py](file:///Users/ari/github/proseview/proseview/config.py) and `extract_beatmap_with_agent` in [beatmap.py](file:///Users/ari/github/proseview/proseview/beatmap.py) (including `discard_ephemeral_thread` cleanup).
  - Updated [72-beatmap.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/72-beatmap.js), [82-beatmap-settings.js](file:///Users/ari/github/proseview/proseview/templates/assets/js/82-beatmap-settings.js), and [index.html.j2](file:///Users/ari/github/proseview/proseview/templates/index.html.j2).
