# Adaptive Engineering Loop Contract

Use this contract to prevent stale repository assumptions, context drift,
self-review bias, issue loss, review theater, and unbounded iteration.

## 1. Convergence policy

Record before the first edit:

```markdown
## Convergence policy
- Cycle budget and rationale:
- Per-finding remediation allowance and rationale:
- Must-pass acceptance proofs:
- Must-pass review stages and lanes:
- Required broad/live gates discovered from repo policy:
- Permitted deferred severity/lanes:
- User-decision triggers:
- Stop conditions:
```

Choose finite limits based on scope and risk, or use the user's explicit limit.
A single-layer isolated change needs less iteration than a cross-layer write,
browser, process, or compatibility change. Never increase the budget merely to
chase optional polish or force an approval.

## 2. Immutable objective and change manifest

Create once, then append explicit amendments only with user authorization:

```markdown
## Change manifest
- Objective and source of truth:
- Acceptance criteria:
- Constraints and non-goals:
- Authorized mutation scope:
- Before commit/worktree state:
- Known unrelated/concurrent changes:
- Current repository profile summary:
- In-scope contracts, owners, and consumers:
- Activated implementation/review lanes:
- Expected evidence graph:
- Baseline failures:
- Current implementation summary:
- Current changed files/contracts:
- Current limitations:
```

Do not replace an acceptance criterion with a reviewer's preferred design.
Refresh discovered operational facts when current code/config/CI changes, while
keeping the objective immutable.

## 3. Evidence ledger

Maintain fresh proof separately from implementation claims:

| Claim/criterion | Evidence layer | Exact command/probe | Result | Cycle | Classification/limits |
|---|---|---|---|---|---|

- Record red, green, and post-refactor observations for testable behavior.
- Record exit status, relevant counts/duration, and durable/browser/process
  effects when available.
- Keep pre-existing, environmental, flaky, suspected harness, and introduced
  failures distinct.
- A previous cycle's pass must be rerun when remediation touches its owner or
  boundary.
- No “should pass,” implementer report, or partial suite proves completion.

For material stateful capabilities, append a discovered journey ledger:

| Capability/claim | Starting state | Invocation | Intermediate transitions | Outcome | Recovery/next action | Boundary case | Fresh proof |
|---|---|---|---|---|---|---|---|

- Derive rows from the current capability and route/state inventory; do not
  hardcode product features in this contract.
- Do not merge disconnected component or surface tests into evidence for a
  continuous user journey.
- Challenge universal, collection-wide, persistence, safety, and accessibility
  claims using current configuration/fixture boundaries.
- An uncovered material state or transition is an evidence gap, not a pass;
  it blocks completion unless the objective explicitly makes it out of scope.

## 4. Issue ledger

| ID | Stage/lane | Severity | Root cause | Scenario/proof | Decision | Acceptance check | Status | Cycle |
|---|---|---|---|---|---|---|---|---|

Allowed decisions: `Accept`, `Reject`, `Defer`, `Needs user decision`.

Allowed statuses: `Open`, `In progress`, `Resolved`, `Still failing`,
`Deferred`, `Rejected`, `Blocked`.

- Preserve finding IDs/root causes across cycles.
- Preserve raw reviewer wording before triage.
- Reject only with current contract/code/test/runtime evidence.
- Defer only when the convergence policy and final verdict permit it.
- Reopen a finding whenever its acceptance check fails.
- Link a new ID when remediation exposes a distinct root cause.
- Track unclear hypotheses without P-level severity until evidence resolves
  them.

## 5. Independent review packet

Provide a fresh reviewer only the evidence needed to reconstruct conclusions:

- immutable objective, criteria, constraints, non-goals, and amendments;
- before-state and current complete diff, including relevant untracked work;
- current repository source, tests, instructions, and profile facts;
- exact raw test/runtime results and proven baseline failures;
- the `$review-code` path and required review range.

Do not provide implementer reasoning, self-check verdict, expected findings,
triage preferences, or a desired outcome. After review, save raw findings before
the implementer sees or responds to them.

## 6. Discovery log

Carry factual discoveries across cycles without carrying conclusions:

| Fact | Repository evidence | Affected owners/lanes | First seen | Revalidated |
|---|---|---|---|---|

Examples include a real entrypoint, lifecycle owner, file/wire invariant,
current validation command, fixture isolation rule, or supported environment.
Do not record opinions such as “the design is clean” or “this should pass.”

## 7. Quality gate

All conditions must pass:

- Stage A independently verifies every material acceptance criterion and
  confirms non-goals remain outside the change.
- Stage B gives every activated lane sufficient evidence and a gate-compatible
  status.
- No open P0/P1 remains; no open P2 violates acceptance, trust/data safety,
  architecture integrity, compatibility, accessibility of a core task, or
  essential verification.
- Every accepted finding passes its behavior-level acceptance check.
- Required focused, boundary, live/system, packaging, and broad gates derived
  from current repository policy pass, except proven unrelated baseline
  failures explicitly allowed by the convergence policy.
- Runtime-dependent browser/process behavior ran in the current isolated
  harness when material to the unchanged objective. Missing material evidence
  always prevents `Complete`. User acceptance may authorize an
  `Incomplete`/`Blocked` handoff, or the user may explicitly amend the objective
  before the affected lanes and gate are reevaluated; acceptance alone cannot
  turn `Not verified` into `Pass`.
- Every material stateful capability has complete journey-ledger evidence,
  including visible operability and dynamically derived boundary cases for
  broad claims.
- The cumulative diff is focused, contains no secret/cache/generated accident,
  preserves unrelated work, and keeps public/persistent contracts and docs
  consistent.
- The independent verdict is `Approve`, or `Approve with follow-ups` containing
  only explicitly permitted deferred work.

## 8. Cycle record

```markdown
### Cycle N
- Objective slice / accepted findings:
- Root-cause and red proof, or pre-edit exception/substitute proof:
- Implementation and refactor:
- Files/contracts/owners changed:
- Fresh validation results:
- Stage A result:
- Stage B result and lane changes:
- Findings opened/resolved/remaining:
- Gate result:
- Discovery log additions:
- Next action or stop reason:
```

## 9. Stop rules

- Stop successfully only when the quality gate passes.
- Stop for the user when a choice changes behavior, durable data, dependencies,
  compatibility, architecture, destructive scope, or the immutable objective.
- Stop when the configured cycle or remediation allowance is exhausted; report
  incomplete rather than extending it silently.
- Stop and revisit architecture when successive evidence-backed fixes do not
  resolve the same root cause or keep revealing coupled failures.
- Stop when overlapping concurrent edits make ownership or safe patching
  uncertain.
- Stop when remaining work is optional P3 polish, generic best practice, or
  speculative refactoring outside the objective.

## 10. Final loop self-check

- [ ] A current repository profile and discovery log—not frozen paths or
      commands—guided every cycle.
- [ ] The convergence policy was finite, risk-justified, and not silently
      extended.
- [ ] The objective/non-goals stayed immutable except for explicit user-approved
      amendments.
- [ ] Every implementation/remediation followed `$develop`, including
      activated lanes, root-cause analysis, and red/green/refactor evidence or
      a pre-edit exception/substitute proof independently validated in review.
- [ ] Every review followed `$review-code`, was read-only, and reported
      separate specification and engineering-quality stages.
- [ ] Independent reviewers received raw artifacts without implementer verdicts
      or desired findings.
- [ ] Every finding has stable identity, technical triage, evidence, an
      acceptance check, and final status.
- [ ] Rejected/deferred findings have evidence and satisfy the quality gate;
      unclear concerns remain hypotheses rather than disguised defects.
- [ ] Remediation handled one root cause at a time and reran affected prior
      proofs plus the cumulative acceptance graph.
- [ ] The final cumulative diff and all affected owners/consumers were
      re-reviewed after the last correction.
- [ ] Every completion claim cites fresh validation from the current cycle and
      all failures/limitations are classified.
- [ ] No unrelated work, real manuscript/profile, secret, cache, harness edit,
      unauthorized dependency, or scope expansion entered the change.
- [ ] The final outcome follows the quality gate and stop rules rather than
      cycle exhaustion or reviewer appeasement.

If a required item remains false, report `Incomplete` or `Blocked` and name the
safest next action.
