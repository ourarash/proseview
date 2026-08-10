# UI/UX Audit Report Contract

Return the report in chat. Do not persist reports or screenshots in the
repository. Use direct language, prioritize user impact, and include enough
evidence for an engineer or designer to reproduce and verify every finding.

## Contents

1. Audit outcome
2. Lane statuses
3. Severity model
4. Evidence model
5. Finding format
6. Required report shape
7. Final self-check

## 1. Audit outcome

Choose exactly one outcome:

- **Complete:** the live completion gate in `SKILL.md` passed.
- **Incomplete:** a live audit ran, but required in-scope workflows, contexts,
  or lanes remain unverified. Trace-unreachable items correctly marked `Out of
  scope` do not prevent completion of an explicitly focused audit.
- **Blocked:** no reliable live browser audit could run. State the blocker,
  preflight evidence, and exact next action. Label any static observations as
  partial.

Never call a static-only review complete.

## 2. Lane statuses

Assign one status to every in-scope lane:

- **Pass:** live evidence covers the lane and no material issue was found.
- **Needs work:** the lane works but contains one or more P2/P3 problems, or a
  narrowly contained P1 with a viable alternative.
- **Fail:** a P0/P1 issue breaks, excludes, misleads, or makes the lane unsafe.
- **Not verified:** evidence is insufficient. Explain what was not tested and
  why.
- **Out of scope:** the focused review's traced workflow cannot affect the
  lane. State the trace-based reason. Full audits cannot use this status for a
  product lane.

Do not average statuses or produce an aggregate numeric score. A Pass means
tested and acceptable, not merely that no source defect was noticed.

## 3. Severity model

- **P0 — critical:** likely data loss/corruption, unsafe action without user
  control, or a broadly blocking failure with no viable recovery.
- **P1 — high:** prevents a core writer task, excludes a material user group,
  creates serious misunderstanding, or makes recovery unreliable.
- **P2 — medium:** causes significant friction, ambiguity, inefficiency, weak
  feedback, or error-recovery difficulty while leaving a workable path.
- **P3 — low:** localized usability, consistency, accessibility, or polish
  issue with limited task impact.

Calibrate using task criticality, occurrence frequency, affected users,
recoverability, and trust impact. Do not assign P0/P1 to taste or cosmetic
preference. Accessibility failures may be P1 when they block a core workflow.

## 4. Evidence model

Label each item as one of:

- **Observed:** reproduced in the live browser through the current harness.
- **Source-confirmed risk:** directly supported by implementation, but not
  reproduced as a user-visible failure.
- **Hypothesis:** credible but not verified; keep outside the prioritized defect
  list unless the user asks for research questions.

For observed evidence, record the starting state, numbered actions, viewport,
zoom, theme, input method, result, repeatability, and relevant console/network
or file effect. Link or name a screenshot only when it materially proves the
claim. For source evidence, cite the repository path and line.

Do not treat an automated assertion as proof of usability. Do not treat a
source pattern as proof of user harm without either reproduction or careful
qualification.

## 5. Finding format

Use this exact field set for each P0-P3 finding:

```markdown
### UX-001 — Concise user-impacting title

- Severity: P1
- Lane: Accessibility and keyboard usability
- Evidence: Observed
- Workflow: Open and edit a scene with keyboard only
- User impact: Who is affected, what task is impaired, and the consequence.
- Expected: The concrete safe or usable behavior.
- Observed: The concrete behavior, including repeatability.
- Reproduction:
  1. Starting state, viewport, theme, and input method.
  2. Exact user action.
  3. Result and any console/network/file evidence.
- Corroboration: Optional source path and line or screenshot path.
- Confidence: High, Medium, or Low, with a short reason if not High.
- Recommendation: Specific behavior-level remedy that fits Proseview.
- Acceptance check: Observable test that proves the issue is resolved.
```

Keep one root cause per finding. Combine repeated manifestations when one
remedy and acceptance check cover them; split findings when impacts or remedies
differ. Place hypotheses in a separate section without P-level severity.

## 6. Required report shape

Use these sections in order:

1. **Outcome and executive verdict**
   - Complete, Incomplete, or Blocked.
   - Two to five sentences on the product's usability, largest risk, and audit
     confidence. Lead with the conclusion.
2. **Scope and environment**
   - Commit/worktree state, repository-profile sources, discovered harness
     entrypoint, browser, viewports, zoom, themes, input methods, isolated
     fixture strategy, and excluded scope.
3. **Baseline E2E health gate**
   - Exact command, pass/fail/skip counts, duration, and failure classification.
4. **Lane scorecard**
   - A compact table with Lane, Status, Highest severity, and Evidence note for
     all eight lanes. For a focused audit, mark other lanes Out of scope rather
     than assigning a quality status.
5. **Prioritized findings**
   - Sort P0 through P3, then by affected workflow. Use the finding format.
6. **Evidence-backed strengths**
   - Include at most three strengths that were actively tested. Omit this
     section if none materially help prioritization.
7. **Hypotheses and unverified risks**
   - Keep separate from confirmed findings. State the test needed to resolve
     each one.
8. **Limitations**
   - Name unavailable workflows, environment/harness constraints, simulations,
     and anything not tested.
9. **Self-check**
   - Reproduce and complete every item below.

## 7. Final self-check

End every report with these items and an evidence note after each checkbox. Use
`[x]` only when true; use `[ ]` and explain the gap otherwise.

- [ ] Every in-scope lane was covered or marked `Not verified`/out of scope.
- [ ] Current commands, routes, selectors, fixtures, themes, features, and
      harness capabilities were discovered rather than assumed from the skill.
- [ ] Every required Proseview workflow was exercised or explicitly listed as
      unverified.
- [ ] A discovered capability-by-state matrix proves complete material tasks;
      disconnected surface checks were not combined as journey evidence.
- [ ] Universal, collection-wide, persistence, safety, and accessibility
      claims were challenged with dynamically derived boundary cases.
- [ ] The baseline E2E command, result, environment, and failure classification
      were reported.
- [ ] For a full audit, the 1400x1000, 1024x768, and 200% zoom passes were
      attempted; for a focused audit, every context activated by the requested
      workflow was attempted and exclusions are trace-justified.
- [ ] For a full audit, light theme, dark theme, and a keyboard-only core pass
      were attempted; for a focused audit, the applicable theme/input contexts
      were attempted and exclusions are trace-justified.
- [ ] Console errors, failed requests, focus behavior, and isolated file effects
      were observed where applicable.
- [ ] Interactive success was based on visible operability and completed user
      outcomes, not DOM presence, programmatic focus, or event dispatch alone.
- [ ] Findings are evidence-labeled, reproducible, deduplicated, and calibrated
      by user impact.
- [ ] Every recommendation has an observable acceptance check and stays within
      the evidence.
- [ ] Hypotheses, source-confirmed risks, and observed defects are separated.
- [ ] Limitations, harness failures, and untested states are explicit.
- [ ] No real manuscript, Proseview product file, test, or E2E harness file was
      changed by the audit.
- [ ] Browser contexts, servers, terminals, event streams, and temporary audit
      artifacts were stopped or any cleanup failure was disclosed.
- [ ] The snapshot manifest was compared with the primary checkout; affected
      live evidence was rerun after drift or explicitly marked stale.

After the checklist, state whether the completion gate passed. If any required
box remains unchecked or any required workflow/high-risk lane probe is `Not
verified`, the outcome cannot be `Complete`.
