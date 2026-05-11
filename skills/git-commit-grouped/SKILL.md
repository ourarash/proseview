---
name: git-commit-grouped
description: Stage changed and untracked files in related groups, create one git commit per logical group, and continue until the proseview repository has no changed or untracked files left. Use when the user asks to split all current worktree changes into sensible commits.
---

# Git Commit Grouped

Use this skill when the user wants Codex to turn the whole current worktree
into one or more focused commits. For each group, use the same staged-diff
message style and commit mechanics defined by `git-commit-staged`.

This workflow is allowed to stage files, unlike `git-commit-staged`. It must
still protect user work: inspect before staging, group related files, and never
discard changes.

## Workflow

1. Inspect the full worktree:
   - `git status --short`
   - `git diff --name-only`
   - `git diff --stat`
   - For untracked files, inspect content before staging with `sed`, `rg`, or another read-only command.
2. Build a commit plan.
   - Group files by one logical purpose, not by file type alone.
   - Typical groups in this repo:
     - server/watch behavior with matching tests
     - browser refresh or UI behavior with matching tests
     - docs/roadmap/README updates
     - tooling or skill additions
     - dependency/config changes
   - If one file contains unrelated changes that need separate commits, use partial staging only when the split is obvious and safe. Otherwise ask the user.
3. For each group:
   - Stage only that group with explicit paths: `git add path ...`
   - Verify the staged set: `git diff --staged --name-only`
   - Inspect the staged diff: `git --no-pager diff --staged`
   - Confirm unrelated unstaged changes remain unstaged with `git status --short`.
4. Validate before committing when feasible.
   - Code or shared behavior: run targeted tests first, then full `python3 -m pytest` if the change is broad.
   - Front-end bundle behavior: include relevant static tests such as `tests/test_bundling.py`, `tests/test_app_refresh.py`, or nearby tests.
   - Docs-only or skill-only groups may skip tests; say so in the final report.
5. Commit the staged group.
   - Follow the commit-message and commit-command rules from
     `skills/git-commit-staged/SKILL.md` for the currently staged group.
   - Write the message to a temporary file.
   - Run `git commit --file <tempfile>`.
   - Use a concise imperative subject, no trailing period.
   - Add a short body only when it clarifies behavior or validation.
6. Repeat until `git status --short` is empty.
   - If new generated files appear during validation, inspect them before deciding whether they belong in a commit.
   - If a file should not be committed, ask the user before removing or ignoring it.
7. Final report:
   - List each commit hash and subject.
   - Note tests run.
   - Confirm whether the worktree is clean.

## Commit Message Shape

Match `git-commit-staged` so staged-only and grouped commits have the same
voice and structure.

Prefer:

```text
Short imperative subject

- Concrete behavior or implementation change
- Related test/docs note when useful

Tests:
- python3 -m pytest tests/...
```

Omit the body for small obvious commits. Do not claim tests passed if they were
not run or failed.

## Safety Rules

- Never use `git add .` or `git add -A`; stage explicit paths.
- Never use `git commit -a`.
- Never discard, reset, checkout, clean, or delete user changes unless explicitly asked.
- Never bypass failing hooks or tests unless explicitly asked.
- Stop and ask if changes are too mixed to group confidently.
- Stop before committing secrets, credentials, generated caches, or accidental large files.
- If a commit fails, leave the staged set intact and report the error.

## Repo Guidance

- Keep Proseview focused: local Markdown novel dashboard, no cloud/account scope.
- New behavior should normally include focused tests in `tests/`.
- User-facing prose should be small, declarative, and explanatory.
- Front-end JS is concatenated by filename order from `proseview/templates/assets/js/`.
- Live reload touches both server SSE and browser refresh paths; keep those changes and their tests together when they form one behavior.
