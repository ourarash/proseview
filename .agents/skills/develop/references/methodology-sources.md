# Methodology Sources and Adaptation Notes

These skills use established engineering workflow ideas but express them in
original, Proseview-specific language. No external skill implementation or
automation is vendored.

## obra/superpowers

Source: <https://github.com/obra/superpowers> (MIT License).

Adapted workflow ideas:

- prove behavior with a red/green/refactor cycle when a testable contract
  changes;
- investigate and state a root cause before patching a bug symptom;
- require fresh command/runtime evidence before a completion claim;
- separate specification-compliance review from engineering-quality review;
- use independent review context where available;
- evaluate review feedback technically and remediate one root cause at a time;
- exercise discipline-oriented skills with realistic pressure scenarios.

Proseview changes: repository discovery replaces fixed plans and paths; risk
lanes include manuscript preservation, local-first trust, browser/runtime
contracts, terminal/agent authority, and the repository's live E2E topology.

## jeffallan/claude-skills

Source: <https://github.com/Jeffallan/claude-skills> (MIT License).

Adapted workflow ideas:

- route work through domain-specific engineering and review specialties;
- use deep reference material only when the affected surface activates it;
- combine implementation, testing, architecture, and security perspectives for
  cross-layer work.

Proseview changes: one repository profile and a shared lane vocabulary replace a
large collection of generic framework personas.

## Agent Skills guidance

Source: <https://github.com/anthropics/skills>.

Applied authoring ideas:

- keep the main skill procedural and move detailed rubrics to references;
- make descriptions explicit enough to trigger on real requests;
- test a skill in fresh contexts, including failure and pressure scenarios;
- revise from observed behavior rather than prose review alone.

This file records provenance for maintainers. It is not required reading during
normal Proseview implementation or review runs.
