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

`0x02`, `0xC6` and `0xC8` all hold on all **314 partitions** read across the 44 AKAI discs, and together they are what identifies a partition header. The two size fields matter most: a block count with no echo behind it is not a partition's, which is a firmer test than anything about the image's length.

**Free blocks carry complete copies of a partition header, and a scan cannot tell them from the real thing.** 374 blocks of `AMG - Global Trance Mission 2`'s free space satisfy all three fields *and* restate a size the disk's table declares; `ProSamples vol.14` has 153 and `vol.12` 91. They are not audio that happens to fit the pattern, which is what an earlier note here said: digested, `vol.14`'s 153 are its five real partition headers plus **one 8192-byte block repeated 148 times, byte for byte**, and `Global Trance Mission 2`'s are three distinct blocks repeated 288, 58 and 19 times. Audio does not do that.

Each copy is a whole header with a volume directory that parses. `vol.14`'s holds the pristine formatted state — `VOLUME 001` … `VOLUME 100`, type 0, start block 0 — and `Global Trance Mission 2`'s names real volumes (`R+R KIT 1`, `REGGAE KIT 1`, `RAP    KIT 1`). What wrote them is not established: filler from the mastering, or headers from an earlier state of the disk. Every one is in a block the partition's own allocation map calls free.

The consequence is the same either way and stronger than the sawtooth reading was: **there is no byte test that separates these from a partition header, because they are partition headers.** A position must be placed by something the disc states — the table, with the container's lost blocks subtracted from it — and confirmed there ([ADR-0023](../adr/0023-partitions-come-from-the-table-the-disc-declares.md), [ADR-0028](../adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md)).

The size at `0x00` is what bounds the allocation map, and it is much smaller than the disc: a partition of 7680 blocks is 62.9 MB inside an image of 500 MB or more. A disc carries **several partitions** — see *More than one partition* below.

Volume entry, 16 bytes:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 12 | name, AKAI charset |
| 12 | **1** | **type** — which sampler owns the volume, or 0 |
| 13 | **1** | a separate field, zero on 43 of 44 discs |
| 14 | 2 | u16 LE start block |

**The type is a byte, and 13 is a different field.** Reading the pair as one u16 was harmless for as long as nothing used the value — `start` at 14 is unaffected, so every volume on every disc was still found — and it produced nonsense the moment anything did: the one disc that sets byte 13 reported volume types of 513, 769 and 1025, an inflation of 256 per volume.

What byte 13 is has not been established. It is zero on 4373 of the 4400 non-empty slots of the 44 discs' **first** partitions, and the exception is `OMI … Universe Of Sounds Vol.1 (Roland S-770,S-750)`, where it runs 2, 3, 4 … 28 over the disc's 27 live volumes in slot order and is 0 on the unused slot at the end — an incrementing per-volume index of some kind, on one disc, with no second specimen to check it against. Over all 314 partitions read it is zero on 31 333 of 31 400; where the other 40 are has not been looked into.

### Volume type

Counted over the **first** partitions, which is where the correspondence below was established:

| Byte | Volumes | Reading | Evidence |
|---|---|---|---|
| 1 | 338 | S1000 | no file in any of them sets the type byte's high bit |
| 3 | 9 | S3000 | 8 of 9 hold nothing but high-bit files |
| 7 | 91 | CD3000 | 57 of 91 hold nothing but high-bit files; the rest are mixed |
| 0 | 10 | not a live volume | — |

Over all 314 partitions the shape is the same at ten times the size — 1 733 type 1, 711 type 7, 107 type 3 and 35 type 0 — with every type-1 volume that holds files holding only low-bit ones, and type 7 and type 3 running 449 of 682 and 79 of 107 all-high with the rest mixed.

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

Read across all 314 partitions the figure is **85 338 of 85 355**, and the seventeen exceptions are one thing rather than a scatter: every one is a `MULTI FILE` — type `m`, all on `AKAI.S3000.Sound.Library.1` — whose chain runs exactly one block past what its size needs. A multi appears to be allocated a spare block. It is the only kind that disagrees anywhere.

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

Where the image holds no header at a position the table declares, the partition is either absent from the disc or **displaced** — moved towards the front by blocks the container lost. The two are told apart by where a header turns up, and the rule for that is in *An image can be short* below.

Across the 44 discs the table declares 384 partitions. **275 sit where the table puts them and 39 more are displaced**, holding **2 586 volumes and 86 177 files** between them, against the 448 volumes and 14 670 files of the first partitions alone.

## An image can be short

`AMG - Kickin' Lunatic Beats 2 AKAI CD1.mdx` decodes cleanly — 16 299 blocks, every one a valid DEFLATE stream emitting exactly 32 768 bytes, no stored blocks but the tail remainder — and the image it decodes to is **missing four of the disc's 32 KB blocks**. The container is faithful to the file; the file is not a complete copy of the disc.

Two structures agree on the displacement and neither knows about the other:

- the four volume directories are each 16 blocks below where the volume entry points, and the partition-1 file directories place the first gap earlier still, at 8 blocks;
- **partition 2's header sits at block `size − 16`** rather than at `size`.

131 072 bytes is exactly four MDX blocks, which is a quantity of the *container* and one the AKAI filesystem knows nothing about — that is what identifies the layer at fault. `CD2` of the same pair is short by one such block (its partition 2 is at `size − 4`), and its partition 1 happens to survive it intact.

**The partition table turns that into a measurement anyone can repeat**, and it explains the discs that looked like a different layout. Where a declared partition has no header at its declared position, searching the image finds one *earlier*, always by a whole number of 32 KB container blocks. These are the eight images short of their disc, with the displacement of every partition recovered from them, in AKAI blocks:

| Disc | Declared | Read | Displacements recovered |
|---|---:|---:|---|
| `AMG - Kickin' Lunatic Beats 2 CD2` | 9 | 8 | 4 on partitions 3–9 |
| `Audio Factory - Classical Wild Takes` | 11 | 10 | 16 on partitions 8–11 |
| `AKAI.S3000.Sound.Library.6` | 9 | 8 | 68 on partitions 3–9 |
| `AMG - Kickin' Lunatic Beats 2 CD1` | 11 | 8 | 52 on partitions 3–8, 200 on 10 |
| `AKAI.S3000.Sound.Library.5` | 9 | 6 | 12, 32, 32 on partitions 5, 7, 8 |
| `AMG - Global Trance Mission 2` | 9 | 7 | 8, 8, 32 on partitions 6, 7, 9 |
| `AKAI.S3000.Sound.Library.7` | 11 | 4 | 5508, 2028, 512 on partitions 3, 4, 5 |
| `Back In Time Rrcords - Elektra Vox` | 13 | 6 | 488, 964, 1844, 2664, 1928 on partitions 3, 5, 7, 9, 11 |

Every displacement is a multiple of 4 blocks — 32 768 bytes, one MDX block — and every one of these images is `.mdx`. They also **accumulate**: `Elektra Vox` slips by 424 blocks, then another 64, then 156, and so on down the disc, which is what a rip losing blocks here and there looks like from inside the filesystem. These are not discs laid out differently; they are incomplete rips.

The 39 recovered partitions hold **432 volumes, 17 180 files and 15 808 samples**, and 15 765 of those samples — 99.7 % — carry a payload header that agrees with the directory entry that placed it. That is the point about a gap: it removes whole blocks, so everything after it moves by a *constant*, and inside a displaced partition the directory and its audio move together and stay consistent. A displacement only breaks that agreement where the gap falls **inside** a partition read at its declared position.

**Where a search may look, and where it may not.** A header is confirmed at a found position exactly as at a declared one, and three constraints keep the search from being a scan ([ADR-0028](../adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md)):

- it walks **backwards from the position the table gives that partition**, because a short image has lost bytes and nothing moved away from the front — which also settles the index, since a header restating size N does not say which N it is;
- it steps in the **unit the container stores the disc in**, 32 768 cooked bytes for these `.mdx` images, because that is what the rip lost whole numbers of;
- it stops at the **end of the partition already accepted**, so nothing is ever found inside a partition already being read.

The last is what refuses the rest. **70 declared partitions stay unread**: 10 have no header at any position the search may look at, 29 land exactly on a partition already read, and 31 would overlap one. `Best Service - Alpha Dance I` is entirely in the third group — its one displaced partition sits four blocks inside partition 4, so the disc recovers nothing.

A missing partition is not always damage, and the two are distinguishable. On the ProSamples discs the declared partitions that are absent were never written — the CD carries only the front of a larger disk — and the nearest header-shaped block is either exactly one partition back (the previous partition's own header, seen through a size the disk repeats) or a stale copy sitting in free space, 70 blocks back on `vol.12` and 21 on `vol.14`. Both are inside a partition already read, and both are refused for that and not for being those discs.

A short image also shows up in the table's arithmetic alone: `Kickin' Lunatic Beats 2 CD1` declares eleven partitions and three of them cannot be read from this image at all, and `ProSamples vol.54` declares nine of a 63 488-block disk on a CD of 30 720 blocks — the second of those is not damage, it is a CD carrying only the front of a larger disk. Declared against read is worth printing for that reason: it names the gap without diagnosing it.

The visible consequence inside partition 1 is not only the four empty volumes. **Nine files in `13-TRACK 06` no longer hold their own audio**: everything past the first gap has slid, so their payload is mid-PCM rather than a header. They are refused and named, one line each saying which fields disagree and which entry placed them ([ADR-0027](../adr/0027-a-payload-must-be-the-file-its-entry-placed.md)). [Issue #23](https://github.com/bmxcode/samplerdisc/issues/23) proposed that check believing they were being written out; they were already being refused, with a message that said neither which test failed nor that a directory entry was involved.

The same damage appears **without a partition going missing**, which is worth stating separately because the table's arithmetic cannot see it. `Alpha Dance II` declares six partitions and holds all six, and 21 of `AC.DRUMLOOPS`'s 22 samples are displaced; `AKAI.S3000.Sound.Library.1` and `.3` are the same shape. The rip lost a run of blocks inside a partition rather than the blocks a header sat on, so it is the payload check — never the partition table — that catches it, and D38 recovers the file from its own header a whole number of container blocks earlier (*The payload repeats what the directory said* below, [ADR-0045](../adr/0045-a-displaced-sample-is-recovered-by-its-own-name-and-word-count.md)).

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

## Sample file — a header, then PCM

| Offset | Size | Meaning |
|---|---|---|
| 0 | 1 | id — `3` for a sample, `1` for a program |
| 1 | 1 | bandwidth |
| 2 | 1 | original pitch, MIDI note |
| 3 | 12 | name, AKAI charset |
| 15 | 1 | valid — a **flag byte**, `0x80` set |
| 26 | 4 | u32 LE number of sample **words** |
| 132 | 4 | u32 LE SLOCAT |
| **138** | **2** | **u16 LE sample rate** |
| **150 or 192** | … | sample data |

The name sits at offset **3**, not 4, and the valid byte at **15**, not 16. Both are off-by-one traps that produce names shifted by one character — readable enough to look like success.

Sample data is **signed 16-bit little-endian mono PCM**. That is already exactly what a WAV data chunk holds, so writing a WAV is a copy with a header in front of it, not a conversion. There is no resampling, no bit-depth change and no dithering anywhere in this project.

### The header is 150 bytes or 192, and the directory says which

**The S3000 family writes 192 and the S1000 family 150**, and the two are not distinguishable from the bytes in front of the audio — every field above sits at the same offset in both. What separates them is the **high bit of the directory entry's type byte**, the same bit that already names a kept original `.s3s` rather than `.s1s`.

Three structures agree, none of them aware of the others:

- **The type byte.** 15 352 of the 44 discs' 72 298 samples have it set and every one of them is 192; the other 56 946 are 150. No disc mixes the two rules and there is not one exception.
- **The word count.** The directory's declared size is `words × 2 + header_len` on **72 190 of 72 190** payloads readable at all — 15 314 at 192, 56 876 at 150. The 108 that fail it are the damaged ones, and every one of those also fails an identity test below.
- **The bytes.** On `AKAI.S3000.Sound.Library.2`'s `NPF E0`, offsets 150–170 are zero and 171–191 are `0a ff ff 22 a8 00 aa ff ff 00 8c ff ff 00 aa ff ff 00 88 ff ff` — the same shape on every sample of the disc, which audio is not. Waveform starts at 192.

Nine of the 44 discs are affected: `AKAI.S3000.Sound.Library.1`–`7` (4 451, 3 083, 1 989, 1 010, 971, 1 123 and 764 samples written), `East Connexion Piano` (730) and `AMG - Now CD-Rom for (AKAI)` (1 193). `Library.5`, `.6` and `.7` are much larger figures than D19 measured, because three quarters of their partitions were unread until the displaced ones were recovered.

**Getting this wrong does not fail, which is why it lasted four deliverables.** Reading a 192 at 150 yields the right frame count, a WAV that opens, and a length within 0.1 % — with 42 bytes of header in place of the attack (a burst of roughly ±20 000 lasting 0.24 ms, an audible click), the last 21 frames of the sound gone, and every loop point 21 frames out. An earlier note here said S3000 discs *may* use a 192-byte variant and advised branching on the id and valid bytes. Both halves were wrong: the variant is not conditional, and those two bytes do not carry the answer — `0x80` appears on 56 876 samples at 150 and 15 314 at 192, and the id is `3` on both. See [ADR-0027](../adr/0027-a-payload-must-be-the-file-its-entry-placed.md).

### The valid byte is a flag, not a value

`0x80` is a bit within the byte and not the byte. 29 samples on `AKAI.S3000.Sound.Library.2` carry `0x81` and two on `Library.1` carry `0x9c`, with a correct id, a name matching their directory entry exactly, a rate of 44 100 or 22 050 and a word count the declared size agrees with. What the low bits mean is not established, and there is no third combination in the collection to check a reading against.

### The payload repeats what the directory said, and the two must agree

Every sample payload restates the file's id, its valid flag and its name, and the directory entry states the name and the size independently. Where they disagree, the payload is not the file the entry placed and it is refused rather than written under that entry's name — a WAV that opens, plays, and is somebody else's audio is the worst failure this format offers ([ADR-0027](../adr/0027-a-payload-must-be-the-file-its-entry-placed.md), [issue #23](https://github.com/bmxcode/samplerdisc/issues/23)).

**104 of the 72 298 samples disagree at their declared position**, on nine discs; the other 35 have none. Almost all are a *displacement*, not damage: the run has slid forward inside its partition and the real bytes sit a whole number of container blocks earlier, carrying the file's own header — so the payload that disagrees at the declared offset is somebody else's audio, and the file itself is intact a little way back. D38 reads it from there ([ADR-0045](../adr/0045-a-displaced-sample-is-recovered-by-its-own-name-and-word-count.md); see *Recovering a sample the rip displaced* below), so **102 of the 104 recover** and only **2 stay refused**. The name test that was "zero unique catch" through D20 is now the anchor those 102 recoveries turn on: it is what says a candidate position holds *this* file, where the id and valid flag only say it holds *a* sample.

Where the 104 are, and what becomes of them:

| Disc | Displaced | Where | Recovered |
|---|---:|---|---|
| `AKAI.S3000.Sound.Library.5` | 30 | `HIT NOISE` last 17 of 20, `SURDO` last 7 of 13, `BELL TREE` last 6 of 13 | 30 |
| `Kickin' Lunatic Beats 2 CD1` | 24 | `09-TRACK 37` last 15 of 26, `13-TRACK 06` last 9 of 20 | 24 |
| `Best Service - Alpha Dance II` | 21 | `AC.DRUMLOOPS`, last 21 of 22 | 21 |
| `Best Service - Alpha Dance I` | 15 | `ATTACK BANK2`, last 15 of 18 | 15 |
| `AMG - Global Trance Mission 2` | 8 | `SYNTH     10` last 5 of 6, `AMBIENT PAD2` last 3 of 6 | 8 |
| `AKAI.S3000.Sound.Library.1` | 3 | `3084 B.BEAT6`, last 3 of 8 | 3 |
| `Audio Factory - Classical Wild Takes` | 1 | `VOLUME 002`, last of 2 | 1 |
| `AKAI.S3000.Sound.Library.3` | 1 | `VOLUME 001`, its only file | **0** |
| `AMG - Loop Soup` | 1 | `SOUP 101-103`, entry 27 of 39 | **0** |

Four more samples are refused for a corrupt rate byte with an otherwise perfect header — `EG 2MUTE` at 0 Hz, `M.VOICE A1` and `SYN 1` at 519, `HOUSE BASS` at 1280. Those *are* the files their entries placed, with one field unusable, and are counted apart; the recovery does not touch them.

**The two that do not recover are the interesting ones.** `Loop Soup`'s record's start block lands mid-sample, so there is no earlier header to find. `Library.3`'s `VOLUME 001`/`20  CHINA2-R` has one — but it is a *different* volume's `20  CHINA2-R` in the previous partition, same name and same size, intact where it sits. Its bytes belong to that file, and the recovery refuses to leave the partition rather than write them here. Both stay refused and named ([ADR-0045](../adr/0045-a-displaced-sample-is-recovered-by-its-own-name-and-word-count.md)).

**A tail run does not require a missing partition.** `Alpha Dance II` declares six partitions and holds all six; `Library.1` and `Library.3` likewise. Their damage is a run of blocks lost *inside* a partition, so no header goes missing and the table's declared-against-present arithmetic sees nothing. Declared equalling present is not a clean bill of health — which is why the payload check, and now the recovery, are the only structures that see this.

### Recovering a sample the rip displaced

A gap inside a partition removes whole container blocks, so a file after it sits that much nearer the front while its directory entry — in the intact header ahead of the gap — still points where the file was on the disk. Its real bytes are therefore a whole number of container blocks before the declared position, carrying the file's own header. The recovery searches **backward from the declared position, in the container's storage unit, for a header restating this entry's name and word count** (`size == words*2 + header_len`), and **stops at the start of the file's own partition** ([ADR-0045](../adr/0045-a-displaced-sample-is-recovered-by-its-own-name-and-word-count.md), [issue #35](https://github.com/bmxcode/samplerdisc/issues/35)).

Three measurements make this a recovery and not a scan:

- **The displacement is always a whole number of container blocks** — one block for `Alpha Dance II`'s first refused file and two for the rest, 134 for `Library.3`'s namesake, one to a few elsewhere.
- **The allocation map does not notice, so there is no cheaper detector.** The map is in the intact header and describes the disk the rip was made from: every displaced file's chain is still exactly as long as its declared size demands. A short chain on these volumes would have been a cheaper check than reading a payload header per sample; there is none. The payload check is the only structure that sees the gap.
- **Exactly one position per recovered file passes the anchor**, and none coincides with any other intact entry's bytes — which is why the partition floor, not a match count, is the safety. `Library.3` is the standing proof: its only match is the cross-partition namesake, below the floor, refused.

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
