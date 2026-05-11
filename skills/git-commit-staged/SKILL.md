---
name: git-commit-staged
description: Create a git commit in the proseview repository from the currently staged changes only. Use when the user asks to commit staged files, write a commit message from the staged diff, or make a commit without staging additional work.
---

# Git Commit Staged

Use this skill when the user wants a commit created from the current staged
index in the proseview repository.

This is a staged-only workflow. Do not stage, unstage, revert, or rewrite the
user's index or worktree unless the user explicitly asks.

## Workflow

1. Confirm there is at least one staged change:
   - `git diff --cached --quiet`
   - If nothing is staged, stop and say no commit was created because the index is empty.
2. Inspect worktree state without changing it:
   - `git status --short`
   - In the final report, distinguish committed staged work from remaining unstaged or untracked work.
3. Inspect the staged change set with non-interactive commands:
   - `git diff --staged --name-only`
   - `git --no-pager diff --staged`
   - Use `git --no-pager show :path/to/file` when a full staged file is clearer than a diff.
4. Decide whether the staged set is one logical change.
   - If it mixes unrelated work, stop and ask whether to split it.
5. Run focused validation when feasible.
   - Python or shared behavior: prefer `python3 -m pytest` or targeted `python3 -m pytest tests/...`.
   - Front-end template or bundled JS behavior: run the relevant static tests in `tests/test_bundling.py`, `tests/test_app_refresh.py`, or nearby tests.
   - Docs-only changes may not need tests; say that explicitly.
   - Never stage test-generated changes unless the user asked.
6. Write a concise commit message from the staged diff.
   - Subject style: imperative mood, no trailing period, usually under 72 characters.
   - Prefer this shape when a body is useful:

```text
Short imperative subject

- Explain the first concrete behavior or code change
- Explain the second only if it materially matters

Tests:
- command that passed
```

   - Omit the body for tiny obvious commits.
   - Mention failed or skipped tests in the final response, not as a misleading `Tests:` line.
7. Create the commit from the staged index only:
   - Write the message to a temporary file.
   - Run `git commit --file <tempfile>`.
   - Do not use `git commit -a`.
   - Do not pass `--only` unless the user gave explicit paths.
8. Report the resulting commit hash and subject.

## Repo Guidance

- Keep Proseview focused: local Markdown novel dashboard, no cloud/account scope.
- User-facing strings should be small, declarative, and explanatory rather than promotional.
- New behavior should normally include a focused test in `tests/` or the synthetic repo in `fixtures/demo-repo`.
- Avoid new dependencies unless the staged diff clearly justifies them and the user has discussed it.
- Front-end JS lives in `proseview/templates/assets/js/` and is concatenated by filename order; message accordingly when JS bundle order matters.
- Asset/template changes may affect live reload behavior; inspect both server and browser paths when relevant.

## Commit Rules

- Never include unstaged changes in the commit.
- Never auto-stage untracked or modified files.
- Never use interactive git flows.
- If `git commit` fails, report the error and leave the staged set intact.
- If hooks or tests fail, do not bypass them unless the user explicitly asks.
- If the staged diff includes secrets, credentials, generated caches, or accidental large files, stop before committing.
