# ADR-0029 · An E-mu record is closed by the channel it declares

**Status:** accepted · 2026-08-24

## Context

[Issue #39](https://github.com/bmxcode/samplerdisc/issues/39): three EIIIX/ESI discs new to the collection each claim a bank, return no files and give no reason. Twelve banks across `emu-classics`, `vintage` and `ditto-drums` — ten on `ditto-drums` alone. That is the [ADR-0012](0012-a-probe-must-confirm-a-file.md) signature, and none of them is the case [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) already explains: every one declares a non-zero sample area, so `0x34` has nothing to say about any of them.

The cause is one field read as something it is not, and it reaches a long way past those three discs.

`+34` carried two names in this module — `OFF_SAMPLE_END_R` and `OFF_SAMPLE_RECORD_LEN` — and the walk took the record's extent from it unconditionally. **It is the right channel's end pointer.** It closes the record only where the right-hand set is what describes the record's audio, and on 10 274 of the 15 272 EIII/ESI records across seven discs the left-hand set is. Four ways it goes wrong, each of them a whole bank or a whole disc:

| Shape | What the right-hand set holds | What the old walk did |
|---|---|---|
| **mirror-92** | `start_R = 0`, `end_R = end_L − 92` — the same channel written from the payload's start instead of the record's | extent **92 bytes short**: 2 127 records on `esi32-gm`, 3 965 on `protozoa`, 7 005 in all |
| **zeroed** | `start_R = end_R = 0` | extent of 2, shorter than the header, so the record is rejected outright — 872 records, and nine of `ditto-drums`'s ten silent banks |
| **fixed frame** | `start_R = 92 + F`, `end_R = 92 + 2F − 2` for a constant allocation frame `F` — 1 MiB on `emu-classics`, 2 MiB on `eiiix-1` | extent past the whole bank region, so the record is dropped as unreadable — `Vox Haunt      X`'s 14, and 95 records in all |
| **right-declared** | `start_R = 92` with the left set not opening the audio — `start_L = 0` on 1 371 of them | invisible: the walk's signature is `92` at `+22`, so it never looks. All of `vintage`'s `Juno Synths`, and **1 429 records** including 353 on `esi32-gm` and 607 on `protozoa` that were never listed |

The last one is the sharpest, because [formats/emu3.md](../formats/emu3.md) already recorded it. *"Either set can be the single one — 542 records on `eiv-studio` … declare their one channel on the **right**, with the left zeroed"*, and *"Read the set whose start is 92 and use it."* That rule was applied to picking a loop and to nothing else. The EIII walk both **located** and **sized** a record from the left-hand pointer alone.

The mirror-92 shape is the answer to a question [docs/README.md](../README.md) had open since D17: *"`esi32-gm` and `protozoa` declare a longer extent than their record length gives … Either the reader is 90 bytes short on those samples or the extent field means something else."* It is the reader, by 92 bytes, and the splice test could not settle it because the splice test was being asked the wrong question.

Two measurements settle it, and neither is the pointer block arguing with itself.

**The stride to the next record.** `end_L + 2` equals the distance to the next record on 2 093 of `esi32-gm`'s records where `end_R + 2` equals it on 30.

**The bank header's own run length — a different field, in a different structure.** ADR-0021 measured that a bank's last record ends exactly at `0x30 + 74 + 0x34` on 72 banks and *"exactly 92 bytes — one sample header — short of it on 19 more"*, and recorded the second population as a loose fit. It is not a loose fit; it is this bug, seen from the bank header. Under the corrected extent it disappears:

| Disc | banks with records | last record ends exactly at the run's end, now | before |
|---|---:|---:|---:|
| `esi32-gm` | 7 | **7** | 2 |
| `protozoa` | 15 | **15** | 0 |
| `eiiix-1` | 44 | **39** | 35 |
| `eiiix-2` | 44 | **39** | 37 |
| `emu-classics` | 19 | **16** | 8 |
| `vintage` | 13 | **13** | 4 |
| `ditto-drums` | 44 | **44** | 0 |
| **total** | **186** | **173** | **86** |

Not one bank on any disc is left in the "92 bytes short" bucket. The reference bank the format doc pins says the same thing on its own: `8M GeneralMidi X` now yields **531 records totalling 8 248 316 bytes**, which is its declared run to the byte, where it previously yielded 452 records and 7 345 200 bytes inside a run of 8 248 316 that nothing filled.

## Decision

**A record's extent is closed by the end pointer of the set that opens its audio, and a record is found by either set opening it.**

Three parts, all in `fs/emu3.py`:

**The signature is `92` at `+22` or at `+26`.** Whichever set opens the audio identifies the record; the two anchors are deduplicated by address and the result is yielded in address order, so which anchor found a record cannot change what is written.

**The extent is `end + 2` of the set whose start is 92** — the larger of the two where both do, which is what the stride follows on every disc measured.

**Except on a confirmed two-channel record, where it is `end_R + 2`** and covers both blocks. Stated from the pointers alone: `start_L == 92`, `start_R == end_L + 2`, and `end_R − start_R == end_L − start_L`. That is algebraically [ADR-0026](0026-the-record-declares-the-channel-count.md)'s three conditions, without reference to the payload size — which matters, because the payload size is what is being computed. `sample/emu3.py`'s `_is_block_split` is the same statement given the payload; the two must agree, and the per-disc stereo counts in the disc-backed suite are what holds them together.

## What the evidence says about the audio

The extent decides how much audio each sample is, so the counts moving is not by itself a reason to believe them. Two independent things say the new audio is right.

**The loops splice.** 838 of `esi32-gm`'s loops and 1 082 of `protozoa`'s are newly admitted — they are exactly the loops [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) refused because the declared end ran past the payload, and with the corrected extent they fit **without being clamped**, which is the move that record showed destroys a loop. Scored by the shape and join tests of [formats/emu3.md](../formats/emu3.md), with its controls — a wrong start at the same end, a 64-frame floor, a 15 % RMS floor at both ends:

| Disc | group | scored | shape *r* | control | join | seamless | control seamless |
|---|---|---:|---:|---:|---:|---:|---:|
| `esi32-gm` | loop newly admitted | 838 | **+0.87** | +0.01 | 1.25 | 87 % | 36 % |
| `esi32-gm` | record newly found | 130 | **+0.90** | −0.03 | 1.36 | 80 % | 29 % |
| `protozoa` | loop already produced | 905 | +0.85 | +0.02 | 1.35 | 83 % | 38 % |
| `protozoa` | loop newly admitted | 1 082 | **+0.82** | −0.01 | 1.07 | 90 % | 32 % |
| `protozoa` | record newly found | 330 | **+0.77** | −0.06 | 0.90 | 87 % | 34 % |
| `eiiix-1` | loop already produced | 413 | +0.96 | +0.02 | 1.03 | 90 % | 36 % |
| `eiiix-1` | record newly found | 133 | **+0.99** | −0.10 | 0.84 | 94 % | 23 % |
| `vintage` | record newly found | 250 | **+0.94** | −0.03 | 1.50 | 85 % | 23 % |

The newly admitted loops score with the loops this project already shipped, against a control at zero. The **records newly found** — the right-declared and zeroed-right-set ones — score the same way, which is the answer to the obvious worry about widening a signature that scans through megabytes of audio: a false hit inside PCM does not carry a loop that splices.

**`protozoa`'s trombones resolve.** [ADR-0026](0026-the-record-declares-the-channel-count.md) identified six records whose *"first half is byte for byte the whole of a one-channel record of the same name in another bank"* — `Trom B2`, 16 756 bytes inside a 33 512-byte payload, with nothing on the disc matching the second half. With the extent taken from the left channel, `Proteus1PresetsX`'s `Trom B2` is 16 764 bytes and is **byte-identical to `Vintage PresetsX`'s and `Vintage InstrmtX`'s**, as are `Trom E3`, `Trom C5`, `Trom D4` and `Trom G4`. The unexplained second half was never part of the record.

That has a consequence for ADR-0026 worth stating plainly. Its gate's third condition — `end_L + 2 == start_R` — caught 65 records across three discs that declared a two-channel shape and were not stereo. Under the corrected extent that population is **zero on all ten discs**: those records only ever looked like a split because they were sized at twice their length. The condition stays, because it is what makes the two-channel test above exact and because a gate is not removed for going quiet, but it is now an unexercised gate and that is recorded rather than glossed.

## Alternatives rejected

**Fall back to `end_L` only where `end_R` yields no usable extent.** The minimal fix. It closes #39 and moves none of the four pinned baselines. Rejected: it is a rule that says *use whichever number works*, which is the kind of thing this project's format docs exist to replace. It leaves 6 092 records on `esi32-gm` and `protozoa` 92 bytes short, it cannot explain the bank-run fit, and it would have to be undone the first time a record's wrong extent happened to be usable.

**Take `max(end_L, end_R) + 2` unconditionally.** Simpler than the rule adopted and right on three of the four shapes. Rejected on the fixed-frame shape: there `end_R` names the far end of a 1 MiB or 2 MiB allocation frame, is larger than `end_L`, and has nothing to do with this record. It also loses the two-channel case's meaning — it would get the right number for the wrong reason, and the reason is what a later reader needs.

**Widen the signature and leave the extent alone.** Fixes `vintage` and nothing else: nine of `ditto-drums`'s ten banks stay silent, `Vox Haunt      X` stays silent, and the 92-byte shortfall stays.

**Bound the extent by the next record found instead of by the pointers.** Attractive because the stride is the evidence. Rejected: records are *found, not chained* on these discs and the runs have gaps, so the next hit is not the next record — the format doc records that as the reason the walk is a scan in the first place. Using it to size a record would make the last record of every run unbounded and would put a measurement in place of a declaration.

**Fix the whole-extent loop guard at the same time.** `ditto-drums` writes a loop spanning the entire sample on 934 of its 948 records, starting at frame 6 rather than frame 0, and `sample/emu3.py` only refuses a whole-extent loop that starts at exactly 0. Rejected as a separate change: the same pattern is already shipping on `eiiix-1` (460) and `eiiix-2` (320) and predates this record, so folding it in would move the loop counts for two unrelated reasons at once and make neither attributable. Filed instead.

## Consequences

**Good.** All twelve banks of #39 yield files, and the only volumes left empty on the three discs are index banks and the sampler's own code banks, both of which already carry their note. `ditto-drums` goes from 74 samples to **948**.

**Good.** The three E-IV discs are **byte-identical** across the change — 449, 2 822 and 828, same digests. They size a record from their own big-endian sample directory and never read `+34` ([ADR-0020](0020-read-e-iv-through-its-sample-directory.md)), so they are the control that says the shared parts were not disturbed.

**Good.** Payload overlaps into the following record fall rather than rise — 439 to 238 on `eiiix-1`, 236 to 188 on `eiiix-2` — and the newly found right-declared records land in the gaps between existing records rather than inside them: 0 of 353 on `esi32-gm`, 0 of 607 on `protozoa`, 1 of 18 on `eiiix-1`.

**Bad, and the headline.** All four EIII/ESI reference discs move, and every pinned payload digest with them. `esi32-gm` 2 265 → **2 635** samples and 107 → **1 778** loops; `protozoa` 5 852 → **6 595** and 1 689 → **5 244**; `eiiix-1` 1 189 → **1 248**; `eiiix-2` 1 333 → **1 337**. **Anyone who extracted an EIII or ESI disc before this should do it again**: on `esi32-gm` and `protozoa` most samples were 46 frames short at the end, and on every disc some samples were missing entirely. This is the same shape of consequence ADR-0021 took, for the same reason — the old number was wrong and nothing asserted the right one.

**Bad.** Two pinned discs turned out to share a file size with another image in the collection — `emu-classics` with `Vol. 03 – Orchestral`, `eiv-studio` with `Producer Series Vol. 2 – More Studio Essentials` — which the disc suite's size-based pin treats as one disc filed twice. A whole publisher's series arriving at once is exactly when that assumption breaks. The pin now falls back to a digest of the image's first megabyte where two share a size, which keeps it a property of the disc rather than of its filename ([ADR-0004](0004-detect-by-signature.md)) and leaves every other pin untouched.

**Watch for.** A fifth shape of right-hand set. The rule refuses a record where *neither* set opens the audio at 92, which is a silent drop of exactly the kind this record exists to remove — it will present as a bank yielding fewer records than its run declares, and the bank-run test above is what would catch it.
