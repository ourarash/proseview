# Proseview Adaptive Validation Matrix

Derive validation from the repository profile and acceptance map. Never assume
a test runner, marker, path, count, fixture, browser, or installation command.
Use the checkout's current contributor documentation, project metadata, test
configuration, and CI as the command source.

## Evidence layers

For each acceptance criterion, select the lowest layer that owns the invariant
and every real boundary needed to prove the user outcome.

| Evidence layer | What it proves | Typical Proseview use |
|---|---|---|
| Contract/unit | Pure rule, parser, transformation, validation, ordering | Manuscript/frontmatter fidelity, analytics, config normalization, range/path rules |
| Component/boundary | Two owners agree on file, wire, event, package, or browser contract | Render payload, endpoint/file effect, route/state, installed assets |
| Live/system | The real process or browser completes the user workflow | Server lifecycle, save/conflict, navigation, editor, terminal, proposal, accessibility |
| Broad repository gate | The change did not break unrelated supported behavior | Current default CI-equivalent test/lint/build/package checks |

A source-text assertion cannot replace a live proof when the contract depends
on runtime JavaScript, browser semantics, process lifecycle, installed package
data, or durable file effects.

For stateful UI capabilities, build an acceptance-specific state-transition
matrix from discovered routes, panels, modes, and entry points. A live proof
must start in the relevant state and complete the user task through its
intermediate transitions and recovery/next action. Do not combine isolated
tests that start from different states. Claims implying universal reach or a
whole collection require a boundary fixture derived from current
configuration, not a hardcoded feature example from this reference.

## Surface-to-evidence selection

| Discovered behavior | Minimum focused proof | Escalate when |
|---|---|---|
| Parser, analysis, sorting, or highlighting | Boundary inputs plus empty/malformed/unknown/long cases | Result crosses serialization or UI labels |
| Manuscript/config mutation | Exact semantic/byte round trip, invalid path/state, stale write | UI/API initiates the write or recovery is user-visible |
| CLI/config/default discovery | Argument/config contract and invalid/missing values | Installed entrypoint, subprocess, or migration changes |
| Rendering/serialization/assets | Typed payload, escaping at actual sink, deterministic output | Runtime loading/order, browser state, or packaging changes |
| HTTP/event/watch behavior | Validation, success/failure effect, ordering, reconnect/cleanup | Browser consumes state or file/process safety is involved |
| Navigation/search/editor/UI | User-facing browser assertion plus console/network check | Keyboard/focus, history/reload, zoom/theme, or data safety changes |
| Agent/terminal/proposal | Fake/stub process and exact scoped context/effect | Lifecycle, approval, stale state, or browser interaction changes |
| Dependency/package/CI | Metadata and installed/package smoke proof | Optional environments, offline behavior, or release gates change |
| Documentation only | Current examples, names, links, and commands checked | Documentation generates runtime output or changes a public promise |

## Red → green → refactor record

For testable behavior changes, record all three observations:

```markdown
- Red proof: command/probe; expected failure; observed failure and reason.
- Green proof: same focused proof; observed pass after the minimal behavior.
- Refactor proof: focused proof rerun after cleanup; observed pass.
```

If a test passes before the implementation, it does not prove the new behavior;
strengthen it until it detects the missing contract. If test-first is not
appropriate, state why and identify the substitute before editing.

## Failure investigation gate

Before changing production behavior in response to a failure:

1. Reproduce it in the narrowest current environment.
2. Capture the value/state at each relevant layer and identify the first
   divergence from the contract.
3. State one root-cause hypothesis with disconfirming evidence to seek.
4. Run one minimal experiment; do not combine independent fixes.
5. Convert the confirmed scenario into durable regression evidence.
6. If successive attempts expose unrelated symptoms, revisit the architecture
   and request direction before expanding scope.

## Test quality gate

- Names describe behavior and failure consequence.
- Assertions prove observable output, exact file/wire effect, accessible state,
  cleanup, or negative behavior—not implementation spelling.
- Fixtures are isolated from real manuscripts, user homes/profiles, real
  agents, networks, fixed ports, order, time, and prior run state.
- Mocks isolate a boundary but do not become the subject of the test.
- Browser checks fail on unexpected page/console/network errors and use
  user-meaningful locators when the current harness supports them.
- Browser assertions verify that focused/activated controls are visible,
  operable, and lead to the intended user outcome; internal focus or event
  state alone is insufficient.
- Failure, empty, boundary, conflict, cancellation, and cleanup paths match the
  activated risk lanes.

## Completion evidence ledger

Every completion claim needs a fresh row:

| Claim or criterion | Required proof | Exact command/probe | Result | Classification/limits |
|---|---|---|---|---|

Use `Passed`, `Failed`, `Blocked`, or `Not run`. Include exit status, relevant
counts/duration when available, before/after file effects, and whether a
failure predates the change. Do not extrapolate from a subset to the broad gate.

For missing optional dependencies, report the repository-documented setup and
ask before installation. For a suspected harness defect, preserve evidence and
continue only with independent valid proofs; do not edit the harness unless the
user separately authorizes harness work.
