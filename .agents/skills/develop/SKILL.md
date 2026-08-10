---
name: develop
description: Implement production-quality changes in the Proseview repository as a senior software engineer, from repository discovery and requirements through test-first or root-cause-driven code, validation, and evidence-backed handoff. Use when Codex is asked to build, change, fix, refactor, harden, optimize, or extend Proseview; implement an approved plan or review finding; add backend, browser, CLI, server, analysis, packaging, documentation, or test behavior; or ensure a Proseview change follows strong engineering, data-safety, security, accessibility, maintainability, and testing practices.
---

# Develop Proseview

Implement the requested change with senior-level rigor. Optimize for correct,
focused, maintainable behavior inside Proseview's local-first product boundary.
Use current repository evidence instead of assuming today's layout or commands.

## Load the engineering references

For every implementation:

- Read [references/repository-discovery.md](references/repository-discovery.md)
  and build the current repository profile before editing.
- Read [references/architecture.md](references/architecture.md)
  for stable product, data, trust, and architecture invariants.
- Read [references/implementation-lanes.md](references/implementation-lanes.md),
  activate lanes from the discovered change surfaces, and keep a lane record.
- Read [references/validation-matrix.md](references/validation-matrix.md) before
  creating tests or selecting validation commands.

Read only the activated lane sections for a small isolated change; read every
lane for a cross-layer, security-sensitive, data-mutating, or architectural
change. The methodology provenance in
[references/methodology-sources.md](references/methodology-sources.md) is for
skill maintenance and need not be loaded during normal implementation.

## Engineering workflow

### 0. Discover the current system

1. Build the repository profile and record the before commit/worktree state.
   Existing tracked or untracked changes belong to the user or another agent;
   preserve them and refresh the profile if concurrent work changes a touched
   boundary.
2. Resolve governing instructions, supported environments, entrypoints,
   architecture owners, persistent/wire/UI contracts, test topology, current
   documented commands, and generated/temp paths from the checkout.
3. Trace the requested behavior end to end and activate implementation lanes
   from the actual surfaces. Do not infer scope from filenames alone.

### 1. Establish the behavior contract

1. State the user-visible outcome, acceptance criteria, constraints,
   compatibility target, and explicit non-goals. Infer only low-risk details;
   request direction when a missing decision changes product behavior, user
   authority, durable data, dependencies, or architecture.
2. Identify the smallest coherent change and every producer/consumer it
   affects. Map each acceptance criterion to an observable proof before code.
3. For a bug or unexpected failure, reproduce it and investigate before
   patching:
   - collect the actual error/state at every crossed boundary;
   - trace the bad value or transition back to its first incorrect source;
   - state one falsifiable root-cause hypothesis and the evidence for it;
   - run the smallest experiment that can disprove it;
   - replace a failed hypothesis instead of stacking another speculative fix.
4. For a testable behavior change, create the smallest failing proof first.
   Confirm that it fails because the behavior is absent or wrong—not because
   the test is broken. Record a justified exception for exploratory spikes,
   generated output, or non-behavioral configuration/documentation work.

### 2. Design the smallest complete solution

1. Place responsibility in the owner discovered from callers and data flow.
   Extend an established cohesive boundary before inventing a parallel one.
2. Keep data contracts explicit from input and validation through domain
   transformation, persistence/process effects, serialization, browser state,
   user feedback, and recovery.
3. Apply every activated lane before choosing the design, especially path and
   manuscript safety, sink-specific escaping, stale writes, AI/terminal
   authority, lifecycle cleanup, keyboard/focus behavior, and compatibility.
4. Avoid speculative frameworks, generic service/repository layers,
   premature caching, and dependencies without a present Proseview need. Obtain
   user agreement for material dependency, migration, compatibility, or scope
   expansion.
5. Keep routine design reasoning in the working plan. Create a durable design
   record only when requested or when the decision changes a lasting public or
   architectural contract.

### 3. Implement in proof-sized slices

1. Preserve concurrent changes and use narrow patches around the discovered
   owner. Do not reformat or absorb unrelated work.
2. Follow red → green → refactor for each testable behavior slice:
   - **Red:** run the focused proof and observe the intended failure;
   - **Green:** implement only enough coherent production behavior to pass;
   - **Refactor:** improve clarity without changing behavior, then rerun the
     focused proof.
3. Keep transformations typed/testable where the current code supports it and
   isolate filesystem, process, network, browser, and time effects.
4. Preserve unrelated manuscript/config bytes and user intent on every write.
   Never exercise mutation against a real manuscript or user profile.
5. Make client/server state transitions and resource ownership explicit. Keep
   keyboard semantics, focus, safe DOM sinks, loading/error/recovery state,
   route/history behavior, event ordering, and teardown consistent.
6. Handle failures at the boundary that can add actionable context. Do not hide
   failures with broad catches, false success, blind retry, or timing sleeps.
7. If repeated fixes fail, pause patching and revisit the root-cause and
   architecture model. Do not layer a new workaround on unexplained behavior.

### 4. Verify from the acceptance map

1. Run the focused proof after each slice, then all affected boundary checks,
   live/system checks, and the broad repository gate discovered in the profile.
2. Use the current isolated E2E fixtures and documented runtime. Do not change
   a harness merely to make implementation pass or install substantial
   optional dependencies without permission.
3. Classify every failure as introduced regression, pre-existing failure,
   environment, flake, or suspected harness mismatch. Investigate failures
   before rerunning; a later pass does not erase an unexplained earlier result.
4. Build a fresh evidence ledger: claim → proof command/probe → result. A
   previous run, partial suite, source inspection, or “should pass” is not
   evidence for completion.
5. Inspect the cumulative diff, untracked files, public contracts, package
   contents, temporary/generated output, and final status. Confirm no unrelated
   or sensitive file entered the change.

### 5. Hand off with lane and proof records

Report:

1. Implemented outcome and material design/root-cause decisions.
2. Changed contracts and files discovered as their owners.
3. Implementation lane table with status, concrete evidence, and remaining
   risk for every activated lane.
4. Exact fresh validation results and failure classifications.
5. Assumptions, limitations, unverified criteria, pre-existing failures, and
   unrelated work that remains untouched.

Do not claim completion when a required acceptance proof or activated lane is
blocked or unverified.

## Completion self-check

- [ ] A current repository profile—not assumed paths or commands—guided the
      implementation.
- [ ] Every acceptance criterion has fresh observable evidence and every
      non-goal remained outside the change.
- [ ] Bugs were reproduced and traced to a supported root cause before repair.
- [ ] Testable behavior followed a witnessed red → green → refactor cycle, or
      the exception and substitute proof are explicit.
- [ ] Every activated implementation lane has a defensible status and evidence;
      `Not applicable` entries have reasons.
- [ ] Manuscript/config fidelity, paths, escaping, writes, AI/terminal authority,
      secrets, and local-first behavior were reviewed where reachable.
- [ ] Error, empty, boundary, concurrency, lifecycle, cancellation, and
      recovery behavior was implemented or explicitly out of scope.
- [ ] UI changes preserve semantics, keyboard/focus behavior, accessible state,
      routes, themes/reflow, and honest feedback where affected.
- [ ] Tests assert behavior and real effects, remain isolated, and cover the
      changed owner plus crossed boundaries.
- [ ] Focused, boundary, live/system, and broad repository gates were run as
      required by current repo policy, or exact blockers are reported.
- [ ] Completion claims cite fresh output; unexplained failures and unverified
      criteria are not hidden by later passing runs.
- [ ] The final diff contains no unrelated work, secret, cache, generated
      artifact, speculative dependency, dead code, or accidental broad edit.
- [ ] Public contracts and documentation agree with the implemented behavior.

If a required item is false, report the result as incomplete or blocked and
name the safest next action.
