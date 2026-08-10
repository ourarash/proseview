# Proseview Implementation Lanes

Activate lanes from the repository profile and traced change surfaces. Record
one status for every lane: `Satisfied`, `Needs work`, `Blocked`, or `Not
applicable`. A lane is satisfied only by the evidence named below; general
confidence or a passing broad suite is insufficient.

## Lane D1 — Intent, scope, and acceptance

**Activate:** Always.

**Required work**

- State the writer/developer problem, observable outcome, acceptance criteria,
  constraints, compatibility expectations, and non-goals.
- Resolve ambiguities that change behavior, durable data, user authority,
  dependency policy, or architecture. Record low-risk inferences.
- Identify current documentation/tests that promise the affected behavior and
  distinguish accepted intent from stale commentary.
- Define the smallest coherent behavior slice and explicit failure/recovery
  behavior before editing.

**Evidence to record**

- Acceptance criterion → observable proof mapping.
- Authorized mutation scope and unrelated work to preserve.
- Decisions, assumptions, and unresolved questions.

## Lane D2 — Repository fit and architecture

**Activate:** Always; depth increases for cross-layer or structural changes.

**Required work**

- Use the repository profile to identify the current owner, callers,
  consumers, dependencies, and lifecycle owner for the changed behavior.
- Trace dependency direction and state authority; avoid parallel sources of
  truth, implicit global synchronization, and circular ownership.
- Keep pure domain work separate from filesystem, HTTP, process, time, and
  browser effects where it improves direct verification.
- Extend an existing cohesive boundary before creating a framework, service,
  repository layer, flag system, or dependency.
- Compare alternatives using present change pressure, not hypothetical scale.

**Evidence to record**

- Current and proposed data/control-flow sketch naming owning symbols.
- Why the selected boundary is smaller/safer than the rejected alternatives.
- New dependency or abstraction justification, or confirmation that none was
  added.

## Lane D3 — Manuscript, domain, and data fidelity

**Activate:** Parsing, analysis, ordering, file/config reads or writes,
annotations, proposals, history, or derived writer-facing data.

**Required work**

- Define invariants for missing/empty/malformed input, unknown values, zero and
  false, Unicode, long content, quoting, line endings, and deterministic order.
- Preserve manuscript body, frontmatter, unknown keys, annotations, emphasis,
  whitespace, and untouched regions according to the current contract.
- Confirm calculations and labels describe exactly what is measured; avoid
  turning heuristics into factual claims.
- Make write identity, source range, conflict token, and round-trip behavior
  explicit.
- Provide backward-compatible reading or a user-approved migration for durable
  data changes.

**Evidence to record**

- Input/output examples including at least one boundary or malformed case.
- Exact byte/semantic round-trip proof for affected writes.
- Determinism, ordering, and migration evidence where applicable.

## Lane D4 — Interfaces, integration, and compatibility

**Activate:** Any CLI, config, route, URL, HTTP/event, serialization, browser
global, package, or cross-module contract.

**Required work**

- Inventory every producer and consumer before changing shape, name, default,
  type, ordering, status, or error semantics.
- Validate at the authoritative boundary and preserve meaningful distinctions
  among absent, null, empty, false, zero, invalid, and unknown.
- Keep request/response, event, route/history, and browser state transitions
  explicit and recoverable after reload or reconnection.
- Discover supported runtimes/platforms and installed-package behavior; do not
  assume source-checkout behavior proves compatibility.
- Define migration/fallback behavior for public or persistent contracts.

**Evidence to record**

- Producer/consumer matrix with changed fields or states.
- Contract tests at the lowest owner plus one real boundary proof when the
  change crosses layers.
- Compatibility and migration result, including platforms not verified.

## Lane D5 — Security, privacy, trust, and data safety

**Activate:** All writes; user-controlled text/paths; HTML/JS/URL/selector
sinks; agent/terminal/process work; network behavior; logs/errors; destructive
or elevated actions.

**Required work**

- Normalize and resolve paths, enforce containment after symlink resolution,
  and authorize the specific read/write/preview/command action.
- Validate shape, type, size, range, state, and conflict tokens server-side or
  at the authoritative local boundary.
- Escape or encode for the actual sink; use argument arrays and text DOM APIs
  where executable interpretation is unnecessary.
- Keep agent context, terminal authority, auto-approval, and proposal apply
  actions explicit, narrow, and visible to the user.
- Prevent stale overwrite, wrong-range application, misleading success, secret
  disclosure, manuscript leakage, and accidental network/service expansion.
- Make destructive actions scoped and recoverable where possible.

**Evidence to record**

- Threat/failure cases for each newly reachable boundary.
- Negative tests for traversal/injection/invalid state or a reason they cannot
  apply.
- Confirmation of local-first, log/error, and user-authority behavior.

## Lane D6 — Reliability, concurrency, and lifecycle

**Activate:** Writes, async work, events, watchers, caching, terminals,
subprocesses, browser resources, retries, timeouts, or recoverable UI state.

**Required work**

- Define success by durable outcome and handle partial failure without
  contradictory state.
- Specify idempotency, duplicate event/request behavior, ordering, stale data,
  cancellation, timeout, reconnection, and external-edit handling.
- Bind cleanup to ownership for files, threads, processes, terminals, streams,
  editors, listeners, observers, timers, browser contexts, and temporary data.
- Replace arbitrary sleeps and blind retries with observable conditions or
  bounded failure behavior.
- Preserve user work through navigation, refresh, disconnect, conflict, and
  failed saves; expose an actionable recovery path.

**Evidence to record**

- Lifecycle state table or concise transition trace.
- Failure/cleanup test showing the resource or draft is preserved/released.
- Known race, platform, or recovery state not verified.

## Lane D7 — UI, accessibility, and content design

**Activate:** Rendered structure, browser behavior, styles, user-facing copy,
navigation, editor/selection, charts, menus/dialogs, status, or preferences.

**Required work**

- Use semantic controls with accurate accessible name, role, value/state,
  keyboard operation, visible focus, and intentional focus restoration.
- Check default, focus, hover, active, selected, disabled, loading, success,
  empty, error, conflict, and recovery states affected by the change.
- Preserve URL/deep-link/history behavior, dirty-state protection, theme
  coherence, zoom/reflow, reduced motion, and non-color communication.
- Keep DOM sinks safe and event/resource ownership explicit.
- Make labels and explanations writer-centered, accurate about analytics/AI,
  and specific about consequences and recovery.
- Use the live browser harness for behavior that depends on rendering or
  JavaScript; source assertions alone do not establish usability.

**Evidence to record**

- Keyboard/focus and accessible-state observations for the affected task.
- Live viewport/theme/reflow checks appropriate to the request.
- Browser console/network state and screenshot only if it proves a defect or
  acceptance criterion.

## Lane D8 — Performance and resource use

**Activate:** Hot paths, large-scene/many-file behavior, repeated rendering or
analysis, caching, events, terminal output, startup, or an optimization request.

**Required work**

- Define the user-visible performance problem or complexity boundary before
  optimizing; measure a representative case.
- Inspect repeated repository scans, parsing, serialization, DOM rebuilds,
  charts, file I/O, subprocess work, and leaked resources across the traced
  flow.
- Keep work and output bounded; verify cache keys and invalidation before
  improving hit rates.
- Prefer the simplest measured improvement and guard against correctness or
  readability regressions.

**Evidence to record**

- Before/after measurement or complexity argument tied to a writer workflow.
- Dataset/fixture shape and environmental caveats.
- Regression test or threshold when stable enough to be meaningful.

## Lane D9 — Test design and verification evidence

**Activate:** Always for behavior changes; proportionate for docs-only work.

**Required work**

- For a testable feature/fix/refactor, establish a failing behavior proof and
  confirm it fails for the intended reason before implementation. Record a
  justified exception for generated/config-only/exploratory work.
- Add the lowest-layer test that owns the invariant plus a real boundary test
  when the defect crossed layers.
- Assert observable behavior, exact file/wire effects, negative evidence,
  cleanup, and recovery—not mock choreography or source spelling.
- Keep tests isolated from real manuscripts, user profiles, networks, agents,
  fixed ports, ordering, prior state, and arbitrary timing.
- Run focused checks, affected integration/system checks, and the broad gate
  discovered from the repository profile.

**Evidence to record**

- Red → green → refactor commands/results for the new proof.
- Acceptance criterion → test/runtime evidence mapping.
- Fresh final commands, exit status/counts, failure classifications, and
  unverified criteria.

## Lane D10 — Packaging, documentation, and operations

**Activate:** Public behavior, CLI/config, dependencies, assets, optional
features, startup/shutdown, CI/release, diagnostics, or installed use.

**Required work**

- Verify runtime assets and dependencies work from the supported installed
  form, not only the checkout.
- Keep optional features optional and explain missing prerequisites with the
  repository's current installation path.
- Update user/developer documentation only for changed contracts; ensure names,
  examples, defaults, and recovery steps execute against the current build.
- Keep diagnostics actionable for a local user without leaking sensitive
  content or hiding root causes.
- Preserve CI/release expectations or explicitly update the authoritative
  source when the task changes them.

**Evidence to record**

- Installed/packaged smoke evidence when packaging is affected.
- Documentation examples or configuration validation exercised.
- CI/release/optional-environment checks and any missing dependency blocker.

## Final lane record

Use this compact record in the handoff:

| Lane | Status | Evidence | Remaining risk |
|---|---|---|---|

Do not fill the evidence column with “reviewed” or “tests pass.” Name the
specific contract, test, runtime observation, or reason the lane cannot apply.
