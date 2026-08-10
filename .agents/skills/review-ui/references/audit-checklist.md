# UI/UX Audit Checklist

Use this checklist as a demanding review rubric, not a mechanical source of
findings. Require evidence of user impact. Apply WCAG 2.2 Level AA to the
desktop experience and use established usability heuristics such as visibility
of system status, user control, consistency, error prevention, recognition over
recall, and recovery.

## Lane execution contract

For each lane, record:

- **Activation:** which discovered product surfaces and workflows make it
  relevant;
- **Live probes:** exact tasks/states exercised in the current build;
- **Evidence:** runtime outcome, focus/accessibility state, timing, console or
  request signal, isolated file effect, and source corroboration as applicable;
- **Coverage gaps:** unavailable states or harness limitations;
- **Status:** `Pass`, `Needs work`, `Fail`, `Not verified`, or `Out of scope`
  under the report contract.

Before assigning lane status, derive a capability-by-state matrix from the
current runtime and repository profile. Record each capability's claimed
scope, invocation states, complete task transition, recovery/next action, and
data boundary. Do not combine disconnected surface checks into journey
evidence. For claims implying universal reach, persistence, safety, or a whole
collection, select a counterexample from discovered configuration or fixture
boundaries rather than hardcoding a product feature or path here.

A lane passes only when its high-risk probes ran in the live product and the
evidence supports the expected writer outcome. Never generate a finding from a
generic heuristic without a concrete Proseview task, reachable scenario, and
observable impact.

## Contents

1. Information architecture and discoverability
2. Core workflow effectiveness and correctness
3. Interaction behavior, feedback, and recovery
4. Accessibility and keyboard usability
5. Visual design and data visualization
6. Content design and cognitive load
7. Performance and perceived responsiveness
8. Trust, data safety, and local-first clarity

## 1. Information architecture and discoverability

**Activation:** Product entry, navigation, dashboard/tabs, routes/history,
files/scenes, search/filter/sort, empty states, or control discoverability is in
scope or touched by the reviewed workflow.

- Verify that first-time users can identify the product's purpose, current
  location, primary actions, and a sensible next step without prior knowledge.
- Check whether dashboard, scene, file, TODO, note, editor, AI, and terminal
  concepts have clear boundaries and stable terminology.
- Confirm that global navigation, local navigation, browser history, deep
  links, and back behavior agree about location and state.
- Check that high-frequency writer tasks are prominent while advanced controls
  remain discoverable without dominating the reading surface.
- Verify that icons, symbols, disclosure controls, menus, filters, and table
  affordances communicate what is clickable and what will happen.
- Assess whether navigation or state depends on memory, hidden gestures,
  hover-only discovery, or unexplained shortcuts.
- Inspect empty collections and first-use states for guidance rather than dead
  space or unexplained absence.

**Pass evidence:** A new-session orientation trace plus successful pointer and
keyboard discovery of the primary dashboard, scene, file, and contextual action
paths, including URL/history state and one empty/first-use state.

## 2. Core workflow effectiveness and correctness

**Activation:** Always for a full audit; for a focused audit, the requested
writer workflow and every prerequisite, durable effect, and recovery path.

- Complete each workflow in `proseview-workflows.md` from the user's point of
  view; do not rely only on existing assertions.
- Verify that displayed titles, paths, counts, statuses, selections, filters,
  chart values, and saved content match the underlying demo data.
- Confirm that editing preserves frontmatter, Markdown meaning, annotations,
  emphasis, untouched prose, and file identity.
- Test undo, cancel, save, stale-file conflict, external changes, refresh, and
  navigation with unsaved edits. Look for silent loss or duplicate actions.
- Verify that TODO/note actions target the intended passage and preserve tag,
  location, text, and source file.
- Check that AI and terminal actions receive the intended file, selection, and
  instruction and that proposals remain reviewable and reversible.
- Assess large, sparse, empty, malformed, and unknown-status content where the
  harness supplies it. Distinguish product behavior from fixture limitations.
- Check whether analytics and editorial labels describe what is actually
  measured and avoid implying unsupported certainty.

**Pass evidence:** Required workflow completion with expected isolated file,
route, selection, count/status, terminal/agent context, and recovery effects;
unavailable safety states are named rather than inferred.

## 3. Interaction behavior, feedback, and recovery

**Activation:** Any control, selection, navigation transition, async action,
pending/error state, dismissal, undo/cancel, persistence, or recovery behavior
is exercised or changed.

- Verify immediate, perceivable feedback for navigation, filtering, saving,
  loading, spawning, refreshing, applying, rejecting, and destructive actions.
- Inspect default, hover, focus, active, selected, disabled, loading, success,
  warning, error, conflict, and empty states for major controls.
- Confirm that controls cannot be accidentally submitted twice and that
  disabled states explain prerequisites where ambiguity would result.
- Check whether modals, menus, popovers, selection tools, terminal panels, and
  sidebars open near the user's context, manage focus, dismiss predictably, and
  preserve work.
- Verify Escape, browser Back, Cancel, Undo, and close actions. Ensure each has
  an understandable scope and does not silently discard changes.
- Test failures and timeouts for actionable recovery. Reject raw exceptions,
  blocking browser alerts, silent catches, or indefinite spinners where they
  prevent the user from understanding or recovering.
- Check persistence across scene navigation and reload for preferences and
  work-in-progress states; distinguish intentional reset from lost state.

**Pass evidence:** State-transition observations for pending, success, error,
cancel/undo, conflict, duplicate activation, dismissal, reload, and recovery on
the affected core controls.

## 4. Accessibility and keyboard usability

**Activation:** Every user-facing workflow in a full audit; in a focused audit,
every rendered or interactive surface required to complete the requested task.

Apply WCAG 2.2 AA. Record failures by concrete success criterion when certain;
otherwise describe the behavior without claiming formal non-conformance.

### Semantics and names

- Verify a logical document title, language, landmarks, heading hierarchy,
  lists, tables, form labels, and native elements where available.
- Confirm that every interactive control exposes an accurate accessible name,
  role, value/state, and disabled/expanded/selected status.
- Check custom tabs, listboxes, menus, dialogs, trees, sliders, sortable
  headers, editor regions, status messages, and live updates against their
  expected keyboard and ARIA patterns.
- Ensure icon-only and symbol-only controls have meaningful names and purely
  decorative glyphs are hidden from assistive technology.
- Verify that validation, save results, errors, live reload, terminal state,
  and proposal state are announced without requiring focus movement.

### Keyboard and focus

- Complete core reading, navigation, editing, annotation, search, and recovery
  tasks without a pointer.
- Verify logical focus order, visible focus, no keyboard traps, and no focus
  loss into hidden or removed content.
- Confirm that dialogs contain focus, place initial focus intentionally,
  restore focus to the opener, and support Escape when dismissal is safe.
- Test standard keys for tabs, menus/listboxes, tree controls, sliders, table
  sorting, search results, and editor shortcuts. Do not accept pointer-only
  `onclick` behavior as keyboard support.
- Ensure sticky or fixed UI does not obscure the focused element.

### Perception and layout

- Check normal text contrast of at least 4.5:1, large text at least 3:1, and
  meaningful UI component, focus indicator, and chart contrast at least 3:1.
- Verify that color is not the sole carrier of status, selection, chart series,
  alert level, or editing state.
- Test text resizing and 200% zoom for clipping, overlap, hidden controls,
  two-dimensional scrolling, and loss of content or function.
- Check pointer targets against the WCAG 2.2 AA 24-by-24 CSS pixel minimum or a
  valid spacing/equivalent-control exception.
- Verify readable line length, line height, paragraph spacing, and typography
  in the reading/editor surface across supported fonts and themes.
- Respect reduced-motion preferences; avoid motion or flashing that obscures
  state or causes discomfort.
- Ensure charts and visual indicators have equivalent names, values,
  explanations, or tabular/text access where needed.

**Pass evidence:** A keyboard-only core-task trace, accessibility-tree or
computed-name/state inspection of custom controls, visible focus/focus recovery,
contrast/non-color evidence, and reflow/zoom observations mapped to relevant
WCAG 2.2 AA criteria.

## 5. Visual design and data visualization

**Activation:** Layout, hierarchy, typography, color/theme, responsive/reflow
behavior, charts, metrics, highlights, or visual status is visible in scope.

- Evaluate hierarchy, alignment, spacing, density, grouping, and consistency
  across dashboard, scene, file, editor, annotation, AI, and terminal surfaces.
- Check that primary, secondary, destructive, selected, and disabled actions
  are visually distinct without relying on decoration alone.
- Verify supported fonts and light/dark themes for contrast, layout stability,
  syntax/prose legibility, focus treatment, and semantic color consistency.
- Inspect 1400x1000, 1024x768, and 200% zoom for overflow, occlusion, cramped
  controls, broken sticky regions, and competing scroll containers.
- Check charts for meaningful titles, units, axes, legends, scales, ordering,
  target bands, zero baselines where relevant, and honest treatment of missing
  or small samples.
- Verify that dashboard density helps a writer decide what to do rather than
  presenting analytics without priority, explanation, or action.
- Treat personal visual taste as low-confidence unless it creates measurable
  comprehension, accessibility, consistency, or task-efficiency problems.

**Pass evidence:** Side-by-side observations across the required desktop
contexts and exposed themes/fonts, plus verified chart labels/units/scales and
text alternatives against current fixture data.

## 6. Content design and cognitive load

**Activation:** Labels, headings, help, errors, confirmations, onboarding,
shortcuts, analytics/AI terminology, or decision complexity appears in scope.

- Check labels, headings, help text, errors, confirmations, tooltips, and empty
  states for clarity, consistency, brevity, and writer-centered language.
- Verify that technical concepts such as MATTR, MTLD, SSE, agents, proposals,
  file paths, and terminal behavior are explained where users need them.
- Prefer specific action labels over ambiguous icons, internal terminology, or
  generic verbs such as "Submit", "Run", or "Open" without context.
- Check whether shortcut notation and platform assumptions match the running
  OS and whether keyboard alternatives are discoverable.
- Verify that warnings describe consequence and recovery, not merely that an
  error occurred.
- Assess whether defaults reduce decisions and whether advanced options are
  progressively disclosed.
- Look for contradictions between README promises and the live product, but
  report only user-relevant discrepancies.

**Pass evidence:** First-use and recovery copy explains the next action,
consequence, and relevant writer/AI/analytics concept without requiring source
knowledge; terminology stays consistent across live surfaces and current docs.

## 7. Performance and perceived responsiveness

**Activation:** Startup, loading, async feedback, large/many-content behavior,
search/filter/edit/render, terminal/process start, or an explicit performance
claim is part of the workflow.

- Observe initial load, scene open, search, filtering, chart rendering, theme
  switching, edit entry, save, large-scene editing, terminal startup, and live
  reload.
- Record measured timing when calling something slow; do not rely on vague
  impressions.
- Check for layout shifts, input lag, blocked interaction, scroll jank, stale
  data, duplicate requests, runaway console errors, and work hidden behind an
  unexplained delay.
- Verify that operations longer than an instant expose progress or a stable
  pending state and remain safe against duplicate activation.
- Separate network, environment, test-harness, and product costs.
- Judge performance by impact on writing flow, not synthetic numbers alone.

**Pass evidence:** Measured representative timings or responsiveness traces for
the activated workflows, including large-content or repeated interaction where
available, with product cost separated from environment and harness overhead.

## 8. Trust, data safety, and local-first clarity

**Activation:** File/draft mutation, discard/conflict/reload, destructive
actions, external editors, agent context, terminal authority, proposals,
network behavior, sensitive errors, or local-first claims are reachable.

- Verify that local-only behavior, file ownership, external-editor boundaries,
  agent access, terminal power, and any network use are communicated honestly.
- Check that saving, conflicts, refresh, live reload, AI proposals, destructive
  actions, and terminal closure prevent or clearly warn about data loss.
- Confirm that the UI distinguishes suggestions from applied changes and makes
  approval, rejection, undo, and current status visible.
- Verify that errors do not expose sensitive absolute paths or terminal output
  unnecessarily while still giving a local user enough information to recover.
- Check that dangerous actions are differentiated, narrowly scoped, and
  reversible where practical; confirmations should name the consequence.
- Ensure user files are never used for audit mutations. Validate write effects
  only in the harness's discovered disposable fixture copy.
- Treat silent failure, silent overwrite, misleading success, and ambiguous
  ownership as high-severity trust defects.

**Pass evidence:** Isolated demonstrations of save/conflict/discard, proposal
approval, agent/terminal scope, destructive action, and error recovery showing
that no real manuscript is touched and user authority remains explicit.
