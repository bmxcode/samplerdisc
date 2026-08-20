# Roland `S770 MR25A`

The filesystem Roland wrote on CD-ROMs for the S-770, S-750 and S-760. It is *not* the S-550 format — `Roland LCD1` opens `* ROLAND S-550 *` and shares no magic, no addressing scheme and no directory record with this one ([ADR-0014](../adr/0014-one-backend-per-on-disc-format.md)).

Verified against **nine discs across every system-disk lineage the archives hold** — Ver. 1.04, 1.06, 2.19, 2.21, 2.25 and the S-760's 2.23Y and 2.24s. Every constant below holds on all nine unless it says otherwise.

Four are local and read end to end:

| Short name | File | Size | System disk |
|---|---|---|---|
| `lcdp05` | `Roland - LCDP05 Solo Strings.iso` | 130 344 960 | Ver. 2.19 |
| `edirol-brass` | `Edirol - Brass Section vol.1 - Solos (Roland Sxx CD-ROM).iso` | 162 271 232 | Ver. 1.06 |
| `northstar` | `NorthStar - Global Instruments - Volume 1 (S7xx).iso` | 296 032 256 | Ver. 2.21 |
| `amg-now` | `AMG - Now CD-ROM (Roland).iso` | 681 140 224 | Ver. 2.25 |
| `l-cdx-01` | `Roland - L-CDX-01 - Rhythm Section Instruments (Roland Sxx CD-ROM).iso` | 629 149 696 | **S-760, Ver. 2.23Y** |

Four more were checked by range-fetching four regions each — the header, the sample directory at block 1644, the sample parameter record at block 4780, and the allocation-table window covering the first sample's chain — from `archive.org/details/archive-oldschoolscds`:

| Short name | Size | System disk | Samples |
|---|---|---|---|
| `l-cdp02` | 125 829 120 | **Ver. 1.04** — the oldest lineage | 812 |
| `l-cdx-02` | 629 454 848 | **S-760, Ver. 2.23Y** | 2 605 |
| `l-cdx-03a` | 629 149 696 | S-760, Ver. 2.23Y | 1 969 |
| `l-cdx-03b` | 629 149 696 | **S-760, Ver. 2.24s** | 2 038 |

On all four: the sample directory sits at block 1644 with every entry of the first 16 tagged `0x44`, the parameter record at block 4780 index 0 is the same object as directory entry 0, its cluster count agrees with the directory's, the FAT chain from the declared start cluster is exactly that long, and `ceil(2 × end_frames / 9216)` equals it. **The S-760 lineage is the same format at every level, not merely at the header** — which was the last place a second format could have hidden under an identical signature, and it does not.

Addressing is in **512-byte blocks**, not the 2048-byte cooked sector. That ratio of four is where an off-by-four hides.

## Probe on the magic and nothing else

`S770 MR25A` at **byte 4**. Not byte 0 — the first four bytes are zero.

The free-text field at `0x20` is a trap. It reads `SYS-772 HardDisk Sys Ver. N.NN` on most discs and `S-760 System Disk    Ver.2.23Y` on `L-CDX-02`, so **a probe keyed on `SYS-772` would silently drop the entire L-CDX series** — four large libraries whose format is identical underneath.

## Header

| Offset | Size | Meaning | `lcdp05` |
|---|---|---|---|
| `0x04` | 10 | `"S770 MR25A"` | — |
| `0x20` | 31 | free text, **varies; never probe on it** | `SYS-772 HardDisk Sys Ver. 2.19` |
| `0x40` | 32 | `"       Copyright   Roland      "` | — |
| `0x100` | 16 | volume label, `ID<n>:<12-char name>` | `ID2:Solo Strngs ` |
| `0x110` | 4 | u32 LE, filesystem size in 512-blocks | 253 952 |
| `0x114` | 2 | u16 LE, **volume count** | 13 |
| `0x116` | 2 | u16 LE, **performance count** | 53 |
| `0x118` | 2 | u16 LE, **patch count** | 200 |
| `0x11A` | 2 | u16 LE, **partial count** | 1 169 |
| `0x11C` | 2 | u16 LE, **sample count** | 890 |
| `0x11E` | … | `0xFF` filler to `0x200` | — |

The five counts are what makes this filesystem cheap to read: **a directory is read to its declared count, never walked to a terminator.** That removes the entire directory-overrun failure class — the one that `protozoa`'s `0x42` filler produced on `EMU3` ([emu3.md](emu3.md)) — because there is no terminator to mistake filler for.

| Disc | volumes | performances | patches | partials | **samples** |
|---|---|---|---|---|---|
| `lcdp05` | 13 | 53 | 200 | 1 169 | **890** |
| `edirol-brass` | 20 | 46 | 253 | 1 232 | **1 016** |
| `northstar` | 32 | 32 | 255 | 1 722 | **1 284** |
| `amg-now` | 78 | 107 | 828 | 2 169 | **1 230** |

`0x110` is *not* derivable from the disc size and does not divide evenly by the cluster size on any of the local four. It is a partition size, useful as a bound on the highest legal cluster and nothing more.

It does, however, have a ceiling, and the ceiling closes: **`amg-now` and all four L-CDX discs declare exactly 1 184 980 blocks** despite spanning 629–681 MB of physical media, and `5548 + 65 524 × 18 = 1 184 980` exactly. That is the format filling its u16 allocation table — roughly 604 MB of sample data — and it confirms from arithmetic what the block map only implied from adjacency: the table at sector 257 runs the full 256 blocks to the volume directory, 65 536 entries. No disc measured comes close to using it; the highest cluster seen anywhere is 42 194, on `amg-now`.

## The block map is fixed

There is no pointer chasing above the sample layer. Every base below sits at the same 512-block on all four discs, and each region's capacity is exactly the distance to the next.

| Block | Sector | Region | Blocks | Record | Entries |
|---|---|---|---|---|---|
| 0 | 0 | header | — | — | — |
| 1028 | 257 | allocation table | 256 | u16 LE | 65 536 clusters |
| 1284 | 321 | volume directory (`0x40`) | 8 | 32 B | 128 |
| 1292 | 323 | performance directory (`0x41`) | 32 | 32 B | 512 |
| 1324 | 331 | patch directory (`0x42`) | 64 | 32 B | 1 024 |
| 1388 | 347 | partial directory (`0x43`) | 256 | 32 B | 4 096 |
| 1644 | 411 | **sample directory (`0x44`)** | 512 | 32 B | **8 192** |
| 2156 | 539 | volume / performance / patch parameters | 1 600 | — | — |
| 3756 | 939 | partial parameters | 1 024 | 128 B | 4 096 |
| 4780 | 1195 | **sample parameters** | 768 | **48 B** | **8 192** |
| **5548** | **1387** | **sample data — first cluster is 2** | to end of disc | 9 216 B | — |

Two closures make this a finding rather than an arrangement that happens to fit. 8 192 sample-directory entries of 32 bytes is *exactly* the 512 blocks to the next region, and 8 192 sample-parameter records of 48 bytes is *exactly* the 768 blocks from 4780 to 5548. **The sample data area begins where the parameter area ends.**

## Directory record — 32 bytes, one shape for all five classes

| Offset | Size | Meaning |
|---|---|---|
| 0 | 16 | name, ASCII, space-padded |
| 16 | 1 | class tag — `0x40` volume, `0x41` performance, `0x42` patch, `0x43` partial, `0x44` sample |
| 17 | 1 | zero |
| 18 | 2 | u16 LE next link, `0x8000`-flagged |
| 20 | 2 | u16 LE prev link, `0x8000`-flagged, `0xFFFF` on the head |
| 22 | 2 | u16 LE own index, 0-based, unflagged |
| 24 | 4 | zero on all 4 420 sample entries measured |
| 28 | 2 | u16 LE **first cluster** — sample entries |
| 30 | 2 | u16 LE **cluster count** — sample entries |

The links at 18/20/22 form a doubly-linked list per class and **are not needed to read the disc**. Entry *i* lives at `base + i × 32` and the count comes from the header; the links are a cross-check, not a walk.

## The allocation table is a DOS-style FAT

At sector 257, u16 LE, one entry per cluster, indexed by cluster number. `entry[0]` is a media marker and `entry[1]` is unused — the **first data cluster is 2**, exactly as FAT12/16 reserves its first two entries.

Cluster 2 is the first *addressable* cluster, not necessarily the first *allocated* one. The four local discs happen to put sample 0 there; all four L-CDX discs start it at **cluster 116**. Read the start cluster from the directory and never assume where the data begins.

**Any value `>= 0xFFF6` terminates a chain**, and that figure is load-bearing in both directions.

Too high and a marker reads as a cluster. `0xFFF8` and `0xFFFA` occur on the local discs and `0xFFFE` was seen remotely, so testing for `0xFFF8` alone runs a chain off the end of its own file and into the next one.

Too low and a cluster reads as a marker. The largest partition observed declares 1 184 980 blocks, which is `(1184980 - 5548) / 18` = 65 524 clusters numbered **2 to 65 525** — that is `0xFFF5`. A floor of `0xFFF0` is inside that range, and it is not hypothetical: `l-cdx-01`'s last sample starts at cluster 63 737 and runs 1 789 clusters to the very top of the partition. A `0xFFF0` floor drops that sample silently, and would truncate any chain routed through those five clusters.

`0xFFF6` is above every cluster number the arithmetic can produce and below every marker ever seen. Better still, **bound the walk by the partition's own arithmetic** — `(fs_blocks - 5548) / 18` — which tightens automatically on a small disc instead of trusting one constant everywhere.

**Cluster = 9 216 bytes = 18 blocks.**

```
cluster_address = 5548 × 512 + (c − 2) × 9216
```

Verified three independent ways, which is what it took, because a cluster size that is not a power of two is the sort of thing one talks oneself out of:

- **The FAT chain length equals the directory's declared cluster count on 4 420 of 4 420 samples**, across all four discs. No other cluster size is consistent with that at all.
- On `lcdp05` sample 0 — 21 clusters, 189 292 declared bytes — the audio's zero tail begins at block 5918 and the *next* sample's audio begins at block 5926, which is cluster 23 to the byte.
- `ceil(2 × end_frames / 9216)` equals the declared cluster count on 4 417 of 4 420 samples.

### Contiguity is a coincidence here too

All 4 420 chains on all four discs are contiguous — `entry[i] == i + 1` throughout. **Do not use that.** It is the same shape of coincidence that broke on 41 of 46 banks on `eiiix-2` in [emu3.md](emu3.md), and using contiguity as a validity test costs nothing until the disc that does not do it arrives, at which point a sample reports its neighbour's audio as its own and nothing complains. Follow the FAT.

## Sample parameter record — 48 bytes, index-parallel to the directory

Record *i* is at `4780 × 512 + i × 48`, for the same *i* as sample-directory entry *i*. The relation is **the index and only the index** — see the trap below.

| Offset | Size | Meaning |
|---|---|---|
| 0 | 16 | name — *may be stale*, see below |
| 16 | 4 | u32 LE **start point**, 24.8 fixed point |
| 20 | 4 | u32 LE **sustain loop start**, 24.8 fixed point |
| 24 | 4 | u32 LE **sustain loop end**, 24.8 fixed point |
| 28 | 4 | u32 LE **release loop start**, 24.8 fixed point |
| 32 | 4 | u32 LE **release loop end**, 24.8 fixed point |
| 36 | 2 | u16 LE, values `{0, 1, 2, 4, 5, 6}` — **not named** |
| 40 | 2 | zero on all 4 420 |
| 42 | 2 | u16 LE cluster count, duplicating the directory |
| 44 | 1 | **loop mode** — an open enum, see below |
| 45 | 1 | **original key**, MIDI note |
| 46 | 2 | zero on all 4 420 |

The addresses are **24.8 fixed point** — the low byte is a fractional sample, so the frame address is the u32 shifted right by 8. The fraction is zero on every record for the fields at 16, 24, 28 and 32, and *non-zero on 220 records* for the **loop start** at 20, which is what a sub-sample loop tuning looks like and is the tell that confirms the reading. Nothing else in the format carries a fraction, and the one field that does is the one where a sampler needs it.

### There are two loops, and no length field at all

The five addresses are a start point and **two loops** — a sustain loop and a release loop, which is the S-7xx's own model. Every record on five discs fits one of three shapes:

| Shape | Samples | What it is |
|---|---|---|
| `(28, 32)` is a few frames near the end | 6 188 | release loop unused, parked |
| `(28, 32)` is a verbatim copy of `(20, 24)` | 166 | release reuses the sustain loop |
| `(28, 32)` is a third region | 9 | a genuinely separate release loop |
| `32 < 28` — inverted, damaged | 29 | see the trap below |

That accounts for all 6 392.

**None of the five is a length, and there is no length field.** The end of the audio is the **furthest address the record references** — a sample must at least reach the last point it points at. That is not a convenience, because every single field fails alone:

| End taken from | Fits its allocation | Contains its own loop | Cluster arithmetic exact |
|---|---|---|---|
| field 28 | 99.9% | 97.4% | 97.3% |
| field 32 | 99.9% | 99.5% | 99.4% |
| **furthest of 24, 28, 32** | **99.91%** | **100.00%** | **99.84%** |

### How the sustain loop was established

Two measurements that use different evidence, over every ordered pair of the five address fields — the loop start was *not* assumed:

**The join test.** A forward loop `[L, E)` splices `x[E-1]` back to `x[L]`, and on a well-made loop that join is no rougher than any ordinary sample-to-sample step. Scoring each pair by the size of its join over the local mean step: `a20 -> a24` is the outright winner on **460 of 579 samples (79.4%)**, is the winner on **every disc individually** (56–88%), and has a median join of **1.47× the local step** — which is what seamless looks like. No other pair wins more than 10%.

**The shape test.** At a loop point the tone at `L` and the tone at `E` are the same phase of the same note, so their waveforms should correlate once amplitude is normalised away, while a wrong pair lands at a random phase. `a20 -> a24` wins on **73–99% per disc**. Absolute correlations are modest — these are vibrato'd acoustic instruments and the two windows are seconds apart — but the ranking is unambiguous.

The release pair was then forced by the records that no single-loop reading can explain: 166 samples where `(28, 32)` is a verbatim copy of `(20, 24)`, and 70 on `lcdp05` alone where field 28 falls *before* the sustain loop end and so cannot be an end point.

A first pass at the join test crowned `a28 -> a32` with a median join of exactly 0.00. That was **not** a loop: those two fields are four frames apart in a fade-out, so the join was small because the signal was silent, not because the waveform matched. Guarding on a minimum loop length and a minimum amplitude is what made the measurement mean anything, and it is worth recording as the shape of the mistake — a metric that rewards silence will find plenty of it on a sampler disc.

**The original key at 45 is verified against the names.** `STR:Vln Mt1 G_4` reads 67, `G#4` 68, `A_4` 69, `D#5` 75; the range across the four discs is 24–108.

The cluster count at 42 duplicates the directory's field and matches it on 4 420 of 4 420, and on all five range-fetched discs. Either may be read; the directory is the authority.

**Loop mode is an open enum and must not be validated against a closed set.** The values seen across five discs are `{0, 1, 2, 4, 16}` — and `16` appears only on `l-cdx-01`, which is to say only on the S-760 lineage. A parser that rejected an unknown value would have dropped 144 of that disc's samples, silently, on the strength of a set that four discs happened to agree on.

**The mode byte gates playback, not validity.** It is tempting to read mode `0` as "these loop fields are junk". It is not: mode-0 samples have a `a20 -> a24` join that is seamless on **80.6%** of them, against **86.5%** for non-zero modes. The loop points are crafted on nearly every sample; the mode byte decides whether the sampler uses them. So a loop should be emitted when the mode is non-zero, and the mode being zero is not evidence that the addresses are wrong.

What the non-zero values *mean* — forward, alternating, reverse — is **not established**. All of `{1, 2, 4, 16}` show seamless joins, and nothing distinguishes them. Mode 1 covers 3 962 of the 6 392 samples measured; the other three together cover 263.

## The payload is 16-bit little-endian

Sample data is signed 16-bit little-endian mono PCM — already what a WAV data chunk holds, so writing a WAV is a copy with a header in front of it ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)).

Measured at **each record's own start**, never at a sector boundary: little-endian first-difference beats big-endian on **252 of 252** windows sampled across the four discs. This is the measurement `emu3` got wrong first, and the reason it is stated with its method — sampling at 2048-byte boundaries makes little-endian data one byte out read exactly like big-endian data, and "LE from *n*" versus "BE from *n+1*" cannot be told apart by smoothness because they share their high bytes.

## The sample rate

**44 100. No rate field has been identified, and one measurement cannot settle it on its own — so here is exactly what the evidence does and does not support.**

Measuring the period of the recorded waveform against the note in the original-key byte puts `edirol-brass` at 44 100 on **93%** of its chromatic samples. Pooled over the discs the figure is 62%, with the remainder sitting at almost exactly ×0.5 and ×2.0.

**Those are octave ambiguities, and they are the reason pitch alone cannot decide this.** 44 100 and 22 050 differ by exactly one octave, which is precisely the interval that pitch estimation is worst at resolving and that a sample's original key can itself be wrong by. Any method that octave-corrects destroys the distinction it was meant to measure. This is stated plainly because the tempting move — octave-correct the estimates, watch them all snap to 44 100, and call it verified — proves nothing at all.

What the measurement *does* establish is the fine structure. Every ratio measured lands within a few percent of an exact power of two: 0.486, 0.959, 0.977, 0.988, 0.998, 1.924, 1.956, 1.980. So **all samples share one rate**, and that rate is 44 100 × 2ᵏ. Anything like 32 000 or 48 000 is excluded. Given the S-770 records at 44.1 and 22.05 kHz, that leaves two candidates, and the majority landing on ×1.0 picks 44 100.

**Byte 36 is not the rate flag.** Its values `{0, 1, 2, 4, 5, 6}` do not stratify the measured pitch at all — ×0.5, ×1.0 and ×2.0 appear in every bucket, as they do for every value of the loop-mode byte. Nothing else in the 48-byte record has the cardinality a rate flag would.

That is a measurement, not a decode, and the exposure is stated in [ADR-0018](../adr/0018-the-s7xx-sample-rate-is-measured.md): a 22.05 kHz disc would come out at double speed with nothing reporting it.

## The object hierarchy — located, not walked

Samples live in one flat, global directory. What groups them is the chain volume → performance → patch → partial → sample, and this project does not walk it ([ADR-0016](../adr/0016-the-s7xx-hierarchy-is-located-not-walked.md)). Both ends of the chain are visible, and are recorded here so that a later deliverable starts from evidence rather than from a hex editor:

- **Volume parameter records** at block 2156 carry a `0xFFFF`-terminated list of u16 performance indices at `+32`.
- **Partial parameter records** at block 3756 are 128 bytes with four 16-byte slots; each slot opens with a u16 sample index, or `0xFFFF` when empty. On `lcdp05`, partial `STR:Mute Vln MAA` references sample 0, `STR:Vln Mt1 G_4` — the muted violin it is named for.
- The **performance and patch** parameter records in between are located and not decoded.

## Names

ASCII 32–126, space-padded, **plus `0x7F` and nothing else** — over 4 420 names on four discs.

`0x7F` is the **stereo side marker**: `STR:Vn1 Pizz55\x7fL` and `STR:Vn1 Pizz55\x7fR` are the two halves of one stereo sound, in the same convention AKAI spells `-L`/`-R`. It appears 2 130 times across the four discs and covers 1 110 of `northstar`'s 1 284 samples, so a joiner that only recognises a hyphen leaves most of that disc mono ([ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md)).

`amg-now` also suffixes 340 names with `^`, and `northstar` 174 with `*`. Neither has been shown to mean anything.

## Verified constants

The nine-disc cross-check, first sample of each. Every row confirms four things at once: the directory entry's class, the index-parallel parameter record, the FAT chain length against the declared cluster count, and the end point against both.

| Disc | Sample 0 | Start cluster | Clusters | Chain | Key |
|---|---|---|---|---|---|
| `lcdp05` | `STR:Vln Mt1 G_4 ` | 2 | 21 | 21 | 67 |
| `edirol-brass` | `BRS:1Fr.Horn A#3` | 11 507 | 56 | 56 | 58 |
| `northstar` | `GTR:Gm Walk*\x7fL` | 2 | 18 | 18 | 36 |
| `amg-now` | `KIK:JJ Ambo K1 ^` | 2 | 6 | 6 | 60 |
| `l-cdp02` | `GTR:12Str E3 Lng` | 2 | 48 | 48 | 52 |
| `l-cdx-01` | `KIK:TV Kik 2    ` | 116 | 6 | 6 | 60 |
| `l-cdx-02` | `===:Keys Vol.I==` | 116 | 1 | 1 | 60 |
| `l-cdx-03a` | `FLT:Picc2E_5C   ` | 116 | 22 | 22 | 76 |
| `l-cdx-03b` | `===:BrsSections=` | 116 | 1 | 1 | 66 |

`lcdp05`, sample 0, in full:

| Quantity | Value |
|---|---|
| Name | `STR:Vln Mt1 G_4 ` |
| First cluster | 2 |
| Clusters | 21 |
| Byte address | 2 840 576 |
| End point | 94 646 frames |
| Payload | 189 292 bytes |
| Original key | 67 (G4) |
| Loop mode | 1 |
| Sustain loop | 77 268 frames |

Whole-disc listings — a backend that reports anything else is wrong, because these come straight from the header:

| Disc | Volumes | Samples |
|---|---|---|
| `lcdp05` | 1 | 890 |
| `edirol-brass` | 1 | 1 016 — one skipped, see below |
| `northstar` | 1 | 1 284 |
| `amg-now` | 1 | 1 230 |

## What a reader gets

Against the five local discs, listing every sample the header declares:

| Disc | Samples | Payload | Looped | Stereo halves |
|---|---|---|---|---|
| `lcdp05` | 890 | 122 444 586 | 435 | 361 |
| `edirol-brass` | 1 016 | 153 184 618 | 584 | 56 |
| `northstar` | 1 284 | 219 814 004 | 1 284 | 1 110 |
| `amg-now` | 1 230 | 388 698 996 | 1 100 | 603 |
| `l-cdx-01` | 1 972 | 601 370 200 | 806 | 600 |
| **total** | **6 392** | **1 485 512 404** | **4 209** | 2 730 |

Every count equals the header's declared figure exactly — including the loop counts, which come out right on every disc — and 231 sampled payloads read back byte-identical to an independent walk of the allocation table.

Six entries declare more frames than their clusters hold and are clamped to the allocated length — one on `edirol-brass`, five on `l-cdx-01`, including a `:  :` divider entry claiming 13 822 636 frames in a single cluster.

## Traps

- **Probe on `S770 MR25A` at byte 4 and nothing else.** The version string at `0x20` varies across lineages and keying on it drops the whole L-CDX series.
- **The directory name is authoritative; the parameter record's name can be stale.** `northstar` has 7 samples where the directory reads `PLK:F7MuteChr*` and the parameter record still reads `PLK:F7MuteChor`. The two records are joined by **index**, never by name — validating the pairing on name equality drops those 7 silently.
- **A sample may declare more than it owns.** `edirol-brass`'s `BRS:Cpm Tpt G_3A` declares 203 415 frames against 28 clusters, which hold 129 024. Clamp to the allocated bytes and log it; do not trust the declared length as a read size.
- **Contiguity holds on all 4 420 chains and must not be used as a validity test.**
- **The terminator floor is `0xFFF6`, not `0xFFF0`.** Cluster numbers reach `0xFFF5` on a full 604 MB partition and one disc really does use the top of it, so too low a floor is as wrong as too high — in the direction that loses a sample rather than corrupting one.
- **The addresses are 24.8 fixed point.** Reading them as plain u32 gives a byte address 256 times too large, which is inside the disc on a large image and therefore does not look wrong.
- **There is no length field, and field 32 is the tempting impostor.** It is the end point plus four frames on most records — and on 29 of 6 392 it holds the *cluster count* instead. `STR:ArcBss f C_2` reads 13 there against a real end of 56 647 frames, so sizing a read from it writes 26 bytes of a 113 KB sample: a WAV that opens cleanly in any editor, reports 13 frames, and is silent. Nothing anywhere reports a problem. Take the furthest address instead.
- **Field 28 is not an end point either.** On 166 samples it is the release loop's *start* and sits before the sustain loop end.
- **`0x110` is a partition size, not a derivation.** It does not divide evenly by the cluster size on any disc.
- **Cluster 2 is the first addressable cluster, not the first used one.** All four L-CDX discs start sample 0 at cluster 116.
- **Loop mode is an open enum.** Four discs say `{0, 1, 2, 4}` and the S-760 disc says `16`. Do not gate on it.
- **Loop mode 0 does not mean the loop addresses are junk.** They are crafted on mode-0 samples too — the byte decides whether the sampler *uses* them. Emit a loop when the mode is non-zero; do not conclude anything about the addresses when it is zero.
- **A loop metric that rewards silence will find silence.** Scoring loop candidates by splice smoothness picks `a28 -> a32` — four frames apart in a fade-out — unless it is guarded by a minimum loop length and a minimum amplitude.
