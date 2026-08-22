# ADR-0023 · An AKAI disc's partitions come from the table it declares

**Status:** accepted · 2026-08-21 · *amended by [ADR-0028](0028-a-displaced-partition-is-anchored-quantised-and-floored.md): "a declared position with no header is skipped, never searched for" becomes "searched for backwards from the declared position, in the container's storage unit, for a header restating this partition's size, and never below the end of the partition already accepted". The refusal of a **scan** stands — and the 374 blocks below turn out to be complete stale partition headers rather than audio, which makes it firmer.*

## Context

An AKAI disc is a **disk image**. The sampler wrote a hard disk of several partitions and the CD is a copy of it, so a disc of 66 000 blocks carries nine partitions of 7680 rather than one. `AkaiBackend.volumes()` walked the partition at the resolved origin and stopped, which is [issue #22](https://github.com/bmxcode/samplerdisc/issues/22): across the 44 AKAI discs on the shelf that listed **448 volumes and 14 670 files** of the **2 154 volumes and 68 997 files** they hold.

The issue recorded partitions as tiling **at multiples of the size declared at `0x00`** — an observation across 44 discs, not a field anyone had read — and named three discs it did not fit. It also named the obvious unread candidate: the 100 u16 at `0x02` that carry the same ramp on every disc.

Both questions have answers, and neither is the one the issue expected.

**The field at `0x02` declares nothing about other partitions.** Its 196 bytes are byte-identical on every disc *and every partition* — `3333 × i`, i = 0…97 — so nothing in it varies with anything. What does vary is the pair after it: the u16 at `0xC6` is the block count at `0x00` plus 47573, and the u16 at `0xC8` is 47, on all 276 partitions measured. That is the header restating its own size, not a table of anyone else's.

**The table is at `0x4500`**, in the first partition, past the largest allocation map that fits in front of it: a u8 count, a u8 flag, that many u16 partition sizes, then the disk's total in blocks. **All 44 discs carry one, and on all 44 the sizes sum to the total.** `Loop Soup` declares nine partitions — eight of 7680 blocks and a last of 4095, totalling 65 535, which is the ceiling u16 block numbers imply.

That last entry is what tiling could not have got right. The sizes are **not all equal**: the final partition is a remainder. Tiling reproduces the same partitions everywhere both can be applied, and then invents a fourteenth on `AKAI.S3000.Sound.Library.1` at block 65 535 that the table does not declare.

The three discs the issue could not explain are explained too, and not by the filesystem. Where a declared partition has no header at its declared position, a header turns up *earlier*, and the slippage accumulates down the disc: `Library.6` by 60 blocks and then 68, `Elektra Vox` from 424 to 2888 over nine partitions. **Every displacement is a whole number of 32 KB MDX blocks**, and every one of those images is `.mdx`. They are incomplete rips, the same finding [#17](https://github.com/bmxcode/samplerdisc/issues/17) reached from inside partition 1; the full table is in [the format doc](../formats/akai-fs.md).

## Decision

**Partitions come from the table the disk declares, and the header at each declared position confirms it.**

Four parts:

**The table places them.** Each partition begins where the sizes before it end. The table is refused unless its sizes sum to its total, which is the check that tells a table from whatever else could land at a fixed offset — the two are written separately and agree on all 44 discs.

**The header confirms them.** A partition is read only where the constant field, the size echo at `0xC6` and the tail at `0xC8` all hold *and* the size the header declares is the size the table gave it. Placement and confirmation come from different structures, which is the shape [ADR-0020](0020-read-e-iv-through-its-sample-directory.md) and [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) already use: locate by one thing, confirm by another, and never place anything by arithmetic no field agrees with.

**A declared position with no header is skipped, never searched for.** Because the table gives absolute positions, one missing header costs its own partition and nothing after it — `Best Service Brass Super Section CD1` has an unwritten partition 6 and reads 7, 8 and 9 regardless.

**Block numbers stay the numbers the directory declares.** A `Volume` and a `File` carry the byte offset their blocks count from, and `read_file` adds it. Rewriting block numbers to be disc-relative would have been less plumbing and would have made every note, every allocation-map lookup and every future check speak in numbers no structure on the disc states.

Volume names repeat across partitions — nearly every one has a `VOLUME 001` — so extraction writes each volume **under its partition**: `out/partition-2/SOUP 120/`. `list` prints how many partitions the disk declares against how many the image holds.

## Alternatives rejected

**Tile at multiples of the first partition's size**, as the issue observed. Rejected on the register [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) settled: a field the disc states beats a bound inferred between structures, and here the field exists. The measurement agrees — tiling and the table place the same partitions on every disc — but the two disagree exactly where a rule is worth having: the last partition is a remainder rather than a full size, and tiling puts a fourteenth partition on `Library.1` where the disk declares thirteen.

**Chain each header's own declared size**, taking the next partition to begin where this one's `0x00` says it ends. Genuinely attractive: it is also a declared field, and measured across the collection it yields **exactly the same 2 154 volumes and 68 997 files**. Rejected because it is a chain — a missing header takes everything after it with it, since the next position is unknown — and because it is one field where the table is a statement about the disk as a whole. It has the same fourteenth-partition fault as tiling.

**Locate every partition by scanning for the header signature.** This is [ADR-0015](0015-locate-banks-by-signature.md)'s instrument and it recovers 15 006 more files, so it was measured rather than dismissed. Rejected on three counts, each sufficient. The signature is a **sawtooth waveform** — `3333 × i` as PCM — and audio reproduces it: 374 blocks of `Global Trance Mission 2` and 153 of `ProSamples vol.14` match, every one in a block the allocation map calls free. Filtering those with the file-yielding test then *loses* real partitions elsewhere, 94 volumes down to 72 on `Advanced Media Trax 3`. And what it gains comes almost entirely from short images, where the audio is displaced: 7 723 of those files are on `Kickin' Lunatic Beats 2 CD1`, the disc whose partition 1 already extracts nine samples that are not their own ([#23](https://github.com/bmxcode/samplerdisc/issues/23)). Recovering a short image's partitions is deferred to [#25](https://github.com/bmxcode/samplerdisc/issues/25), with the displacements written down.

**Walk partitions in `probe()`/`find_origin`.** Rejected: a partition is an AKAI notion and origin resolution is shared with every backend, so this would put brand knowledge in the layer [ADR-0003](0003-brand-neutral-pluggable-backends.md) keeps clear of it. `Backend.volumes(image, offset)` already means "walk the filesystem rooted here", and for AKAI the filesystem is all of its partitions. The probe still resolves exactly one origin and is not touched.

**Rewrite block numbers as disc-relative when the walk yields them.** No plumbing at all: `read_file` would keep working untouched. Rejected because it discards the only numbers the disc actually states. The allocation map is per partition and indexed by the partition's own block numbers, so the ADR-0022 notes and the chain check would both have to undo the rewrite, and a `list` line would name a block no structure on that disc mentions.

**Nest extraction under the partition only where a disc has more than one.** Backwards compatible, and rejected for making the output layout depend on the disc: a script that finds `VOLUME 001` in one place on one disc and another on the next is worse than one that moved once.

## Consequences

**Good.** The 44 AKAI discs go from 448 volumes and 14 670 files to **2 154 and 68 997**; the collection from 872 and 56 662 to **2 578 and 110 989**. Partition 1 does not move on any disc — 448 volumes and 14 670 files before and after, pinned per disc in `tests/test_discs.py`, which is the control on the origin arithmetic.

**Good.** The new files verify against a structure that did not place them. Of 44 174 samples past the first partition, **44 101 (99.83 %)** carry a payload header whose id, valid byte and name match the directory entry — the same rate as partition 1, whose 19 mismatches include #23's nine. On `Loop Soup` all 3 200 agree exactly, and that is a test.

**Good.** A short image is now a stated fact: `list` prints eleven partitions declared against one present, where before the other ten were an absence nobody could see.

**Bad.** Extraction paths change for every AKAI disc, single-partition ones included. Anyone with a script pointing at `out/VOLUME 001` needs `out/partition-1/VOLUME 001`.

**Bad, and stated plainly.** Roughly fifteen thousand files on short images stay unread, and they are readable — a search would find their partitions ([#25](https://github.com/bmxcode/samplerdisc/issues/25)). That is deliberate: the audio on those images is displaced by the missing blocks, and [#23](https://github.com/bmxcode/samplerdisc/issues/23) is the standing evidence of what displaced audio extracts as.

**Watch for.** A disc whose first partition is damaged. The table lives there, and nowhere else that has been found, so losing it drops the disc back to reading one partition — quietly, since that is also the honest fallback for a disc that declares no table.

**Watch for.** `allocation_map` now takes its block count from a header that restates it rather than from what the image can hold, so a partition the image *ends inside* gets the map for the blocks present. That is what stopped two volumes on `ProSamples vol.17` being empty and silent, and it narrows [ADR-0022](0022-a-volume-is-explained-by-the-allocation-map.md)'s "no map, no note" to a count that is absent or unvouched for.
