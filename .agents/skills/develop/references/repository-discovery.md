# Proseview Repository Discovery

Build a current repository profile before implementing, reviewing, or auditing.
The profile keeps the skills Proseview-specific without freezing today's paths,
commands, fixtures, feature names, or architecture into tomorrow's workflow.

## Authority order

Resolve conflicting information in this order:

1. The user's current objective, constraints, and accepted decisions.
2. Repository instructions that govern the affected path.
3. Executable contracts: current code, configuration, tests, package metadata,
   and CI behavior.
4. Current product documentation and accepted design records.
5. The stable Proseview invariants in `proseview-architecture.md`.
6. Examples in skill references.

Do not treat a filename, command, marker, version, route, fixture, selector,
theme, or module named in a skill as authoritative until the current checkout
confirms it. References describe concerns and discovery routes, not a frozen
inventory.

## Repository profile

Keep this profile in the working context; do not write it into the repository
unless the user requests documentation.

```markdown
## Repository profile
- Root, commit, branch, and worktree state:
- Governing instruction files:
- Product promises and current scope:
- Runtime, package manager, and supported environments:
- User entrypoints and public contracts:
- Architecture map by responsibility and owning symbols:
- Persistent data and write paths:
- Server/browser/process boundaries:
- UI asset and runtime-loading model:
- Test topology, markers, fixtures, and documented commands:
- CI/release/package gates:
- Generated, cached, temporary, and user-data paths:
- Concurrent or unrelated changes to preserve:
- Facts still uncertain:
```

Record where each material fact came from. Mark inferred facts as inferred.

## Discovery procedure

### 1. Resolve scope and repository state

- Resolve the actual repository root from version-control metadata instead of
  assuming the current directory is the root.
- Record the current commit, branch/detached state, status, and relevant diff.
- Locate every applicable repository instruction file from the root through
  the target path. Read the most specific instructions before acting.
- Separate user/concurrent changes from the requested change using the
  objective, status, diff, timestamps only as supporting context, and direct
  inspection. When ownership remains ambiguous, preserve the file and report
  the uncertainty.

### 2. Discover product and development contracts

- Locate current overview, contributor, roadmap, design, configuration, and
  packaging documents by searching the file inventory and references from the
  project metadata. A familiar filename is a candidate, not a guarantee.
- Extract current runtime versions, entrypoints, dependencies, optional
  dependency groups, package data, test configuration, markers, and scripts
  from machine-readable project files.
- Inspect CI workflows to learn which commands and environments are release
  gates. Reconcile CI with contributor documentation; disclose drift rather
  than silently selecting one.
- Identify the public CLI, configuration, file-format, HTTP/event, browser,
  package, and user-visible contracts affected by the task.

### 3. Build an architecture map from symbols and flows

- Inventory current source, template, asset, test, fixture, and tooling files
  with `rg --files` or the platform equivalent.
- Search for entrypoint declarations, route registration, configuration
  loading, persistent writes, serialization, template rendering, browser
  initialization, process creation, and cleanup. Record owning symbols and all
  important callers/consumers.
- Trace the task's input through validation, normalization, domain logic,
  persistence/process effects, serialization, rendering, client state, and
  user feedback. Include reverse/recovery paths.
- Discover how browser code is loaded and ordered. Do not assume modules,
  bundling, globals, or a build step.
- Discover how tests create repositories, users/homes, agents, servers,
  browsers, ports, and temporary data. Never infer isolation from a fixture
  name alone.

### 4. Derive the validation graph

- Read the current test configuration, contributor commands, CI jobs, and
  affected tests before choosing commands.
- Identify the smallest check that proves each changed invariant, the boundary
  check that proves integration, and the broad gate that detects collateral
  regressions.
- Collect or list tests before relying on assumed paths, counts, markers, or
  optional environments.
- Determine dependency-install commands only from current repository
  documentation. Ask before installing substantial or optional dependencies.
- Record a validation item as `Required`, `Conditional`, or `Not applicable`
  with its reason. A missing optional environment is evidence to report, not a
  reason to invent a replacement command.

## Change-surface lane activation

Activate lanes from discovered behavior, not file extensions alone. A single
file may activate several rows.

| Discovered surface | Lanes that normally activate | Proseview-specific probes |
|---|---|---|
| Manuscript/config parsing or writing | Domain/data fidelity; interfaces; security; reliability; tests | Non-lossy round trip, unknown fields, containment, conflict protection, recovery |
| HTTP, event, route, or serialization contract | Specification; interfaces; security; reliability; compatibility | Validation, escaping, ordering, stale state, reconnect/reload, all consumers |
| Browser structure, behavior, or styling | UI/accessibility; interfaces; security; lifecycle; performance | Keyboard/focus, safe DOM sinks, history/deep links, cleanup, themes/reflow |
| Agent, terminal, subprocess, or shell boundary | Security/trust; reliability/lifecycle; compatibility; operations | Explicit authority, argument safety, context scope, teardown, failure clarity |
| Watcher, concurrency, caching, or live reload | Reliability; performance; correctness; tests | Ordering, invalidation, idempotency, external edits, bounded resources |
| CLI, configuration, package, dependency, or CI | Interfaces/compatibility; packaging/operations; security; docs; tests | Defaults, installed behavior, offline/local-first constraints, migration |
| Analytics, highlights, sorting, or derived data | Specification; domain correctness; performance; content/UI | Determinism, empty/unknown data, honest labels, scaling, explanation |
| Test or harness-only change | Test quality; isolation; maintainability; operations | Failure sensitivity, production fidelity, cleanup, no real user data |
| Documentation-only change | Specification; content accuracy; compatibility | Executable examples, current names, no unsupported promise |

Add lanes when the traced flow crosses additional boundaries. Mark a lane not
applicable only after stating why the change cannot affect it.

## Stable versus discovered facts

Hard-code only deliberate quality policy and durable product invariants, such
as local ownership, manuscript safety, explicit AI approval, accessible core
workflows, and evidence before completion. Discover operational facts such as:

- paths, module names, function names, routes, selectors, and asset order;
- test commands, markers, counts, fixture names, ports, and browser setup;
- runtime versions, dependency groups, supported themes, and feature flags;
- CI jobs, package-data declarations, generated outputs, and roadmap files.

When a discovered fact changes during concurrent work, refresh the affected
profile section before editing or issuing a verdict.
