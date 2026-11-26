# Configuring Proseview

[← back to the README](../README.md)

`proseview` works with zero config against a book in `manuscript/`. Without
that folder it opens as plain Markdown until you choose where the book is,
which writes `manuscript_path` here. Drop a `.proseview.yaml` at the repo root
if you want to customize:

```yaml
# Whether rendered Markdown may load images: all | local | off.
# `local` serves only files inside this repo; `off` shows alt text instead.
# `remote_in_agent_output: false` stops remote images inside AI replies
# from loading, since there the URL is the model's choice, not yours.
images:
  mode: all
  remote_in_agent_output: true

# Where the manuscript lives: chapter folders of scene files. Default:
# manuscript/. Use ./ when the whole folder is the book. If the folder does
# not exist, Proseview opens everything as plain Markdown until you choose.
manuscript_path: manuscript/

# Where character bios live. Default: story-bible/characters
characters_path: story-bible/characters

# Where AI skill prompts live. Default: .proseview/skills
skills_path: .proseview/skills

# Word-count goal for the finished book.
target_words: 80000

# Daily word goal (drives the "days to finish" estimate).
daily_target: 500

# Settings → General → Word variety sets these three: a preset saves the
# genre alone, Custom… saves both ranges.
#
# Genre: picks the typical MTLD range. childrens 40–60, contemporary 60–85,
# literary 85–110, speculative 90–120. Default: contemporary.
genre: literary

# Typical range for word variety nearby (Variety, MATTR). Default: 0.74–0.77.
mattr_band: [0.74, 0.77]

# Typical range for word variety across a scene (MTLD). Wins over the genre's.
mtld_band: [85, 110]

# Editor URL handler. One of: vscode, cursor, zed, positron, custom.
editor:
  scheme: vscode

# Folders shown in the file tree alongside the manuscript.
repo_tab:
  folders: [plans, continuity, outline, story-bible, docs, templates]

# Stable shortcuts shown when asking Codex about selected prose. Proseview
# displays at most three presets inline; additional presets are under More.
discuss:
  # Which agent tab the dock opens on: codex | claude. Both tabs always
  # exist and run independently; this only picks which one is in front.
  agent: codex
  selection_presets:
    - Is the grammar correct?
    - Make this more direct.
    - Check the point of view.

# Which frontmatter keys the Timeline and scene labels read. Defaults shown;
# point them at your own convention instead of renaming fields across the
# manuscript.
story:
  thread_field: thread
  day_field: day
  label_field: label

# Optional color assignments for scene labels (`c0` through `c7`, matching the
# eight Story tab colors). Unlisted labels automatically take the next unused
# color in the order they first appear in your book.
labels:
  palette:
    Main Plot: c0
    Subplot B: c2
    Flashback: c3

# Background colours for callouts (> [!letter] Title boxes), per type: one
# hex colour, or one per screen theme with `default` and `print`. See
# "Callouts" in docs/manuscript.md.
callouts:
  letter:
    background: "#f7f1e6"
```

Every key has a sensible default. Missing optional folders are skipped, but the
configured manuscript directory is required.

## Scene labels

Each scene can carry one label in its YAML frontmatter (by default `label: Main Plot`).
Your Markdown files only store the label name, never color codes:

- **`label:`** — sets a single label for the scene (or pick it from the dropdown in reading mode). If written as a YAML list, Proseview uses the first item and adds a note in **Analysis → What stands out**; picking, renaming or removing a label changes only that first item.
- **`story.label_field`** — defaults to `label`. Point it at an existing key such as `pov` or `thread` if you already track labels there.
- **`labels.palette`** — optionally maps label names to one of the 8 Story theme colors (`blue`, `orange`, `teal`, `amber`, `pink`, `green`, `purple`, `red` — legacy `c0`–`c7` aliases also work) or a custom `#hex` color (such as `"#4f7cac"`), editable from **Settings → Appearance → Labels** or directly here. You can also add, rename, or remove labels in **Settings → Appearance → Labels** (renaming or removing updates matching scene `.md` frontmatter and `.proseview.yaml`). Any invalid color raises a configuration error. Labels omitted from `palette` take the next unused color in the order they first appear in the manuscript (and any labels past eight fall back to neutral gray).
- **Display toggle** — **Settings → Appearance → Label colors** switches between **Subtle** (default: tinted sidebar icons, table dots, 3px card edges, and *Read the book* dots), **Soft sidebar rows** (adds a muted row wash in the file tree), and **Off**.

## Group profiles and conversation

**Settings → Group** holds a reusable library of agent profiles and
discussion presets on this computer. The default pair is **Story Editor**
(plot, stakes, pacing, continuity) and **Voice Editor** (voice, emotion,
atmosphere, rhythm). Each profile has a display name, specialty, conversational
style, Claude or Codex provider, and optional model and reasoning effort.
Blank model and effort choices inherit the provider’s individual chat settings.
Claude or Codex stays visible beside each name. A specialty guides perspective
without limiting what the agent can discuss.

Choose two profiles before starting a Group. Each conversation saves its own
participant snapshots, so later Settings edits or deletions do not rename or
change a saved conversation. Existing book-level Group names and prompts seed
the library until you save the new Settings; the original `.proseview.yaml`
configuration and saved revision plans remain available.

Groups belong to the book. Opening another scene keeps the current discussion;
the scene label shows the context for your next message. Messages already sent
or queued retain their original scene, and older line references still open
the scene they describe. **History** lists conversations across the whole book,
with their starting scenes. Open a saved Group without leaving the scene you are
reading, or choose **New** to start a separate discussion. A Group started by
typing uses its first message as its title. Existing discussions stay separate
and remain available in History.

A discussion preset selects two profiles and 2–12 explicit invitations, each
with a recipient and prompt. Click a starter card to preview its invitations,
swap participants, adjust the count, or select an optional recap. **Start
discussion** posts the invitations as small **Preset** notes in the shared
thread. A recap is an additional invitation to one of the existing participants.
There is no permanent moderator, and you can keep talking after the preset ends.
Edit preset names, descriptions, participants, invitations, and recap choices
in Settings, or add your own presets and profiles.

Type **@** in the Group composer to choose an agent or project file/folder.
The default tags are `@StoryEditor` and `@VoiceEditor`; `@Codex` or `@Claude`
also work when that provider belongs to just one participant. Tags override
the **To** selector for that message. Tag one agent for one invitation, tag
both to invite them in mention order, or use `@all` to address both editors.
Untagged messages default to both agents on a new discussion, and then follow the
last agent that replied for seamless back-and-forth conversation. You can also
choose a recipient with **To**. Either agent can quietly pass when they have nothing useful to add. A pass completes only
that invitation, never implies agreement, and does not cancel the next agent.
Use the arrow keys and Enter or Tab to choose a tag, Enter again to send, or
Escape to dismiss the picker. Custom names get corresponding tags, with a
number added when needed to distinguish duplicate names. Agent and file mentions
stay highlighted after sending, keep together as one token, and delete as a
whole mention in the composer. Copying a message preserves its original text.

File mentions identify reference material rather than changing who replies.
For example, `@VoiceEditor compare this with @story-bible/characters/shadi.md`
addresses the Voice Editor and makes that reference available in the discussion.
Group participants use the same tools and project settings as their individual
chats: they can read project files, search, and use configured tools and MCP
servers. References remain available when continuing or reopening the saved
thread, and mentioned paths must remain inside the project.

The composer includes the same context and model controls as individual chat:
**+** opens people/files/folders, typing **$** lists available agent skills, and each
participant has a model/effort picker. Model overrides belong to this Group and
leave the reusable profile and individual chat unchanged. A warning on a model
chip identifies an unavailable agent or model catalogue; open it to retry.
Presets check required agents before starting any invitations. These availability
checks do not guarantee authentication or connectivity for a later request.
The scene label shows the current context. Quick send uses the same favorites,
selection presets and recent instructions as individual chat. The text box can be resized; unsent
drafts and selected passages survive reload, and a selection stays attached for
follow-ups until removed or changed by an agent.

Editors can pass when they have nothing to add. A small status note acknowledges
the pass; if both pass on the same message, one note says neither had additions.
Passing does not stop the next invitation or create an empty reply card.

You can queue a message while agents are replying.
Queued messages keep their chosen recipients and can be removed before they
run. They are posted to the shared thread after the current invitations finish.
Change reviews never pause the discussion. Reloading reconnects to the server-owned discussion, including
remaining preset invitations and queued messages, without sending them twice.
After Stop, use **Resume remaining invitations** when you are ready.

Review snapshots and agent conversation links survive server restarts, so saved
changes can still be inspected or undone. If the server stops during a reply,
the Group first checks whether that reply completed. Otherwise it preserves any
partial reply and saved changes, then offers **Retry interrupted invitation**
or **Skip interrupted invitation**. It never automatically repeats an uncertain
edit. Saved changes remain available for optional review. An older review
that predates recovery support may be unavailable; the Group explains this and
keeps messages usable, with file history available to inspect the saved edits.

Tool permission requests appear in the Group with the same decisions as in
single chat. A critique or proposal does not itself authorize an edit.
After an agent changes files, the Group uses the same compact review card and
**Expand view** as individual chat. The large viewer can be resized, offers
split/inline layouts and font-size controls, and lets you untick individual
changes. Close it to use **Looks good**, **Undo all**, or undo only the unticked
changes. The next agent can reply immediately. Sending your next message keeps
the saved edits and applies any unticked changes automatically, as in single
chat; there is no separate **Continue discussion** step.

Ask either agent to summarize when you want, for example
`@Claude summarize the action items we all agreed on`. The agent receives the
shared discussion, including earlier proposals and corrections. Background
guidance asks it to distinguish the writer’s approval, agreement about a
direction, agreement on exact wording, and unresolved alternatives. Summaries
are ordinary chat replies and do not authorize edits. Existing revision-plan
cards from earlier Groups can still be reopened, applied, or added as TODOs.

## Privacy screen password

`Mod-J J` (hold Cmd, or Ctrl off a Mac, and tap J twice) covers the dashboard
with a plain budget spreadsheet, and the same again uncovers it. A covered
page stays covered through a reload, a new tab and a restart of Proseview,
until you uncover it. To ask for a
password before uncovering, set one under **Privacy screen** in Settings, or
from a terminal:

```bash
proseview privacy-password
```

Changing or removing it in Settings asks for the current password. If you
forget it, `proseview privacy-password --clear` removes it.

It is not kept in the book or in `.proseview.yaml`: only a salted hash is
stored, in your user folder (`~/Library/Application Support/Proseview` on
macOS, `$XDG_STATE_HOME/proseview` or `~/.local/state/proseview` elsewhere).
With a password set, `Mod-J J` on the spreadsheet shows a small password box;
Enter with the right one uncovers the page and a wrong one leaves it covered.
The covered state is a small `privacy-covered` file in the same folder. To
cover the page automatically after inactivity, choose a timeout under **Cover
when idle** in Settings (off by default); that preference is saved in
`privacy-settings.json` in the same user folder, never in the book, and
activity in any open Proseview tab keeps the timer reset. It keeps the
page from a glance over your shoulder; it does not encrypt anything, and
anyone at the computer can still open the files. A read-only snapshot and the
in-browser `/write/` book have the spreadsheet and idle timer, remembered by
that browser, but no password.
