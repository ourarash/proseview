# Proseview Code and Architecture Review Lanes

Use these lanes as failure-oriented investigations. Each lane states when it
activates, what to probe, and what evidence permits a status. For a full audit,
cover all lanes. For a focused review, justify every `Out of scope` result.

## Lane R1 — Specification and behavioral compliance

**Activates:** Always. This is review stage A.

**Review probes**

- Map every acceptance criterion, constraint, and non-goal to the current
  implementation and an observable proof.
- Exercise happy, error, empty, boundary, conflict, reload, cancellation, and
  recovery paths that the objective implies.
- Check absent/null/empty/false/zero/unknown values, ordering, Unicode, long
  content, malformed input, and unsupported states where reachable.
- Verify displayed success corresponds to the intended file, route, proposal,
  terminal, preference, package, or process effect.
- Identify unrequested behavior, silently changed defaults, compatibility
  changes, or scope expansion.

**Required evidence for Pass:** every material criterion is independently
mapped to code and fresh test/runtime/file evidence; non-goals remain excluded.

## Lane R2 — Architecture, ownership, and dependency direction

**Activates:** Always; inspect deeply for cross-layer or structural changes.

**Review probes**

- Identify the current owner, callers, consumers, state authority, and cleanup
  owner from the repository profile.
- Trace data/control flow across parsing, analysis, rendering/serialization,
  local server/events, browser state, persistence, and process boundaries.
- Check cohesion, dependency direction, cycles, duplicated authority, global
  synchronization, and contracts hidden in DOM strings or execution order.
- Challenge new layers/dependencies and cross-layer shortcuts using actual
  change pressure, not pattern labels.
- Verify abstractions protect a real invariant, isolate an effect, or serve
  actual consumers and do not make common changes harder.

**Required evidence for Pass:** an owner/consumer trace for every changed
contract and no unexplained split authority, cycle, or unjustified abstraction.

## Lane R3 — Manuscript, domain, and data fidelity

**Activates:** Parsing, analysis, annotations, proposals, sorting, history,
configuration, or any read/write of durable user data.

**Review probes**

- Verify optional/unknown metadata, manuscript body, emphasis, annotations,
  whitespace/line structure, and untouched regions survive affected writes.
- Check file identity, range offsets, encoding, line endings, deterministic
  order, missing/malformed input, and large-content behavior.
- Confirm calculations, editorial flags, chart values, and labels represent
  the implemented algorithm honestly.
- Review backward readers, migration, defaults, and failure behavior for
  durable format changes.
- Trace round trips through every writer, not only the new path.

**Required evidence for Pass:** boundary fixtures plus exact byte/semantic
round-trip proof for writes and a producer/consumer proof for derived data.

## Lane R4 — Interfaces, integration, and compatibility

**Activates:** CLI/config, file schema, routes/URLs, HTTP/events, serialized
payloads, browser globals/state, packages, dependencies, or platform behavior.

**Review probes**

- Inventory producers/consumers for changed names, shapes, types, defaults,
  status/error semantics, ordering, and version assumptions.
- Check validation at the authoritative boundary and distinctions among
  absent, empty, false, zero, invalid, and unknown.
- Verify direct URL, history/reload, reconnect/duplicate event, and stale-client
  behavior where the contract exposes them.
- Discover supported runtimes/platforms and test installed use rather than
  assuming the source checkout proves it.
- Assess migration/fallback behavior and documentation for public changes.

**Required evidence for Pass:** current producer/consumer matrix and boundary
tests for changed contracts; untested supported environments are explicit.

## Lane R5 — Security, privacy, trust, and data safety

**Activates:** Writes, paths, untrusted text, executable/rendering sinks,
terminal/agent/process behavior, network behavior, sensitive logs/errors, or
destructive/elevated actions.

**Review probes**

- Trace path normalization, symlink resolution, containment, authorization,
  and time-of-check/time-of-use behavior for each file action.
- Review validation of request/state/type/size/range/conflict tokens at the
  authoritative boundary.
- Inspect sink-specific handling for HTML text/attributes, JavaScript, JSON,
  URLs, selectors, Markdown, logs, and process arguments.
- Verify agent context and terminal authority are narrow, visible, and not
  expanded by ambiguous selection or auto-approval state.
- Check stale writes, proposal range drift, misleading success, manuscript or
  absolute-path leakage, secrets, telemetry, and silent network dependencies.
- Assess destructive scope, confirmation wording, reversibility, and recovery.

**Required evidence for Pass:** a traced threat/failure model plus negative
tests or direct proof for every newly reachable trust boundary.

## Lane R6 — Reliability, concurrency, and lifecycle

**Activates:** Writes, asynchronous work, watchers/events, caching, terminals,
subprocesses, browser resources, retries, timeouts, or persistent draft state.

**Review probes**

- Check atomicity, partial failure, idempotency, repeated actions, event order,
  reconnect duplication, invalidation, and external edits.
- Trace cancellation, timeout, shutdown, and cleanup for files, threads,
  subprocesses, terminals, streams, timers, listeners, observers, editors,
  browser contexts, and temporary data.
- Search for broad exceptions, empty catches, blind retry, arbitrary sleeps,
  false success, unbounded output, and cleanup that runs only on success.
- Verify work survives navigation, refresh, disconnect, save failure, conflict,
  and server/process restart as promised.
- Check platform-specific process behavior and actionable failure diagnostics.

**Required evidence for Pass:** lifecycle/state trace and failure-path proof
showing durable state and resources end correctly.

## Lane R7 — UI, accessibility, and content integrity

**Activates:** Browser markup/behavior/styles, navigation, editing/selection,
charts, menus/dialogs, user-facing copy, feedback, or preferences.

**Review probes**

- Verify semantic element, accessible name/role/value/state, keyboard operation,
  visible focus, logical order, focus containment/restoration, and live status.
- Check default, focused, active, selected, disabled, loading, success, empty,
  error, conflict, and recovery states for changed controls.
- Verify deep links/history/reload, dirty-state protection, safe DOM updates,
  theme/zoom/reflow, reduced motion, and non-color communication.
- Confirm copy is writer-centered, accurate about analysis/AI/local behavior,
  and specific about consequences and recovery.
- Use the real browser for rendered behavior; inspect source afterward to
  establish cause. Static selectors alone cannot establish usability.

**Required evidence for Pass:** a live keyboard/focus/state observation for
the affected workflow plus relevant console/network/file-effect evidence.

## Lane R8 — Performance and resource efficiency

**Activates:** Hot paths, startup, large scenes/many files, search/analysis,
rendering, caching, events, terminal output, or an optimization claim.

**Review probes**

- Identify repeated scans, parsing, serialization, file I/O, DOM/chart rebuilds,
  subprocess work, allocations, and retained resources in the traced flow.
- Check algorithmic behavior at representative large-scene, many-file,
  annotation, result, and output volumes.
- Validate cache keys/invalidation, backpressure, output bounds, and cleanup.
- Require a measured user-facing regression or defensible complexity bound;
  reject micro-optimization findings without impact.
- Check that an optimization preserves correctness, clarity, and recovery.

**Required evidence for Pass:** measurement/complexity evidence for affected
hot paths or a reasoned demonstration that the change cannot reach one.

## Lane R9 — Tests and verification quality

**Activates:** Always for implementation reviews.

**Review probes**

- Map tests to acceptance criteria, regression cause, domain invariants, trust
  boundaries, recovery, and crossed integration points.
- Verify new tests can fail when the production behavior is removed or wrong;
  check whether the author observed the intended pre-fix failure.
- Inspect assertions for exact observable effects, negative evidence, browser
  errors/accessibility state, cleanup, and false-positive paths.
- Review fixture fidelity and isolation from real manuscripts, user profiles,
  networks, agents, fixed ports, ordering, arbitrary time, and prior runs.
- Identify mock choreography, source-spelling assertions, broad snapshots,
  sleeps/retries without diagnosis, stale selectors, and overly broad expected
  failures.
- Independently run focused and broad current gates when feasible.

**Required evidence for Pass:** criterion-to-proof mapping, failure sensitivity
of changed tests, and fresh results from the current required gates.

## Lane R10 — Packaging, documentation, and operations

**Activates:** Dependencies, assets, CLI/config, optional features, startup or
shutdown, diagnostics, package metadata, CI/release behavior, or public docs.

**Review probes**

- Verify required assets/dependencies exist in the supported installed form and
  optional features fail with current actionable setup guidance.
- Check version/support claims, default configuration, offline behavior, CI
  commands, generated/vendor policy, and dependency provenance/scope.
- Compare changed public behavior with user/developer docs and executable
  examples; avoid reporting unrelated stale prose.
- Inspect startup/shutdown diagnostics and cleanup for actionable local
  recovery without sensitive leakage.
- Ensure operational complexity remains proportional to a local application.

**Required evidence for Pass:** installed/package or CI-equivalent proof for
affected behavior and verified current documentation contracts.

## Lane statuses

- **Pass:** required probes ran with sufficient evidence and no material issue.
- **Needs work:** confirmed P2/P3 weakness; core contract remains safe/usable.
- **Fail:** confirmed P0/P1 defect or a material specification/trust boundary is
  broken.
- **Not verified:** lane applies but required evidence is unavailable.
- **Out of scope:** traced change cannot affect the lane; include the trace-based
  reason.

No lane passes merely because it produced no finding.
