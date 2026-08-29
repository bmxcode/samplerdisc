# ADR-0032 · Read the E-IV `FORM/E4B0` bank and its embedded `E3S1` samples

**Status:** accepted · 2026-08-29 · extends [ADR-0020](0020-read-e-iv-through-its-sample-directory.md)

## Context

[ADR-0020](0020-read-e-iv-through-its-sample-directory.md) reads an E-IV bank through a chained `E3S1` sample directory, binding a bank only where the per-disc allocation fit — `base == 512 × (unit × start + bias) + 8` — predicts an address holding a **confirmed flat chain**. A bank with no such chain is listed with `no sample directory found for this bank; listed only`, and ADR-0020 recorded the leading guess for why: preset-only banks, "the likely explanation, and it is not established."

[Issue #44](https://github.com/bmxcode/samplerdisc/issues/44) measured the scale once twelve E-IV discs were in hand. It is not one disc's 100 of 230 — it is **170 banks of 788**, across all twelve. Every one is named by the folder directory, declares a non-zero length, and reads nothing. The issue ruled out the bank's own start block (the magic distribution at it is identical to the read banks') and the `E3S1` chain surplus (the discs that read completely show the same surplus), and pointed the investigation elsewhere.

**Measured, the discriminator is the bank's storage format, and it is clean on every one of the 170.** At each unread bank's predicted base sits `FORM … E4B0` — a native E-IV IFF bank file — where a read bank holds a raw `E3S1` record. The **same** per-disc fit predicts both: the `FORM` tag sits at exactly `512 × (unit × start + bias)`, the block-aligned address a flat bank's first record prefix occupies. Only the interior differs. A `FORM/E4B0` carries its samples as **`E3S1` IFF chunks** — the four-byte tag, a big-endian u32 size, then an ordinary 92-byte sample record and its PCM — beside `TOC1`, `E4Ma` and `E4P1` (preset) chunks. The flat chained-directory reader never walks an IFF container, so this audio was listed empty.

It is not the preset-only hypothesis. The samples are physically present and are new: across the three named specimens every embedded chunk body parses as a real record (174 of 174 on `eiv-3d`, 132 of 132 on `eiv-studio-vol2`, 987 of 987 on `eiv-studio`), with plausible names and valid rates, and **not one duplicates** a sample already read from a flat bank. The chunk body is exactly the record the flat path already reads at `EIV_RECORD_OFFSET`, and the chunk's big-endian size is exactly the directory's big-endian length seen one layer in — so the record, pointer, loop and stereo path applies unchanged.

## Decision

**When a bank's predicted base holds a `FORM/E4B0` container rather than a flat chain, walk its IFF chunks and read each `E3S1` chunk body as a sample record.**

Three things follow, each measured.

**The chunk size is the record length.** The record's own `+34` is unusable on E-IV, exactly as ADR-0020 found for the flat banks; the IFF chunk header states the length, as the directory does for a flat bank. `size − 92` is the PCM, rejected unless it is a positive even number of bytes.

**The declared FORM size bounds where a chunk may begin, not where its body may end.** On every reference disc the declared size understates the container by 4 to 12 bytes: the last `E3S1` chunk's body ends just past it, and only the next region's bytes follow — bytes that decode as an enormous chunk. So the walk lets a chunk header sit up to the declared end and bounds the body by the image alone; the garbage past the declared end is never walked into, and a chunk whose body is not wholly present is dropped (tail damage degrades, it does not crash — [ADR-0012](0012-a-probe-must-confirm-a-file.md)).

**A `FORM/E4B0` with no `E3S1` chunk is genuinely sample-free and gets a note of its own.** These are the `Credits` text banks and a few preset/globals banks (four `E-mu Systems 96` entries on `eiv-studio`). The note is `the bank holds presets or text and no samples; listed only` — distinct from the generic `no sample directory` wording, which is now wrong for a bank that has no flat directory yet carries audio. The [ADR-0012](0012-a-probe-must-confirm-a-file.md) invariant holds: no bank is silent.

The fit rests on the flat sample banks and the FORM banks ride on it, so this places nothing that ADR-0020's guards did not already place. A bank binds one way or the other, never both.

## Alternatives rejected

**Keep the note and treat the 170 as preset-only.** The state ADR-0020 left, and the issue's own leading guess. Rejected on measurement: the banks carry ~2 017 samples of embedded `E3S1` audio, none of it a duplicate of what is already read. `E4P1` presets are unread and stay unread — that is ConvertWithMoss's job ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)) — but the samples beside them are ours to give.

**Segment the IFF by physical adjacency, scanning for `E3S1` tags inside the FORM.** The obvious reading, and the same trap ADR-0020 rejected one layer up: a scan through a multi-megabyte payload finds `E3S1` byte sequences inside PCM. Walking the chunk sizes from the FORM header is a *declared* relation and self-terminating, and it steps over the `TOC1`/`E4Ma`/`E4P1` chunks to reach the samples rather than guessing at them.

**Trust the declared FORM size as a hard bound on the body.** The first implementation did, and lost 91 samples on `eiv-studio` alone: the size understates the container and the last chunk of most banks overruns it by a few bytes. Rejected on measurement — the size is a begin-bound, not an end-bound.

**Add an `EMU4` backend for the FORM banks.** Rejected under [ADR-0014](0014-one-backend-per-on-disc-format.md), for the same reason ADR-0020 gave. It is one on-disc format: same `EMU3` magic, same header, same folder and bank directories, and the fit that places a FORM bank is the fit that places a flat one. Only the bank interior branches, and it already branched.

## Consequences

**Good.** 162 of the 170 banks read: ~2 017 samples across the twelve discs. `eiv-studio` gains 987 (2 822 → 3 809), `eiv-vitous` 24, and three discs are pinned for the first time by this recovery — including `eiv-phatt-cd1`, whose one previously-empty bank alone yields 692.

**Good.** `eiv-analogia` is the control. It has no FORM bank, so its samples, loops, stereo count and every payload digest are byte-for-byte what D23/D18 left — the check that the new path did not disturb the old. The four EIII/ESI reference discs are likewise unmoved.

**Good.** The eight residual banks say what they are. The four `Credits` text banks and four `E-mu Systems 96` preset banks carry a FORM with no sample chunk, and their note now names that rather than a directory they never had.

**Bad.** Opening an E-IV disc now reads a FORM header at each unbound bank's predicted base, on top of the ADR-0020 passes. It runs only where a bank has no flat chain, so a disc whose banks are all flat pays nothing.

**Watch for.** A FORM whose declared size overstates rather than understates, or whose chunks are padded on a boundary these discs do not use. The walk would stop early and list the bank short — visible as fewer samples than the FORM holds, not as wrong audio. And `E4P1` presets remain unread: a bank that is genuinely preset-only is correctly noted, but the key ranges and envelopes inside it are not this project's to decode ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)).
