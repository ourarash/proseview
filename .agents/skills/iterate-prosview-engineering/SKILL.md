---
name: iterate-prosview-engineering
description: "Orchestrate a bounded, repository-adaptive senior engineering loop for Prosview: discover current contracts, implement with $develop-prosview, independently run specification and engineering-quality review with $review-prosview-code, technically triage every finding, remediate root causes, rerun fresh validation, and repeat until the quality gate passes or a recorded stop rule fires. Use when Codex is asked to build or fix Prosview and keep iterating through code/architecture review, run an implement-review-fix loop, address review feedback automatically, or deliver only after independent approval."
---

# Iterate Prosview Engineering

Drive a disciplined discover → implement → specification review → engineering
review → triage → remediate → verify loop. Converge on independent evidence,
not reviewer appeasement or endless polishing. The loop may implement the
requested change and accepted in-scope corrections; it may not expand product
scope, add material dependencies, commit, deploy, or take destructive action
without separate authorization.

## Required skills and contract

1. Read and follow `../develop-prosview/SKILL.md` for every implementation or
   remediation pass, including repository discovery and activated lanes.
2. Read and follow `../review-prosview-code/SKILL.md` for every review pass,
   including the separate specification and engineering-quality stages.
3. Read [references/loop-contract.md](references/loop-contract.md) before the
   first edit. Maintain its repository profile, immutable objective, convergence
   policy, change manifest, evidence ledger, issue ledger, and cycle record.
4. If either sibling skill is unavailable, stop and report the missing
   dependency rather than improvising a weaker workflow.

## Loop workflow

### 0. Discover and define convergence

1. Build the current repository profile from the developer skill's discovery
   reference. Record governing instructions, before-state, unrelated changes,
   actual architecture owners, current test topology/commands, and supported
   live environments.
2. Freeze the user objective, acceptance criteria, constraints, non-goals, and
   authorized mutation scope. Review findings may improve implementation but
   cannot silently redefine the request.
3. Set a finite cycle budget and per-finding remediation allowance in the
   convergence policy. Use a user-supplied limit when present; otherwise choose
   and justify the smallest budget appropriate to the number of independent
   behavior slices, crossed boundaries, and risk lanes. Do not silently extend
   it.
4. Create the change manifest, expected evidence graph, and activated lane map.
   Discover commands and fixtures from the checkout; do not encode assumed
   paths, markers, counts, or environment names into the loop.

### 1. Implement a proof-sized increment

1. Apply `$develop-prosview` to the objective or current accepted finding set.
2. For the initial pass, implement the smallest complete behavior. For later
   passes, edit only the root causes of accepted findings and resulting
   regressions.
3. Use the developer's root-cause protocol for failures and witnessed red →
   green → refactor evidence for testable behavior.
4. Run focused then boundary/live/broad validation derived from the current
   repository profile. Update the evidence ledger and change manifest.
5. Complete the developer lane record and self-check. Treat them as handoff
   claims for independent verification, not proof.

### 2. Run independent two-stage review

1. Give the reviewer the immutable objective, before-state, current cumulative
   diff (including untracked files), relevant repository source/tests, exact
   raw validation output, known baseline failures, and the review skill path.
2. Prefer a fresh reviewer context when available. Do not prime it with the
   implementer's design defense, self-check conclusion, suspected defects, or
   desired verdict.
3. Run Stage A specification compliance first, then Stage B engineering quality
   across every activated lane. Keep review read-only.
4. Preserve raw findings, questions, scorecard, evidence, and verdict in the
   issue ledger before discussing or changing them.
5. If no fresh reviewer is available, deliberately rebuild the repository
   profile and inspect the complete diff/callers before reading the developer
   self-evaluation.

### 3. Triage review feedback technically

For every finding, read the full claim and record one decision:

- **Accept:** scenario and evidence are valid; correction is in scope.
- **Reject:** claim is contradicted by current code, contract, test, or runtime
  evidence; record that proof.
- **Defer:** valid, outside current acceptance, safe under the quality gate,
  and paired with consequence/follow-up.
- **Needs user decision:** valid choices change product behavior, durable data,
  compatibility, dependency policy, architecture, or authorized scope.

Restate unclear technical requirements and gather evidence before implementing.
Do not accept feedback performatively or reject it defensively. Automatically
accept confirmed in-scope P0/P1 issues and P2 issues that violate acceptance,
trust/data safety, architecture integrity, compatibility, or essential proof.
Keep unverified reviewer concerns as hypotheses until tested.

### 4. Remediate one root cause at a time

1. Feed only accepted findings, their scenarios/proof, and acceptance checks
   into the next `$develop-prosview` pass.
2. Reproduce each issue and see its regression proof fail for the expected
   reason. When a reliable pre-change red is inappropriate, record the reason
   and substitute proof before editing; the independent reviewer must validate
   the exception. Fix the root cause, run its acceptance check, then proceed to
   the next independent issue.
3. Do not mechanically copy a suggested patch. Validate that the remedy fits
   current Prosview ownership, invariants, and consumers.
4. Re-run every affected prior proof and the cumulative acceptance graph. If a
   correction fails, form a new hypothesis rather than layering patches.
5. Add material repository discoveries to the loop's discovery log so later
   implementation/review contexts receive current facts without receiving the
   implementer's conclusions.

### 5. Re-review cumulatively and decide

1. Re-run both review stages against the entire cumulative change, not only the
   last patch. Confirm prior findings with their acceptance checks and search
   for remediation regressions across activated lanes.
2. Refresh repository profile facts invalidated by concurrent changes.
3. Stop successfully only when the loop quality gate passes and the reviewer
   verdict permits completion.
4. Stop without claiming success when a convergence-policy condition fires, a
   required user decision/new authority is needed, ownership becomes unsafe,
   evidence cannot run, or further work is optional polish/speculation.
5. Do not call the result complete because the cycle budget expired. Report the
   exact safe state, remaining ledger, proof, and next decision.

## Final handoff

Return:

1. Outcome: `Complete`, `Incomplete`, or `Blocked`.
2. Objective, implemented behavior, root causes, and material architecture
   decisions.
3. Repository profile facts that governed the work and any concurrent drift.
4. Cycle table with implementation, fresh validation, two-stage review result,
   findings opened/resolved, and gate decision.
5. Final issue and evidence ledgers, remaining limitations/follow-ups, lane
   statuses, and completed loop self-check.

Do not commit or deploy unless separately requested.
