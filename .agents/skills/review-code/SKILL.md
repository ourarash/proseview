---
name: review-code
description: Conduct a skeptical, read-only senior code and architecture review of Proseview changes or the current implementation, using current repository discovery, a specification-compliance gate, and detailed evidence lanes for domain fidelity, architecture, interfaces, security, reliability, UI/accessibility, performance, tests, packaging, and operations. Use when Codex is asked to review a Proseview diff, pull request, feature, fix, refactor, implementation produced by $develop, remediation, or repository architecture; identify must-fix issues; validate a correction; or issue an approval verdict with a rigorous self-check.
---

# Review Proseview Code

Act as an independent senior engineer and architect. Find consequential defects
before merge while rejecting style preference, generic advice, and speculative
scale concerns. This skill is strictly read-only: inspect and test, but do not
edit source, tests, configuration, documentation, generated files, or staging
state.

## Load the review references

- Read `../develop-proseview/references/repository-discovery.md` and build a
  current repository profile. If unavailable, perform the same discovery from
  repository instructions, metadata, code, tests, docs, and CI; do not fall
  back to assumed paths or commands.
- Read `../develop-proseview/references/architecture.md` for durable
  Proseview invariants and verify current ownership from the profile.
- Read [references/review-lanes.md](references/review-lanes.md), activate lanes
  from traced surfaces, and collect the required evidence for each.
- Read [references/report-contract.md](references/report-contract.md) before
  assigning severity or a verdict.

## Review workflow

### 0. Reconstruct intent and current reality

1. Determine the authoritative objective from the user request, accepted plan,
   issue/PR description, acceptance criteria, or loop manifest. Summarize it in
   one sentence and preserve explicit non-goals.
2. Resolve the exact review set from a supplied range/path or the recorded
   before-state through the current worktree. Include relevant untracked and
   remediation files; exclude unrelated work only with evidence.
3. Build the repository profile, record status/diff statistics, and discover
   current architecture, commands, tests, fixtures, supported environments,
   public contracts, and baseline failures. Never stage, format, repair, or
   refresh generated output in the primary checkout.
4. Read surrounding owners, callers, consumers, tests, docs, and history needed
   to understand the change. A diff alone is not a system model.

### 1. Build the change and risk map

1. Trace changed inputs through validation, domain transformations,
   persistence/process effects, serialization/events, browser state, user
   feedback, and recovery. Name the owning symbols discovered at each step.
2. Identify affected persistent/public contracts and high-risk Proseview
   invariants: manuscript fidelity, path containment, stale writes, proposal
   ranges/approval, agent context, terminal authority, live events, routing,
   accessible operation, installed assets, and local-first behavior.
3. Map each acceptance criterion and non-goal to implementation and independent
   proof. Activate review lanes from behavior surfaces, not file extensions.
4. For a full audit, cover every lane. For a focused change, mark a lane out of
   scope only after documenting why no traced input, state, effect, or consumer
   can reach it.

### 2. Run stage A — specification compliance

1. Apply Lane R1 before judging implementation elegance.
2. Verify that every requested behavior is present, non-goals remain excluded,
   error/recovery semantics are defined, and user-visible success matches the
   actual durable effect.
3. Compare code and runtime evidence with acceptance criteria line by line.
   Passing tests are supporting evidence only if they fail when the required
   behavior is absent.
4. Record missing, extra, contradictory, or unverified behavior. A material
   specification failure prevents approval even if the code is otherwise clean.

### 3. Run stage B — engineering and architecture quality

1. Apply every other activated lane using its probes and evidence requirements.
2. Review architecture before local style: ownership, dependency direction,
   state authority, lifecycle, data contracts, migration, and failure
   containment.
3. Review implementation details: boundaries, escaping, path resolution,
   exact write behavior, async ordering, cleanup, platform assumptions,
   keyboard/focus semantics, performance characteristics, and diagnostics.
4. Search all callers and duplicate implementations before claiming a change
   is safe, unreachable, or dead.
5. Review tests as production code and run proportionate checks discovered from
   the repository profile. Use isolated fixtures and the current live harness
   for runtime-dependent behavior; never edit the harness.

### 4. Apply the finding admission gate

A review observation becomes a P-level finding only when all are present:

1. A current Proseview contract, invariant, or user/developer workflow.
2. A minimal reachable scenario.
3. Direct code, test, file, process, or live-runtime evidence.
4. Material impact and calibrated likelihood/recoverability.
5. A behavior-level recommendation with an observable acceptance check.

Keep unsupported concerns as hypotheses/questions without severity. Deduplicate
symptoms that share one root cause. Do not report “best practice” without the
Proseview failure it prevents.

### 5. Verify evidence and issue a verdict

1. Run the smallest proof for each suspected issue and the current broader gate
   when it materially changes confidence. Record exact fresh output; do not
   trust implementer summaries or previous runs.
2. Classify failures as regression, pre-existing product failure, environment,
   flake, or suspected harness mismatch. A later pass does not erase an
   unexplained failure.
3. Compare repository state before and after review and disclose unexpected
   changes without reverting user work.
4. Produce the two-stage result, lane scorecard, prioritized findings, evidence
   ledger, and exactly one verdict from the report contract.
5. If a confirmed defect already meets the `Request changes` gate, use that
   verdict even when other evidence is missing. Otherwise, if a required
   criterion or activated lane lacks material evidence, use `Blocked`. Never
   use either approval verdict for a material evidence gap.

## Reviewer constraints

- Recommendations describe the smallest required behavior; implementation
  belongs to `$develop` or the engineering loop.
- Severity follows impact, reach, likelihood, and recovery—not fix effort,
  unfamiliar code, or reviewer preference.
- Do not demand an abstraction without a present boundary, safety invariant,
  or multiple actual consumers.
- Do not approve because tests pass; assess whether they can detect the risky
  behavior and whether runtime-dependent contracts ran live.
- Do not accept repository references as frozen truth. Refresh any profile fact
  invalidated by concurrent work before issuing the verdict.
