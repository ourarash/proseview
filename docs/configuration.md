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

# Which frontmatter keys the Timeline reads. Defaults shown; point them at
# your own convention instead of renaming fields across the manuscript.
story:
  thread_field: thread
  day_field: day

# Background colours for callouts (> [!letter] Title boxes), per type: one
# hex colour, or one per screen theme with `default` and `print`. See
# "Callouts" in docs/manuscript.md.
callouts:
  letter:
    background: "#f7f1e6"
```

Every key has a sensible default. Missing optional folders are skipped, but the
configured manuscript directory is required.

## Writers’ Room names and conversation

**Settings → Writers’ Room** lets you name the two editorial seats and the
moderator. The defaults are **Story Editor** (plot, stakes, pacing, and
continuity), **Voice Editor** (voice, emotion, atmosphere, and rhythm), and
**Moderator** (the revision plan). Display names only change labels; role
instructions control each editor’s focus. Every editor header still identifies
Claude or Codex, independently of the name.

Names are saved with the book and can also be configured directly:

```yaml
room:
  critic1_name: Story Editor
  critic2_name: Voice Editor
  moderator_name: Moderator
```

Names may contain up to 60 characters; blank names use the defaults. Agent,
model, effort, and turn-count preferences remain on this computer.

When you send a message to both editors, the first answers you directly and the
second responds to your direction and the first editor’s contribution. Replies
use natural language rather than mandatory Agree/Disagree/Add labels. Concise
and Detailed set a preference for reply depth rather than a hard word limit.

Type **@** in the Room composer to choose an editor or a project file/folder.
The picker groups editors separately and shows each editor’s provider.
The default tags are `@StoryEditor` and `@VoiceEditor`; `@Codex` or
`@Claude` also work when that provider belongs to just one editor. Tags override
the **To** selector for that message. Tag one editor for one reply, or tag both
to have them reply in mention order. Untagged messages use the selected
recipient as before, and all replies remain in the shared Room transcript.
Use the arrow keys and Enter or Tab to choose a tag; press Enter again to send,
or Escape to dismiss the picker. Custom names get corresponding tags, with a
number added when necessary to distinguish duplicate names.

File mentions supply reference material rather than changing who replies. For
example, `@VoiceEditor compare this with @story-bible/characters/shadi.md`
addresses the Voice Editor and includes that file in the discussion. Room
editors use the same tools and project settings as their individual chats:
they can read other project files, search, and use configured tools and MCP
servers. File mentions identify references for the agent to inspect, as in
single chat. References remain available when continuing or reopening the
saved discussion, and mentioned paths must remain inside the project.

Tool permission requests appear in the Room with the same decisions as in
single chat. A critique or proposed revision does not itself authorize an edit;
editors change files when you ask them to. After an editor changes files, the
Room shows a review with the saved changes and an Undo action. Review the edits
and choose **Continue discussion** before the next editor or moderator proceeds.
The moderator only summarizes the transcript and does not use editing tools.

The revision plan separates **Agreed changes** (explicit support from both
editors for the same fix), **Other suggestions** (not yet endorsed by both), and
**Still open** (unresolved questions or competing fixes). Other suggestions
start unticked; you can select them to apply or add them as TODOs. Agreement on
a problem does not imply agreement on its replacement wording.

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
The covered state is a small `privacy-covered` file in the same folder. It keeps the
page from a glance over your shoulder; it does not encrypt anything, and
anyone at the computer can still open the files. A read-only snapshot and the
in-browser `/write/` book have the spreadsheet, remembered by that browser,
but no password.
