# E-mu `EMU3`

The filesystem E-mu wrote on CD-ROMs for the Emulator III, EIIIX, ESI-32, ESI-4000 and Emulator IV. The archives file these as separate generations; the disc does not. All five reference discs write `EMU3` at byte 0 and share one directory format.

The *bank interior* is not shared. EIII/ESI banks carry an `EMULATOR 3X` header and are read; E-IV banks carry no header and are listed only ([ADR-0015](../adr/0015-locate-banks-by-signature.md)).

Verified against five discs:

| Short name | File | Size |
|---|---|---|
| `esi32-gm` | `Vol. 14 – ESI-32 General Midi Collection.iso` | 93 077 504 |
| `protozoa` | `E-MU Formula 4000 Series Vol. 5 – Protozoa.iso` | 131 690 496 |
| `eiiix-1` | `E-MU - EIIIX Sound Library Vol. 1 – Emulator Standards (EIIIX CD-ROM).iso` | 304 128 000 |
| `eiiix-2` | `E-MU - EIIIX Sound Library Vol. 2 – More Emulator Standards (EIIIX CD-ROM).iso` | 304 435 200 |
| `eiv-analogia` | `Producer Series Vol. 6 – Analogia Project (CD 2) (E-MU E-IV CD-ROM).iso` | 293 912 576 |

Addressing is in **512-byte blocks**, not the 2048-byte cooked sector.

## Header

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 4 | `"EMU3"` |
| `0x08` | 4 | u32 LE, **folder table** block |
| `0x0C` | 4 | u32 LE, blocks reserved for the folder table |
| `0x10` | 4 | u32 LE, first folder's bank directory block |

**`0x08 + 0x0C == 0x10` on every disc**, so the third field is derived and the first is the authority:

| Disc | `0x08` | `0x0C` | `0x10` |
|---|---|---|---|
| `esi32-gm`, `eiiix-1`, `eiiix-2` | 7 | 2 | 9 |
| `protozoa` | 6 | 6 | 12 |
| `eiv-analogia` | 6 | 7 | 13 |

The pointer at `0x10` takes four distinct values across five discs. **Read it; never assume 9.**

## The trap at `0x08`

`0x08` and `0x10` both point at 32-byte records with 16-character ASCII names, and reading the folder table as a bank directory produces a *shorter, entirely believable listing* rather than obvious garbage — on `eiv-analogia`, `Boom da Drumz`, `Symphoniks`, `Strung Out`, which look exactly like library names.

**Only the flags word at `+26` separates them**: `0xFFFF` for a folder, `0x0080`/`0x0081` for a bank. Nothing in the names, the record length or the field positions does.

## Directory records — 32 bytes

| Offset | Size | Meaning |
|---|---|---|
| 0 | 16 | name, ASCII, padded with **spaces or NULs** |
| 17 | 1 | index |
| 18 | 2 | u16 LE start |
| 20 | 2 | u16 LE length |
| 26 | 2 | u16 LE flags — `0xFFFF` folder, `0x0080`/`0x0081` bank |

**Padding is not consistently spaces.** `eiv-analogia` NUL-pads. Requiring printable bytes across the full 16 rejects `619 Grooved\0\0\0\0\0` and `AM Dreams\0\0\0\0\0\0\0`, which dropped **4 of that disc's 12 banks** with no error and a listing that looked complete. A hex dump renders NUL exactly like a full stop, so the cause reads as punctuation.

### Where a directory ends

At a zeroed entry, **or** at a record whose flags are not a bank's. Both occur: four discs terminate on zeros, `protozoa` runs into `0x42` filler that decodes as a perfectly plausible entry — `start=16962, len=16962`, name `BBBBBBBBBBBBBBBB`.

**Contiguity is not a terminator and not a validity test.** `start[i+1] == start[i] + len[i]` holds on the simple discs — 15 of 16 on `protozoa`, all of `eiv-analogia` — and `eiiix-2` breaks it on **41 of its 46 banks**. Using it to validate truncates that disc at the second entry. Banks are placed, not packed.

## Folders

Each folder has its **own** bank directory, one block, at the folder record's start. The header at `0x10` points at the first folder's, which is why walking only that one is wrong: on `eiv-analogia` it stops at the first zero entry and reports 6 banks. Walking the folder table finds **12**, in three folders at blocks 13, 14 and 15.

Four discs have a single folder — `Designed by S&M.`, `Default Folder` — which is why this is easy to miss.

## Locating a bank

**The directory's `start` field is not a usable byte address.** The implied allocation unit, measured as the gcd of consecutive bank-header offsets, is:

| Disc | Unit |
|---|---|
| `esi32-gm`, `eiiix-1`, `eiiix-2` | 262 144 (256 KiB) |
| `protozoa` | 1 048 576 (1 MiB) |

No header field predicts which — `0x2c` happens to equal 2048 on `protozoa`, matching 2048 × 512 = 1 MiB, and equals 8 on the others, where the answer is 512. The physical layout also does not follow `start` consistently: on `esi32-gm` two adjacent banks differ by 24 in `start` and by 8 units on the disc.

So banks are found by their own header instead, which is exact and self-checking because it repeats the directory name:

| Offset in bank | Size | Meaning |
|---|---|---|
| 0 | 16 | `"EMULATOR 3X    \0"` |
| 16 | 16 | bank name, matching the directory entry |
| 0x30 | 4 | u32 LE, bytes before the sample area |
| 0x34 | 4 | u32 LE, bytes of sample data |
| 0x38 | 4 | u32 LE, bank size — `0x30 + 0x34 == 0x38` |

A bank ends where the next located bank begins. Without that bound a bank's sample walk runs into its neighbour and reports the neighbour's samples as its own — which reads as a longer, plausible listing.

`eiv-analogia` contains **no `EMULATOR` string at all** in 294 MB. Its banks are listed from the directory and not extracted.

## Sample records

Found by signature within a bank, not followed as a chain. Records do sit back to back in runs — a 15-record piano multisample on `esi32-gm` where each stride equals the declared length exactly — and then a gap appears, after which the "next" record lands inside PCM.

A record starts **two bytes before its name**; those two bytes are `00 00` on every record after the first.

| Offset in record | Size | Meaning |
|---|---|---|
| 2 | 16 | name, ASCII |
| 18 | 4 | u32 LE checksum |
| 22 | 4 | u32 LE **header length — 92 on every record measured** |
| 34 | 4 | u32 LE record length, **two short** of the distance to the next |
| 54 | 4 | u32 LE **sample rate** |
| 92 | … | sample data |

The signature — header length exactly 92, a plausible rate, sixteen printable name bytes — is specific enough to scan megabytes of audio without false hits. On `esi32-gm`'s `8M GeneralMidi X` bank it yields **452 records with 452 distinct names** totalling 7.00 MiB inside a bank declaring 8 MiB.

## The payload is little-endian

Sample data is **signed 16-bit little-endian mono PCM** — already what a WAV data chunk holds, so writing a WAV is a copy with a header in front of it. Verified: all 452 samples of `8M GeneralMidi X` extract byte-identical to the disc with rates matching their records.

**This was got wrong first, convincingly.** Sampling the data at 2048-byte sector boundaries makes it read as big-endian, on four independent regions of two discs, reproducibly. It is an artifact: a sample record's payload starts at an *odd* byte offset, so a sector-aligned probe reads every 16-bit word one byte out, and reading little-endian data one byte out looks exactly like big-endian data.

The tell that should have been noticed earlier is that every other integer in the format is little-endian — the rate field reads 12000 as LE and nonsense as BE. A format does not usually mix.

Beware the near-miss: comparing "LE from *n*" against "BE from *n+1*" cannot distinguish them by smoothness, because both readings share the same high bytes. Read from the record's declared start and the question does not arise.

## Verified constants

`esi32-gm`, bank `8M GeneralMidi X`:

| Quantity | Value |
|---|---|
| Bank header at | 842 752 |
| First sample record at | bank + 138 317 |
| Sample records | 452 |
| Distinct names | 452 |
| Total record bytes | 7 345 200 (7.00 MiB) |
| Bank declares (`0x38`) | 8 388 608 (8 MiB) |
| First record | `Piano E0`, rate 12 000, 146 852 bytes of PCM |

Whole-disc listings:

| Disc | Volumes | Samples |
|---|---|---|
| `esi32-gm` | 10 | 2 424 |
| `eiiix-1` | 46 | 1 189 |
| `eiiix-2` | 46 | 1 333 |
| `protozoa` | 16 | 6 788 |
| `eiv-analogia` | 12 | 0 — listed only |

## Traps

- `0x08` is the folder table, not a bank directory. Only the flags word tells them apart, and reading the wrong one gives a believable short listing.
- Names are padded with spaces **or** NULs. Requiring one silently drops banks.
- Contiguity of `start`/`len` is a coincidence on simple discs. It breaks on 41 of 46 banks on `eiiix-2`.
- The `start` field is not a byte address, and the allocation unit is not one value across discs.
- Sample records are found, not chained; the chain has gaps.
- The payload is little-endian. A sector-aligned measurement says otherwise and is wrong.
