# Proseview Visual Quality Bar

Use this reference for audits concerned with modernity, polish, visual
direction, density, chrome, or interaction craft. It supplements the UI/UX
checklist; it does not replace workflow, accessibility, or safety evidence.

## Contents

1. Experience direction
2. Visual-craft criteria
3. Live comparison set
4. Workspace and design-system inventory
5. Interaction polish
6. External references
7. Classification and acceptance

## 1. Experience direction

Judge the current product against these durable qualities, while giving
accepted repository design records precedence when they are more specific:

- **Writing-first:** manuscript content dominates; application controls support
  the current task without competing with the prose.
- **Calm and literary:** typography, color, and spacing support long reading and
  editing sessions without becoming ornamental or precious.
- **Compact, not cramped:** frequent controls remain close and efficient while
  labels, focus indicators, and pointer targets stay legible and operable.
- **Contemporary desktop:** the interface feels intentionally composed rather
  than like default browser controls, an admin dashboard, or a collection of
  independently styled panels.
- **Quietly capable:** advanced analysis, AI, files, and terminal tools remain
  discoverable but use progressive disclosure and do not dominate reading.
- **Coherent:** repeated roles share tokens, component anatomy, state treatment,
  terminology, and motion across dashboard, scene, editor, and dock surfaces.

Do not equate modernity with a current fashion such as glass effects, extreme
minimalism, icon-only controls, low contrast, or animation. Prefer durable
clarity, proportion, restraint, and system coherence.

## 2. Visual-craft criteria

### Shell, hierarchy, and chrome

- Measure how much vertical and horizontal space persistent chrome consumes in
  the default writing state and with each discovered sidebar or dock state.
- Check whether global, document, contextual, and transient actions have
  visibly different levels instead of becoming one undifferentiated toolbar.
- Look for repeated boxed controls, nested cards, redundant headings, borders
  on every surface, and large empty regions that reduce content dominance.
- Verify that sticky, hidden, and auto-hidden regions preserve orientation,
  access to essential actions, focus visibility, and stable layout.
- Check whether opening a dock or sidebar leaves a deliberate reading column
  rather than merely squeezing the existing layout.

### Typography and spacing

- Identify the effective type scale, weights, line heights, measure, and use of
  prose versus interface fonts. Verify that headings differ by hierarchy, not
  only by boldness.
- Check alignment and spacing rhythm across repeated groups. Flag arbitrary
  one-off gaps when they create visibly inconsistent cadence or density.
- Judge compactness by task efficiency and readability together. Smaller is not
  automatically better when controls wrap, labels truncate, or targets shrink.

### Controls, icons, and states

- Compare buttons, fields, tabs, chips, menus, disclosures, and icon-only
  actions by role, height, padding, radius, border, label placement, and state.
- Identify mixed icon families, text glyphs used as icons, ambiguous symbols,
  baseline misalignment, inconsistent stroke weight, and icons that carry more
  meaning than their labels or accessible names support.
- Inspect default, hover, focus, active, selected, disabled, loading, success,
  warning, and destructive treatments side by side. State changes should feel
  related without depending on color alone.

### Surfaces, color, and depth

- Inventory page, panel, card, popover, dialog, editor, and dock surfaces.
  Verify that borders, shadows, elevation, and background shifts communicate a
  stable spatial model rather than decorative layering.
- Check semantic color consistency across themes. Accent color should identify
  priority or state, not make every interactive element compete equally.
- Look for obsolete visual signals such as heavy beveling, excessive outlines,
  browser-default controls beside custom controls, and dense card grids without
  a clear decision hierarchy. Describe the concrete system pattern; do not call
  something "dated" as a substitute for evidence.

### Composition and responsiveness

- Compare visual balance, content width, alignment anchors, wrapping, and scroll
  ownership at the required desktop contexts and 200% zoom.
- Inspect long titles, paths, labels, translated-length-like copy, empty states,
  dense results, and multi-panel states. A polished default with a broken edge
  state does not meet the bar.
- Verify that the most important writer action remains visually apparent after
  opening files, Discuss, terminal, menus, or proposal review.

## 3. Live comparison set

For a visual-modernization audit, capture this minimum temporary comparison
set. Do not multiply every state across every viewport, theme, and zoom level:

1. At the primary desktop viewport: populated dashboard, normal scene in
   reading mode, the same scene in editing mode, and the primary auxiliary dock
   or sidebar closed and open.
2. At the compact desktop viewport: the core reading or editing state and its
   most relevant open auxiliary panel. Add the dashboard only when the audited
   surface or recommendation affects it.
3. At either representative viewport: one relevant loading, empty, error, or
   conflict state when the audited surface participates in that state.
4. In light and dark themes: one identical high-information workspace state.
5. At 200% zoom: the core writing state with the audited chrome or panel visible.

Use identical fixture content, route, viewport, scroll position, and panel state
when comparing themes or variants. Record dimensions and visible state. Use the
set to evaluate system-level consistency and composition, even if no individual
screenshot proves a P-level defect. Delete it with the other audit artifacts
after extracting report evidence.

A discovered state that cannot expose or be affected by the requested surface
may be marked `Out of scope` with a trace-based reason. An applicable state that
is exposed but could not be exercised is `Not verified` and makes the focused
audit incomplete under the main completion gate.

## 4. Workspace and design-system inventory

Build a compact inventory from rendered UI and source corroboration:

| Category | Roles/variants found | Repeated pattern | One-off drift | User/craft consequence |
| --- | --- | --- | --- | --- |
| Typography | | | | |
| Spacing and sizing | | | | |
| Buttons and fields | | | | |
| Tabs, chips, and menus | | | | |
| Icons | | | | |
| Surfaces and depth | | | | |
| Semantic colors | | | | |
| Motion and transitions | | | | |

Do not demand a formal token framework merely because one is fashionable.
Recommend consolidation when repeated visible roles have drifted, one-off CSS
creates inconsistent outcomes, or future changes would predictably multiply
the inconsistency.

For the workspace shell, also record:

- persistent top-chrome height and approximate share of the compact viewport;
- reading-column width with auxiliary panels closed and open;
- number of simultaneously prominent primary-looking actions;
- wrapping, overflow, and number of competing scroll containers;
- whether the current document, mode, connection, and save state remain clear.

These measurements support comparison; they are not universal pass thresholds.

## 5. Interaction polish

Observe rather than infer:

- opening, closing, docking, resizing, and auto-hiding panels;
- menus, disclosures, tabs, selection tools, and proposal transitions;
- loading-to-content, save-to-confirmation, error-to-recovery, and live reload;
- hover and focus changes that move geometry or cause visual jitter;
- animation interruption, repeated activation, and reduced-motion behavior.

Prefer stable geometry and short, purposeful transitions. Motion should explain
where content came from or what changed, never delay a writing action or hide
system status. Record dropped frames or duration only when measured.

## 6. External references

When the user explicitly asks for design research or competitive comparison,
inspect a small current set of relevant desktop writing or productivity tools.
Use current first-party product material or a live product when accessible, and
record the source and date. Compare transferable principles such as content
dominance, chrome strategy, hierarchy, and panel behavior; do not recommend
pixel copying or treat popularity as usability evidence.

Without external research, evaluate against the experience direction and the
product's own cross-surface consistency. State that limitation.

## 7. Classification and acceptance

- Report demonstrated task, accessibility, comprehension, or recovery harm as
  a P0-P3 finding under the main report contract.
- Report a repeated visual-system problem without demonstrated task harm as a
  **craft opportunity**, not an inflated defect.
- Omit isolated taste preferences that cannot be tied to the experience
  direction, repeated system evidence, or a clear before/after principle.

A craft recommendation must name:

- the intended experience quality;
- the observed repeated pattern and affected surfaces;
- the visual or cognitive consequence;
- a system-level direction rather than a pixel prescription;
- an acceptance review across the comparison set, both themes, compact desktop,
  and 200% zoom where applicable.

This is expert heuristic evaluation, not user research. Do not claim that real
writers prefer, discover, understand, or complete something faster without
evidence from actual participants. Convert those claims into research questions
and propose the smallest task-based study needed to answer them.
