# ADR-0012 · A probe must confirm a file, not a plausible directory

**Status:** accepted · 2026-08-18

## Context

[ADR-0005](0005-probe-for-the-filesystem-origin.md) closes with a warning: *"A probe loose enough to match arbitrary data. It would resolve an origin confidently and wrongly, which is the same silent failure this decision exists to prevent."*

That happened. Two discs with no AKAI content on them were reported as AKAI:

| Disc | Byte 0 | Reported |
|---|---|---|
| `E-MU - EIIIX Sound Library Vol. 2` | `EMU3` | `akai at offset 3465216` |
| `OMI Universe of Sounds Sonic Images Vol. 1 (SampleCell)` | `ER` | `akai at offset 5496832` |

Both are false. Walking either yields volumes named `010000000000` and `0D0 07070D0D` with **zero files in every one**.

`AkaiBackend.probe` tested the volume directory for structure — names in the charset range, start blocks ordered and in range — and returned `True` on two such entries without ever opening one. Mid-disc sample data satisfies that more readily than it appears: twelve bytes below 41 is not a demanding test when the data is quiet PCM, and "ordered and increasing" is satisfied by any rising pair.

The helper that asks the right question already existed. `_directory_looks_real` opens the volume and looks for a file, and it was wired into one branch only — the single-volume case, added because a lone volume could not be confirmed by ordering alone. The multi-volume path, which is nearly every disc, never called it.

The failure mode is the one this project keeps meeting. Nothing raises. `samplerdisc info` prints a confident offset, `list` prints volumes, and the volumes are empty. It reads as a disc with nothing on it rather than as a tool that is wrong, and it makes every triage result untrustworthy — which is how it was found, while using triage output to decide which discs were which format.

## Decision

A probe must confirm a file, not a plausible directory.

`probe()` keeps its structural tests and then requires that **the first allocated volume yields at least one entry passing the same tests `_files` applies** — plausible name, valid type byte, non-zero size, non-zero start block. `_directory_looks_real` is applied in all cases rather than only when exactly one volume is found, and its entry test is aligned with the walk's, type byte included.

The general invariant, asserted across whatever collection a contributor has: **no backend may claim a disc and then produce zero files.** Resolving to `None` stays a legitimate outcome — that is what [ADR-0009](0009-export-iso-escape-hatch.md) is for. Claiming and walking out empty is not.

## Alternatives rejected

**Tighten the volume-header heuristic instead** — require more entries, narrow the charset, bound the start blocks harder. Keeps the probe to a single cheap read. Rejected because it is the same kind of evidence, only more of it: structural plausibility of a directory, which is exactly what arbitrary data supplies. It would raise the bar without changing what is being measured, and the next disc that clears it fails the same silent way.

**Score candidate offsets and take the best match.** Handles hybrid discs and would rank a real partition above a coincidental one. Rejected as a larger change than the evidence supports, and because "best" is still a plausibility judgement — a disc with no AKAI content would win its own ranking. A yes/no question that opens the volume is both cheaper and more decisive.

**Have `probe()` accept if *any* volume yields a file**, not just the first. More forgiving of a disc whose first volume is damaged. Rejected as unvalidated: the first-volume rule was measured across the full local collection, and widening it re-opens the door for a false positive to slip in through some later volume. Better to keep the tested rule, and let a disc that needs the looser one arrive first.

## Consequences

**Good.** The two false positives resolve to `None`. All 22 genuine AKAI discs in the local collection still resolve at offset 0 — including `OMI … (Roland S-770,S-750)`, which is an AKAI disc mislabelled by the archive and reads 28 volumes and 636 samples. A whole-collection sweep before and after showed exactly two changes and no others.

**Good.** The invariant generalises. It is stated as a disc-backed test that holds for any collection, not a table of expected offsets, so every backend added later inherits it — and `probe()` and the walk can no longer drift apart about what a valid entry is.

**Bad, and worth watching.** This is a tightening, so its risk runs opposite to the bug it fixes: a genuine AKAI disc whose first allocated volume is empty, deleted-out or damaged would now be rejected where it was previously accepted. None of the 22 behaves that way, and the probe reads 8 entries rather than 1 to see past a run of deletions, but the disc-backed suite is what will catch it if such a disc arrives.

**Note on the type-byte alignment.** Making the probe check the type byte was *not* forced by the evidence — the pre-existing `_directory_looks_real`, applied generally, rejects both observed false positives on its own. It is included because probe and walk disagreeing about a valid entry is the thing that produces an empty volume, which is the symptom here; aligning them removes the class rather than the instance. Recorded as a judgement call so a future reader does not mistake it for something the discs demanded.

**Watch for.** Any new backend whose `probe()` tests only structure. `EMU3`'s four-byte magic and Roland's `S770 MR25A` are far stronger signatures than AKAI's volume table, but a magic plus a pointer is still structure — the pointer should be followed and the thing it points at confirmed.
