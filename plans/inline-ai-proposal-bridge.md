---
title: Terminal-Driven Inline AI Proposal Bridge
status: draft
date: 2026-05-10
---

# Terminal-driven inline AI proposal bridge

## Why this exists

The embedded terminal is the right place for a writer to talk with Codex:
it uses the user's existing CLI auth, feels close to the VS Code workflow,
and can run the same repository-local skills and instructions. The markdown
view is the right place to review prose changes: it can highlight exact
text, show replacement options in context, and apply edits through the
existing ProseMirror save path.

This feature connects those two surfaces. Codex stays the conversational
agent in the terminal. Proseview becomes the visual proposal, selection, and
apply surface.

## Target user journey

1. The user opens a scene in Proseview and starts Codex in the embedded
   terminal.
2. The user says something like: "Run the polish skill on this scene."
3. Codex reads the scene, applies the skill instructions, and finds a list of
   prose issues.
4. For each issue, Codex sends a structured proposal to Proseview. The
   proposal includes the target text, an issue summary, and several possible
   replacements.
5. Proseview resolves the target text against the current ProseMirror
   document, highlights that section in the markdown view, and opens an
   inline proposal panel.
6. The user can pick an option in Proseview or keep talking to Codex in the
   terminal to refine the suggestion.
7. Codex can update the active proposal with revised options.
8. When the user is satisfied, either the user clicks accept in Proseview or
   tells Codex to apply the final suggestion.
9. Proseview applies the replacement to the ProseMirror document and saves
   through the existing scene save flow.
10. Codex moves on to the next issue and Proseview highlights the next
    section.

## Responsibilities

Codex owns analysis and conversation:

- Run skills and interpret `AGENTS.md` or `SKILL.md` instructions.
- Read enough scene context to make good suggestions.
- Create, update, focus, skip, and apply proposals through the local bridge.
- Continue the natural-language conversation with the user in the terminal.

Proseview owns document interaction:

- Receive proposal events from Codex.
- Resolve target quotes or offsets against the current scene.
- Highlight the selected section in the ProseMirror view.
- Show issue text and replacement options in a compact review panel.
- Apply accepted replacements to ProseMirror, then save through the existing
  `/save-scene` endpoint.
- Protect against ambiguous ranges, missing ranges, stale documents, and
  external write conflicts.

Codex should not write the scene file directly for this workflow. All accepted
changes should pass through Proseview so the highlighted text, editor state,
mtime conflict checks, and saved file stay aligned.

## Architectural decisions

These decisions should be treated as part of the v1 contract so the
implementation does not take hidden shortcuts.

- Codex should discover the bridge through repo-local instructions, ideally
  `AGENTS.md` plus any relevant skill instructions. Those instructions should
  tell Codex to use the `proseview proposal ...` helper commands by default,
  not raw `curl`.
- Proposal state should live in memory on the running `proseview serve`
  process. Proposals are session review state, not manuscript data. Persistent
  proposal history can come later.
- Applying a proposal should update the live ProseMirror document first, mark
  it dirty, and save through the existing `/save-scene` flow. Server-side
  proposal endpoints must not directly rewrite scene files behind the browser.
- Range targeting must support raw Markdown line/column coordinates, explicit
  editor offsets, and exact-quote fallback. Line/column is the preferred agent
  path because Codex sees the raw Markdown file. If a target crosses
  `<!-- NOTE -->` or `<!-- TODO -->` annotations, Proseview must reject it
  rather than deleting hidden review state.
- Proposals may target any scene, but v1 apply behavior should first open and
  mount the target scene in the browser so ProseMirror owns the edit.
- Applying from terminal and accepting in the Proseview UI should use the same
  underlying proposal apply path. The terminal helper sends an apply intent;
  it does not edit files itself.
- V1 should support multiple Proseview browser tabs, but proposal focus/apply
  must be owned by one browser session. Each tab should register a client id,
  report its active scene, and only the matching/targeted tab should highlight
  or apply a proposal.
- The server stays localhost-only. All proposal paths must be repo-relative
  and validated under the configured manuscript root before any highlight or
  apply action.
- Skills should create one proposal at a time, wait for the user to accept,
  skip, or request refinement, then move to the next issue. Bulk proposal
  queues can wait until there is a dedicated queue UI.
- V1 should use a stable proposal panel in the scene chrome or side/bottom
  area. Avoid a floating text-adjacent bubble until the interaction model is
  proven.
- Accepting should apply the replacement to the editor and leave the normal
  save bar active. `Accept & Save` can be added if it fits cleanly, but normal
  editor save behavior is the baseline.
- This bridge should land before broad per-hunk AI diff review. The bridge can
  later feed item 17's diff-confirm workflow.

## Local bridge interface

The bridge is local to `proseview serve`. Codex can call it from the embedded
terminal, the VS Code Codex extension, or any other local Codex/external
terminal session by using either HTTP requests to `localhost` or a thin helper
command that wraps those requests. The embedded terminal is the recommended
default because it keeps the conversation and review surface in one app, but
the bridge should not depend on that origin.

### Proposal model

A proposal should contain:

- `id`: server-generated stable identifier.
- `client_id`: optional browser-session target for focus/apply events.
- `file`: repo-relative scene path.
- `quote`: exact text Codex wants Proseview to highlight.
- `range`: optional explicit start/end offsets or raw Markdown line/column
  coordinates when Codex can provide them.
- `message`: the issue summary shown to the user.
- `options`: one or more replacement candidates.
- `status`: one of `created`, `focused`, `updated`, `accepted`, `skipped`,
  or `failed`.
- `created_by`: usually `codex`.

Use raw Markdown line/column coordinates when available. Otherwise, the server
should locate `quote` in the current scene text before accepting the proposal.
Quote resolution should normalize whitespace into the editor-facing text shape,
but quotes and ranges that include `<!-- NOTE -->` or `<!-- TODO -->`
annotations should fail immediately.
If the quote is missing or appears more than once, `proseview propose` or
`proseview proposal update` should fail immediately with a useful error
instead of creating a broken proposal. The browser should still keep a final
resolution guard because it may have unsaved editor changes.

### HTTP endpoints

V1 should expose these local endpoints:

- `POST /ai/proposals`: create a proposal and enqueue it for the browser.
- `PATCH /ai/proposals/:id`: update message, quote/range, options, or status.
- `POST /ai/proposals/:id/focus`: make a proposal active and highlight it.
- `POST /ai/proposals/:id/apply`: apply the selected or final replacement.
- `POST /ai/proposals/:id/skip`: mark the proposal skipped and advance.
- SSE event stream: notify the browser when proposals are created, updated,
  focused, accepted, skipped, or failed.

The browser should subscribe to proposal events alongside the existing server
event stream or through a dedicated proposal stream. A dedicated stream is
cleaner once proposal state grows, but the existing SSE path is enough for a
first implementation.

### Browser sessions

Multiple browser tabs should be allowed. Each tab should register a generated
`client_id` with the server and include its current active scene in heartbeat
or focus events. Proposal events should be routed as follows:

- If a proposal has a `client_id`, only that tab should focus, highlight, or
  apply it.
- If a proposal has no `client_id`, the server may route focus to the tab
  already viewing the target scene.
- If no tab is viewing the target scene, the most recently active tab may open
  the scene and claim the proposal.
- If more than one tab is viewing the target scene and no tab is explicitly
  targeted, the proposal should enter a visible "needs target tab" state
  rather than applying in multiple places.

Only one browser session should own an active proposal at a time. This keeps
the user free to keep several Proseview tabs open while preventing duplicate
highlights or conflicting applies.

### Helper command contract

A helper command gives Codex a stable, easy-to-teach interface in `AGENTS.md`
and skills:

```bash
proseview propose \
  --file manuscript/ch01/01-opening.md \
  --start-line 42 \
  --start-col 1 \
  --end-line 44 \
  --end-col 24 \
  --quote "The exact passage to highlight" \
  --message "This sentence flattens the character's reaction." \
  --option "Replacement option one." \
  --option "Replacement option two." \
  --option "Replacement option three."
```

When Codex can provide raw Markdown coordinates, prefer `--start-line`,
`--start-col`, `--end-line`, and `--end-col`. Use `--quote` as a fallback.
Line/column targets must cover visible prose only; do not include NOTE/TODO
comment blocks.

Useful follow-up commands:

```bash
proseview proposal focus <id>
proseview proposal status <id>
proseview proposal update <id> --quote "Longer exact quote" --option "Refined replacement."
proseview proposal update <id> --start 120 --end 156
proseview proposal update <id> --start-line 42 --start-col 1 --end-line 44 --end-col 24
proseview proposal apply <id> --option 2
proseview proposal skip <id>
```

The helper should print the proposal id and enough status text for Codex to
continue the conversation naturally.

If Proseview cannot locate the quote, the browser should mark the proposal
`failed` with an error message. Codex should check `proseview proposal status
<id>`, then update the same proposal with a longer exact quote or explicit
offsets instead of creating unrelated duplicate proposals.

The helper must not assume it was launched from Proseview's embedded
terminal. It should discover the active local server from a runtime file such
as `.proseview/server.json`, containing at least the server URL, repo root,
and start time. If no server is running, the helper should fail with a clear
message telling the user to start `proseview serve`.

## Browser behavior

When a proposal becomes active, Proseview should:

- Open the target scene if it is not already open.
- Resolve the range and highlight it in ProseMirror.
- Scroll the highlighted section into view.
- Show a proposal panel near the highlighted text or in the scene chrome.
- Display the issue summary and replacement options.
- Offer `Accept`, `Skip`, `Refine in terminal`, and `Dismiss`.

Accepting an option replaces only the highlighted range. The document should
be marked dirty before saving, and the save itself should reuse the existing
mtime-checked `/save-scene` path. If the file changed externally after the
proposal was created, Proseview should surface the existing conflict behavior
instead of overwriting.

The terminal remains useful throughout the flow. The user can ask Codex to
combine options, change tone, explain the issue, or apply the final wording.
Codex then updates or applies the same proposal through the bridge.

## V1 scope

Build the smallest useful loop:

- Scene-local proposals only.
- One active highlighted proposal at a time.
- Quote-based range resolution, with optional explicit offsets.
- Multiple replacement options per proposal.
- Refinement by updating the active proposal.
- Apply from Proseview UI and from the helper command.
- Save through existing scene editor infrastructure.

Do not build cross-file edits, arbitrary patch application, per-hunk diffs, or
provider-specific API integrations in v1. Those belong after the bridge proves
the interaction model.

## Future extensions

- Full proposal queue sidebar with all issues found by the skill.
- Per-hunk diff review for larger scene rewrites.
- Manual range picker when Codex sends an ambiguous quote.
- Provider adapters for Claude, Gemini, and direct agent APIs.
- Proposal history stored with scene notes or session logs.
- Skill metadata declaring whether a skill produces proposals, diagnostics, or
  whole-file edits.

## Acceptance tests

- Codex or the helper can submit a proposal for the open scene and Proseview
  highlights the matching text.
- Multiple proposals queue and advance one at a time.
- Updating a proposal changes the visible options without losing the
  highlighted range.
- Accepting an option replaces only the highlighted text and saves through
  `/save-scene`.
- Applying from the terminal helper and clicking accept in Proseview produce
  the same document result.
- Ambiguous or missing quotes produce a visible failed state and do not edit
  the file.
- External file modification still triggers the existing mtime conflict path.
