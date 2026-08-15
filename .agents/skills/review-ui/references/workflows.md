# Proseview Live Workflow Matrix

Use the current E2E harness and its fixture content as the source of exact
selectors, paths, example prose, and supported helpers. Do not copy private
helper implementations into the skill or edit the harness to enable an audit.

Before executing the matrix, build a live capability inventory from the current
repository profile:

| Workflow capability | Current route/control | Fixture/state source | Harness entrypoint/helper | Availability/evidence |
|---|---|---|---|---|

Resolve these fields from current code and live semantics. Never embed the
inventory back into the skill. The workflows below are durable audit intents;
their routes, labels, selectors, test names, fixture paths, agents, themes, and
implementation may evolve.

For a full audit, attempt every P0 workflow and every P1 workflow that the
current build exposes. Mark unavailable or obsolete workflows `Not verified`
with evidence. P0/P1 here describes coverage priority, not finding severity.

## Contents

1. Test contexts
2. Dashboard and navigation
3. Reading and analysis
4. Editing and file safety
5. Annotations and organization
6. Agents, terminal, and proposals
7. Exceptional states
8. Accessibility pass
9. Visual-modernization focused pass

## 1. Test contexts

- Use the harness's discovered generated/isolated fixture copy, never its
  committed source fixture, the primary repository as a manuscript, or a
  user's real manuscript.
- Use fake agent executables and isolated terminal/home configuration supplied
  by the harness. Do not launch a real Codex, Claude, or Gemini session.
- Run the primary context at 1400x1000 in the default light theme.
- Run a compact desktop context at 1024x768 and inspect the dashboard, scene
  header, reading body, editing bar, sidebars, popovers, and terminal panel.
- Run a 200% browser zoom pass on core navigation and editing. Record the base
  viewport and effective layout; do not describe this as a mobile audit.
- Run relevant reading and interaction checks in both light and dark themes.
- Capture uncaught JavaScript errors, console errors, failed requests, and
  unexpected page closures throughout every context.

## 2. Dashboard and navigation

### P0: orient and open a scene

1. Load the dashboard from a fresh browser context.
2. Identify the product purpose, total progress, major sections, primary
   navigation, and the likely next action.
3. Confirm that the scene table and charts finish rendering without errors.
4. Open a scene from the table, verify the URL and scene identity, then use
   browser Back and Forward.
5. Deep-link directly to a scene in a new context and verify equivalent state.

### P1: dashboard controls

- Switch Overview, TODOs, and Notes; reload each route and verify persistence.
- Sort the scene table in both directions and verify visible ordering and sort
  state. Exercise issue/status filtering and reset it.
- Search for scene text, metadata, a TODO, and a note. Navigate results with
  pointer and keyboard; verify empty, many-result, and dismissed states.
- Inspect chart labels, axes, legends, tooltips, target bands, empty data, and
  the relationship between chart values and fixture data.
- Open and close the file sidebar, expand/collapse directories, preview a
  non-manuscript file, deep-link it, and return to the dashboard.
- Resize the sidebar where supported and verify content remains reachable.

## 3. Reading and analysis

### P0: read and navigate scenes

- Open a normal scene, annotated scene, and large scene. Verify title, path,
  metadata, prose, alerts, and related information correspond to the source.
- Navigate to previous and next scenes, including boundaries. Verify URL,
  scroll position, selection state, and controls update coherently.
- Enter and leave focus mode. Verify the reading surface gains space without
  hiding the safe route back.

### P1: presentation and editorial aids

- Change reading font, size where exposed, and theme; navigate and reload to
  verify intended persistence and avoid flash/layout shifts.
- Toggle multiple editorial highlight passes, inspect labels and highlighted
  prose, navigate/reload, and verify selected states and explanations.
- Toggle line numbers where available and verify that they align, remain
  readable, and do not interfere with selection or zoom.
- Validate that alert and metric language is comprehensible and does not imply
  more certainty than the calculation supports.

## 4. Editing and file safety

### P0: safe edit lifecycle

1. Open a fresh isolated scene and enter edit mode.
2. Type into a known paragraph; verify the dirty state and save affordance.
3. Undo and redo with platform-appropriate shortcuts.
4. Save and verify visible confirmation plus exact file effects: preserve
   frontmatter, headings, annotations, emphasis, line structure where promised,
   and all untouched prose.
5. Reload and reopen the scene to confirm persistence.

### P0: loss prevention and conflicts

- Modify prose, then test Cancel, Escape, navigation, browser Back, scene close,
  and refresh. Verify the discard confirmation's copy, focus, choices, and file
  effect.
- Produce a stale-file conflict through the isolated harness. Verify no
  overwrite, clear consequence, preserved draft where possible, and a viable
  recovery path.
- Modify the scene externally and observe live reload in reading and editing
  contexts. Check that pending local work is not silently replaced.

### P1: demanding editor states

- Edit and save the annotated scene; verify TODO/NOTE atoms and Markdown
  emphasis survive.
- Edit the generated large scene and confirm input responsiveness, save timing,
  and untouched-content fidelity.
- Inspect selection, caret, scroll, and focus behavior when toggling edit mode,
  opening panels, zooming, and switching theme.
- Exercise save failure or rejected request if the harness already supports a
  safe route interception. Do not change the harness to manufacture it.

## 5. Annotations and organization

### P0: add annotations from prose

- Select known prose and open the selection affordance.
- Add a TODO, verify its source location and text, then find it in the TODO tab
  and navigate back to the exact scene context.
- Add a tagged note, verify tag/text/location, find it in Notes, filter by tag,
  and navigate back.

### P1: manage annotations

- Edit and delete an existing TODO and note in the isolated demo copy. Verify
  confirmation, cancellation, focus, exact file changes, and empty states.
- Inspect selection affordance placement near viewport edges, at 200% zoom, and
  for keyboard discoverability.
- Verify that annotations remain intact after unrelated scene edits and save.

## 6. Agents, terminal, and proposals

### P0: controlled agent context

- Launch each exposed fake agent from the scene menu and verify the UI makes
  the active file/context and terminal state understandable.
- Send a known selection and instruction to the fake Codex process; verify the
  exact passage and instruction reach it without exposing unrelated prose.
- Verify auto-approve state and labels communicate the elevated consequence.

### P1: terminal lifecycle

- Open a shell terminal, run a harmless marker command, create/switch/close
  tabs, change font size, change dock position, resize, clear, and reload.
- Verify disabled shortcut buttons, restoration after reload, output scrolling,
  keyboard focus, close semantics, and pending-file-change indication.
- Test terminal startup failure only if safely supported by existing harness
  controls or request interception.

### P0: AI proposal safety

- Create a proposal through the harness's supported CLI path and inspect its
  source range, proposed text, message, and visual distinction.
- Apply, reject/skip, and undo proposals as supported. Verify that no proposal
  silently writes, targets the wrong text, or loses surrounding content.
- Exercise arrival over SSE, page reload, stale proposal, and competing local
  edits where supported. Report untested safety states explicitly.

## 7. Exceptional states

Use existing fixtures, route interception, or safe temporary data only. Do not
extend the E2E harness to create a state.

- Empty search, no TODOs, no notes, unknown status, missing frontmatter, absent
  optional folders, disabled agent actions, and first-use preferences.
- Slow or failed fetch, save rejection, server disconnect, SSE reconnect,
  terminal failure, malformed preview response, and offline module behavior
  where the existing setup permits safe simulation.
- Very long scene, long path/title, many controls, small desktop viewport,
  multiple terminal tabs, and dense annotations.
- Verify each state for explanation, safe default, recovery, focus, accessible
  announcement, and absence of stale or misleading success UI.

## 8. Accessibility pass

Complete the following without a pointer:

1. Reach and operate global tabs, search, theme/font controls, file sidebar,
   scene table sorting, and scene opening.
2. Navigate a scene, toggle at least one highlight, enter edit mode, type, undo,
   invoke save/cancel, and safely exit.
3. Find and operate TODO/Note navigation and any accessible selection or
   annotation alternative. Mark pointer-only functionality as such.
4. Open and dismiss menus, dialogs, popovers, file preview, and terminal while
   tracking initial focus, focus containment, Escape, and focus restoration.
5. Inspect the accessibility tree or computed roles/names/states for custom
   tabs, listboxes, search results, dialogs, editor, tree, slider, sortable
   table, terminal controls, and live status.
6. Inspect visible focus, contrast, non-color cues, target size, reading
   typography, chart alternatives, reduced motion, 200% zoom, and compact
   desktop reflow using the accessibility checklist.

## 9. Visual-modernization focused pass

Use this section when the request emphasizes a modern, slick, polished,
compact, calm, or less dated interface. This is a focused audit mode, not a
shortcut around accessibility or core-task correctness: activate every lane
and workflow that the discovered visual change can affect.

1. Read `visual-quality-bar.md` and derive the current product's accepted
   visual direction from repository design records before judging style.
2. Build a state matrix for the discovered workspace shell. Include the primary
   dashboard, reading, editing, and auxiliary-panel states; current controls
   and routes must be discovered rather than copied from this reference.
3. Capture the visual quality bar's minimum temporary comparison set. Do not
   run a Cartesian product of every state, viewport, theme, and zoom level;
   use its stated primary, compact, theme, exceptional-state, and zoom samples.
   Mark a trace-unreachable state `Out of scope` and an applicable but untested
   state `Not verified` under the main completion gate.
4. Measure persistent top chrome, available reading width with panels closed
   and open, competing primary-looking actions, wrapping/overflow, and scroll
   ownership. Use measurements comparatively, not as universal thresholds.
5. Inventory rendered and source-level typography, spacing/sizing, controls,
   tabs/chips/menus, icons, surfaces/depth, semantic colors, and motion. Trace
   repeated visible drift to its component or token source when possible.
6. Exercise opening, closing, docking, resizing, sticky/auto-hidden behavior,
   menus, loading, save, error, and recovery transitions exposed by the current
   build. Inspect stable geometry, focus visibility, interruption, and reduced
   motion rather than reviewing only static screenshots.
7. Identify what should be removed, consolidated, demoted, progressively
   disclosed, or made content-dominant before proposing decoration. Preserve
   Proseview's local, dependency-light desktop constraints.
8. Report demonstrated user harm as P0-P3 findings. Report repeated visual
   system gaps without demonstrated task harm as craft opportunities using the
   report contract. Do not inflate aesthetic preference into severity.
9. If the user explicitly asked for research or competitive comparison,
   inspect a small current set of relevant products under the visual quality
   bar's external-reference rules and cite the current sources. Otherwise state
   that no external benchmark was performed.
