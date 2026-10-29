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

# Healthy band for local lexical variety (MATTR).
mattr_band: [0.74, 0.77]

# Healthy band for whole-scene lexical variety (MTLD).
mtld_band: [105, 130]

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

## Privacy screen password

`Mod-J J` (hold Cmd, or Ctrl off a Mac, and tap J twice) covers the dashboard
with a plain budget spreadsheet, and the same again uncovers it. To ask for a
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
Enter with the right one uncovers the page, a wrong one leaves it covered, and
a reload or a new tab stays covered until the password is given. It keeps the
page from a glance over your shoulder; it does not encrypt anything, and
anyone at the computer can still open the files. A read-only snapshot and the
in-browser `/write/` book have the spreadsheet but no password.
