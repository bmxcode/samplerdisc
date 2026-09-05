# ADR-0045 · A displaced AKAI sample is recovered by searching backward for its own name and word count, under the partition floor

**Status:** accepted · 2026-09-05

## Context

[Issue #35](https://github.com/bmxcode/samplerdisc/issues/35) records the fault [ADR-0028](0028-a-displaced-partition-is-anchored-quantised-and-floored.md) deferred: an AKAI rip can lose a run of 32 KB container blocks from *inside* a partition rather than from the blocks a partition header sits on. No header goes missing, so the partition table's declared-against-present arithmetic reads clean and the disc looks whole — while a tail run of one volume's samples has slid forward and now decodes as somebody else's audio. [ADR-0027](0027-a-payload-must-be-the-file-its-entry-placed.md) refuses these and names them: **104 samples across nine discs**, `Best Service - Alpha Dance II`'s `AC.DRUMLOOPS` (21 of 22) the clean specimen, on a disc complete by every other measure.

ADR-0028 recovered the *sibling* case — a partition header displaced — and explicitly declined this one, "a partition has a declared position to search back from and a file has only the chain its allocation map states." Issue #35 asked for three measurements before any recovery, and they are the reason this is now buildable rather than blind.

**The displacement is always a whole number of container blocks.** `AC.DRUMLOOPS` shifts one block, then two; `Library.1`'s `3084 B.BEAT6` one; `Library.3`'s one record 134. Every one is an exact multiple of `image.granularity` — 32 768 cooked bytes for these `.mdx` images — the same fault as the short images of [#25](https://github.com/bmxcode/samplerdisc/issues/25), one layer down.

**The allocation map does not notice, so there is no cheaper detector.** The map lives in the partition header, ahead of the gap and intact, and it describes the disk the rip was *made from*: every displaced file's chain is exactly `ceil(size / BLOCK_SIZE)` blocks long, agreeing with its declared size, because nothing about losing payload bytes changes the metadata in front of them. (The one chain that disagrees anywhere among the 104 is `Loop Soup`'s record whose start block lands mid-sample — a bogus start, not a gap the map caught.) #35 hoped a short chain on these volumes would be a cheap second detector; it is not, and the ADR-0027 payload-header check remains the only structure that sees this at all. That check reads a header per sample already, so nothing cheaper was on offer.

**The displacement is per file, not a per-volume constant** — `AC.DRUMLOOPS` moves by one block and then by two mid-volume, as a second gap accumulates — so a single correction per volume would be wrong. But searching backward from each declared position, in the container's unit, for a header that restates **this entry's own name and word count**, finds each recoverable file at **exactly one** position, never two, across the whole collection. Name says *which* file; the word-count identity `size == words*2 + header_len` is an independent structure confirming it. This is the "which file is this?" answer ADR-0028 said recovery would need — and it is exactly the name test ADR-0027 built and the docs called "exercised only synthetically." This deliverable exercises it on real data.

The falsifying case is the whole reason for the floor. On `AKAI.S3000.Sound.Library.3` the one refused record — `VOLUME 001`/`20  CHINA2-R` in partition 12 — has its only backward match **in partition 11**, a *different* volume's `20  CHINA2-R`, same name and same size, intact where it sits. Its bytes belong to that file; writing them under partition 12's entry would be the exact failure ADR-0027 exists to prevent. The search must not leave the file's own partition.

## Decision

**A sample whose payload at its declared position is not the file its entry placed is searched for backward, in the container's storage unit, for a header restating this entry's name and word count — and never below the start of its own partition.** Found, it is read from there; not found, it stays refused and named.

Five parts, deliberately the shape of ADR-0028 one layer down.

**Only when the declared position fails, and only for samples.** A payload that is already the file its entry placed is read where it sits — every file on a complete image, and the fast path, so a healthy disc pays nothing. Programs are not relocated: the anchor is the payload repeating the directory's name, and a program has no such field to confirm by.

**Backward from the declared position, in the container's unit.** A short image has *lost* bytes, so everything after a gap moved towards the front and nothing away from it; the real bytes sit a whole number of `image.granularity` blocks earlier. The filesystem asks the container for the unit and does not name it ([ADR-0003](0003-brand-neutral-pluggable-backends.md), ADR-0028).

**Confirmed by this entry's name and word count.** `is_placed_here` requires id 3, the valid flag, a name equal to the entry's, a plausible rate, and `size == words*2 + header_len`. Placement by the search, confirmation by two independent fields, the shape [ADR-0020](0020-read-e-iv-through-its-sample-directory.md)/[ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md)/ADR-0023/ADR-0028 all use.

**Never below the partition floor.** This is the whole safety argument and it does all the rejecting: the `Library.3` cross-partition namesake is below the floor and never examined, so it stays refused rather than recovered wrongly. Within a partition, measured across the collection, exactly one position per recovered file passes the anchor and none coincides with any other intact entry's bytes.

**A recovered sample carries its displacement.** `Extracted.displaced` is the byte distance, per file because it grows down a volume; `list` prints a recovered-count line and `batch` records it per disc. Per file rather than per partition — unlike ADR-0028's partition displacement, which was constant across a partition's thousands of files — because here it varies file to file.

The result: **102 of the 104 recover** and verify against their own headers; the collection's written samples rise by 102 and its refused-mismatch count falls from 104 to **2**. The two are named, not hidden: `Loop Soup`'s one directory record whose start block lands mid-sample (no header exists earlier to find), and `Library.3`'s `20  CHINA2-R`, whose only match is the cross-partition namesake the floor refuses. ADR-0028's loose "103 found intact" figure counted that namesake as a find; it is not a safe recovery, and this record corrects it to 102.

## Alternatives rejected

**Leave them refused (ADR-0027's conservatism).** The right answer while a recovered payload could not be told from a coincidence. It can now: name and word count give exactly one within-partition match per file and zero collisions with any intact entry, measured across the collection. Refusing readable audio that proves it is the file its entry placed, on a rule whose stated reason has been answered, is not conservatism.

**Recover by one displacement constant per volume.** Simpler, and wrong: `AC.DRUMLOOPS` displaces by one block and then two as a second gap accumulates mid-volume. Each file must confirm its own displacement, which the per-file anchor does.

**Drop the partition floor, or loosen it to the disc origin.** This is what the `Library.3` case forbids: without the floor its record's nearest match is a different volume's same-named, same-sized sample in the previous partition, and recovering it would put one sample's audio under another's name. The floor is not a cost bound that happens to be safe — it is the safety.

**Anchor on the name alone, or the word count alone.** Name alone admits the `Library.3` namesake (same name, different file); word count alone admits any same-sized sample. Together, under the floor, they are unambiguous. Both are kept.

**Recover programs too.** A program's payload does not repeat its directory name, so there is no field to confirm a relocation by — the anchor that makes this safe does not exist for them. A displaced program stays where its entry puts it; if a specimen shows this costs real files, it gets its own issue.

**Walk the allocation-map chain to place a file's blocks.** The map is in the intact header and describes the original disk, so it is blind to the gap (measured: every damaged file's chain equals its declared length). It cannot place the moved bytes, and reading a file by its map chain rather than its contiguous extent is the search ADR-0022 and ADR-0023 refused for other reasons.

**Search forward as well as backward.** A rip makes an image short, never long; every one of the 104 is displaced towards the front. Forward search would double the candidates for a fault nothing produces (ADR-0028 rejected the same for partitions).

## Consequences

**Good, and the headline.** 102 samples on nine discs that were refused as somebody else's audio are now written, each read from where its own header sits and each verified by name and word count against the directory entry that placed it. `Alpha Dance II`'s `AC.DRUMLOOPS` goes from 1 of 22 to 22 of 22.

**Good.** ADR-0027's name test finally has positives on real data — 102 of them — and is the load-bearing anchor rather than a synthetic-only check. `test_an_akai_payload_is_never_written_under_another_files_name` stops holding trivially and starts holding because the recovery respects it.

**Good.** The `declared == present` caveat #35 insisted on keeping is now backed by a recovery rather than only a refusal: a complete-looking image with an internal gap says so, in the recovered-count line, per disc.

**Bad, and stated plainly.** Two samples stay refused. `Loop Soup`'s record genuinely has no header to find; `Library.3`'s has one, and it is the wrong file's. Both are named, and the second is the standing proof that the floor is doing real work.

**Bad.** Extraction on nine discs writes 102 files that were not there before, and `--keep-originals` writes their `.s3s`/`.s1s` from the displaced offset too. Anyone who extracted those discs should do it again.

**Watch for.** A disc where two same-named, same-sized samples sit within *one* partition, one displaced onto the other. The floor does not protect against that; the word-count identity and the single-match measurement are what would, and a second match appearing where the collection shows exactly one is the signal that the anchor has weakened. The measurement is wired into the suite for that reason.

**Watch for.** `Extracted.displaced` growing meanings. It is the byte distance a sample's bytes were found from where its entry declared them, and nothing else — not an alignment, not a container fact. The container's `granularity` says what the rip lost whole numbers of; this says how many of them fell in front of one file.
