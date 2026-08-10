---
name: commit
description: Create git commits in the Proseview repository, either from the currently staged index only (the default) or by grouping the whole worktree into one focused commit per logical change. Use when the user asks to commit staged files, write a commit message from a diff, or split all current work into sensible commits.
---

# Commit

Two modes, one entry point. **Pick the mode before touching anything**, because
they differ in whether the index may be modified.

| The user says | Mode | May stage? |
| --- | --- | --- |
| "commit", "commit this", "commit what I staged" | **Staged-only** (default) | No |
| "commit everything", "split this into commits", "group these changes" | **Grouped** | Yes, explicit paths only |

When the request is ambiguous, use **staged-only**. If nothing is staged and
the worktree is dirty, do not silently switch modes — say the index is empty
and ask whether to group the worktree instead. Staging work the user
deliberately left out is the one failure this skill exists to prevent.

## Mode A — staged-only (default)

Never stage, unstage, revert, or rewrite the index or worktree unless the user
explicitly asks.

1. Confirm there is at least one staged change: `git diff --cached --quiet`.
   If nothing is staged, stop and say no commit was created because the index
   is empty.
2. Inspect worktree state without changing it: `git status --short`. In the
   final report, distinguish committed staged work from remaining unstaged or
   untracked work.
3. Inspect the staged change set non-interactively:
   - `git diff --staged --name-only`
   - `git --no-pager diff --staged`
   - `git --no-pager show :path/to/file` when a whole staged file reads clearer
     than a diff.
4. Decide whether the staged set is one logical change. If it mixes unrelated
   work, stop and ask whether to split it.
5. Validate (see [Validation](#validation)).
6. Write the message (see [Commit message](#commit-message)).
7. Commit from the staged index only:
   - Write the message to a temporary file.
   - `git commit --file <tempfile>`
   - Never `git commit -a`. Do not pass `--only` unless the user gave paths.
8. Report the resulting commit hash and subject.

## Mode B — grouped

This mode may stage files. It must still protect user work: inspect before
staging, group related files, and never discard changes.

1. Inspect the full worktree:
   - `git status --short`, `git diff --name-only`, `git diff --stat`
   - Read untracked files before staging them, with a read-only command.
2. Build a commit plan. Group by one logical purpose, not by file type.
   Typical groups here:
   - server/watch behavior with matching tests
   - browser refresh or UI behavior with matching tests
   - docs/roadmap/README updates
   - tooling or skill additions
   - dependency/config changes

   If one file holds unrelated changes, use partial staging only when the split
   is obvious and safe. Otherwise ask.
3. For each group:
   - Stage only that group with explicit paths: `git add path ...`
   - Verify with `git diff --staged --name-only`
   - Inspect with `git --no-pager diff --staged`
   - Confirm unrelated changes remain unstaged via `git status --short`
4. Validate (see [Validation](#validation)).
5. Commit that group using the same message shape and commit mechanics as
   Mode A.
6. Repeat until `git status --short` is empty. If validation generates new
   files, inspect them before deciding whether they belong in a commit. If a
   file should not be committed, ask before removing or ignoring it.
7. Final report: each commit hash and subject, tests run, and whether the
   worktree is clean.

## Validation

Run focused validation when feasible:

- Python or shared behavior: `python3 -m pytest`, or targeted
  `python3 -m pytest tests/...`.
- Front-end template or bundled JS behavior: the relevant static tests in
  `tests/test_bundling.py`, `tests/test_app_refresh.py`, or nearby.
- Broad changes in grouped mode: targeted tests first, then the full suite.
- Docs-only or skill-only changes may skip tests — say so explicitly.
- Never stage test-generated changes unless the user asked.

## Commit message

Imperative subject, no trailing period, usually under 72 characters.

```text
Short imperative subject

- Explain the first concrete behavior or code change
- Explain the second only if it materially matters

Tests:
- command that passed
```

Omit the body for small obvious commits. Never claim tests passed if they were
not run or failed — mention failures in the final response, not in a misleading
`Tests:` line.

## Safety rules

- Never `git add .` or `git add -A`; stage explicit paths.
- Never `git commit -a`.
- Never use interactive git flows.
- Never discard, reset, checkout, clean, or delete user changes unless asked.
- Never bypass failing hooks or tests unless the user explicitly asks.
- Stop before committing secrets, credentials, generated caches, or accidental
  large files.
- If a commit fails, leave the staged set intact and report the error.
- Stop and ask if changes are too mixed to group confidently.

## Repo guidance

- Keep Proseview focused: a local Markdown novel dashboard. No cloud or account
  scope.
- User-facing strings stay small, declarative, and explanatory rather than
  promotional.
- New behavior should normally include a focused test in `tests/` or the
  synthetic repo in `fixtures/demo-repo`.
- Avoid new dependencies unless the diff clearly justifies them and the user has
  discussed it.
- Front-end JS lives in `proseview/templates/assets/js/` and is concatenated by
  filename order; mention it when bundle order matters.
- Live reload touches both the server SSE path and the browser refresh path;
  keep those changes and their tests in one commit when they form one behavior.
