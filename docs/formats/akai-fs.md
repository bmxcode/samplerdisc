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

Type is `0x70` or `0xF0` for a program and `0x73` or `0xF3` for a sample — ASCII `p` and `s` with the high nibble varying between S1000 and S3000 discs. **Mask the high nibble**; do not compare the whole byte.

Programs hold key ranges and envelopes, not audio. They are listed and skipped.

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

All three discs are 44 100 Hz throughout.
