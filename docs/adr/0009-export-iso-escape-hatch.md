# ADR-0009 · `export-iso` is an escape hatch, not a convenience

**Status:** accepted · 2026-08-18

## Context

The container layer is the novel part of this project: nothing else open-source reads compressed `.mdx`. The filesystem layer is the opposite — [akaiutil](https://sourceforge.net/projects/akaiutil/) covers AKAI variants this project will not reach for a long time, and E-mu, Roland, Ensoniq and Kurzweil discs sit in the same archives with no backend here at all.

So the likely failure is precise: the container is understood, the sectors are in hand, and the filesystem inside them is one nobody has written a backend for.

## Decision

`samplerdisc export-iso <image> <out.iso>` unwraps any supported container into a flat 2048-byte-sector image, without looking at the filesystem. It is a first-class command, documented in the README, and it works whether or not any backend recognises the contents.

## Alternatives rejected

**Fail with "unrecognised filesystem".** Honest about what the tool can do. Rejected because it throws away the part that worked, and that part is the part no other tool has. A user with an E-mu `.mdx` currently has no way to get at those sectors; refusing to hand them over helps nobody.

**Auto-run akaiutil when no backend matches.** More helpful, and what a wrapper would do. Rejected: it introduces the C dependency [ADR-0001](0001-pure-python-stdlib-only.md) exists to avoid, and it silently hands data to a tool the user did not choose. Emitting the ISO and letting them pick their tool is the same benefit without the coupling.

## Consequences

**Good.** The coverage gap costs a step, not the disc. The exported ISO is the natural input to akaiutil, which makes it the mechanism for the oracle diff in testing. It is also how a contributor investigates a new filesystem: export, then explore.

**Bad.** An ISO is roughly twice the size of a compressed `.mdx`, and users need somewhere to put it.

**Watch for.** `export-iso` quietly becoming filesystem-aware — trimming, reordering, or "fixing" sectors. Its value is being a faithful unwrap of the container and nothing more.
