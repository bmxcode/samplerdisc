# ADR-0007 · Emit the mono originals and the joined stereo file

**Status:** accepted · 2026-08-18

## Context

AKAI samplers have no stereo sample type. A stereo sound is two mono files whose names end `-L` and `-R`, paired by the sampler at load time. `black2black` is full of them: `MOVIN 105 -L` / `MOVIN 105 -R`, `SWG-T2-100-L` / `SWG-T2-100-R`.

Nothing in the filesystem records the pairing. It exists only in the names, so reconstructing stereo is a heuristic — and names are 12 fixed-width characters, truncated and padded, which is exactly the situation where a heuristic quietly picks up a false pair.

## Decision

Write both. Every sample file produces a mono WAV in `<out>/<volume>/`. Detected `-L`/`-R` pairs additionally produce a joined stereo WAV in `<out>/<volume>/stereo/`.

## Alternatives rejected

**Join into stereo and drop the mono halves.** The cleanest library, and what a user wants for the common case. Rejected because it makes a heuristic destructive: a wrong pairing silently produces a stereo file with two unrelated sounds in it, and the originals needed to notice and fix that are gone. The user finds out in a DAW, weeks later.

**Mono only, faithful to the disc.** Provably lossless and the simplest thing to defend. Rejected as offloading a tedious, mechanical job — pairing hundreds of files by name — onto every user, to avoid a risk that keeping the originals already removes.

## Consequences

**Good.** Nothing is lost, the common case is convenient, and a mis-pairing is recoverable because both inputs are still on disk.

**Bad.** Roughly 1.5× the output for a stereo-heavy disc.

**Watch for.** Silent pairing of files that differ in sample rate or length. Rates must match to pair; differing lengths pad the shorter side with silence rather than truncating, and log.
