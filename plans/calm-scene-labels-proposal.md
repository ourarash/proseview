---
title: Calm Scrivener-Style Scene Labels & Color Coding in Pure Markdown
status: proposal
date: 2026-11-19
---

# Calm Scrivener-Style Scene Labels & Color Coding in Pure Markdown

## Goal

Bring Scrivener’s scene **Labels** and **color coding** (for tracking POVs, subplots, timelines, or scene types) into Proseview while preserving two core Proseview commitments:

1. **Pure Markdown & Git-friendly files:** Every label lives in ordinary YAML frontmatter inside the scene’s `.md` file; no sidecar database, no HTML comments, and no hex color codes inside prose files.
2. **Calm editorial UI:** Avoid Scrivener’s loud highlighter bars and 6-checkbox per-surface settings menu. Reuse the Story tab’s existing color variables for tinted sidebar icons (plus an optional soft binder row wash), table dots, 3px card edges, and subtle *Read the book* cues, controlled by one setting in Appearance.

---

## 1. Data & Configuration Model

### Per-scene storage (YAML frontmatter)

Each scene carries **one scalar label value** in its YAML frontmatter—by default `label:`:

```yaml
---
pov: Mara
status: revision
label: Subplot B
---
```

- **One label per scene:** Matches Scrivener’s model, keeps the YAML scalar (`key: value`), and prevents multi-color clutter in the sidebar and on cards.
- **List-valued label handling:** If a scene writes its label field as a YAML list (e.g. `label: [Main Plot, Flashback]`), use the **first item** for display/filtering and emit a note in **What stands out** ([`_analysis_findings`](file:///Users/ari/github/proseview/proseview/generator.py#L809-L840)) naming the affected scenes.
- **Distinct from `status:`:** `status` (`draft`, `revision`, `done`, `unknown` in `proseview/scenes.py`) remains the workflow state; `label` is the structural/editorial tag.
- **No hex codes in `.md` files:** Keeping the frontmatter purely semantic ensures manuscripts stay clean and portable in Obsidian, VS Code, and Git diffs.
- **Keep [`FRONTMATTER_SCAFFOLD_FIELDS`](file:///Users/ari/github/proseview/proseview/server.py#L1457-L1459) unchanged:** Empty scenes are never padded with blank `label:` keys, and unlabeled scenes render with zero visual clutter.

### Project-level mapping (`.proseview.yaml`)

Follow the convention already established by [`StoryConfig`](file:///Users/ari/github/proseview/proseview/config.py#L194-L205) (`thread_field`, `day_field`):

```yaml
story:
  thread_field: thread
  day_field: day
  label_field: label   # optional; e.g. point at `pov` or `thread` instead

labels:
  palette:
    Main Plot: c0
    Subplot B: c2
    Flashback: c3
    Mara: c4
```

- **Configurable `story.label_field` (default `"label"`):** Writers who already categorize scenes by `pov:` or `thread:` can point `label_field` at that existing frontmatter key rather than duplicating metadata across files.
- **Reuse the Story tab’s palette (`--story-c0`..`--story-c7`):** `labels.palette` maps label names directly onto the existing 8 Story tab color tokens already defined in [`proseview/templates/assets/app.css`](file:///Users/ari/github/proseview/proseview/templates/assets/app.css#L11110-L11131) for `:root`, `[data-theme="dark"]`, and `[data-theme="hopscotch"]`.
- **Strict validation (`c0`..`c7` only):** `labels.palette` accepts only `"c0"` through `"c7"` and raises a clear `ConfigError` for any other value (such as hex codes, CSS color names, or out-of-range slots).
- **First-seen order assignment (no hash fallback):** When `labels.palette` is omitted—or when a scene uses a label not listed in `labels.palette`—assign unmapped labels in the order they first appear in the manuscript across the remaining unused slots (`c0`..`c7`), matching [`build_story_model`](file:///Users/ari/github/proseview/proseview/story.py#L231-L242) (`MAX_THREADS = 8`). Beyond 8 distinct labels, render overflow in a neutral muted tone (`--accent-neutral`) rather than wrapping back onto `--story-c0`.

---

## 2. Calm UI Design

Color coding uses `--story-c0`..`--story-c7` strictly as small, scannable anchors across Proseview’s views:

### Five calm touchpoints

1. **Sidebar file tree (`80-sidebar-init.js` + `repo.py`)**
   - **Tinted scene icons (default):** In [`buildSidebarItem`](file:///Users/ari/github/proseview/proseview/templates/assets/js/80-sidebar-init.js#L245-L250), tint `.sidebar-scene-icon` directly with `var(--story-cN)` (and a soft fill) for labeled scenes, with the label name in `title` / `aria-label`. Coloring the existing page icon adds zero extra clutter per row.
   - **Optional soft row wash:** When **Soft sidebar rows** is chosen in Appearance, also give labeled rows a muted, desaturated wash (`color-mix(in srgb, var(--story-cN) 16%, transparent)`) starting at the icon so tree indentation and the active selection row remain legible. Unlabeled scenes stay neutral.

2. **Overview Table & Cards view (`generator.py`, `index.html.j2`, `50-discard-confirm.js`)**
   - **Table ([`_scene_table_body`](file:///Users/ari/github/proseview/proseview/generator.py#L771-L780)):** Add `data-label` to `.scene-row` and render a **6px color dot** (plus quiet pill using `color-mix(in srgb, var(--story-cN) 12%, transparent)`) next to `status_badge` when a label is set. Keep table rows borderless on the left.
   - **Cards view ([`renderOverviewSceneCards`](file:///Users/ari/github/proseview/proseview/templates/assets/js/50-discard-confirm.js#L200-L294)):** Apply a **`3px` left edge stripe** (`border-left: 3px solid var(--story-cN)`) to `.scene-overview-card`—evoking Scrivener’s index-card color tab without tinting the card body—and place the quiet label pill in `.scene-overview-card-foot`.
   - **Filter (`#issueFilter`):** Extend [`_sceneRowMatchesFilter`](file:///Users/ari/github/proseview/proseview/templates/assets/js/50-discard-confirm.js#L170-L186) and `#issueFilter` in [`index.html.j2`](file:///Users/ari/github/proseview/proseview/templates/index.html.j2#L443-L444) with `label:<slug>` options so writers can isolate a single label across the table and cards grid.

3. **Scene Reading Mode Header & YAML Frontmatter (`30-router-modal.js`, `13-frontmatter.js`, `40-prose-editor.js`)**
   - **Reading mode only:** In [`updateModal`](file:///Users/ari/github/proseview/proseview/templates/assets/js/30-router-modal.js#L158-L169), display a compact dropdown trigger beside `.scene-technical-path` (`● Subplot B`, or `+ Label` when unset) **only while in reading mode**. In edit mode, hide the dropdown because `#sceneFrontmatter` is directly editable as YAML (which also avoids any unsaved-prose conflict).
   - The dropdown lists the book’s existing labels (each with its color dot), plus **“New…”** (inline input for a new label name) and **“Clear”** (when a label is set).
   - **Save through existing `/save-scene` (no new endpoint):** Selecting or clearing a label updates only the `label_field` line in the scene’s YAML frontmatter (creating a `---` block if `frontmatter_text` is `null`, and preserving comments/other keys) and persists via the existing `/save-scene` handler in [`server.py`](file:///Users/ari/github/proseview/proseview/server.py#L3507-L3522) with `open_mtime` conflict protection and scene history backup.
   - In [`fillFrontmatterHighlight`](file:///Users/ari/github/proseview/proseview/templates/assets/js/13-frontmatter.js#L107-L140), render a matching inline color dot beside the `label_field` value in the frontmatter viewer so the UI-to-Markdown link stays transparent.

4. ***Read the book* continuous view (`45-book.js`)**
   - On each [`.book-scene`](file:///Users/ari/github/proseview/proseview/templates/assets/js/45-book.js#L91-L110) section in **Read the book**, show a small colored dot (and tooltip/quiet label tag) next to the `.book-scene-open` cue—giving writers Scrivener’s *Scrivenings Titles* orientation while reading straight through without interrupting prose.

5. **Timeline tab (`18-timeline.js`)**
   - In [`_renderShape`](file:///Users/ari/github/proseview/proseview/templates/assets/js/18-timeline.js#L97-L124), add a lightweight `Color by: Chapter | Label` toggle (shown when at least one scene has a label). This lets writers inspect POV or subplot balance across the entire manuscript strip using the exact same Story colors.

### One Appearance setting (no 6-checkbox menu)

Instead of Scrivener’s 6-checkbox *Use Label Color In* submenu (`Binder`, `Icons`, `Index Cards`, `Outliner Rows`, `Scrivenings Titles`, `Show as Background Color in Binder`), put one **Label colors** setting in **Settings → General → Appearance** ([`#settingsPanelGeneral`](file:///Users/ari/github/proseview/proseview/templates/index.html.j2#L706-L715)), persisted in `localStorage`:

- **Subtle** *(default)* — tinted sidebar scene icons, table dots, 3px card edges, and *Read the book* scene dots.
- **Soft sidebar rows** — same as Subtle, plus a muted row wash starting at the icon in the sidebar.
- **Off** — hides all label colors across the workspace while keeping YAML frontmatter untouched.

---

## 3. Codebase Integration Map

| Layer | Module | Proposed Change |
| :--- | :--- | :--- |
| Config | [`proseview/config.py`](file:///Users/ari/github/proseview/proseview/config.py#L194-L205) | Add `label_field: str = "label"` to `StoryConfig` and parse `labels.palette` (`label -> c0..c7`), raising `ConfigError` on any invalid palette value. |
| Scene parsing | [`proseview/scenes.py`](file:///Users/ari/github/proseview/proseview/scenes.py#L39-L82) | Add scalar `label: str` (and `label_is_list: bool`) to `SceneStats`, using the first item when `fm.get(cfg.story.label_field)` is a list. |
| Sidebar tree | [`proseview/repo.py`](file:///Users/ari/github/proseview/proseview/repo.py#L562) | Attach `label` and resolved `label_slot` (`0..7`, `"other"`, or `None`) to scene nodes in `build_sidebar_tree`. |
| Payload, table & findings | [`proseview/generator.py`](file:///Users/ari/github/proseview/proseview/generator.py#L631-L870) | Emit `label`, `label_slot`, and `labelsCatalog` in `build_scene_data`; emit `data-label`, a 6px dot, and quiet pill in `_scene_table_body`; add a **What stands out** finding in `_analysis_findings` when any scene has a list-valued label. |
| Styles & HTML | [`proseview/templates/index.html.j2`](file:///Users/ari/github/proseview/proseview/templates/index.html.j2#L706-L715), [`proseview/templates/assets/app.css`](file:///Users/ari/github/proseview/proseview/templates/assets/app.css#L11110-L11131) | Add the **Label colors** setting (`Subtle` / `Soft sidebar rows` / `Off`) under **Settings → General → Appearance**; reuse `--story-c0`..`--story-c7` (plus `color-mix()` for pill tints and soft sidebar row washes, and `--accent-neutral` for `other`). |
| Frontend JS | [`80-sidebar-init.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/80-sidebar-init.js), [`50-discard-confirm.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/50-discard-confirm.js), [`45-book.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/45-book.js), [`13-frontmatter.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/13-frontmatter.js), [`30-router-modal.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/30-router-modal.js), [`40-prose-editor.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/40-prose-editor.js), [`18-timeline.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/18-timeline.js), [`80-settings.js`](file:///Users/ari/github/proseview/proseview/templates/assets/js/80-settings.js) | Tint sidebar scene icons (and optional soft row washes), render table dots, card 3px edges, *Read the book* scene dots, filter options, inline YAML dot, reading-mode-only header dropdown (`<labels>` + `New…` + `Clear`) saving via `/save-scene`, Timeline toggle, and Appearance mode switch. |
| Documentation | [`docs/manuscript.md`](file:///Users/ari/github/proseview/docs/manuscript.md), [`docs/configuration.md`](file:///Users/ari/github/proseview/docs/configuration.md) | Add a short section explaining `label:`, `story.label_field`, and `labels.palette` (`c0`–`c7`). |

---

## 4. Phased Rollout (Tests & Docs with Each Phase)

1. **Phase 1 — Config, read-only calm display, and unit/browser tests:**
   - Implement `StoryConfig.label_field`, strict `labels.palette` (`c0`..`c7` validation), first-seen slot assignment (no hash fallback), list-to-first-item coercion + **What stands out** note, tinted sidebar scene icons (plus optional soft row wash), Overview table dots, card 3px left edges, *Read the book* scene dots, `#issueFilter` label filtering, and the Appearance **Label colors** switch.
   - **Ship tests:** Unit tests for config validation (`c0`..`c7` vs invalid errors), first-seen slot ordering, `>8` overflow, list-valued label parsing + `_analysis_findings` note; browser tests for tinted sidebar icons, soft row wash mode, Overview table dots vs card edges, *Read the book* cues, filtering, and Appearance toggle.
   - **Ship docs:** Document `label:`, `story.label_field`, and `labels.palette` in `docs/manuscript.md` and `docs/configuration.md`.

2. **Phase 2 — Reading-mode dropdown, Timeline toggle, and E2E tests:**
   - Implement the reading-mode-only header dropdown (`<labels>`, `New…`, `Clear`) saving via `/save-scene` (including scenes with no prior frontmatter), inline YAML frontmatter dot, and Timeline `Color by: Chapter | Label` toggle.
   - **Ship tests:** Browser/E2E tests verifying the dropdown appears only in reading mode (hidden in edit mode), updates/creates/clears YAML frontmatter cleanly via `/save-scene` without stripping comments, and updates the Timeline color toggle.
