# Code and Architecture Review Report Contract

Lead with confirmed findings. Keep hypotheses separate and do not pad a clean
review with generic advice.

## Severity

- **P0 — blocker:** likely data loss/corruption, critical trust-boundary
  failure, destructive broad effect, or a core workflow that cannot safely run.
- **P1 — major:** confirmed correctness, security, architecture, compatibility,
  accessibility, or reliability defect with material impact and no acceptable
  routine workaround.
- **P2 — moderate:** meaningful friction, maintainability/test weakness,
  performance cost, recovery gap, or edge-case defect with a workable path.
- **P3 — minor:** localized clarity, consistency, or low-impact robustness issue.

Severity follows impact, reach, likelihood, and recoverability—not fix effort.
Do not assign P-level severity to an unverified hypothesis.

## Finding contract

```markdown
### CR-001 — Concrete failure-oriented title

- Stage: Specification compliance | Engineering quality
- Severity: P1
- Lane: R6 — Reliability, concurrency, and lifecycle
- Evidence type: Code-confirmed | Test-reproduced | Live-reproduced
- Location: repository/relative/path:line
- Affected contract: Acceptance criterion or durable invariant
- Impact: Who/what fails and the consequence
- Scenario: Minimal reachable inputs/actions
- Proof: Exact code flow, file effect, command output, or runtime observation
- Recommendation: Smallest behavior-level correction
- Acceptance check: Observable proof that fails before and passes after
- Confidence: High | Medium, with reason when not High
```

Use one root cause per finding. Combine repeated symptoms only when one
correction and acceptance check cover them. Do not include a large replacement
patch unless necessary to clarify the required behavior.

## Two-stage result

Report separately:

- **Stage A — Specification compliance:** `Pass`, `Fail`, or `Not verified`.
- **Stage B — Engineering quality:** `Pass`, `Needs work`, `Fail`, or `Not
  verified`, backed by the lane scorecard.

A Stage A failure or unverified material criterion prevents `Approve`.

## Verdicts

- **Approve:** Stage A passes; no open P0-P2; every material activated lane and
  acceptance criterion has sufficient evidence.
- **Approve with follow-ups:** Stage A passes; no P0/P1; remaining P2 is safely
  outside current acceptance and has an explicit follow-up without hidden
  correctness, data-safety, or architecture debt.
- **Request changes:** any open P0/P1, or P2 violating acceptance, trust/data
  safety, architecture integrity, compatibility, or essential verification.
- **Blocked:** no confirmed issue already requires changes, but intent, review
  set, current environment, or material evidence is insufficient for a
  responsible approval verdict. When both a confirmed blocking defect and an
  evidence gap exist, use `Request changes` and list the gap as a limitation.

## Required report shape

1. **Findings** — P0 through P3; explicitly state when none qualify.
2. **Intent, repository profile, and change surface** — Objective, source of
   truth, before-state, discovered owners/contracts, and review range.
3. **Two-stage result** — Stage A and Stage B status with concise rationale.
4. **Lane scorecard** — Lane, activation reason, status, highest severity, and
   required evidence for every lane.
5. **Acceptance and evidence ledger** — Criterion/claim, exact proof, fresh
   result, failure classification, and limits.
6. **Hypotheses/questions** — No severity; state the proof needed.
7. **Evidence-backed strengths** — At most three tested patterns worth
   preserving; omit when not useful.
8. **Verdict** — Exactly one verdict and why the gates permit it.
9. **Self-check** — Complete every item below.

## Reviewer self-check

- [ ] I rebuilt a current repository profile and did not assume paths, modules,
      commands, counts, fixtures, or supported environments.
- [ ] I summarized authoritative intent and reviewed the correct cumulative
      range, including relevant untracked/remediation work.
- [ ] Stage A maps every acceptance criterion/non-goal to implementation and
      independent evidence.
- [ ] I inspected owners, callers, consumers, public/persistent contracts, and
      recovery paths rather than the diff alone.
- [ ] Every activated lane has the required evidence and status; exclusions
      have a trace-based reason.
- [ ] Every finding passes the contract/scenario/proof/impact/remedy/acceptance
      admission gate and names one root cause.
- [ ] Severity is impact-calibrated; hypotheses carry no P-level severity.
- [ ] I examined manuscript/data fidelity, paths, escaping, writes,
      AI/terminal authority, local-first behavior, lifecycle, and compatibility
      wherever reachable.
- [ ] I reviewed tests as deeply as production code, assessed failure
      sensitivity, and used live evidence for runtime-dependent behavior.
- [ ] Completion and pass claims cite fresh output; unexplained failures,
      baseline issues, and unverified criteria are explicit.
- [ ] I did not block on taste, generic best practice, speculative scale, or an
      abstraction without a demonstrated boundary.
- [ ] I changed no source, tests, docs, configuration, staging state, harness,
      or user data during the review.
- [ ] The verdict follows both stage gates and is not stronger than evidence.

If a required item is false, use `Request changes` when a confirmed finding
already meets that gate; otherwise use `Blocked` and state the missing evidence.
