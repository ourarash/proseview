# Working with AI

Every AI feature in Proseview is optional and stays off until you ask.
Proseview has no model of its own and needs no API keys: it connects to the
local AI agent CLIs already installed and signed in on your computer—**Codex**
(OpenAI), **Claude** (Anthropic), and **Antigravity** (Google Gemini)—using
your existing plan.

[← back to the README](../README.md)

## Setup & prerequisites

Each agent tab runs on demand as a local process under your own login, model,
and settings. A missing or failing agent never blocks the other tabs or the
rest of Proseview.

- **Codex (OpenAI):** Install the Codex CLI (`npm install -g @openai/codex`)
  and sign in once (`codex`).
- **Claude (Anthropic):** Install [Claude Code](https://claude.com/claude-code),
  sign in once (`claude`), and make sure Proseview's `claude` extra
  (`claude-agent-sdk`) is installed. The one-line installer includes it
  automatically. If you installed with `pipx`, run:
  ```bash
  pipx install "proseview[claude]"
  # or add it to an existing install:
  pipx inject proseview claude-agent-sdk
  ```
  If you installed earlier with the one-line installer (`uv`), upgrade with:
  ```bash
  uv tool install --upgrade "proseview[claude]"
  ```
  Claude runs as it does in the Claude Code VS Code extension—loading your
  `CLAUDE.md`, skills, permission rules, and MCP servers—with two Proseview
  rules appended: only edit when asked, and surface every edit for review and
  one-click undo.
- **Antigravity (Google Gemini):** Install the Antigravity CLI (`agy`) and
  sign in once in a terminal (`agy`).

## Where AI shows up

### 1. Selection menu
Highlight any passage in a scene to see `Add TODO`, `Add Note`, and (when an
agent is connected) `Ask about selection` and `Skills`.

- Custom skills live in `.proseview/skills/<name>/SKILL.md` (or your
  configured `skills_path`) and appear automatically in the menu.
- In the composer, `$` picks project skills (currently lists Codex skills;
  Claude uses skills from your Claude settings automatically).
- Up to three **Presets** appear above the composer from
  `discuss.selection_presets` and your browser-local favorites, with extra
  presets and recent prompts under **More**.

### 2. Agent tabs (Codex, Claude, Antigravity)
The side dock gives each agent its own independent conversation, queue,
history, and approvals. Switch agents or open another file and active runs
keep going in the background—tab dots and the browser title let you know when
an agent is working or waiting on approval.

- **Context & mentions:** Every turn tells the agent which file is open (and
  any selected passage). Click the filename in the composer footer to open
  **Prompt context** and optionally attach the scene beat map, full scene text,
  story notes & frontmatter, or ±1 neighboring excerpts (all off by default,
  scoped to the thread). Type `@` to reference other files or folders as path
  chips. Each reply shows token usage and context fullness.
- **Approvals & reversible edits:** Reading files needs no confirmation;
  commands that write, reach the network, or interact with a running process
  wait for your approval. Every edit is saved with a review card showing the
  change count, **Expand view** (side-by-side diff), **Undo all**, and
  **Looks good**.
- **Progress & history:** A status strip shows the current step, elapsed time,
  **Details** (files read, searches, approvals), and **Stop**. Queued messages
  can be edited, removed, or sent immediately. `History` lets you reopen,
  rename, export, or delete past project conversations. Raw model reasoning is
  never stored or shown.

### 3. Scene reviews & Beat Map
Opening the dock on a scene offers four review workflows—click a card to run
with defaults, or **Customize** to choose the scope (this scene, neighbors,
chapter, or selection), feedback lanes, and finding count (5 by default, up to
20):

- **Quick critique:** Evidence-linked findings quoting the passage (**Before**),
  explaining the issue (**Why**), and offering a replacement (**After**).
- **Deepen & layer:** Finds opportunities for stronger tension, subtext, and
  sensory or emotional detail.
- **Craft review:** Evaluates the scene through McKee's *Story*, *The Story
  Grid*, *Story Genius*, *Save the Cat!*, *On Writing*, or *Bird by Bird*.
- **Comedy review:** Ten comedy lanes (truth and pain, comic premise, status,
  deadpan/subtext, setup/surprise, escalation/callbacks, specificity, timing,
  tone/target, violation/distance) plus optional style lenses (**Dark comedy**,
  **Sarcasm**, **Dry / deadpan**) and goals (**Strengthen existing humor**,
  **Find comic opportunities**).

**Comparing and applying findings:**
- Click **Compare** beside any quoted suggestion to open a word-level diff
  against your current scene (including unsaved edits) without applying
  anything.
- Check the items you want—and optionally click **Add note** on any item to
  steer the edit—and Proseview drafts an `"Apply items 1, 3, 5."` request in
  the composer (or click **Add to draft** if you already typed custom text).
- When a reply offers multiple rewrite options, you can select one directly to
  send back as an apply request.
- In a chat that already has messages, reviews ask whether to start fresh or
  **Run in this chat** (remembered per preference).
- **Beat Map** (in the **Beats** tab) plots an estimated tension curve and
  scene moments (dialogue, action, internal thought, silent reaction) without
  editing your prose, and flags itself out of date when the scene changes.

**Customizing prompts:**
Built-in prompts stay with Proseview and update automatically. Override any
prompt for the current book in **Settings → Discuss** (saved in
`.proseview.yaml`), or take full ownership of a skill by creating
`.proseview/skills/<name>/SKILL.md`. Precedence is YAML override → writer-owned
skill file → built-in prompt.

### 4. The Group (multi-agent debate)
Put two or three AI agents (**Codex**, **Claude**, and **Antigravity**) in one
conversation—focused on **story**, **voice**, and (optionally) **continuity**.

- Agents read the same scene and respond to each other—agreeing, pushing back,
  or passing—then produce a Markdown recap of agreed edits (with Before/After
  cards, clickable file/line links, and **Compare**), open decisions for you,
  and collapsed agent positions.
- **Send to Group** (in the menu beside **Send**) forks a finished one-on-one
  chat into the Group for a second opinion. You can keep the last 1–10
  exchanges (with an optional summary of earlier turns), let the other agent(s)
  weigh in and recap, or direct the conversation yourself.
- Checked review selections and notes transfer with **Send to Group** and
  survive reloads.

### 5. Scene illustrations
Click the picture button in the scene toolbar to ask Codex, Antigravity, or
Claude (when an image tool is available) for an illustration in one of six
styles, from woodcut to oil painting. Previews appear above the scene until you
insert one; inserted images save beside the chapter in its `assets/` folder
with a standard relative Markdown link so Obsidian, VS Code, and GitHub show
them too. Ask for revisions right in the chat that generated the image.

### 6. Continuity tools
Under the collapsed **Continuity tools** section:

- **Trace a canon change** scans your manuscript and configured repository
  folders (up to 200 supported text files / 4 MB, 50 displayed findings) and
  separates direct contradictions from ambiguous or intentional references,
  citing exact files and lines without editing anything.
- **Check this scene's continuity** runs the same read-only workflow focused on
  the open scene.

### 7. TODOs and Notes as plain Markdown
Every inline TODO and Note is stored as a standard
`<!-- TODO: ... -->` or `<!-- NOTE[tag]: ... -->` HTML comment in the scene
file—visible to your AI agents, tracked in Git, and searchable with `grep`.
