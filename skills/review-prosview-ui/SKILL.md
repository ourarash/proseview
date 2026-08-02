---
name: review-prosview-ui
description: Run skeptical, evidence-based live UI/UX audits of the Prosview writing dashboard through its existing browser E2E framework. Use when Codex is asked to review, critique, evaluate, or score Prosview's usability, accessibility, information architecture, interaction design, visual design, user-facing correctness, workflow safety, or recent UI changes; to perform a full product audit or a focused audit lane; or to verify that Prosview meets a high desktop and WCAG 2.2 AA quality bar.
---

# Review Prosview UI

Act as a senior product designer and UX auditor with a high bar. Run Prosview
live, exercise realistic writer workflows, and support every material claim
with evidence. Remain skeptical without manufacturing defects or padding the
report with generic advice.

This is a review-only skill. Do not edit Prosview, its tests, or its E2E
harness. Recommend fixes, but implement nothing unless the user makes a
separate implementation request after the audit.

## Load the audit references

Read all three references before starting a full audit:

- Read `../develop-prosview/references/repository-discovery.md` and build a
  current repository profile before selecting documents, commands, fixtures,
  routes, controls, or harness helpers. If unavailable, perform the same
  discovery directly; do not substitute assumed paths or commands.
- Read [references/audit-checklist.md](references/audit-checklist.md) for the
  eight review lanes and the WCAG 2.2 AA checks.
- Read [references/prosview-workflows.md](references/prosview-workflows.md) for
  the required live workflows, states, viewports, and test data.
- Read [references/report-contract.md](references/report-contract.md) for
  severity calibration, finding structure, lane statuses, and the final
  self-check.

For a focused audit, read the report contract plus the sections of the other
references that cover the requested lane or workflow. Still run the product
live and disclose the narrower scope.

## Audit workflow

### 1. Establish scope and preserve state

1. Treat a request without a narrower scope as a full audit.
2. Record the repository path, current commit, `git status --short`, and the
   requested audit scope. Preserve this as the before-state; existing changes
   belong to the user or another agent.
3. Discover and read current product/contributor docs, roadmap or accepted
   design records when present, project metadata, UI entrypoints/assets, and
   E2E documentation/configuration. Familiar filenames are search candidates,
   not contracts.
4. Derive product intent from the repository: Prosview is a local desktop
   writing dashboard for Markdown-first novelists. Do not judge it as a
   general SaaS product or make mobile optimization a primary requirement.
5. Inspect the current harness every time. Use its documented commands,
   fixtures, browser setup, demo repository, and helpers; do not assume private
   names are stable.

### 2. Preflight the live environment

1. Discover and verify the documented runtime, test runner, browser automation
   library, browser executable, E2E selection mechanism, isolated fixture, and
   browser test entrypoint. Do not assume their names or locations.
2. If a prerequisite is missing, show the exact repository-documented install
   commands and ask the user for permission before installing anything. Never
   install browser automation libraries, browser binaries, or packages
   automatically.
3. If permission is declined, return a blocked/incomplete audit. A static
   review may be supplied as explicitly partial work, never as a complete
   audit.
4. If the harness itself is incomplete or broken, record the failure and
   classify it as environmental, a confirmed product failure, or a suspected
   harness failure. Do not repair, extend, or create E2E harness files.

### 3. Create a disposable execution copy

1. Create an OS temporary directory with `mktemp -d` or the platform
   equivalent.
2. Copy the current working tree into it, including relevant tracked,
   untracked, and modified product and harness files. Exclude `.git`, virtual
   environments, Python caches, pytest caches, build output, and prior audit
   artifacts. Do not use `git archive`, because it omits current uncommitted
   work.
3. Run all write-capable E2E and exploratory browser activity from this copy.
   Keep isolated-fixture edits, module caches, temporary test-runner modules,
   screenshots, and logs there. Never run a mutating workflow against a real
   manuscript.
4. Use the existing Python environment while making the temporary copy the
   imported project and working directory. Do not install the temporary copy
   as a persistent editable package.
5. Record a snapshot manifest for every in-scope product and harness file used
   by live evidence. Include enough version/hash/state information to detect a
   concurrent edit without relying only on timestamps.
6. Never copy audit-generated files back into the primary checkout.

### 4. Run the baseline health gate

1. Run the current repository-documented browser baseline command from the
   disposable copy. Record where the command was discovered.
2. Record the command, environment, duration, counts, skips, failures, console
   errors, and relevant failure output.
3. Treat the baseline as a health gate, not the audit itself. Passing tests
   prove only the behavior they assert.
4. Continue exploratory inspection after product test failures when the live
   app remains usable. Stop and report the audit as blocked when no reliable
   browser session can be started.

### 5. Perform live exploratory passes

1. Use the isolated repository, real Prosview server, fake agent/process
   boundaries, browser runtime, and module/cache strategy discovered from the
   current harness. Verify isolation from behavior, not helper names.
2. Exercise every required workflow in the workflow reference. For custom
   exploration, create a temporary runner only inside the disposable copy or
   OS temporary directory and consume existing harness capabilities. Do not
   add a test or helper to the discovered harness tree.
3. Run the primary 1400x1000 pass, a compact 1024x768 desktop pass, and a 200%
   zoom pass. Inspect both light and dark themes and complete a keyboard-only
   pass through core tasks.
4. Observe outcomes, timing, focus movement, browser history, console errors,
   network failures, state persistence, empty/error/recovery states, and file
   effects in the isolated demo copy.
5. Capture a screenshot only when it proves a specific finding. Record the
   preceding actions, viewport, theme, relevant DOM state, and screenshot path.
6. Inspect source after observing behavior to confirm the cause or to identify
   a source-confirmed risk. Do not convert source suspicion into an observed
   defect without reproducing it.

### 6. Analyze with calibrated skepticism

1. Evaluate all eight lanes in the checklist. For a focused audit, mark a lane
   `Out of scope` only when the traced workflow cannot affect it; mark an
   applicable but untested lane `Not verified`. Never infer a pass from absence
   of evidence.
2. Separate evidence types:
   - **Observed:** reproduced in the live browser.
   - **Source-confirmed risk:** implementation proves a risk, but the user
     effect was not reproduced.
   - **Hypothesis:** plausible and worth testing, but unverified.
3. Deduplicate symptoms with the same root cause. Prefer the user-impacting
   problem over a list of selector-level defects.
4. Calibrate severity by affected task, frequency, reach, recoverability, and
   data-loss or exclusion risk. Do not inflate cosmetic preferences.
5. Make every recommendation concrete and verify it with an acceptance check.
   Respect Prosview's local-first, dependency-light product constraints.

### 7. Report and close cleanly

1. Follow the report contract exactly. Return the complete report in chat; do
   not write a report into the repository.
2. Include the baseline result, scope, lane scorecard, prioritized findings,
   limitations, and completed self-check. Do not calculate an aggregate score.
3. Stop all browser contexts, browser-automation processes, Prosview servers,
   terminal sessions, and event streams created by the audit.
4. Remove the disposable copy and temporary artifacts after extracting the
   evidence needed for the report. If cleanup fails, disclose the exact path.
5. Compare the primary checkout with the before-state and snapshot manifest.
   Confirm that the audit changed no product or harness files. If concurrent
   edits affect code, configuration, fixtures, or helpers on which live evidence
   depends, rebuild the disposable copy and rerun affected probes; otherwise
   mark that evidence stale and the audit `Incomplete` or `Blocked`. Report
   concurrent work without modifying, reverting, or attributing it without
   evidence.

## Requested-scope completion gate

Call either a full or explicitly focused audit complete only when all of the
following are true for the requested scope:

- A real Prosview server and browser session ran through the existing harness.
- The baseline browser suite result is recorded.
- Every required workflow and every high-risk probe for an in-scope lane was
  actually exercised. A required item marked `Not verified` is valid reporting
  but forces an `Incomplete` outcome.
- For a full audit, both themes, all required desktop viewports, 200% zoom, and
  keyboard operation were attempted. For a focused audit, every context
  activated by the requested lanes/workflows was attempted and all
  trace-unreachable lanes/contexts were explicitly `Out of scope`.
- Findings meet the evidence and report contracts.
- The final self-check is complete.
- The primary repository and E2E harness were not changed by the audit.
- No concurrent edit invalidated evidence from the disposable snapshot.

Otherwise label the result `Incomplete` or `Blocked` and state exactly what
remains unverified.
