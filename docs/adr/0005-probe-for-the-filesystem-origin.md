# ADR-0005 · Probe for the filesystem origin; never assume byte 0

**Status:** accepted · 2026-08-18

## Context

Two of the three reference discs put the AKAI partition header at offset 0 of the cooked sector stream, and an early draft of this design assumed that was simply where filesystems live.

`loopsoup` disproved it. The Nero image includes the **150-sector pregap**, so bytes `0 … 307199` are zeros and the filesystem begins at 307 200. The `DAOX` chunk records the track start; the arithmetic closes exactly (`264703 + 150 = 264853`, `× 2048 = 542418944`, the recorded track end).

The failure mode is what makes this worth an ADR. A parser assuming byte 0 reads 307 200 zeros, finds no volume directory, and reports **an empty disc — not an error**. There is no traceback to follow and nothing that looks wrong except an absence.

Hybrid discs make the same point differently: some sampler CDs carry an ISO 9660 track ahead of the sampler partition, so a valid filesystem at byte 0 is not necessarily the one you want.

## Decision

The container reports where its track starts. The image layer then **probes** for a filesystem from that offset, scanning sectors and asking each registered backend's `probe()` whether it recognises what it sees. The resolved origin is explicit, logged, and asserted in tests.

## Alternatives rejected

**Trust the container's track start and stop there.** Correct for `loopsoup` and cheap. Rejected because it does not cover hybrid discs, and because a `.bin` with no `.cue` has no authoritative track start at all — sniffing is needed anyway, so having one mechanism is better than two.

**Scan for the AKAI partition signature specifically.** Simplest thing that works today. Rejected: it puts a manufacturer's constant in `container/`, which is exactly the seam [ADR-0003](0003-brand-neutral-pluggable-backends.md) exists to keep clean. Asking the backend registry costs nothing and keeps brand knowledge in `fs/`.

## Consequences

**Good.** Pregaps, hybrid discs and multi-track images all work through one mechanism. A new backend gets origin detection for free by implementing `probe()`.

**Bad.** Startup does a bounded scan rather than a single read. Backends must supply a `probe()` cheap enough to run at every candidate offset and specific enough not to false-positive on zeros or audio.

**Watch for.** A probe loose enough to match arbitrary data. It would resolve an origin confidently and wrongly, which is the same silent failure this decision exists to prevent.
