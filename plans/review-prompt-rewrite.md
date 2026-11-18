# Review prompts: a short contract that leaves the model free

## Reasoning

Reviews got worse when the prompt got longer. Before commit 01ea10c ("Add
configurable scene reviews"), Quick critique sent only its short skill: quote the
line, explain the problem, give a drop-in replacement, remove anything not
useful. The reviews were long and gave good Before/After fixes. Now every card
adds about 1,400 words of shared rules, and reviews come back short and minor.

The rules were not wrong one by one. Each fixed a real failure. Together they
change how the model behaves:

- **Every "don't" makes the model more cautious.** About ten of the rules say
  what not to report: "do not manufacture faults", "zero revisions is
  acceptable", "a limit, not a target: give fewer, or none", "if unverified,
  don't build a finding on it", "remove marginal notes". A literal model reads
  them together as "saying little is safest" and picks the findings easiest to
  prove, such as continuity slips.
- **Structure takes the place of judgment.** The prompt asks for a reading, an
  arc and scene notes before any finding. The model spends its effort filling in
  the sections and treats the fixes as an afterthought.
- **Detailed formats leave loopholes.** "A short optional replacement or a
  possible beat sequence" allowed arrow summaries and "try cutting lines
  111–121". More wording did not make the fixes more useful.

Agents do better when they are told the goal and left free to decide how to
reach it. So this proposal keeps a rule only if it passes one of two tests:

1. **The app depends on it.** The citation checker, the quote labels and the
   lane guide links need a particular format.
2. **A real review failed without it,** and one line fixes it.

Everything else is the model's call: how many findings, how to group them,
whether to explain the chapter's arc first, how long each fix is. Rules come
back one at a time, and only when a test shows they are needed.

## Evidence

| Run | Cap | Result |
| --- | --- | --- |
| Codex · Craft review (McKee) · Chapter 8, 8 scenes | 16 | 3 findings: two timing mismatches and one trim, none chapter-level |
| Codex · Quick critique · 08-perkinss-office | 5 | 1 finding: shorten a paragraph. Opens with "motivated on the page" |
| Claude · Craft review (McKee) · Chapter 8 | 5 | 4 findings, but two fixes are "cut L185–L206" or an arrow sequence |
| Claude · same chat, asked for "before and after" | n/a | Full pasteable Before/After for all four |

Asked why it gave 3, Codex said it treated the cap as a ceiling, kept only what
it could clearly support, and "filtered too aggressively".

## The proposed contract

About 220 words, shared by every card except Bird by Bird. The selected lanes'
definitions follow it as now; they describe what to look for, not how to behave.

> The review guide below supplies the editorial lens; this format governs the
> output. If they conflict on format, follow this format.
>
> Find what most holds this scene or selection back, and fix each problem with
> text the writer can paste. Give up to {N}, most important first.
> Start with problems in how the scene (or selection) works as a whole: its
> turn, a choice that doesn't land, a stretch where the pressure stalls. Then
> problems in single passages.
>
> For each problem:
> - A short heading and a **Lane: <name> — <why>** line, using a selected
>   lane's exact name.
> - **Before:** on its own line, then the passage quoted exactly in an italic
>   blockquote, with its link on the line below it, such as
>   [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18).
> - **Why:** what goes wrong for the reader, in plain words.
> - **After:** Replace [03-the-harbor.md · Line 18](…):, then the replacement text in
>   a plain blockquote, ready to paste. For an addition, cite the insertion
>   point instead: **After:** Insert after [03-the-harbor.md · Line 18](…):. For a cut,
>   show how the passage reads after it.
>
> Rules:
> - Quote exactly; no ellipses.
> - Before saying something never appears or is never set up, search for one
>   distinctive word. If you can't check, say so.
> - Replacement text keeps the scene's voice. Mark any new story fact as a
>   possibility.
> - Notes and frontmatter are background, not requirements.
> - Do not modify files.

The Customize options each add one sentence when set: the plan check replaces
the notes line, and "Show what to keep" adds the Keep rule.

The labels set the order, not the length: an explanation can be one line or a
paragraph, and a fix can be a phrase or a rewritten page.

### Format details the app depends on

- **Before:** sits on its own line above the quote, and its link goes below
  the quote, never in the label (`**Before** ([link]):` would break
  verification). **Why:** can be followed on the same line or the next.
  **After:** shares its line with the lead-in (`**After:** Replace [link]:`),
  since that lead-in is what labels the rewrite.
- `citations.py` (`_blockquote_above`) and the renderer's `followingCitation`
  both read a quote's link from the line below it.
- Italic blockquote means quoted evidence; plain blockquote means a rewrite.
  The citation checker and the existing skills rely on that difference.
- `**Lane: <name> — <why>**` matches `linkDiscussCraftLanes` (`^Lanes?:\s`).
- `**After:** Replace [link]:` and `**After:** Insert after [link]:` are short
  lead-ins ending in a colon (five words or fewer), so
  `_discussIntroducesQuote` labels the rewrite with the right scene and line.
  In `citations.py`, "after" is a stopword, so the lead-in has only one
  distinctive word and cannot trigger cross-scene link reassignment.

### Why each line is there

| Line | Test it passes |
| --- | --- |
| Find what most holds it back; fix with pasteable text | The goal. Being explicit here is what brings back Before/After |
| Up to {N}, most important first | Your Customize cap |
| Whole selection first | Failure: Chapter 8 reviews were mostly local line fixes |
| Lane line | App: guide links and lane labels |
| Quote, then link on the line below | App: the citation checker pairs a quote with a link only in that order |
| Before / Why / After labels | Makes every finding easy to scan; sets no lengths |
| Replace [link]: / Insert after [link]: | App: without it, rewrites were labeled with the wrong scene; additions have no line to replace |
| Plain blockquote for the rewrite | App: separates rewrites from quoted evidence |
| For a cut, show the result | Failure: "try cutting 111–121" |
| Search one distinctive word | Failure: a review called a set-up joke unseen because the phrase wrapped across lines |
| Keep the voice; mark new facts | Failure: a rewrite invented "office hours she never kept" |
| Notes are background | Failure: stale plan notes led every review |

## What goes

- The Book-based reading, Selection arc and Scene notes requirements, and the
  table. The model may still write an arc or notes when it helps.
- The restraint wording in both `craft.py` and `reviews.py`: "Zero necessary
  revisions is acceptable", "Do not score the draft or require a quota",
  `findings_limit_rule`'s "a limit, not a target: give fewer, or none", "Remove
  abstract or marginal notes", "a line edit only when it blocks the movement".
- "Quote the smallest complete passage", which pushed toward small fixes.
- The detailed rules for structural fixes, arrow sequences and beat sequences.
  "Text the writer can paste" covers them.

The citation checker, absence search, plan check, cap and Keep toggle stay.

## Wiring it up

- **Prompt order in `discuss.py`.** Today the request is the receipt, then the
  `Craft review instructions:` (or `Scene review instructions:`) divider and the
  skill, with `scene_review_contract(...)` appended at the end. Put the contract
  right after the divider, before the skill, so the model reads the goal and
  format first. Its first line says the skill supplies the editorial lens and
  the contract governs the format, so later skill wording cannot undo the
  format. Keep the divider itself: `renderDiscussCraftRequest` in
  `68-discuss.js` splits on it.
- **Tests that assert removed phrases** need updating:
  `test_craft_review_context.py`, `test_review_setup.py` and
  `test_discuss_manager.py` check "Book-based reading", "Scene notes" and "Zero
  necessary revisions is acceptable".

## Per card

- **Quick critique:** its skill already says this; no change beyond the shared
  contract.
- **Craft reviews (McKee, Coyne, Cron, Snyder, King):** each skill gains one
  closing line, "Then fix what you find," because today they ask only for
  analysis.
- **Comedy:** keeps its comic-specific guidance (styles, goals, the
  Strengthen/Opportunity labels). Remove the lines that would bring optional or
  arrow-style fixes back: "Begin with a brief Comic reading" becomes optional,
  and "a concrete optional replacement or beat sequence" goes, in both
  `reviews.py` and `comedy_review/SKILL.md`. The rest of that block is long too;
  review it after the test.
- **Deepen & layer:** "fix" becomes "expand", with the expansion written out.
  Drop "Identify 2–3 moments" from its skill so the cap governs the count. Keep
  "expand a thin beat into 2–3 rich sentences", which is about length.
- **Bird by Bird:** unchanged.

## Testing

1. Before changing anything, save today's outputs as the baseline: the Codex
   chapter review, the Codex Perkins's Office quick critique and the Claude
   chapter review.
2. Rerun the same three requests with both agents on the new contract.
3. Compare: the number of findings, how many have a pasteable fix, and whether
   any are chapter-level. The writer judges whether each finding matters.
4. If the new version is too timid or stays local, add back one rule at a time
   and rerun. Candidates, in order: a two-tier list (full priorities plus
   one-line smaller fixes), a silent lane check, a checklist of chapter-level
   failures.
5. If the new version wins, save Chapter 8 as an eval fixture for future prompt
   changes.

Cost: about six review runs, roughly the price of a few ordinary chapter
reviews.

## Loop results (Codex · Quick critique · 08-perkinss-office, cap 5)

| Run | Findings | Scene-level | Links |
| --- | --- | --- | --- |
| Old prompt (5:54) | 1 | 0 | real |
| New contract, writer's run | 3 | 0 | "scene.md" (copied the example) |
| New contract, test run | 3 | 2 | real |
| + realistic example link | 2 | 0 | real |
| + "start with how the scene works" | 2 | 1 | real |
| + "keep going while you find problems" | 2 | 0 | real |
| + "look in every selected lane" | 2 | 1 | real |

Every run since the new contract has a pasteable Before/Why/After. Codex gives
2–3 findings for this scene whatever the wording; "keep going" and "every lane"
changed nothing measurable and were dropped. The scene-level line stays. Single
runs vary as much as the wording changes, so judging a wording change needs
several runs of each version.

## Chapter results (Craft review · McKee · Chapter 8, final prompt, fresh chats)

| Run | Findings | Story-level | Pasteable After |
| --- | --- | --- | --- |
| Codex, cap 16, baseline | 3 | 0 (two timing mismatches, one trim) | partly |
| Codex, cap 16, new | 8 | 4 (Perkins's rule, the first betrayal, the water trick, Grace's question) | all |
| Claude, cap 5, baseline | 4 | 2 | two were "cut L185–L206" or an arrow sequence |
| Claude, cap 5, new | 5 | 5 (the hack stays private, a belief repeated across four scenes, the Madam Mim leak) | all |
