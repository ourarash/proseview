# Working with AI

Every AI feature is opt-in and none of it runs on its own. Proseview has
no model of its own and no API key of yours: it drives the agent CLIs
already installed on your machine, under your login.

[← back to the README](../README.md)

Three places where AI shows up, all opt-in:

1. **Selection menu.** Highlight any text in a scene. The pill that
   appears includes `Add TODO`, `Add Note`, and (if an agent is installed
   locally) `Ask about selection` and `Skills`. Skills are
   reusable prompts you keep in `.proseview/skills/<name>/SKILL.md`; they show up
   automatically in the menu. In the question box, `$` picks one of the
   skills Codex offers for the project; on the Claude tab that picker is
   still empty, though Claude uses the skills in your Claude settings on its
   own.
2. **Discuss, on either agent.** The side dock has a **Codex** tab and a
   **Claude** tab. Each has a separate project conversation, with its own queue,
   history, and approvals — ask one, switch agents or open another file, and
   both keep working. `discuss.agent` decides which tab opens first; both tabs
   are always there, and one that cannot start explains why rather than
   disappearing.

   Every question tells the agent where you are, the way the editor
   extensions do: which file is open, and your selection if it is in the
   panel. A quiet line at the top of the panel names that file. The agent
   reads the file from the project when it needs to; the text itself goes
   along only when it has unsaved edits, which are not on disk to be read.
   Press `@` to mention other files and folders: they stay in the question as
   `@path` chips and send the path, not the file. Selection tasks and their
   follow-ups stay anchored to the passage you selected.
   Reading needs no answer. A command that would write, reach the network,
   or type into a command already running waits on an approval you can see.
   An edit is saved as it is made. After the turn a compact card shows the
   file and "N changes · saved", with **Expand view** for the diff side by
   side, **Undo all**, and **Looks good**; the card goes away when you send
   the next question. A reading pass makes no edits.

   A status strip between the conversation and the composer says what the
   agent is doing: starting, working (with the current step and a running
   clock), waiting on an approval, or finished, with how long the answer took.
   **Details** opens the turn's trail — the files it read, the searches it ran,
   the approvals you granted — in the order they happened. A turn that has
   produced nothing for a minute says so rather than spinning. The **Stop**
   button lives in that strip.

   The same state reaches you when you are not looking at the dock: the agent's
   tab carries a pulsing dot while it works and a steady amber one when it
   needs a decision, and the browser tab title says which agent is working or
   waiting whenever the dock is closed or the window is in the background.

   Every button is a shortcut to a skill supplied by Proseview. Built-in prompts
   stay with the app and receive its updates. Settings → Discuss lets you change
   a prompt for this book; only your override is saved in `.proseview.yaml`.
   You can also deliberately take over a skill by creating
   `.proseview/skills/quick_critique/SKILL.md` (or using your configured skills
   directory). Prompt precedence is YAML override, writer-owned skill file,
   then Proseview's built-in prompt. A writer-owned file can also customize the
   card's `description:` in its frontmatter.

   On the first run after this change, Proseview removes recognized untouched
   copies installed by older versions. Body-only edits are preserved as YAML
   overrides. Skills with custom metadata or supporting files remain writer-owned.

   Reading passes — critiques from the selection pill, and the scene passes
   below — are ordinary questions with ordinary answers. Nothing they return is
   written to your manuscript, so none of them produces a card, a structured
   result or anything that can go stale: the agent replies in the conversation
   and the passage it read stays attached, so a follow-up needs no reselecting.
   Rewrites are different, because their answer is prose that gets applied to
   your draft; those keep their card and their exact target.

   Opening the dock on a scene offers four review types. Click a card to run
   with defaults, or choose Customize to select this scene, its neighbors, the chapter, or a custom selection;
   then choose one or several feedback lanes. **Quick critique** returns evidence-linked findings, each quoting
   the line it came from and suggesting a fix. **Deepen & layer** explores places
   where a scene could carry more tension or emotional detail. **Craft review**
   lets you choose a writing book and the principles to examine. **Comedy review**
   examines the comic idea, character, delivery, and timing. Every lane has
   a short description and an information button with explanations and before/after
   examples. Lane labels in the feedback open the matching guide.

   Scene selection, context toggles, and one-time instructions carry across review
   types. Lane choices are remembered separately for each review type and book.
   Story facts and purpose are saved per scene and reused across review types and
   providers. All selected scenes are supplied in full, with source line numbers;
   neighboring excerpts are optional background for a single-scene review.
   **Check my notes for planned beats** is off by default: notes provide background.
   Turn it on to compare the draft with beats planned in frontmatter, beat maps,
   or TODO notes. The request receipt and context inspector show that choice.

   Each finding shows **Before** (the quoted passage and its line), **Why** (what
   goes wrong for the reader), and **After** (a replacement you can paste, or the
   passage as it reads after a cut). A review starts with problems in how the
   scene, or the selection, works as a whole. Customize sets how many findings a
   review may give (5 by default, up to 20) and remembers it; a card's Run now
   uses 5. **Show what to keep**, off by default and also remembered, adds one or
   two moments that already work. Bird by Bird keeps its single assignment.

   Comedy review has ten lanes: truth and pain; comic premise and perspective;
   character and status; deadpan and subtext; setup and surprise; escalation and
   callbacks; specificity and detail; timing and wording; tone and target; and
   violation and distance. The guides explain the techniques with original
   before/after examples, another example, a short exercise, and context for
   deciding when the technique helps. Book references are available in the
   guide; benign violation is credited separately to McGraw and Warren.

   Combine **Dark comedy**, **Sarcasm**, and **Dry / deadpan**, or leave the styles
   clear to follow the draft. Styles guide how the selected lanes are read;
   they do not add extra lanes. Both goals are selected by default:
   **Strengthen existing humor** preserves passages that need to stay serious,
   while **Find comic opportunities** asks for optional additions that serve the
   scene. Select either goal or both.
   Combined reviews label each finding as strengthening existing humor or proposing
   a comic opportunity, with one shared priority limit across both goals and the selection.
   Findings include source quotes, lane labels,
   explanations, and revisions you can paste. Comic options remain selected
   when switching review types and are sent only with Comedy review.

   The collapsed **Continuity tools** section contains two occasional revision
   actions. **Trace a canon
   change** scans the configured manuscript and repository-tab folders,
   separates direct contradictions from ambiguous and likely intentional
   references, and cites the exact file, line, and passage for every finding.
   Nothing is edited during the scan. You can preserve an intentional
   exception, send one scene finding at a time through the existing proposal
   review, then rescan to verify the result. **Check this scene's continuity**
   runs the same guarded workflow with the active document as its focus.

   Repository continuity scans are bounded to 200 supported text files, 4 MB
   of context, and 50 displayed findings. The impact report shows the actual
   files and bytes scanned, and warns when the finding limit is reached. These
   impact reports and their decisions are session-only in the current MVP.

   Under the hood each tab starts its agent on demand — a local
   `codex app-server`, or Claude through `claude-agent-sdk` — and uses the
   login, model, and history you already have. Neither sees the other's
   conversation, and a failure on one tab leaves the other running.

   Proseview stores one bounded project history per agent in your state
   directory, including which documents each thread discussed, and discards raw
   reasoning: only progress summaries reach the browser, never unedited model
   thinking. `History` lets you reopen, rename, export, or remove a previous
   project conversation. `New conversation` starts a blank discussion while
   keeping the previous one available there.

   The Claude tab needs the Claude Code CLI and Proseview's `claude` extra,
   which brings in `claude-agent-sdk`:

   ```bash
   pipx install "proseview[claude]"
   ```

   If Proseview is already installed with pipx, add the SDK to it instead:

   ```bash
   pipx inject proseview claude-agent-sdk
   ```

   Claude runs here as it does in the Claude Code VS Code extension: it loads
   your user, project, and local Claude settings (permission rules,
   `CLAUDE.md`, skills, MCP servers), uses Claude Code's own system prompt
   with Proseview's instructions appended, and asks you in the panel exactly
   where the extension would ask. Proseview adds only two rules: an edit is
   made only when you asked for a change, and every edit goes into the review
   at the end of the turn, where you can undo it.

   When selected prose is attached, the composer shows up to three **Presets**
   from `discuss.selection_presets` and your browser-local favorites. Favorites
   come first, duplicates are removed, and additional presets are available
   under **More**. Recent instructions are kept out of the inline preset row;
   open **More** to reuse or star one as a personal preset.
3. **TODOs as Markdown.** Every TODO and Note is a plain
   `<!-- TODO: ... -->` or `<!-- NOTE[tag]: ... -->` comment in the
   scene file. Your AI assistant can see them through the file, your
   repo can track them through git, and you can grep them.
