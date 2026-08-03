# Prosview Product and Architecture Invariants

Read this after building the current repository profile. It defines durable
product constraints and ownership tests; it intentionally does not freeze the
current file tree or toolchain.

## Product boundary

- Prosview is a local, Markdown-first writing dashboard and agent harness. Keep
  authors in control of their files, editing tools, terminal sessions, and AI
  proposals.
- Do not introduce telemetry, accounts, hosted-service assumptions, silent
  network dependencies, or mandatory cloud state without an explicit product
  decision.
- Keep runtime/build dependencies proportional to a local tool. A new
  dependency needs a concrete capability, maintenance rationale, offline
  impact review, and current packaging support.
- Treat manuscript text, frontmatter, annotations, configuration, file paths,
  history, and terminal context as durable or sensitive user data.
- Discover supported runtimes and operating systems from current metadata and
  docs. Do not preserve or change compatibility based on this reference alone.

## Durable data and behavior contracts

- Reads tolerate documented optional data and fail clearly on unsafe or
  malformed input.
- Writes preserve unrelated content and unknown metadata unless the user
  explicitly requests a transformation.
- Every user-selected path is normalized, resolved, authorized, and contained
  before read, write, preview, command, or proposal use.
- A stale external edit cannot be silently overwritten. The UI and API expose
  a recoverable conflict state.
- Visible success means the intended durable file/process effect completed;
  queued work or a successful transport response alone is insufficient.
- Browser deep links, reload, Back/Forward, current selection, dirty state, and
  recovery behavior are public contracts where the current product exposes
  them.
- AI output remains a proposal until the user knowingly applies it. Context
  sent to an agent is bounded to the represented file/selection/instruction.
- Tests and audits mutate only disposable repositories and isolated process
  configuration, never a real manuscript or user profile.

## Ownership boundaries to locate dynamically

| Concern | Healthy owner | Boundary questions |
|---|---|---|
| CLI and configuration | Thin entrypoint plus validated configuration model | Are defaults, errors, discovery, and compatibility defined once? |
| Manuscript parsing and editing | Domain layer independent of transport/UI | Are round trips non-lossy and invariants testable without a server/browser? |
| Analysis and derived data | Deterministic transformations | Are labels honest, ordering stable, and filesystem/browser effects excluded? |
| Rendering and serialization | Explicit server-to-client contract | Are types, missing values, escaping, and deterministic output defined at the correct sink? |
| Local HTTP and events | Narrow request validation and orchestration | Are paths, writes, conflicts, event order, and errors safe and recoverable? |
| Watch/process/terminal lifecycle | One lifecycle owner per resource | Are start, cancellation, reconnect, teardown, and failure states bounded? |
| Browser navigation and state | One authoritative owner per state domain | Do URL, view, focus, dirty state, and persistence agree after reload/history? |
| Browser presentation | Semantic structure plus reusable visual tokens | Are controls accessible, themes coherent, reflow usable, and data perceivable without color alone? |
| Packaging and tests | Installed behavior and isolated evidence | Do package assets, optional dependencies, fixtures, and CI exercise the actual runtime? |

Use the repository profile to fill in the current owning symbols and consumers.
If ownership is split, determine whether the split is intentional or a source
of contradictory state before proposing a refactor.

## Cross-layer design rules

- Trace data end to end. A field or state is not complete because one layer
  supports it; every producer, validator, serializer, consumer, mutation path,
  error path, and test must agree.
- Keep pure computation separate from filesystem, process, time, network, and
  browser effects when that separation makes invariants directly testable.
- Prefer one source of truth for route, editor, proposal, preference, terminal,
  and file state. Synchronization code must name authority and recovery rules.
- Escape for the destination sink. HTML text, attributes, JavaScript, JSON,
  URLs, selectors, Markdown, logs, and shell/process arguments are distinct
  contexts.
- Bind cleanup to the resource owner. Listeners, observers, streams, timers,
  editor objects, browser contexts, subprocesses, terminals, files, and
  temporary directories close on both success and failure.
- Prefer cohesive extensions of an existing boundary. Add an abstraction when
  it protects a real invariant, separates an effect, or serves multiple actual
  consumers—not to satisfy a pattern name.
- Preserve compatibility or define an explicit migration for durable file,
  config, CLI, wire, URL, and package contracts.

## Architecture decision test

For every material design choice, record:

1. The current owner and contract discovered from the repository.
2. The concrete failure or change pressure being addressed.
3. The smallest design that preserves the invariants above.
4. Alternatives rejected and the Prosview-specific cost of each.
5. How tests and runtime evidence will prove the boundary.
6. Any dependency, compatibility, migration, or user-authority consequence.

Reject both speculative architecture and expedient cross-layer shortcuts. The
right solution is the smallest one that makes the actual contract clear, safe,
and verifiable.
