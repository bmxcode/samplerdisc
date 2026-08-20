# E-mu `EMU3`

The filesystem E-mu wrote on CD-ROMs for the Emulator III, EIIIX, ESI-32, ESI-4000 and Emulator IV. The archives file these as separate generations; the disc does not. All seven reference discs write `EMU3` at byte 0 and share one directory format.

The *bank interior* is not shared. EIII/ESI banks carry an `EMULATOR 3X` header and are located by it. E-IV banks carry none at all — not one `EMULATOR` string on any of the three E-IV discs — and reach their samples through an `E3S1` sample directory instead ([ADR-0020](../adr/0020-read-e-iv-through-its-sample-directory.md)).

Verified against seven discs:

| Short name | File | Size |
|---|---|---|
| `esi32-gm` | `Vol. 14 – ESI-32 General Midi Collection.iso` | 93 077 504 |
| `protozoa` | `E-MU Formula 4000 Series Vol. 5 – Protozoa.iso` | 131 690 496 |
| `eiiix-1` | `E-MU - EIIIX Sound Library Vol. 1 – Emulator Standards (EIIIX CD-ROM).iso` | 304 128 000 |
| `eiiix-2` | `E-MU - EIIIX Sound Library Vol. 2 – More Emulator Standards (EIIIX CD-ROM).iso` | 304 435 200 |
| `eiv-analogia` | `Producer Series Vol. 6 – Analogia Project (CD 2) (E-MU E-IV CD-ROM).iso` | 293 912 576 |
| `eiv-studio` | `Producer Series Vol. 1 – Studio Essentials (E-MU E-IV CD-ROM).iso` | 399 077 376 |
| `eiv-vitous` | `Miroslav Vitous … String Ensembles (EMU E-IV CD-ROM).iso` | 532 443 136 |

`eiv-analogia` and `eiv-studio` are both Producer Series and may share a mastering run; `eiv-vitous` is a different publisher and is the independence check. Where a constant holds on Producer Series and not on Vitous, Vitous is right.

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
| `eiv-studio` | 9 | 6 | 15 |
| `eiv-vitous` | 6 | 4 | 10 |

The pointer at `0x10` takes **six distinct values across seven discs**. Read it; never assume 9.

## The trap at `0x08`

`0x08` and `0x10` both point at 32-byte records with 16-character ASCII names, and reading the folder table as a bank directory produces a *shorter, entirely believable listing* rather than obvious garbage — on `eiv-analogia`, `Boom da Drumz`, `Symphoniks`, `Strung Out`, which look exactly like library names.

**Only the flags word at `+26` separates them**: `0xFFFF` for a folder, `0x0080`/`0x0081` for a bank. Nothing in the names, the record length or the field positions does.

**But the flags word is not a folder test.** `eiv-studio` writes `0x0013` and `0x0018` on its first two folder entries. Requiring `0xFFFF` aborts that walk on entry 0, finds no folder table at all, and falls back to the single bank directory at `0x10` — **77 banks of the 230 that disc has**, with no error. The folder table does not need the test: the header pointer already says what it is, and every disc terminates it with a zeroed entry. The flags word is still what tells a *bank* directory's entries apart from a folder table read by mistake.

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

**Each folder's directory is bounded by the next folder's start block.** On `eiv-studio` the five folders sit at blocks 15, 20, 26, 28 and 30 — two to six blocks apart. An unbounded walk runs out of one directory and into the next, reporting the neighbour's banks a second time.

| Disc | Folders | Folder blocks | Banks |
|---|---|---|---|
| `eiv-analogia` | 3 | 13, 14, 15 | 12 |
| `eiv-studio` | 5 | 15, 20, 26, 28, 30 | 230 |
| `eiv-vitous` | 6 | 10, 11, 12, 13, 14, 16 | 44 |

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
| 0 | 16 | `"EMULATOR 3X    \0"` on EIIIX and ESI, `"EMULATOR THREE \0"` on EIII |
| 16 | 16 | bank name, matching the directory entry |
| 0x30 | 4 | u32 LE, bytes before the sample area |
| 0x34 | 4 | u32 LE, **bytes of sample data** |
| 0x38 | 4 | u32 LE, not identified |

An earlier revision of this doc gave `0x38` as the bank size and claimed `0x30 + 0x34 == 0x38`. **That sum holds on 0 of the 112 located banks** across the four EIII/ESI discs, and nothing checked it. `0x38` reads a constant 8 388 608 on every `EMULATOR 3X` bank — including a 256 KiB one — which is the sampler's memory size and not a property of the bank; on `EMULATOR THREE` banks it reads 0, or a small number unrelated to the bank's extent. Do not use it for anything.

A bank ends where the next located bank begins. Without that bound a bank's sample walk runs into its neighbour and reports the neighbour's samples as its own — which reads as a longer, plausible listing.

### A bank may declare no sample area at all

`0x34` reads **zero** on 4 of the 112 located banks of the four EIII/ESI discs. Three of the four are one bank each on `esi32-gm`, `eiiix-1` and `eiiix-2`:

| Disc | Bank | `start` | `length` | Bytes to the next header | `0x34` |
|---|---|---|---|---|---|
| `esi32-gm` | `General Midi   X` | 3 | 1 | 262 144 | 0 |
| `eiiix-1` | `E-mu Banks 1-44` | 17 | 1 | 262 144 | 0 |
| `eiiix-2` | `Emu Banks 45-88` | 2 | 1 | 262 144 | 0 |

Each is located by its own `EMULATOR` header, and the distance to the next located header is exactly the one allocation unit its directory entry claims — so the bank is placed right and bounded right, and the walk finds nothing because there is nothing to find. Two of the three say so in their names: they are the library's index, listing the banks on this disc and on its companion volumes.

The fourth is `protozoa`'s `Protozoa       X`, and it is **not** an index bank in the reader's eyes: the walk currently reports 218 samples for it, because its bound is wrong. See the open question below. That is exactly why `0x34` is consulted only after the walk has already come back empty — as a reason for an emptiness already observed, never as a prediction that a bank will be empty.

**This has to be stated rather than merely observed.** A bank with no files and no note is the signature of a probe that matched something it should not have ([ADR-0012](../adr/0012-a-probe-must-confirm-a-file.md)), and an index bank reads exactly like a mis-bounded one unless the reader says which it is. `0x34` is what lets it say so, and it says only what the bank declares. A bank that declares sample data and yields none gets **no** note, because there the emptiness is genuinely unexplained and must stay visible as such.

`eiv-analogia` contains **no `EMULATOR` string at all** in 294 MB, and neither do the other two E-IV discs. Those banks are located through the sample directory below instead.

## Sample records

Found by signature within a bank, not followed as a chain. Records do sit back to back in runs — a 15-record piano multisample on `esi32-gm` where each stride equals the declared length exactly — and then a gap appears, after which the "next" record lands inside PCM.

A record starts **two bytes before its name**; those two bytes are `00 00` on every record after the first.

| Offset in record | Size | Meaning |
|---|---|---|
| 2 | 16 | name, ASCII |
| 18 | 4 | u32 LE checksum |
| 22 | 4 | u32 LE **header length — 92 on every record measured** |
| 34 | 4 | u32 LE record length, **two short** of the distance to the next (EIII only) |
| 54 | 4 | u32 LE **sample rate** |
| 92 | … | sample data |

The signature — header length exactly 92, a plausible rate, sixteen printable name bytes — is specific enough to scan megabytes of audio without false hits. On `esi32-gm`'s `8M GeneralMidi X` bank it yields **452 records with 452 distinct names** totalling 7.00 MiB inside a bank declaring 8 MiB.

## E-IV: the `E3S1` sample directory

E-IV banks have no header to locate them by, so their samples are reached through a directory instead. `E3S1` has **two distinct uses**, which is why the tag count runs at roughly twice the record count:

| Disc | `E3S1` tags | sample records | `E4P1` (presets) | banks |
|---|---|---|---|---|
| `eiv-analogia` | 1 042 | 523 | 916 | 12 |
| `eiv-studio` | 7 544 | 3 894 | 901 | 230 |
| `eiv-vitous` | 1 840 | 935 | 284 | 44 |

### The directory entry — 32 bytes

**These fields are big-endian.** They are the only big-endian structure in the format; every EIII header field and the payload itself are little-endian. This is a trap in the opposite direction from the one below, and worth stating twice.

| Offset | Size | Meaning |
|---|---|---|
| 0 | 4 | `"E3S1"` |
| 4 | 4 | u32 **BE** record length |
| 8 | 4 | u32 **BE** running offset of this sample within the bank |
| 12 | 2 | u16 **BE** index, restarting at 1 in each bank |
| 14 | 16 | name, ASCII |

### The record sits eight bytes after its tag

The other use of `E3S1` is the eight bytes immediately before a sample record. Cross-checked against an independent signature scan, the `+8` rule agrees 523/523 on `eiv-analogia` and 935/935 on `eiv-vitous`.

### The chain is what bounds a bank

Consecutive entries satisfy

```
position[i+1] == position[i] + length[i] + 10
```

— eight bytes for the next record's tag and two spare — and the index increments by one. **A break in either is a bank boundary.** Both halves are self-checking, which is what makes the split exact rather than a heuristic.

**Do not segment by physical stride instead.** Runs of 32-byte-adjacent entries look like the obvious reading and give 24 runs for `eiv-analogia`'s 12 banks and **935 runs for `eiv-studio`'s banks**, because that disc scatters its entries rather than packing them into a table. The chain is a *declared* relation and survives the scattering; adjacency is not and does not. This is the same trap as the contiguity one above, one layer down.

### Resolving a chain to an address

A chain's running offsets count from a base the disc does not state. It is recovered by finding, for one entry, the record whose name matches, and taking `record − position`; a chain is kept only when **every** one of its entries then lands on a record with the right name. A chain that does not fully confirm is dropped rather than partly believed.

`base − 8` is block-aligned on every confirmed chain, and the base then relates to the bank directory's `start` field as

```
base == 512 × (unit × start + bias) + 8
```

| Disc | unit (blocks) | bias |
|---|---|---|
| `eiv-analogia` | 2 048 (1 MiB) | −1 866 |
| `eiv-studio` | 1 024 (512 KiB) | −817 |
| `eiv-vitous` | 1 024 (512 KiB) | −890 |

No header field predicts either, exactly as [ADR-0015](../adr/0015-locate-banks-by-signature.md) found for EIII. The fit is therefore measured per disc from the confirmed chains and used **only to confirm** a bank against a chain that was already located independently — a wrong fit binds nothing rather than binding wrongly.

Two constraints keep the fit honest. It needs **at least two** agreeing chains, because a single `(base, start)` pair is satisfied by every candidate unit at some bias. And a fit that puts any bank at a **negative** address is rejected: the fit shifted by one whole unit explains just as many chains by pairing every base with its neighbour's `start`, and would hand each bank the samples of the bank before it.

### A directory can be written twice

Two chains can resolve to the same base — a bank whose directory is written twice, or split and recovered in halves. Listing both reports each record twice: on `eiv-analogia` that gave 509 samples at **449 distinct addresses**, and 60 byte-identical WAVs under names that read like a genuine stereo pair rather than like a bug. One record at one address is one sample.

### The record's own length field is not usable

The EIII rule — `+34` plus a bias of two equals the distance to the next record — matches on **0 of 522, 0 of 3893 and 0 of 934** consecutive pairs across the three E-IV discs. No other offset survives all three either: `+34` with a bias of four scores 93% on `eiv-vitous` but 18% on `eiv-studio`, and `+30` with a bias of four scores 74% on `eiv-studio` and **0%** on `eiv-vitous`. The directory's big-endian length matches every sample on all three discs, and is the authority.

`OFF_SAMPLE_HEADER_LEN` is not usable as a validity test either. It reads 92 on most E-IV records and **0 on 547 of `eiv-studio`'s** — those carry 92 at `+26` instead. Requiring it drops a fifth of the disc. It is not needed: the directory already says where the record is and what it is called.

## Everything is mono

The 92-byte header carries two paired length fields — `+26`/`+30` against `+34`/`+50` — with `+34 == 2 × (+30) − 90` holding identically on `esi32-gm` and on E-IV. The obvious reading is a channel count, and it is wrong.

Measured by comparing the mean absolute sample-to-sample delta of the payload read as mono against the same payload de-interleaved as stereo: de-interleaving roughly **doubles** the roughness (ratio ≈ 0.5), which is what taking every other sample of a smooth mono signal does. Interleaved stereo would come out smoother, not rougher. The known-good `esi32-gm` `Piano E0` — mono, verified byte-identical in the section below — scores 0.58, the same as the E-IV records. So ≈ 0.5 is the signature of mono, confirmed against the reference.

There is no stereo record. E-IV discs do pair samples into stereo, and they do it the way the rest of the collection does: two mono records that [ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md) joins by name.

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
| Bank declares (`0x34`) | 8 248 316 bytes of sample data |
| First record | `Piano E0`, rate 12 000, 146 852 bytes of PCM |

Whole-disc listings:

| Disc | Volumes | Samples |
|---|---|---|
| `esi32-gm` | 10 | 2 424 |
| `eiiix-1` | 46 | 1 189 |
| `eiiix-2` | 46 | 1 333 |
| `protozoa` | 16 | 6 788 |
| `eiv-analogia` | 12 | 449 |
| `eiv-studio` | 230 | 2 822 |
| `eiv-vitous` | 44 | 828 |

The four EIII/ESI counts are the regression baseline: any change to the shared record parser is a bug if they move. `protozoa`'s is a baseline of current behaviour and not of correct behaviour — see the open question at the end of this doc.

`esi32-gm`, `eiiix-1` and `eiiix-2` each list one index bank with a note and no samples, which is why their volume counts run one ahead of the banks that extract. On `eiv-studio`, 100 of the 230 banks have no confirmed sample directory and are listed with a note rather than guessed at. That disc carries 901 `E4P1` presets, and preset-only banks are the likely explanation — it is not established, so it is not claimed.

## Traps

- `0x08` is the folder table, not a bank directory. Only the flags word tells them apart, and reading the wrong one gives a believable short listing.
- Names are padded with spaces **or** NULs. Requiring one silently drops banks.
- Contiguity of `start`/`len` is a coincidence on simple discs. It breaks on 41 of 46 banks on `eiiix-2`.
- The `start` field is not a byte address, and the allocation unit is not one value across discs.
- Sample records are found, not chained; the chain has gaps.
- The payload is little-endian. A sector-aligned measurement says otherwise and is wrong.
- The E-IV **sample directory** is big-endian, alone in the format. The trap runs both ways.
- The flags word is not a folder test. `eiv-studio` writes `0x0013` and `0x0018`, and requiring `0xFFFF` costs that disc 153 of its 230 banks.
- Each folder's bank directory must be bounded by the next folder's start block; they sit two blocks apart on `eiv-studio`.
- On E-IV the record's own length field is unusable and the directory's is authoritative. The EIII rule matches 0 of 5 349 consecutive pairs.
- An E-IV sample directory can appear twice. Deduplicate by address or every one of its records is listed twice.
- The paired length fields are not a channel count. Everything is mono, measured.

## Open question: three `protozoa` banks report samples that are not theirs

Found while working out why the index banks above come back empty; recorded here rather than fixed, because it is a different failure on a different disc and the other six reference discs are unaffected.

A bank is bounded by the next *located* bank header, and two things stop a header from being located. `_bank_offsets` keys on the bank name and keeps the first occurrence of each, so `protozoa`'s **second** `EMULATOR 3X` header named `Phatt Presets  X`, at 0x7a14c00, is discarded — leaving no boundary between 0x7814c00 and the end of the image. `Protozoa       X` starts at 0x7814c00, declares a zero-length sample area and a single allocation unit, and is nonetheless credited with 218 records, 156 of them beyond its own 1 MiB extent.

The other way is a bank the directory lists that carries no header at all. `Orbit Presets 4k` and `Phatt Presets 4K` are both in the directory and neither has an `EMULATOR` header, so the `…  X` bank before each swallows its region: `Orbit Presets  X` reports 1 077 records where 8 MiB of bank can hold 539, with **541 duplicated names**, and `Phatt Presets  X` reports 298 more than its extent allows. Duplicated names across a bank boundary are the tell, and they are the same tell as the twice-written E-IV directory above.

So `protozoa`'s entry in the whole-disc listing table above — 16 volumes, 6 788 samples — is **not** a clean baseline; roughly a thousand of those records are a neighbour's, counted twice. The three other EIII/ESI counts are unaffected and remain the regression baseline.
