# Shorter prompts and more useful reviews

Apply shared improvements to Quick critique, Deepen & layer, Craft, and Comedy.
Keep each review's identity. Send each selected lane's name, book/source, and
brief; Craft also retains each lane's book principle. Full guides stay in the app.

Implemented; verified with 1,700 non-browser tests and 48 browser tests.

## Changes

1. **Send compact lane descriptions.** In both lane-list builders
   (`proseview/craft.py` and `proseview/reviews.py`), start each selected lane
   with `- <name> (<source, if any>) — <brief>`. Use each lane's existing
   `brief` directly; every lane already has one. For Craft, name the selected
   book once above the lane list, not on each lane. For Comedy, use each lane's
   own sources. Omit parentheses when a lane has no source.

   **Craft exception:** also keep each lane's `summary` (the book's principle)
   after the brief. Drop only the “look for” checklist. This preserves concepts
   such as McKee's Gap that the brief does not carry. Other cards omit long
   principles, checklists, and revision approaches. Full guides and examples
   remain in the app.

2. **Keep findings concrete.** In `review_contract` in
   `proseview/craft.py`, use `finding` as the default item name and make the
   opening goal about useful improvements. Change **Why** to:

   > **Why:** the specific weakness or missed opportunity, and what the change
   > improves for the reader.

   In both lane-list builders (`proseview/craft.py` and
   `proseview/reviews.py`), replace “Report only problems in these lanes” with
   “Stay within the selected lanes.”

3. **Prioritize larger improvements.** Replace the shared priority sentence:

   > Within the selected review and lanes, start with improvements to how the
   > scene works as a whole. Then address individual passages and wording.

   For multiple scenes, refer to the selection as a whole and development
   across scenes. Keep each card's overall editorial lens concise.

4. **Allow connected edits.** Add to the shared contract:

   > When a finding requires changes in several places, group the connected
   > edits under one finding and write out each replacement or insertion.

   Each edit needs its own citation or insertion point. One connected finding
   counts once toward the existing cap.

5. **Remove duplication.** Read each generated contract and built-in guide in
   `proseview/skills/` as one prompt. Keep format, citations, and dynamic rules
   in the contract; keep the editorial lens in the guide. Consolidate repeated
   instructions; guides must not reintroduce the omitted long lane guidance.
   Record combined instruction word counts before/after for each card with
   the same options, including the self-check. Reduce the total;
   explain any necessary increase.

6. **Append the self-check below after the review guide** in
   `proseview/discuss.py`, including with writer-owned guides. Keep it outside
   manuscript/reference text. Fold Quick critique's existing built-in
   self-check into this shared version. The reviewing agent checks silently
   before returning feedback.

## Preserve

Keep Before/Why/After and citation formatting, selected lanes/goals/styles,
voice and facts, read-only scope, plan checks, applicable Keep toggles, and
writer-owned overrides. Full explanations and examples stay in the in-app guides.
Deepen retains written-out expansions without a Keep list; Craft retains the
selected book and each lane's `summary`. Bird by Bird keeps one manageable
assignment and its Keep behavior, without mandatory Before/After rewrites.

Preserve Comedy's goal restrictions and Type labels.

## Tests and docs

Update shared tests in `tests/test_review_setup.py` across all standard cards
and single/multiple scenes: selected lane names, accurate book/source labels,
each lane's exact existing `brief`, finding/Why wording, priority, connected
edits, existing cap, and preserved formatting. For Craft, assert the book is
named once above the lane list, each selected `summary` follows its brief, and
the “look for” checklist is absent. For other cards, replace assertions
requiring long lane guidance with checks for its omission. Retain full
guide-data checks. Check per-lane source labels and no empty parentheses.
Check the three-question self-check follows the guide, including writer-owned
overrides, and appears once with
built-ins. Exact quotes, citations, marked new facts, and voice remain existing
contract rules; do not repeat them in the self-check.
Keep separate Bird by Bird expectations. Update affected assertions in
`tests/test_comedy_review.py`, `tests/test_craft_review_context.py`, and
`tests/test_discuss_manager.py`, plus relevant descriptions in `docs/ai.md`.

Run and report results:

```bash
.venv/bin/python -m pytest -q --ignore=tests/e2e tests/test_review_setup.py tests/test_comedy_review.py tests/test_craft_review_context.py tests/test_discuss_manager.py tests/test_builtin_skills.py
.venv/bin/python -m pytest -q -n 4 --ignore=tests/e2e
.venv/bin/python -m pytest -q -m e2e_browser -n 4 tests/e2e/test_comedy_review_e2e.py tests/e2e/test_review_setup_e2e.py tests/e2e/test_craft_review_topics_e2e.py
```

## Instruction sizes

Words with all lanes, one scene, and default options: contract plus built-in
guide, including the new self-check after the change; receipt/context excluded.

| Review | Before | After |
| --- | ---: | ---: |
| Quick critique | 720 | 500 |
| Deepen & layer | 722 | 494 |
| Comedy review | 1237 | 990 |
| McKee · Story | 899 | 791 |
| Cron · Story Genius | 852 | 773 |
| Coyne · The Story Grid | 880 | 812 |
| Snyder · Save the Cat! | 817 | 778 |
| King · On Writing | 867 | 815 |
| Lamott · Bird by Bird | 668 | 578 |

Findings ranges, customization UI, new evaluation campaigns, and unrelated
uncommitted work are out of scope. Don't commit unless asked.

## Reviewer self-check — append to the prompt

> Before returning feedback, check silently:
>
> - Have I considered the whole selection through the selected review
>   and lanes?
> - Did I combine overlapping findings and retain worthwhile findings within
>   the configured limit?
> - Does every finding end in complete, pasteable edits?
>
> Resolve any gaps before returning. Do not print this checklist.

For Bird by Bird, replace the findings/edit questions with whether its single
assignment is useful, manageable, and has a clear starting point.
