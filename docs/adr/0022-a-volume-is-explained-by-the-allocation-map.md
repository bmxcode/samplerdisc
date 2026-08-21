# ADR-0022 · An AKAI volume's emptiness is explained by the partition's allocation map

**Status:** accepted · 2026-08-21 · *amended by [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md): "no map, no note" now turns on the header restating its block count, rather than on the count fitting the image, so a partition the image ends inside keeps the map for the blocks it holds.*

## Context

[ADR-0012](0012-a-probe-must-confirm-a-file.md) states the invariant this project keeps returning to: **no backend may claim a disc and then produce zero files.** It was asserted per disc, which is the weaker half of what it says. Asserted per *volume* it is the check that would have caught the E-mu index banks of [#15](https://github.com/bmxcode/samplerdisc/issues/15) years earlier — those discs always had some bank with records in it, so a per-disc form could never see them.

Of 79 images in the local collection and 71 claimed by a backend, exactly three fail the per-volume form, all AKAI, ten volumes between them. They are two different faults ([#16](https://github.com/bmxcode/samplerdisc/issues/16), [#17](https://github.com/bmxcode/samplerdisc/issues/17)) and from the volume entry they are indistinguishable: a plausible name, a start block inside the image, and nothing at that block the file walk will take.

AKAI pre-formats all 100 volume slots with a default name like `VOLUME 008`, so an unused slot is a *named* entry rather than an empty one. `volumes()` rejected the ones pointing at block 0 and `probe()`'s docstring claimed that was the whole story. It is not: three discs keep a stale start block from formatting, pointing at a real block that holds something else.

The obvious discriminators were measured first and all of them cost real data or fail to separate the cases.

**The type byte is not an allocation flag.** All six unused slots are type 0 — and so are four volumes that hold **63 files** between them, on `Big Bang` and ProSamples `vol.01`, `vol.19` and `vol.24`. Rejecting type 0 is one line and discards all 63.

**Whether the directory parses is a plausibility test, and the format doc already warns about the trap it walks into.** It rejects three of `Advance Orchestra`'s four slots and misses the fourth, which points at `0x01` filler decoding to the perfectly plausible name `101010101010`.

What settled it is a structure that was sitting unread in the partition header. At `0x70A`, immediately after the volume directory's hundred slots, is a **block allocation map**: one u16 per block, as many as the partition declares at `0x00`. It is verified, not merely plausible — a file's chain length and the size its directory entry declares are stated by two different structures, and across all 44 AKAI discs they agree for **14 607 of 14 607 files**, exactly.

The five volumes excluded from that count are themselves a finding. They sit on blocks the map calls free and their chains are gone, yet four of them hold readable directories and real audio: they are **deleted** volumes, on mastered CD-ROM that never reused the blocks. They are the 63 files above.

Read against the map, the ten empty volumes are three different situations:

| Map code at the start block | The disc is saying | Volumes |
|---|---|---|
| chain link or `0xC000` | the block holds file data | `Advance Orchestra` ×4, OMI ×1 |
| `0x0000` | the block belongs to nothing | `Kickin' Lunatic Beats 2 CD1` `VOLUME 018` |
| `0x4000` | a directory belongs here | `Kickin' Lunatic Beats 2 CD1` ×4 |

The third row is not a filesystem fault at all, and finding that out is what #17 asked for. The map says those four blocks are volume directories; the image has none at them; and the four directories are present in the image, each exactly **16 blocks earlier** than the volume entry points. Partition 2's header is 16 blocks low by the same amount, which is a second structure agreeing that knows nothing of the first. 131 072 bytes is four MDX blocks — a quantity of the container, which the AKAI filesystem has no notion of. **That image is short of the disc it was made from by four 32 KB blocks**, and the container decoded every block it does contain correctly.

## Decision

**A volume that lists no files is explained by the partition's allocation map, in the disc's own words, and is never dropped on the strength of one.**

Three parts:

**The map explains; it does not gate.** Every named slot with a non-zero start block is still listed and still walked. Where the walk finds files, the map is not consulted. Where it finds none, the map's code for that block becomes the volume's `note`, which is what ADR-0012's invariant tests for. Nothing is filtered out, so no disc's volume or file count moves: 872 volumes and 56 662 files across the collection, before and after, unchanged to the number.

**The note reports and does not diagnose.** Each branch states what the map declares about the block and stops. A free block under an empty volume is an unused slot on one disc and a damaged image on another, and the map cannot tell them apart — so it says the block is free and leaves it there.

**No map, no note.** A partition whose declared block count is absent or absurd yields no map, and a volume that is empty then gets nothing. Emitting a note as a fallback would explain away precisely the case the invariant exists to catch.

The invariant in `tests/test_discs.py` moves to its per-volume form at the same time, since this is what unblocks it.

## Alternatives rejected

**Reject volumes whose type byte is 0.** One line, and it removes all six unused slots. Rejected on measurement: it also removes four volumes carrying 63 files. The byte says which sampler owns a volume — 1 is S1000, 3 S3000, 7 CD3000, and the correspondence holds against the high bit on the file type byte — and 0 means the sampler will not load it, which is not the same as there being nothing there. On read-only media a deleted volume's audio outlives its deletion.

**Require the volume's first directory entry to be readable.** No new structure needed. Rejected as a plausibility test of exactly the kind ADR-0012 exists to refuse, and it fails on the specimen: `VOLUME 016` on `Advance Orchestra` points at `0x01` filler whose every 24 bytes decode to `101010101010`, which is the trap the format doc already warns about for file entries. It would also be judging a volume by how convincing its bytes look rather than by anything the disc states — the ADR-0021 lesson, one layer down.

**Use the map as an allocation flag: list a volume only where the code is `0x4000`.** The tempting reading, and it is wrong in both directions. It drops the four deleted volumes and their 63 files, and it drops **every volume on every S3000 and CD3000 disc** — 100 of them — because there a directory block is the head of a chain running into the volume rather than a standalone block, so it reads as a chain link. `0x4000` means "volume directory" on the S1000 discs only. `0x0000` is the sole code that means the same thing on all four generations, and it means "the disc is not accounting for this block", which is a reason to explain a volume and not a reason to hide it.

**Recover the four directories that are 16 blocks low.** They are right there, they parse, and the volumes would extract. Rejected: nothing on the disc declares that displacement — it would be inferred by searching backwards for a block that looks like a directory, which is how a sixth directory-shaped block at 6387 belonging to no volume also turns up. It is the arithmetic-where-no-header-agrees that [ADR-0015](0015-locate-banks-by-signature.md) refused and [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) upheld. The displacement is also not constant across the image — it is 8 blocks earlier in the disc and 16 later — so a single correction would be wrong somewhere. The honest answer to a short image is to say it is short and re-rip the disc.

**Report the four as damage in the note.** Nearly the same wording, and it claims more than the map can support. The map says a directory belongs at the block; that the image is short is a conclusion drawn from the MDX block size and partition 2's placement, neither of which the filesystem layer knows. The note states the disagreement; the analysis lives here and in the format doc.

## Consequences

**Good.** All ten volumes are explained, the per-volume invariant holds across all 79 images, and no count moves anywhere. The three discs go from listing empty volumes silently to naming the block and what the disc says is in it.

**Good.** The map is now available for more than notes, and it is the strongest verification this filesystem has offered so far — 14 607 of 14 607 file extents confirmed against an independent structure. `tests/test_discs.py` asserts it per disc, so a container that starts decoding an AKAI image wrongly now has something to fail against rather than presenting as a disc with less on it.

**Good.** #17's two candidate readings were both wrong, and settling it produced two findings that outlive the issue: partitions tile at multiples of the declared size and only the first is read ([#22](https://github.com/bmxcode/samplerdisc/issues/22)), and a payload header that disagrees with its directory entry is an unmade check that would have caught this image's damage ([#23](https://github.com/bmxcode/samplerdisc/issues/23)).

**Bad, and stated plainly.** `Kickin' Lunatic Beats 2 CD1` yields 669 files and **nine of them are wrong** — everything in `13-TRACK 06` past the first gap extracts audio belonging to a different sample. This change does not fix that and does not detect it; it explains the four volumes the same damage emptied. Anyone who has extracted that disc should treat its last volume with suspicion.

**Watch for.** A disc whose partition header is damaged: no map, no notes, and an empty volume there fails the invariant with nothing to say. That is the designed behaviour — visible rather than explained away — but the failure will name the disc and not the reason.

**Watch for.** The `0x8000` code. It appears 14 times on one disc and never under a volume, so it has no reading here and falls to a note that names the code without interpreting it.
