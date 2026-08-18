# ADR-0003 · Brand-neutral name, pluggable filesystem backends

**Status:** accepted · 2026-08-18

## Context

The project started as an AKAI tool, because all three discs to hand are AKAI and the format work was done against them. The natural name was `unakai` — following `unzip`/`unrar`, obvious on sight, free on GitHub.

Then the source archives were actually surveyed. [nnty.fun](https://nnty.fun/downloads/other/90ssamplecds/originals/) carries E-mu (Mo Phatt X, Beat Garden X, Platinum 88), Roland (L-CDX, LA Composer, orchestral), Kurzweil (Gigapack) and Ensoniq (ESI-32) discs alongside the AKAI ones, in the same containers. [archive.org retro-sample-cds](https://archive.org/download/retro-sample-cds) is mostly AKAI, with a Korg.

The layers are not equally brand-specific. Containers — `.mdx`, `.nrg`, `.bin`, `.iso` — know about compression and sector geometry and nothing about music; they are identical for an E-mu disc. So is the WAV writer, the stereo joiner, the CLI and the batch runner. Only the filesystem walker and the sample header are AKAI-specific, and they are the smaller part.

## Decision

Name the project `samplerdisc`. Structure it as a brand-neutral core — `container/`, `wav.py`, `stereo.py`, `cli.py` — with sampler knowledge confined to `fs/` and `sample/` behind a common `Backend` interface. AKAI ships first.

`container/` may not contain a manufacturer's name, constant or assumption.

## Alternatives rejected

**`unakai`, AKAI-only.** Better name for the AKAI case: shorter, funnier, self-explanatory as a command. Rejected because the rename cost is paid later and is much higher — a GitHub repo people have starred and linked, a PyPI name, a command in other people's scripts. The name would be wrong the first time an E-mu backend lands, and the survey says that is a matter of when.

**`unakai` now, rename at v2.** Defers the decision at the cost of migrating exactly the things that are painful to migrate. Rejected: the only thing saved is a slightly better name for a few months.

**Keep it AKAI-only but name it neutrally.** Honest, and cheaper today. Rejected in favour of building the backend seam now, while there is one implementation and the interface can be shaped by hindsight rather than guessed at across two.

## Consequences

**Good.** A second manufacturer is one module plus a registry entry. The interface gets designed while it is cheap to change. The name stays true.

**Bad.** A `Backend` abstraction with exactly one implementation is speculative generality, and the interface may prove wrong when the second one lands. Accepted because it is small and the alternative — retrofitting a seam through working code — is worse.

**Watch for.** Any AKAI-specific constant drifting into `container/`, particularly a sample-header check used to identify a filesystem. That is the seam leaking, and the origin probe in [ADR-0005](0005-probe-for-the-filesystem-origin.md) is where the temptation will be.
