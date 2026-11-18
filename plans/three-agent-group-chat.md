# Three-Agent Group Chat Design (`2` or `3` Agents, Default `3`)

## 1. Summary & Decisions

Extend Proseview's **Group** chat room, preset workflows, Moderator summary, and **Send to Group** fork flow so writers can collaborate with either **2** or **3** AI editors simultaneously, with **3 agents as the default**.

Agreed product decisions:
1. **Default 3rd critic (Seat 3)**: **Continuity Editor** (`continuity-editor`) running on **Agy** alongside **Story Editor** on **Codex** (Seat 1) and **Voice Editor** on **Claude** (Seat 2). Focuses on timeline continuity, setup/payoff consistency, physical logic, and concrete scene details.
2. **Turn execution & untagged addressing**:
   - Turns run **sequentially** in queued seat order so later editors see and respond to earlier editors' messages within the same round.
   - Fresh / untagged rounds default `To:` to **All active seats** (`[1, 2, 3]` in 3-agent mode; `[1, 2]` in 2-agent mode). Once at least one critic has replied, untagged composer messages continue auto-targeting the **last critic who spoke** (matching current `auto` behavior), while `@all`, `@mentions`, or explicit selection in the `To:` dropdown can address `All (3)`, `All (2)`, any subset via `@mentions`, or a single `Seat N only`.
3. **Choosing `2` vs `3` agents & workflow adaptation**:
   - Provide a **`2 agents` / `3 agents`** switcher in **Settings › Group** (default `3`) and in the **Group dock bar** before the first turn of a conversation (locked once turns begin).
   - Built-in workflows (`Editorial critique`, `Trim & tighten`, `Deepen & layer`, `Pitch the next beat`, and `Second opinion & recap`) dynamically adapt cleanly between 2 and 3 seats.
4. **Send to Group**:
   - Defaults to **3 participants** (`Original assistant`, `Second opinion`, `Third perspective` spanning Codex / Claude / Agy) with a **2-vs-3 toggle** in the Send-to-Group dialog.
   - Each participant card exposes independent **Provider**, **Model** (including custom model), and **Reasoning effort** pickers.

---

## 2. Backend Changes

### 2.1 Configuration (`proseview/config.py`)
- Extend `GroupConfig` with book-level Seat 3 fields:
  - `critic3_name: str = "Continuity Editor"`
  - `critic3_prompt: str = ""`
- Extend `.proseview.yaml` serialization and `_coerce_group()` validation with `critic3_name` and `critic3_prompt` using the same character-length bounds (`SUGGESTION_PROMPT_MAX`) as Seats 1 and 2. Existing `.proseview.yaml` files lacking Seat 3 fields keep working seamlessly using the new defaults.

### 2.2 Library, Profiles, Computer Settings & Moderator Prompts (`proseview/suggestions.py`)
- Add `DEFAULT_GROUP_CRITIC3_PROMPT` (continuity, setup/payoff consistency, physical details, scene logic).
- Extend `GroupComputerSettings`:
  - Add `critic3: GroupSeatSettings = field(default_factory=lambda: GroupSeatSettings(agent="agy"))` and update `to_json()` / `from_json()`.
  - Update `effective_library()` default profiles to include:
    1. `story-editor` (Story Editor · Codex)
    2. `voice-editor` (Voice Editor · Claude)
    3. `continuity-editor` (Continuity Editor · Agy)
  - Default `default_profiles` to `["story-editor", "voice-editor", "continuity-editor"]`.
  - When upgrading an existing untouched 2-profile library on disk, append `continuity-editor` if absent; preserve user-customized 2-seat `default_profiles` if intentionally saved, while still exposing the 3rd profile and 2/3 toggle in Settings › Group.
- Update `group_participants(book, app)` to construct 2 or 3 participants from `default_profiles`, assigning seats `1..N`, unique `@handles`, and provider aliases only when a provider appears once among active participants.
- Update `DEFAULT_GROUP_PRESET_STEPS`:
  - Expand built-in 5-turn workflows (`editorial_critique`, `tough_love`, `deepen_and_layer`, `pitch_next_beat`) so Seat 1 opens, Seat 2 audits voice/subtext, Seat 3 audits continuity/physical logic/plot holes, Seat 1 synthesizes, and Seat 2/3 stress-tests the ending or climax, with recap defaulting to Seat 3 (or adapted to Seat 2 in 2-seat mode).
- Update `render_group_moderator_prompt(...)`:
  - Accept any `N ∈ {2, 3}` participants (`participants` context dynamically lists seats 1..N instead of `"between two critics"`).
  - Allow `proposed_by` to be `"Critic 1"`, `"Critic 2"`, `"Critic 3"`, or `"Writer"`.
  - Clarify `agreed`: explicit endorsement by the active participating critics without false failure when a critic passed or was uninvolved on a sub-point.
  - Extend `open` disagreements from fixed `{issue, critic1, critic2}` to allow optional `critic3` (or `positions` keyed by seat, keeping `critic1`/`critic2`/`critic3` backward-compatible with existing tests/sessions).

### 2.3 Pure Group Validation & Prompt Helpers (`proseview/group.py`)
- Rename pair helpers / generalize validation:
  - `clean_participants(raw)`: validate `isinstance(raw, list)` and `2 <= len(raw) <= 3`, unique profile IDs, unique handles (`Editor1..EditorN` fallback), and `seat` `1..N`.
  - `clean_library(raw)`:
    - Validate `2 <= len(profiles) <= 32`.
    - Validate `default_profiles` and `preset["profiles"]` as `roster(value)` allowing **2 or 3** distinct valid profile IDs.
    - Validate invitation `seat` in `(1, 2, 3)` and `recap` in `(0, 1, 2, 3)`. If a preset specifies `seat == 3` with only 2 `profiles` configured for that preset, raise `GroupLibraryError` cleanly unless dynamically adapted at runtime.
  - Add `adapt_preset_for_participants(preset: dict, participants: list[dict]) -> dict`:
    - When `len(participants) == 3` and a preset was saved for 2 seats: keep the preset's invitation steps, and when running a built-in workflow in a 3-seat room insert/assign Seat 3 into the review cadence (or fall back cleanly without dropping Seat 3 from `session.participants`).
    - When `len(participants) == 2` and a preset includes `seat == 3` (e.g. a 3-seat workflow run in a 2-seat room): remap `recap == 3` → `recap = 2` and filter or fold redundant `seat == 3` steps so the 2 active editors still execute a clean alternating debate.
  - Update `second_opinion_preset(profiles)`:
    - For 3 profiles: Seat 2 weighs in → Seat 3 adds third-angle critique/continuity → Seat 1 responds → Recap (`recap: 3`).
    - For 2 profiles: retains Seat 2 → Seat 1 → Recap (`recap: 2`).
  - Update `GENERAL_CHAT_GUIDANCE`, `DEFAULT_CHAT_GUIDANCE`, `chat_instructions`, `chat_prompt`: replace `"two"` / `"both"` phrasing with `len(participants)`-aware wording (`"participant {seat} of {count}"`).
  - Update `positions_table(turns)`: record explicit stances for `seat in {"1", "2", "3"}`.

### 2.4 Durable Group Runtime (`proseview/group_runtime.py`)
- Replace `(1, 2)` and `[1, 2]` with `valid_seats = tuple(range(1, len(group["participants"]) + 1))` across:
  - `_submit`: `@all`/`@everyone` or initial untagged turn queues `list(valid_seats)`; auto-last-responder picks last `turn["seat"] in valid_seats`; explicit `seats` validates `all(s in valid_seats for s in seats)` while preserving requested order. Error text becomes `"Choose at least one active participant"`.
  - `_preset`: resolve steps with `adapt_preset_for_participants(preset, group["participants"])` before queuing steps and recap.
  - `_load` & `command("models")`: allow updating `model` and `effort` across all `2` or `3` participants in `group["participants"]` while keeping participant identity, provider, and count immutable once turns exist.

### 2.5 Moderator Schema & Discuss Manager (`proseview/discuss.py`)
- Update `_MODERATOR_SCHEMA` in `proseview/discuss.py`:
  - `proposed_by` enum: `["Critic 1", "Critic 2", "Critic 3", "Writer"]`.
  - `open` item properties: `issue`, `critic1`, `critic2`, and optional `critic3` (not required when only 2 critics participated).
- Preserve `"critic3"` in normalized moderator output and `_clean_group_session` in `proseview/suggestions.py`.

### 2.6 Send to Group (`proseview/group_fork.py`)
- Update `prepare(manager, source, body)`:
  - Default roster builds **3 participants**:
    - Seat 1: `Original assistant` (`source.agent`, carrying active chat `model` & `effort`),
    - Seat 2: `Second opinion` (first available other provider in `DISCUSS_AGENTS`),
    - Seat 3: `Third perspective` (next available other provider in `DISCUSS_AGENTS`, e.g., `[Codex, Claude, Agy]` ordered around `source.agent`).
  - If `body.get("participants")` supplies 2 or 3 customized participants (provider, `model`, `effort`), validate with `clean_participants` (`2..3`) and check token/context limits via `_limit_errors` across all selected participants.
  - Update user-facing warning strings from `"Both participants start fresh sessions..."` to `"All participants start fresh sessions..."`.

---

## 3. Frontend & UX Changes

### 3.1 Group Header, Roster & Disagreements (`proseview/templates/assets/js/68-discuss.js`)
- Replace `_groupSnapshotPair` / `_groupPairPicker` with `_groupSnapshotRoster` / `_groupRosterPicker` supporting `2` or `3` participants.
- Add a **`2 agents` | `3 agents`** segmented toggle in the pre-chat Group setup bar (disabled/hidden once the room has turns or queued steps, mirroring current lock rules):
  - Switching `2 → 3` appends Seat 3 from `default_profiles[2]` (or next unused library profile with remaining provider).
  - Switching `3 → 2` removes Seat 3 while retaining Seat 1 & Seat 2 choices.
- Per-seat header pickers render profile + provider (`Codex`, `Claude`, `Agy`) for each active seat, with a **`↻ Rotate providers`** (or swap) button for multi-seat assignment.
- Generalize `_groupLastCriticSeat`, `_groupEffectiveTarget` (`'all'` instead of `'both'`, keeping legacy `'both'` alias mapped cleanly), `_groupBothLabel` → `_groupAllLabel` (`Group (All 3: Codex, Claude, Agy)` or `Group (Both: Codex, Claude)`), and `@mention` routing so selecting e.g. `@StoryEditor @ContinuityEditor` queues `[1, 3]` cleanly.
- Render Seat 3 turn cards with `.is-critic-3` badge/border and include `Critic 3` in the Moderator **Open disagreements** block when present.

### 3.2 Group Composer (`proseview/templates/assets/js/69-group-composer.js`)
- Dynamically build `#groupTargetSelect` options:
  - `all`: `Group (All N: ...)`
  - `critic1`: `<Seat 1> only`
  - `critic2`: `<Seat 2> only`
  - `critic3`: `<Seat 3> only` (rendered when `session.participants.length === 3`)
- Render compact `createGroupModelControl(session, profile)` buttons for all active participants, styled cleanly with flex-wrap so 3 model chips fit without clipping inside the dock width.

### 3.3 Send to Group Dialog & Positions Table (`proseview/templates/assets/js/69-group-fork.js`)
- Add a **`Participants: [ 2 agents | 3 agents ]`** selector in `renderDiscussGroupFork()` (default `3`).
- Render each participant card (`2` or `3` cards) with:
  1. **Provider** (`Codex`, `Claude`, `Agy`)
  2. **Model** (`Provider default`, fetched model list, and `Custom model…` input)
  3. **Reasoning effort** (`Provider default` + supported effort levels for the chosen model/provider)
- Generalize `groupPositionsCard()` to iterate `session.participants` (`1..N`) instead of hardcoded `[1, 2]`.
- Update `openCurrentGroupWorkflow()` so 3-seat rooms retain all 3 active participants when invoking any workflow card.

### 3.4 Settings › Group (`proseview/templates/assets/js/81-suggestion-settings.js`)
- Replace hardcoded pair-only controls (`_rmPairFields`) with `_rmRosterFields` + a **Default room size (`2 agents` | `3 agents`, default `3`)** control.
- Allow adding/selecting `2` or `3` default participants and `2` or `3` preset participants; populate invitation `seat` (`1..N`) and `recap` (`0..N`) selectors dynamically from `preset.profiles.length`.
- Guard profile deletion on `library.profiles.length <= Math.max(2, library.default_profiles.length)` and any active preset/default reference.

### 3.5 CSS (`proseview/templates/assets/app.css`)
- Add `.group-turn-card.is-critic-3` and `.group-critic-badge.is-critic-3` across light, dark, `hopscotch`, and `graphite-dark` themes (emerald/teal accent distinct from Seat 1 sky blue, Seat 2 amber, and Writer coral).
- Adjust `.group-composer-actions`, `.group-participant-choice`, and `.group-fork-models` grids to accommodate 3 items smoothly at standard dock and dialog widths.

---

## 4. Verification Plan
1. **Backend unit & integration tests**:
   - Extend `tests/test_group.py`, `tests/test_group_runtime.py`, `tests/test_group_context.py`, `tests/test_group_fork.py`, and `tests/test_highlight_suggestions.py`:
     - Validate 2-seat and 3-seat `clean_participants` / `clean_library` / default `GroupConfig` & `GroupComputerSettings`.
     - Verify `@all` routes `[1, 2, 3]`, subset `@mentions` route `[1, 3]`, and `To: Auto` targets the last critic in `1..3`.
     - Verify `adapt_preset_for_participants` expands/folds workflows cleanly between 2 and 3 seats.
     - Verify Moderator `open` & `agreed` outputs accept `Critic 3` and optional `critic3`.
     - Verify `group_fork.prepare` defaults to 3 participants, accepts 2-or-3 toggles, and preserves per-seat `model` + `effort`.
     - Verify saved 2-seat Group history records reload without errors.
2. **Browser E2E tests (Playwright)**:
   - Update affected 2-seat expectations where default is now 3 seats, and add end-to-end tests covering:
     - Default 3-agent Group room turn flow (`Codex` + `Claude` + `Agy`), Seat 3 badge/card, `Positions` 3-column table, and Moderator `Critic 3` disagreement rendering.
     - Toggling `3 → 2 → 3` before turn 1 and verifying workflow preset adaptation.
     - Opening **Send to Group**, toggling `2` vs `3` agents, selecting per-agent **Provider + Model + Effort**, and verifying the forked Group inherits all chosen models and efforts.
