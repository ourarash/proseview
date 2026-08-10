# Proseview: pre-launch review and positioning

**Date:** 2026-08-09
**Scope:** honest assessment of the repo, competitive landscape, and what to do
before inviting outside users.

> ✅ **Section 1 is fixed** and shipped before the first public release. It is
> summarised here for the record; the exploit details are deliberately omitted.

---

## 1. Ship-blocker: unauthenticated mutations — FIXED

Pre-release, only `/api/discuss/*` required authorization. Every other
state-changing endpoint — terminals, saves, TODOs, notes, AI proposals —
accepted requests from any origin, and endpoints taking an absolute path
resolved it without a containment check.

"Local-only" is not a security boundary. The browser is: any page the user
visits can reach `localhost`, and a rebound hostname can do it with its own
origin attached.

### What shipped

1. `_authorize_mutation` gates **every** mutating request on a per-run session
   token, delivered to the page and to the CLI via `.proseview/server.json`
   (mode `0600`). A custom header also forces a CORS preflight that the server
   never answers.
2. `_is_local_request` pins `Host` (and `Origin`, when sent) to loopback on
   reads as well as writes, closing DNS rebinding.
3. `_contained_abs_path` requires client-supplied paths to resolve inside the
   served repository and refuses symlinks.

See [SECURITY.md](../SECURITY.md) for the resulting model. No vulnerable
version was ever published to PyPI.

---

## 2. Honest review

### Genuinely good

- 16k LOC product / 8.6k LOC tests, 400 tests across three tiers including a
  real-browser tier. Rare discipline for a solo alpha.
- Zero-config, vendored front-end dependencies, no build step.
- Plain Markdown + git. No lock-in, and it is real rather than marketing.
- The analytics (MATTR/MTLD, sentence-rhythm variance, character
  co-occurrence) are the actual differentiator, and they are undersold.

### Weak

| Problem | Why it matters |
|---|---|
| macOS/Linux only | Novelists skew Windows and iPad. `fcntl` at `server.py:12` is unconditional, so Windows fails at import, not just at the terminal. |
| No export | No docx/epub/compile anywhere in the codebase. Writers submit to agents and publishers. bibisco and Longform both export. |
| No demo | You must clone and run the server to see anything at all. |
| Discuss is Codex-only | A headline feature is bet on one vendor's CLI. |

### The uncomfortable one

This is a developer's tool wearing a novelist's clothes. It assumes git, a
terminal, Markdown files on disk, and a logged-in Codex CLI. The overlap
between "writes novels" and "has Codex installed" is tiny. Every AI feature —
the most-promoted section of the README — is invisible to a normal novelist.

Decide honestly who this is for. It changes everything downstream.

---

## 3. Competitive landscape

| Tool | Model | Price | Their strength | Gap vs Proseview |
|---|---|---|---|---|
| **Sudowrite** | SaaS | $10–44/mo | Muse, a model fine-tuned on published fiction | Will never be beaten on prose generation |
| **NovelCrafter** | SaaS, BYO key | ~$4/mo + API | Codex wiki keeps a long book consistent | Proseview has no worldbuilding/consistency layer |
| **AutoCrit** | SaaS | paid | Prose analytics benchmarked against published books | **Closest competitor.** Cloud, upload-your-manuscript, subscription |
| **Fictionary** | SaaS | paid | Story-structure / developmental editing | Different altitude |
| **Obsidian + Longform** | Local, free | free | Where Markdown novelists already live (70+ books written in it) | No analytics, no git view, no dashboard |
| **novelWriter / bibisco** | Local, OSS | free | Mature, cross-platform, exports | Proseview loses on platform + export, wins on analytics |

**The gap worth owning:** AutoCrit's analytics, but local, free, and on your own
files. Nobody in the open-source/local tier does what these charts do.

---

## 4. Positioning

### Stop leading with AI

1. That fight is unwinnable. Sudowrite has a fine-tuned fiction model and funding.
2. A loud share of novelists are actively hostile to AI tooling. An AI-forward
   README gets dismissed by exactly the Markdown-and-git purists most likely to
   love everything else.
3. The AI features require a dev environment almost none of them have.

### Lead with this instead

> **Proseview — a writer's dashboard for a folder of Markdown.**
> Point it at your manuscript. Get lexical health, pacing, character presence,
> and revision history from your own files. Nothing uploads. Nothing locks in.
> AI is optional and brings your own.

This reframes every weakness as a feature: local-only becomes privacy,
no-account becomes no-subscription, Markdown becomes no-lock-in, and the AI
work becomes a bonus for those who want it.

### Who to target, in order

1. **Developers who write fiction.** Small, but reachable this week on
   HN/Lobsters, and the product already fits them exactly. The first 100 users.
2. **Obsidian + Longform / novelWriter users.** Thousands of Markdown novelists
   with an editor and zero analytics. Position as a *companion*, not a
   replacement: "keep writing in Obsidian, run Proseview for the numbers."
   This is the real market.

Do not chase Sudowrite's audience. Different product, different person.

---

## 5. Launch checklist

### Before posting anywhere

- [x] Fix the unauthenticated-mutation hole in section 1. Non-negotiable.
- [x] Rename repo to `proseview`; claim the PyPI name.
- [x] Publish to PyPI so `pipx install proseview` works (0.1.1, trusted publishing).
- [x] Add `SECURITY.md` stating plainly that it runs a local server with shell
      access, and how to report issues.

### Then, highest leverage first

- [ ] **Live demo on GitHub Pages.** The generator emits standalone static
      HTML — dashboard, scenes, charts, and search all work with no backend. A
      "try it in your browser, no install" link is worth more than every README
      paragraph combined. Biggest missing asset, and nearly free.
- [ ] A 20-second GIF at the top of the README (select text → highlight passes
      → search). Stills undersell an interactive tool.
- [x] Rewrite the README's top third around the dashboard pitch; demote AI to
      one section.
- [x] Repo presentation: GitHub Releases for each tag, topics, homepage URL.

### Where to post

Show HN, Lobste.rs, r/selfhosted, r/commandline, the Obsidian forum, and the
novelWriter/Longform communities.

**Skip r/writing** — an AI-adjacent tool posted there gets dogpiled. Lead with
"analytics for your Markdown manuscript" everywhere.

### Two decisions that cap growth (neither blocks launch)

- **Windows support.** WSL-only cuts most of the writer market.
- **Export.** Writers need docx eventually.

---

## Sources

- [Sudowrite vs NovelCrafter comparison](https://usenoren.ai/blog/sudowrite-novelcrafter-alternatives)
- [AI fiction tools tested, 2026](https://blog.mylifenote.ai/the-11-best-ai-tools-for-writing-fiction-in-2026/)
- [AutoCrit review](https://prowritingaid.com/autocrit-review)
- [novelWriter](https://novelwriter.io/)
- [bibisco](https://bibisco.com/)
- [Obsidian Longform](https://github.com/kevboh/longform)
- [Writing 70+ books in Markdown](https://pdworkman.com/writing-a-novel-in-markdown/)
- [Type.ai pricing](https://type.ai/pricing)
