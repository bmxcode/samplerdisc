# ADR-0002 · MIT

**Status:** accepted · 2026-08-18

## Context

The project is published for other music makers. The likely reuse is someone folding sample extraction into a DAW-side utility, a librarian tool, or a commercial sample-library restoration service — much of which is closed source.

## Decision

MIT.

## Alternatives rejected

**GPL-3.0.** Fits the ethos of preservation tooling and keeps forks public, which is a real benefit for a project whose value is accumulated format knowledge. Rejected because it blocks exactly the reuse most likely to help these libraries survive: the closed-source sampler and DAW tools that could bundle this. The format knowledge is protected better by [docs/formats/](../formats/) being thorough and public than by a license — a fork can take the code either way, and what is worth having is the documentation.

**Apache-2.0.** The patent grant is the reason to prefer it, and there is no plausible patent surface in reading twenty-year-old disc formats. Rejected as boilerplate that buys nothing here.

## Consequences

**Good.** No friction for any downstream use. Familiar to every contributor.

**Bad.** A closed-source product can ship this without contributing back. Accepted deliberately.
