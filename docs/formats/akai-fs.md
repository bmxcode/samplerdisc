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
| `0x00` | u16 |
| `0x02` | u16 table, one entry per volume slot |
| `0xCA` | **volume directory** — 16-byte entries |

Volume entry, 16 bytes:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 12 | name, AKAI charset |
| 12 | 2 | u16 LE type |
| 14 | 2 | u16 LE start block |

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

A partition caps at 512 MB, so a large disc carries several. Walk the partition table rather than assuming one partition at the origin.

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
