# AKAI S1000/S3000 filesystem

The filesystem AKAI's S1000, S1100, S2000, S3000, S3200 and CD3000 samplers wrote onto hard disks and CD-ROMs. It is not ISO 9660 and predates any expectation of being read by a computer.

Verified identically across all three reference discs — `s3000-lib1`, `black2black` and `loopsoup` — which is good evidence the layout below is the format rather than one disc's quirk.

Allocation unit is a **block of 8192 bytes**, four cooked sectors. All block numbers below are **relative to the partition start**, not the file start. On `loopsoup` the partition begins at byte 307 200, so block *n* is at `307200 + n × 8192`.

## Character set

Names are not ASCII. Each byte is an index into:

```
"0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-."
```

so `0`–`9` are the digits, **`10` is space**, `11`–`36` are `A`–`Z`, then `#`, `+`, `-`, `.`. Names are fixed-width and padded with the space index, which means trailing spaces are normal and must be stripped before a name becomes a filename.

Getting index 10 wrong is the classic failure and it is not obvious: `KICKIN B0-F1` decodes as `KICKIN9B0-F1`, which looks like a plausible sample name rather than a bug.

## Partition header — block 0

| Offset | Contents |
|---|---|
| `0x00` | u16 LE, **partition size in blocks** — 3840 to 7680 across the 44 discs measured |
| `0x02` | 196 bytes of constant, `3333 × i` as u16 LE for i = 0…97. Byte-identical on every disc and every partition; nothing is known to read it |
| `0xC6` | u16 LE, **the size at `0x00` plus 47573** — the header restating its own size |
| `0xC8` | u16 LE, 47 on every header measured. Unexplained |
| `0xCA` | **volume directory** — 100 entries of 16 bytes |
| `0x70A` | **block allocation map** — one u16 per block, as many as `0x00` declares |
| `0x4500` | **partition table** — the disk's own list of its partitions, in the first partition only |

`0x02`, `0xC6` and `0xC8` all hold on all **275 partitions** of the 44 AKAI discs, and together they are what identifies a partition header. The two size fields matter most: a block count with no echo behind it is not a partition's, which is a firmer test than anything about the image's length.

**The pattern at `0x02` is a rising sawtooth, and sample data reproduces it.** As 16-bit PCM, `3333 × i` is a saw wave, so audio does match it — 374 blocks of one disc's free space carry a complete header prefix, every one in a block the allocation map calls free. That is why a partition header is *confirmed* where the table says one is, and never scanned for ([ADR-0023](../adr/0023-partitions-come-from-the-table-the-disc-declares.md)).

The size at `0x00` is what bounds the allocation map, and it is much smaller than the disc: a partition of 7680 blocks is 62.9 MB inside an image of 500 MB or more. A disc carries **several partitions** — see *More than one partition* below.

Volume entry, 16 bytes:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 12 | name, AKAI charset |
| 12 | **1** | **type** — which sampler owns the volume, or 0 |
| 13 | **1** | a separate field, zero on 43 of 44 discs |
| 14 | 2 | u16 LE start block |

**The type is a byte, and 13 is a different field.** Reading the pair as one u16 was harmless for as long as nothing used the value — `start` at 14 is unaffected, so every volume on every disc was still found — and it produced nonsense the moment anything did: the one disc that sets byte 13 reported volume types of 513, 769 and 1025, an inflation of 256 per volume.

What byte 13 is has not been established. It is zero on 4373 of the 4400 non-empty slots across the collection. The exception is `OMI … Universe Of Sounds Vol.1 (Roland S-770,S-750)`, where it runs 2, 3, 4 … 28 over the disc's 27 live volumes in slot order and is 0 on the unused slot at the end — an incrementing per-volume index of some kind, on one disc, with no second specimen to check it against.

### Volume type

| Byte | Volumes | Reading | Evidence |
|---|---|---|---|
| 1 | 338 | S1000 | no file in any of them sets the type byte's high bit |
| 3 | 9 | S3000 | 8 of 9 hold nothing but high-bit files |
| 7 | 91 | CD3000 | 57 of 91 hold nothing but high-bit files; the rest are mixed |
| 0 | 10 | not a live volume | — |

The generations line up with the high bit on the *file* type byte, which is the same signal that names a kept original `.s3p` rather than `.s1p`. A volume can hold files of both generations, so the correspondence is a strong tendency and not a rule.

**Type 0 is not an allocation flag, and must not be used as one.** Six of the ten type-0 volumes hold nothing, and the other **four hold 63 files between them** — real audio on `Big Bang` and ProSamples `vol.01`, `vol.19` and `vol.24`. Rejecting type 0 is a one-line change that silently discards all of it. What separates the two groups is the allocation map, not the type.

## Block allocation map

At `0x70A`, immediately after the volume directory's hundred slots: **one u16 per block**, as many as the partition declares at `0x00`. This is the partition's own record of what every block holds, and it is the field that answers questions the volume entry cannot.

| Code | Meaning |
|---|---|
| `0x0000` | free |
| `0x0001`–`0x3FFF` | the next block of a chain |
| `0x4000` | a volume directory block |
| `0x8000` | seen 14 times on one disc, never under a volume; unidentified |
| `0xC000` | last block of a chain |

A file's extent is the chain from its start block to `0xC000`. **That is what verifies the map rather than merely making it plausible**: the chain length and the file size are stated by two different structures, and across all 44 AKAI discs they agree for **14 607 of 14 607 files** in the first partitions — exactly, with no disc disagreeing anywhere.

Read across all 275 partitions the figure is **68 267 of 68 284**, and the seventeen exceptions are one thing rather than a scatter: every one is a `MULTI FILE` — type `m`, all on `AKAI.S3000.Sound.Library.1` — whose chain runs exactly one block past what its size needs. A multi appears to be allocated a spare block. It is the only kind that disagrees anywhere.

The exclusion behind that figure is itself the finding. Five volumes sit on blocks the map calls free, and their files' chains are gone with them; four of those five hold 63 files that read perfectly. These are **deleted volumes**: the blocks went back to the free list, and because the medium is a mastered CD-ROM nothing ever reused them, so the directory and the audio are still there to be read. They are listed with their files like any other volume.

`0x4000` marks a volume directory on the S1000 discs, where a directory is a single standalone block — 338 of 338 type-1 volumes. On S3000 and CD3000 discs the directory block is instead the head of a chain running into the volume, so it reads as a chain link. **The code at a volume's start block therefore says different things on different generations, and only `0x0000` means the same thing everywhere.**

## Telling a live volume from a slot that was never used

AKAI pre-formats all 100 slots with a default name like `VOLUME 008`, so an unused slot is a named entry rather than an empty one. Most point at block 0 and are trivially rejected. **Three discs keep a stale start block from formatting instead**, and those point at a real block holding something that is not a directory — which reads as an empty volume, not as an error.

The volume entry cannot settle it: name, type and start block look the same either way. The allocation map can, and each of its answers is a different fact about the disc:

| Map code at the start block | What the disc is saying | Seen on |
|---|---|---|
| chain link or `0xC000` | the block holds file data, so no directory was ever there | `Advance Orchestra` ×4, OMI ×1 |
| `0x0000` | the block belongs to nothing | `Kickin' Lunatic Beats 2 CD1` `VOLUME 018` |
| `0x4000` | a directory belongs here — so the *image* is what lacks one | `Kickin' Lunatic Beats 2 CD1` ×4 |

The last row is the one worth dwelling on, because it points away from the filesystem entirely. On `Kickin' Lunatic Beats 2 CD1` the map says all four blocks are volume directories and the image holds none at them — and the four directories are in fact present, each exactly **16 blocks (131 072 bytes) earlier** than the volume entry points. That image is short of the disc it was made from; see *An image can be short* below.

Note the asymmetry: a chain link is positive evidence that the slot was never used, while `0x0000` is only the absence of evidence — a free block under an empty volume is an unused slot on one disc and a damaged image on another, and the map cannot tell them apart. Report what the map says and stop there ([ADR-0022](../adr/0022-a-volume-is-explained-by-the-allocation-map.md)).

## More than one partition

An AKAI disc is a **disk image**: a disk of several partitions laid end to end, mastered onto a CD. `Advance Orchestra` declares 7680 blocks of an image of 66 616, and the rest is eight more partitions.

**The disk declares them.** At `0x4500` of the first partition — block 2, past the largest allocation map that fits in front of it — is the partition table:

| Offset | Contents |
|---|---|
| `+0x00` | u8, the **number of partitions** |
| `+0x01` | u8, 0 on 37 discs and 1 on the other 7. Unexplained |
| `+0x02` | that many u16 LE **partition sizes**, in blocks, in order |
| `+2n+2` | u16 LE, the **total blocks on the disk** |

All 44 AKAI discs carry one, and on all 44 the sizes sum to the total. `Loop Soup` reads `09 00 | 1e00 ×8 | 0fff | ffff`: nine partitions, eight of 7680 blocks and a last one of 4095, totalling 65 535.

That last entry is why the table is worth reading rather than multiplying the first size out. **The sizes are not all equal**: the final partition is a remainder, and the total never exceeded **65 535 blocks** — 512 MB, the ceiling u16 block numbers imply — across every disc measured. Tiling agrees with the table wherever both can be applied, but on `AKAI.S3000.Sound.Library.1` it invents a fourteenth partition at block 65 535 that the table does not declare and that holds nothing.

A partition's own blocks are numbered from **its** start, so the same block number means a different place in each one, and a file read with the partition term dropped returns another partition's audio rather than an error.

Where the image holds no header at a position the table declares, it is **skipped and not searched for**. On the discs where that happens the header turns up displaced by a whole number of the container's 32 KB blocks — the image is short of the disc it was made from, which is the fault below and not a filesystem to go hunting through.

Across the 44 discs the table declares 384 partitions and 275 are present in the images, holding **2 154 volumes and 68 997 files**, against the 448 volumes and 14 670 files of the first partitions alone.

## An image can be short

`AMG - Kickin' Lunatic Beats 2 AKAI CD1.mdx` decodes cleanly — 16 299 blocks, every one a valid DEFLATE stream emitting exactly 32 768 bytes, no stored blocks but the tail remainder — and the image it decodes to is **missing four of the disc's 32 KB blocks**. The container is faithful to the file; the file is not a complete copy of the disc.

Two structures agree on the displacement and neither knows about the other:

- the four volume directories are each 16 blocks below where the volume entry points, and the partition-1 file directories place the first gap earlier still, at 8 blocks;
- **partition 2's header sits at block `size − 16`** rather than at `size`.

131 072 bytes is exactly four MDX blocks, which is a quantity of the *container* and one the AKAI filesystem knows nothing about — that is what identifies the layer at fault. `CD2` of the same pair is short by one such block (its partition 2 is at `size − 4`), and its partition 1 happens to survive it intact.

**The partition table turns that into a measurement anyone can repeat**, and it explains the three discs that looked like a different layout. Where a declared partition has no header at its declared position, searching the image finds one *earlier*, always by a whole number of 32 KB container blocks:

| Disc | Declared | Present | Displacement, first to last |
|---|---|---|---|
| `AMG - Kickin' Lunatic Beats 2 CD2` | 9 | 1 | 4 blocks, on all eight |
| `Best Service - Alpha Dance I` | 5 | 4 | 4 |
| `AKAI.S3000.Sound.Library.5` | 9 | 3 | 8 … 36 |
| `AMG - Global Trance Mission 2` | 9 | 4 | 8 … 32 |
| `Audio Factory - Classical Wild Takes` | 11 | 6 | 16, on all five |
| `AMG - Kickin' Lunatic Beats 2 CD1` | 11 | 1 | 16 … 336 |
| `AKAI.S3000.Sound.Library.6` | 9 | 1 | 60 … 68 |
| `Back In Time Rrcords - Elektra Vox` | 13 | 1 | 424 … 2888 |
| `AKAI.S3000.Sound.Library.7` | 11 | 1 | 1456 … 7288 |

Every displacement is a multiple of 4 blocks — 32 768 bytes, one MDX block — and every one of these images is `.mdx`. They also **accumulate**: `Elektra Vox` slips by 424 blocks, then another 64, then 156, and so on down the disc, which is what a rip losing blocks here and there looks like from inside the filesystem. These are not discs laid out differently; they are incomplete rips. Recovering their partitions would mean locating headers by search, which [ADR-0023](../adr/0023-partitions-come-from-the-table-the-disc-declares.md) declines to do and [issue #25](https://github.com/bmxcode/samplerdisc/issues/25) records.

A missing partition is not always damage, and the two are distinguishable: on the ProSamples discs the declared partitions that are absent have **no header anywhere near** them, because the CD carries only the front of a larger disk or the mastering never wrote them. Displacement is the tell, not absence.

A short image also shows up in the table's arithmetic alone: `Kickin' Lunatic Beats 2 CD1` declares eleven partitions where the image holds one, and `ProSamples vol.54` declares nine of a 63 488-block disk on a CD of 30 720 blocks — the second of those is not damage, it is a CD carrying only the front of a larger disk. Declared against present is worth printing for that reason: it names the gap without diagnosing it.

The visible consequence inside partition 1 is not only the four empty volumes. **Nine files in `13-TRACK 06` extract audio that is not theirs**: their payload header no longer matches the name the directory gives them, because everything past the first gap has slid. A payload whose header disagrees with its directory entry is a cheap check that would catch this and is not made anywhere yet — [issue #23](https://github.com/bmxcode/samplerdisc/issues/23).

Observed volume names, useful as a smoke test that charset and offsets are both right:

| Disc | Volumes | Count |
|---|---|---|
| `black2black` | `KICKIN C1-A1`, `KICKIN B1-F2`, `KICKIN G2-C3`, `KICKIN D3-G3` | 9 |
| `s3000-lib1` | `3001 G.PF 2`, `3012 E.PF 1`, `3018 STACK P`, `3028 E.PF 2` | 14 |
| `loopsoup` | `SOUP 101-103`, `SOUP 104-105`, `SOUP 106-109`, `SOUP 110-112` | 7 |

### How the charset was confirmed

Two candidate tables fit the byte values, differing in whether index 0 is `'0'` or `' '`. Both decode every name to something that *looks* plausible, which is why this is worth writing down rather than re-deriving.

Three pieces of evidence settle it on the table above:

- **The letters only spell words one way.** `SOUP`, `KICKIN` and `G.PF` come out as `TPVQ`, `LJDLJO` and `H/QG` under the alternative. Since letters run from index 11, immediately after `10 = space` and the ten digits, fixing the letters fixes the digits.
- **`loopsoup`'s volumes are contiguous**: `101-103`, `104-105`, `106-109`, `110-112`, `113-114`, `115-117` — no gaps across six volumes.
- **The numbers are round.** `s3000-lib1` starts at `3001`, which is what an S3000 library's catalogue numbering should look like. The alternative reads it as `4112`.

An early hand decode of `black2black` using the other table produced `KICKIN B0-F1` — a full step out on every key range, and entirely believable. If a name looks *almost* right, suspect this table before suspecting the offsets.

**512 MB is the disk, not the partition.** Block numbers are u16, so a disk cannot exceed 65 536 blocks, and none of the 44 discs declares a total above 65 535. A single *partition* runs 3840 to 7680 blocks, 31 to 63 MB, and cannot grow much past that while the table stays at its fixed `0x4500`: the allocation map of a 7680-block partition already ends at `0x430A`, 502 bytes short of it.

## What a probe must confirm

The volume directory above is not sufficient evidence that a disc is AKAI. Arbitrary data satisfies its structural tests more often than it looks: twelve bytes in the charset range, a type word, and a start block that happens to be larger than the last one. Two non-AKAI discs matched on that alone — `E-MU - EIIIX Sound Library Vol. 2`, which carries `EMU3` at byte 0, and `OMI Universe of Sounds Sonic Images Vol. 1 (SampleCell)`, which carries `ER` — and were reported as AKAI at offsets 3 465 216 and 5 496 832 respectively.

Neither reported an error. Each produced volumes with names like `010000000000` and `0D0 07070D0D`, and **zero files in every one**, because a directory that merely decodes plausibly is one the file walk then rejects entry by entry.

So recognising the filesystem takes two steps, and the second is load-bearing: the volume entries must decode and be ordered, **and then the first allocated volume must yield a file that passes the same tests `_files` applies** — name, type byte, non-zero size, non-zero start block. The type byte is what does most of the work, because it is the field arbitrary data is least likely to land on: an unallocated volume pointing at `0x01` filler gives a plausible name, a size of `0x010101` and a start block of `0x0101`, and only `chr(0x01)` not being one of `p s d x m q t` gives it away.

Where the probe and the walk disagree about what a valid entry is, the symptom is a volume containing nothing — which reads as an empty disc, not as a wrong answer. That is why they share the test rather than each having their own. See [ADR-0012](../adr/0012-a-probe-must-confirm-a-file.md).

## Volume directory — 24-byte file entries

At the volume's start block, entries of 24 bytes:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 12 | name, AKAI charset |
| 12 | 4 | padding, `0x20 0x20 0x20 0x20` |
| 16 | 1 | type |
| 17 | 3 | u24 LE size in bytes |
| 20 | 2 | u16 LE start block |
| 22 | 2 | tag |

**The type byte is ASCII**, with S3000 discs setting the high bit: `0x73` and `0xF3` are both `'s'`. **Mask with `0x7F`, never `0x0F`** — the low nibble cannot distinguish `'d'` (`0x64`) from `'t'` (`0x74`), so a nibble mask silently merges two file types.

| Letter | Byte | Meaning | Evidence |
|---|---|---|---|
| `p` | `0x70` / `0xF0` | Program | payload id byte is `1` |
| `s` | `0x73` / `0xF3` | Sample | payload id byte is `3`, valid flag `0x80` |
| `d` | `0x64` | Drum settings | named `DRUM INPUTS`, 162 bytes, on two discs |
| `x` | `0x78` | Effects | named `EFFECTS FILE`, 7312 bytes |

Only `p` and `s` are confirmed from payload contents; `d` and `x` are inferred from consistent filenames and sizes across discs. Types beyond these are reported as `type-<letter>` rather than guessed at.

Programs hold key ranges and envelopes, not audio. They are listed and skipped by the WAV path, but `--keep-originals` writes them out verbatim, since a WAV cannot carry what they hold and the disc is the only copy.

The generation is readable from the same byte: the high bit is set on S3000-family discs and clear on S1000 ones, which is what names a kept original `.s3p`/`.s3s` rather than `.s1p`/`.s1s`. `s3000-lib1` sets it; `black2black` and `loopsoup` do not.

## Sample file — 150-byte header, then PCM

| Offset | Size | Meaning |
|---|---|---|
| 0 | 1 | id — `3` for a sample, `1` for a program |
| 1 | 1 | bandwidth |
| 2 | 1 | original pitch, MIDI note |
| 3 | 12 | name, AKAI charset |
| 15 | 1 | valid — `0x80` |
| 26 | 4 | u32 LE number of sample **words** |
| 132 | 4 | u32 LE SLOCAT |
| **138** | **2** | **u16 LE sample rate** |
| 150 | … | sample data |

The name sits at offset **3**, not 4, and the valid byte at **15**, not 16. Both are off-by-one traps that produce names shifted by one character — readable enough to look like success.

Sample data is **signed 16-bit little-endian mono PCM**. That is already exactly what a WAV data chunk holds, so writing a WAV is a copy with a header in front of it, not a conversion. There is no resampling, no bit-depth change and no dithering anywhere in this project.

S3000 discs may use a 192-byte header variant. Branch on the id and valid bytes rather than assuming 150.

## Where a directory ends

Two bounds, both learned from discs that broke without them.

**A volume's file directory is exactly one 8192-byte block** — 341 entries of 24 bytes. Reading further walks into the next block, which is file data, and produces "files" assembled from audio.

**An entry ends the directory when its type byte is not a valid letter.** The set seen on real discs is `p s d x m q t` (`q` and `t` appear once each and are unidentified). This matters because an unallocated volume can point at a block of `0x01` filler, and every 24 bytes of that decodes to a plausible name — `101010101010` — so without the type check one bogus volume yields hundreds of files. A cleared type byte, `0x00`, is a **deleted** file: the name survives, the type does not, and the blocks return to the free list as `0xFF`. Deleted entries are skipped rather than ending the walk, since a deletion mid-directory must not truncate what follows.

## Loops and tuning

Eight 12-byte loop records follow the play markers at offset **38**. Only the first `payload[16]` of them are active.

| Offset in record | Size | Meaning |
|---|---|---|
| 0 | 4 | u32 loop **end**, in words |
| 4 | 2 | loop length, fractional part (16.16 fixed point) |
| 6 | 2 | loop length, whole part, in words |
| 10 | 2 | dwell time |

**There is no loop start field.** Start is `end - length`, which is the trap: derive it from the *declared* end before clamping the end to the audio actually present. Clamping first drags the start earlier by however far the end overshot, silently retuning the loop rather than shortening it. On the reference discs 28 of 380 loops declare an end a few words past a payload that is marginally shorter than its header claims, so this path is exercised in practice, not hypothetically.

Dwell `9999` means *hold* — loop for as long as the note sounds. Any other value is a timed dwell, which a WAV `smpl` loop cannot express, so those are not written.

Pitch offset in cents is a signed byte at offset **21**.

Loop coverage on the references: 380 of 687 samples loop, essentially all of them in the piano library and none in the drum-loop discs — which is what you would expect.

## Stereo

Stereo is stored as two mono files whose names end `-L` and `-R`. The sampler paired them at load time; nothing in the filesystem records the relationship. Pairing is therefore a name heuristic, which is why the joined stereo file is written *in addition to* the mono originals rather than replacing them ([ADR-0007](../adr/0007-emit-mono-and-stereo.md)).

## Verified constants

`black2black`, first volume at block 3, file `MOVIN 105 -L` at block 5:

| Quantity | Value |
|---|---|
| Sample rate | 44 100 |
| Sample words | ~439 000 |
| Declared file size | 878 230 |
| Header length | 150 |
| Original pitch | 60 (C3) |

**Sample rate is per sample, not per disc.** An early note here claimed all three references were 44 100 Hz throughout; extracting them proved otherwise. Never assume a disc-wide rate.

| Disc | Samples | Rates |
|---|---|---|
| `black2black` | 77 | 44100 |
| `loopsoup` | 233 (+1 unreadable) | 44100 |
| `s3000-lib1` | 377 | 44100 ×229, 22050 ×132, 33075 ×9, 29400 ×5, 48000 ×2 |

The odd values are real: `33075` is ¾ of 44 100 and `29400` is ⅔, which is how these samplers traded bandwidth for memory. They are not corruption and must not be rounded to something tidier — the WAV carries whatever the header says.

`loopsoup`'s single unreadable entry is a directory record whose start block lands mid-sample rather than on a header. That is ordinary tail damage, and skipping it is the designed behaviour.
