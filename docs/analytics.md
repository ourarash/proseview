# The analytics

[← back to the README](../README.md)

Lexical health is real, not vibes:

- 📐 **MATTR** (moving-average type-token ratio, window 100). Measures
  *local* vocabulary variety. Low = the same words inside a paragraph.
- 📐 **MTLD** (measure of textual lexical diversity). Measures
  *whole-scene* variety. Low = the scene keeps circling the same ground;
  high = the scene keeps reaching.
- 📐 **Dialogue percentage**, **passive voice rate**, **crutch-word rate**,
  **first-person density**, **sensory density**, **filter-verb rate**,
  **paragraph length**.

The `mattr_band` and `mtld_band` (or the genre's range) work as floors: a
scene under either gets a **Review** badge in the deep-dive table, with the
reason on hover. A scene above them is fine and is not flagged.

**Character presence** and **co-occurrence** count scenes, not name
mentions. A character is in a scene when its `characters:` or `pov:`
frontmatter names them; a scene without a `characters:` list falls back to
the prose. Mentions hid a first-person narrator, whose name the prose
rarely says.

**Goals** read the files on disk, not only commits. Proseview keeps the word
total it sees each day in `.proseview/day-log.json`, so "Today", words a
day and the streak count work you have not committed. A day counts toward
the streak when a scene was saved or committed, so a day of cutting keeps it.

**What changed** (the Today number, or the button on the Progress card)
shows the words written and cut in each scene, two ways:

- **Proseview's record:** Today, Yesterday, the last 7 or 30 days. Proseview
  keeps a copy of your scenes in `.proseview/` and updates it whenever it
  sees a file change, whatever editor you write in; when a day ends it keeps
  that day's written and cut per scene. Days it wasn't running are counted
  on the next day it saw, and the dialog says so.
- **Git:** your files now, including anything not committed, against a
  commit you choose.

Until Proseview has a copy from before today, the Progress card's number is
labelled "Since <date> (last commit)" and measured from your last commit.
