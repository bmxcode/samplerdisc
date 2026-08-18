# ADR-0004 · Detect containers by signature, not by extension

**Status:** accepted · 2026-08-18

## Context

These files reach users through archive.org collections, personal FTP mirrors and forum re-uploads, renamed freely along the way. The same disc appears as `.bin`, `.img` and `.iso`. `.img` is used for both raw 2352-byte and cooked 2048-byte images, which are not interchangeable. `.cdr` and `.tao` turn up holding raw CD sectors. A `.cue` naming its `.bin` is frequently missing, because the `.bin` got copied on its own.

Every container in scope has a strong signature: `MEDIA DESCRIPTOR` at byte 0 for MDX, `NER5`/`NERO` at a fixed distance from EOF for NRG, and the 12-byte sync pattern `00 FF×10 00` at byte 0 for raw CD sectors.

## Decision

Dispatch on content. Sniff the head, sniff the tail, then fall back to extension only to disambiguate what the signatures could not.

## Alternatives rejected

**Dispatch on extension, with `--format` to override.** Simpler, and every user knows what their file is called. Rejected because the failure is silent in the direction that matters: a cooked image named `.bin` gets de-interleaved as if raw, producing sectors assembled from the wrong 2048 bytes. That does not error — it yields a filesystem that almost parses, and samples that are noise. Asking users to diagnose that with a flag is asking them to know the answer before they have a question.

## Consequences

**Good.** Renamed and mis-named files work. `.tao` and `.cdr` come free without being enumerated anywhere.

**Bad.** Detection reads from both ends of the file before doing anything, and signature checks have to be ordered so a weaker one cannot shadow a stronger.

**Watch for.** Checking the NRG v1 magic before v2. A v1 read at `EOF-12` finds nothing, but a v2 file has 8 bytes where v1 has 4, so the wrong order produces a plausible huge offset rather than a miss.
