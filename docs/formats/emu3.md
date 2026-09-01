# E-mu `EMU3`

The filesystem E-mu wrote on CD-ROMs for the Emulator III, EIIIX, ESI-32, ESI-4000 and Emulator IV. The archives file these as separate generations; the disc does not. All ten reference discs write `EMU3` at byte 0 and share one directory format.

The *bank interior* is not shared. EIII/ESI banks carry a bank header and are located by it. E-IV banks carry none at all — not one `EMULATOR` string on any of the three E-IV discs — and reach their samples through an `E3S1` sample directory instead ([ADR-0020](../adr/0020-read-e-iv-through-its-sample-directory.md)).

Verified against ten discs:

| Short name | File | Size |
|---|---|---|
| `esi32-gm` | `Vol. 14 – ESI-32 General Midi Collection.iso` | 93 077 504 |
| `protozoa` | `E-MU Formula 4000 Series Vol. 5 – Protozoa.iso` | 131 690 496 |
| `eiiix-1` | `E-MU - EIIIX Sound Library Vol. 1 – Emulator Standards (EIIIX CD-ROM).iso` | 304 128 000 |
| `eiiix-2` | `E-MU - EIIIX Sound Library Vol. 2 – More Emulator Standards (EIIIX CD-ROM).iso` | 304 435 200 |
| `emu-classics` | `Vol. 07 – E-mu Classics.iso` | 526 723 072 |
| `vintage` | `Vol. 08 – Vintage.iso` | 527 030 272 |
| `ditto-drums` | `Vol. 16 – Twenty Six Studio Drum Kits and Percussion ESI-32 (aka Ditto Drums).iso` | 308 121 600 |
| `eiv-analogia` | `Producer Series Vol. 6 – Analogia Project (CD 2) (E-MU E-IV CD-ROM).iso` | 293 912 576 |
| `eiv-studio` | `Producer Series Vol. 1 – Studio Essentials (E-MU E-IV CD-ROM).iso` | 399 077 376 |
| `eiv-vitous` | `Miroslav Vitous … String Ensembles (EMU E-IV CD-ROM).iso` | 532 443 136 |

`eiv-analogia` and `eiv-studio` are both Producer Series and may share a mastering run; `eiv-vitous` is a different publisher and is the independence check. Where a constant holds on Producer Series and not on Vitous, Vitous is right.

The last three arrived with [issue #39](https://github.com/bmxcode/samplerdisc/issues/39) and are the discs the record extent below was established against. They are the same series as `esi32-gm` — `Vol. NN` of one publisher's ESI/EIIIX library — and `ditto-drums` is the one that shows the whole of the record-extent bug on a single disc: 74 samples read before it, 948 after.

**Two of these discs share a file size with another image in the archive**, which the disc-backed suite's size-based pin used to treat as one disc filed twice: `emu-classics` with `Vol. 03 – Orchestral` at 526 723 072, and `eiv-studio` with `Producer Series Vol. 2 – More Studio Essentials` at 399 077 376. A whole publisher's series mastered in one run is where "sizes are distinct" stops holding. The pin falls back to a digest of the image's first megabyte, which covers the `EMU3` header, the folder table and the first bank directory — the parts that actually differ.

Addressing is in **512-byte blocks**, not the 2048-byte cooked sector.

## Header

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 4 | `"EMU3"` |
| `0x08` | 4 | u32 LE, **folder table** block |
| `0x0C` | 4 | u32 LE, blocks reserved for the folder table |
| `0x10` | 4 | u32 LE, first folder's bank directory block |
| `0x1FE` | 2 | u16 LE, **superblock checksum** — see below |

**`0x08 + 0x0C == 0x10` on every disc**, so the third field is derived and the first is the authority:

| Disc | `0x08` | `0x0C` | `0x10` |
|---|---|---|---|
| `esi32-gm`, `eiiix-1`, `eiiix-2` | 7 | 2 | 9 |
| `protozoa` | 6 | 6 | 12 |
| `eiv-analogia` | 6 | 7 | 13 |
| `eiv-studio` | 9 | 6 | 15 |
| `eiv-vitous` | 6 | 4 | 10 |

The pointer at `0x10` takes **six distinct values across seven discs**. Read it; never assume 9.

### The superblock checksum

The header block ends with a checksum: the **sum modulo 2¹⁶ of the 255 u16 LE words spanning bytes `0x000`–`0x1FD`**, stored as a u16 LE at `0x1FE`. It is the format's own integrity test, and because it sums the whole block it fails on a truncated header or one read at the wrong offset — the mis-offset case [ADR-0005](../adr/0005-probe-for-the-filesystem-origin.md) exists to catch, which the four-byte magic and the `0x08 + 0x0C == 0x10` pointer relation both let through. The `EMU3` backend's `probe()` gates on it (`SUPERBLOCK_LEN`, `OFF_CHECKSUM` in `fs/emu3.py`), after the magic and before the pointer arithmetic — magic first, because an all-zeros block sums to its own zeroed checksum and would pass the sum alone.

It was found in the mpc2emu cross-check for [PR #65](https://github.com/bmxcode/samplerdisc/pull/65) and adopted in [issue #66](https://github.com/bmxcode/samplerdisc/issues/66); see "Independent corroboration (mpc2emu)" below for the seven-master table it was first verified against. Probing the whole local collection at each disc's resolved origin, it holds on **17 of 17** EMU3 images — every EIII/ESI and E-IV disc the backend reads, plus the shared-size twins — so gating on it rejects none of the discs the probe accepts today.

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
| 0 | 16 | the signature — three known values, below |
| 16 | 16 | bank name, matching the directory entry |
| 0x20 | 4 | u32 LE, the bank's index in its directory |
| 0x30 | 4 | u32 LE, bytes before the sample area |
| 0x34 | 4 | u32 LE, **length of the record run**, measured from its first record |
| 0x38 | 4 | u32 LE, not identified |

### The signature has three values, and the third cost `protozoa` two banks

| Signature | Where |
|---|---|
| `"EMULATOR 3X    \0"` | EIIIX and ESI |
| `"EMULATOR THREE \0"` | EIII |
| `"EMU SI-32 v3   \0"` | `protozoa`'s `Orbit Presets 4k` and `Phatt Presets 4K` |

The third is a Formula 4000 / ESI-4000 ROM's name for the same structure. Everything else about those two banks is ordinary: the same name field at `+16`, the same directory index at `+0x20`, the same `0x30`/`0x34` pair, the same records — and `Orbit Presets 4k`'s region is **97.98% byte-identical** to `Orbit Presets  X`'s, because the disc ships one library twice, once per sampler.

Matching only `EMULATOR` left both unlocated, which is worse than it sounds. An unlocated bank is not merely unread: it is also not a boundary, so the bank in front of it is handed its region as well. That is where 1 077 records for an 8 MiB `Orbit Presets  X` came from, 538 of them a second listing of `Orbit Presets 4k`'s ([ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md)).

The reader matches the family prefix — `EMULATOR`, `EMU SI-32` — rather than the whole 16 bytes, because the version suffix is a ROM revision and the name at `+16` is what actually confirms a hit.

### The same name can be written twice

Three headers across two discs are duplicates, and picking the wrong one reads the wrong bank:

| Disc | Name | Directory's copy | The other |
|---|---|---|---|
| `esi32-gm` | `2.5M Drums+SFX X` | `0x01f4dc00` | `0x01b4dc00` — an **older revision**, `0x34` 2 454 218 against 2 730 108 |
| `esi32-gm` | `1.3M Drums+SFX X` | `0x0220dc00` | `0x01dcdc00` — byte-identical, in the same unallocated region |
| `protozoa` | `Phatt Presets  X` | `0x05d14c00` | `0x07a14c00` — the same bank again, running off the end of the image |

Note where they sit: `esi32-gm`'s two are **below** the banks its directory points at and `protozoa`'s is **above**. Keeping the first header of a name reads an older revision on one disc; keeping the last reads a truncated copy on the other.

What decides is where the directory put the bank. `header address == unit × start + bias` holds **exactly**, per disc:

| Disc | unit | bias | Agrees |
|---|---|---|---|
| `esi32-gm` | 262 144 | −205 824 | 6 of 6 |
| `protozoa` | 1 048 576 | −963 584 | 14 of 14 |
| `eiiix-1` | 262 144 | −205 312 | 45 of 45 |
| `eiiix-2` | 262 144 | −205 312 | 45 of 45 |

`eiiix-2` is the one that makes this convincing: its `start` values are scattered rather than ordered — 823, 15, 846, 29 — and all 45 land on the nose.

This does **not** reopen [ADR-0015](../adr/0015-locate-banks-by-signature.md). Nothing is placed by the arithmetic; it only says which of two headers already carrying the right name a directory entry meant, and only names with a single header are allowed to vote for the fit. It is the same instrument, used the same way, as the E-IV allocation-unit fit below.

### A header's name can be a corrupted copy of the directory's

A bank's header repeats the directory's name at `+16`, and matching on it is what confirms a hit. On a handful of banks the mastering **mistyped that copy**, so the header no longer matches the directory verbatim and keying the lookup on exact-name equality lists the bank empty — with the `no bank header found for this bank; listed only` note — while its audio sits right there behind a header the signature scan did find. Five such banks across three discs:

| Disc | Directory name | Header `+16` name | Records | First record |
|---|---|---|---:|---|
| `elements1mb` | `Electric Grand X` | `Eelectric GrandX` | 9 | `ELEC GRAND  _000` |
| `ditto-drums` | `PERCUSSION#1   X` | `PERCUSSION #1  X` | 31 | `TAMB BRASS` |
| `heavy` | `HvyGtr FX5     X` | `HvyGtr FX5    XX` | 2 | `Gtr FX 11` |
| `heavy` | `Misc Gtr FX 2MbX` | `Misc Gtr FX 2mbX` | 6 | `Gtr Feedback Shr` |
| `heavy` | `HvGtrFdBkTxtr2Mb` | `HvGtrFdBkTxtr2M ` | 1 | `Gtr FeedbackLoop` |

Every corruption is a shifted space, a case change, or one doubled or dropped character — an edit of at most one once the name is lowercased and its spaces stripped. The header sits at exactly the address `unit × start + bias` predicts, holds a declared run, and names its records for the bank, so all three of "where the directory points", "what the header is called" and "what the audio is" agree that it is the same bank.

So a directory entry that no header names exactly binds the header at its predicted address, when that header's name is within one normalised edit of the entry's and no other entry already owns it ([ADR-0031](../adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)). The near-name gate is load-bearing, not cosmetic: `ditto-drums`'s `E3 Main Code` and `E3X Main Code` slots — real operating-system banks with no audio — predict addresses that fall on the `Ditto Drums    X` and `DAVE W  KIT1   X` headers, a dozen edits from their own names, and binding by address alone would hand each OS slot another bank's records. `elements1mb` and `heavy` are pinned by this recovery in `tests/test_discs.py`; it binds nothing on any of the ten reference discs.

### The directory itself can write a name twice

Distinct from a name carried by two headers above: here the **directory** lists one name in two entries, at two different `start` fields. Two discs do it — `elements1mb` writes `Harpsichord    X` twice, `heavy` writes `HvyGtr Maj.Open` twice — and each entry binds to the header its *own* placement predicts. Resolving a bank by name alone gives both entries one header and lists its records under each, the same audio written twice; the fix is to resolve per directory entry ([ADR-0034](../adr/0034-each-directory-entry-binds-its-own-header.md)).

The two entries need not point at the same audio. `elements1mb`'s two `Harpsichord    X` headers are two different banks — 11 records and 13 — and reading one twice both double-lists it and hides the other:

| Disc | Directory name (×2) | Entry `start` | Predicted address | Header `+16` name | Records |
|---|---|---:|---|---|---:|
| `elements1mb` | `Harpsichord    X` | 96 | `0x017cdc00` | `Harpsichord    X` | 11 |
| `elements1mb` | `Harpsichord    X` | 218 | `0x0364dc00` | `Harpsichord    X` | 13 |
| `heavy` | `HvyGtr Maj.Open` | 51 | `0x03215600` | `               X` (blank) | 6 |
| `heavy` | `HvyGtr Maj.Open` | 292 | `0x12315600` | `HvyGtr Maj.Open` | 6 |

`heavy`'s first entry is the one open thread. Its predicted address holds a real `EMULATOR 3X` header whose 16-byte name is blanked to spaces and the conventional trailing `X`, carrying six `MajOpen …` records that are **byte-identical** to the six the named header holds — the `EMU SI-32` `4k` duplicate-library pattern with the name zeroed rather than re-typed. Its name confirms nothing, so it is left with the `no bank header found` note rather than bound by address alone (which [ADR-0031](../adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md) rejected), and because its audio duplicates the named entry's, nothing is lost by noting it ([ADR-0034](../adr/0034-each-directory-entry-binds-its-own-header.md)).

An earlier revision of this doc gave `0x38` as the bank size and claimed `0x30 + 0x34 == 0x38`. **That sum holds on 0 of the 114 located banks** across the four EIII/ESI discs, and nothing checked it. `0x38` reads a constant 8 388 608 on every `EMULATOR 3X` and `EMU SI-32` bank — including a 256 KiB one — which is the sampler's memory size and not a property of the bank; on `EMULATOR THREE` banks it reads 0 on 60 of 90 and a small number unrelated to the bank's extent on the rest. Do not use it for anything.

### A bank's region holds more than the bank

A bank ends where the next located bank begins — and that is *not* where its records end. Mastering writes a bank image into a fixed region, and whatever was there before survives past the end of what was written over it. On `protozoa` every record past a bank's declared end is another bank's record at a **single constant shift**: 265 of 265 for `Vintage+InstrmtX` against `Vintage InstrmtX`, 71 of 71 for `Phatt Presets  X` against `Phatt Instrmt  X`, 63 of 63 for `Protozoa       X` against the Phatt banks. It is inside the bank's own region, so no bound drawn between banks can exclude it.

The bank's own header can. `0x30` is where its sample area begins and `0x34` is the length of its record run, measured from the first record — which starts exactly 74 bytes into the area on **107 of the 110 populated banks** of the four EIII/ESI discs, and never earlier. The far end is as tight: the last record ends exactly at `0x30 + 74 + 0x34` on 72 banks and one 92-byte header short of it on 19 more.

So a bank owns the records that **start** inside `[0x30, 0x30 + 74 + 0x34)`, and the next located header still caps the read ([ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md)).

**The run bounds the record, not the audio.** On the remaining 19 banks the fit is looser in both directions — 11 whose last record's payload overshoots the declared end, 8 whose run has slack after it. Eight records across `eiiix-1` and `eiiix-2` start inside the run and extend past it, and they are real; requiring a record to *fit* inside the run loses them and moves both EIIIX baselines.

### A bank may declare no sample area at all

`0x34` reads **zero** on 4 of the 114 located banks of the four EIII/ESI discs, one per disc, and each one is the library's index — a bank that lists what is on this disc and its companion volumes, and holds no audio at all. Three say so in their names:

| Disc | Bank | `start` | `length` | `0x34` |
|---|---|---|---|---|
| `esi32-gm` | `General Midi   X` | 3 | 1 | 0 |
| `eiiix-1` | `E-mu Banks 1-44` | 17 | 1 | 0 |
| `eiiix-2` | `Emu Banks 45-88` | 2 | 1 | 0 |
| `protozoa` | `Protozoa       X` | 121 | 1 | 0 |

`protozoa`'s was the hard one. Its 1 MiB region holds 63 records, so a walk bounded by the region reports them and the bank looks populated — but **all 63 carry names from the Phatt banks**, at a constant shift of one allocation unit, and its first record sits at `+0x5f73` where every populated bank on that disc starts at `0x30 + 74`. They are the region's previous occupant, not the bank's.

Since `0x34` bounds the run ([ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md)), a bank declaring zero has an empty run and yields nothing. **This has to be stated rather than merely observed.** A bank with no files and no note is the signature of a probe that matched something it should not have ([ADR-0012](../adr/0012-a-probe-must-confirm-a-file.md)), and an index bank reads exactly like a mis-bounded one unless the reader says which it is.

Be clear about what that note now is and is not. It reports what the header declares, and the header is also what bounded the walk — so it restates the bound rather than corroborating it independently, which is a real loss and is recorded as one in ADR-0021. A bank that declares sample data and yields none still gets **no** note, because there the emptiness is genuinely unexplained and must stay visible as such.

`eiv-analogia` contains **no `EMULATOR` string at all** in 294 MB, and neither do the other two E-IV discs. Those banks are located through the sample directory below instead.

## Sample records

Found by signature within a bank, not followed as a chain. Records do sit back to back in runs — a 15-record piano multisample on `esi32-gm` where each stride equals the declared length exactly — and then a gap appears, after which the "next" record lands inside PCM.

A record starts **two bytes before its name**; those two bytes are `00 00` on every record after the first.

| Offset in record | Size | Meaning |
|---|---|---|
| 2 | 16 | name, ASCII |
| 18 | 4 | u32 LE, not identified — see below |
| 22 | 4 | u32 LE `start_L` — **92 on every record measured**, and the signature the walk scans for |
| 26 | 4 | u32 LE `start_R` |
| 30 | 4 | u32 LE `end_L` |
| 34 | 4 | u32 LE `end_R` |
| 38 | 4 | u32 LE `loop_start_L` |
| 42 | 4 | u32 LE `loop_start_R` |
| 46 | 4 | u32 LE `loop_end_L` |
| 50 | 4 | u32 LE `loop_end_R` |
| 54 | 4 | u32 LE **sample rate** |
| 92 | … | sample data |

The signature — 92 at `+22` **or** at `+26`, a plausible rate, sixteen printable name bytes — is specific enough to scan megabytes of audio without false hits. On `esi32-gm`'s `8M GeneralMidi X` bank it yields **531 records with 531 distinct names** totalling 8 248 316 bytes, which is the bank's declared run to the byte.

Either start, because either set may be the one that opens the audio — see below. **76 of that bank's 531 records declare their one channel on the right**, and scanning for `+22` alone leaves every one of them, and all of `vintage`'s `Juno Synths`, invisible.

### The eight pointers

`+22` through `+50` are one block: a start, an end, a loop start and a loop end, **per channel**. Every one is a **byte offset from the record's own start**, naming the first byte of a 16-bit word.

An earlier revision of this doc listed eight *undecoded* fields at `+18`, `+24`, `+28`, `+32`, `+36`, `+40`, `+44`, `+48`. Those are a four-byte stride started at the wrong place: a `u32` read at `+28` straddles `end_L` and `end_R`, which is why they dump as nine-digit noise and why nothing was ever made of them.

Reading them as pointers explains three things this doc already recorded and could not account for:

- **`+22` is not a header length.** It is `start_L`, and it reads 92 because the header is 92 bytes and the audio begins immediately after it. That is why it also serves as the signature. It reads **0** on 542 of `eiv-studio`'s records and 146 of `eiv-analogia`'s — this doc previously noted 547 "carry 92 at `+26` instead" and left it as an oddity. Those records declare no left channel. Not a broken field: a different value of a working one.
- **`+34`'s "bias of two" is not a bias.** The pointer addresses the *last word* rather than one past it, so the record ends two bytes further on.
- **`+34 == 2 × (+30) − 90`**, reported below without an explanation, is `end_R = end_L + P/2`.

Two record shapes occur, and a reader must handle both. `start_R == start_L + P/2` declares **two channels**, the payload being all of the left then all of the right; a record that declares a single channel puts 92 in one set and zero, or a copy of the same value, in the other. Either set can be the single one — 542 records on `eiv-studio` and 8 on `eiv-analogia` declare their one channel on the **right**, with the left zeroed.

Counts per disc, over every sample the walk yields:

| Disc | two channels, confirmed | two channels, contradicted | one channel, left set | one channel, right set | neither |
|---|---|---|---|---|---|
| `esi32-gm` | 28 | 0 | 2 247 | 353 | 7 |
| `protozoa` | 8 | 0 | 5 927 | 595 | 65 |
| `eiiix-1` | 601 | 0 | 380 | 0 | 267 |
| `eiiix-2` | 592 | 0 | 680 | 0 | 65 |
| `emu-classics` | 185 | 0 | 1 179 | 73 | 79 |
| `vintage` | 2 | 0 | 633 | 350 | 8 |
| `ditto-drums` | 0 | 0 | 941 | 0 | 7 |
| `eiv-analogia` | 279 | 0 | 146 | 8 | 16 |
| `eiv-studio` | 320 | 0 | 1 882 | 542 | 78 |
| `eiv-vitous` | 828 | 0 | 0 | 0 | 0 |
| **total** | **2 843** | **0** | **14 015** | **1 921** | **592** |

**"Contradicted" is a shape of its own and it must be rejected**, not counted as stereo: the record declares `start_R` half a payload on and then closes its left channel somewhere else. **It occurs on none of the ten discs.** An earlier revision of this table gave 65 — 40 on `eiiix-1`, 19 on `protozoa`, 6 on `eiiix-2` — and every one of them was a record sized at twice its length, because the extent came from the wrong pointer. Given the right extent they are not half-payload splits at all. The gate's third condition is kept, and is now exercised only synthetically; see "Stereo" below ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)).

The "neither" column is records whose `start_R` is none of the three values — not a right-hand single channel, which is an ordinary record and is counted as one here. An earlier revision of this table folded those 550 into "neither", giving 620 for `eiv-studio` and 24 for `eiv-analogia`.

### The set that opens the audio is the set that closes it

**This is the whole rule, and it applies to locating a record, sizing it and reading its loop.** The audio begins immediately after the 92-byte header, so the set that describes it opens at 92; the record runs to that set's own end pointer, two bytes on. Only a confirmed two-channel record runs to `end_R`, because there the payload is both blocks.

`+34` was read as the record's length for four deliverables, and it is the **right channel's end**. It closes the record only where the right-hand set is what describes the record, and on 10 274 of the 15 272 EIII/ESI records here the left-hand set is. Four shapes the right-hand set takes when it is not describing this record, each of which breaks a reader that takes `+34` as a length:

| Shape | What the right-hand set holds | Reading `+34` as the length gives | Count |
|---|---|---|---|
| **mirror-92** | `start_R = 0`, `end_R = end_L − 92` — the same channel counted from the payload's start rather than the record's | an extent **92 bytes short**, so every sample loses its last 46 frames | 7 005 |
| **zeroed** | `start_R = end_R = 0` | an extent of 2, shorter than the header, so the record is dropped entirely | 872 |
| **fixed frame** | `start_R = 92 + F`, `end_R = 92 + 2F − 2` for a constant allocation frame `F` — 1 MiB on `emu-classics`, 2 MiB on `eiiix-1` | an address past the whole bank region, so the record is dropped as unreadable | 95 |
| **right-declared** | `start_R = 92` with the left set not opening the audio — `start_L = 0` on 1 371 of them | nothing: the record is never found, because the left-hand signature does not match it | 1 429 |

Per disc, by which set opens the audio:

| Disc | left only | both | right only | of which two-channel |
|---|---:|---:|---:|---:|
| `esi32-gm` | 2 280 | 2 | 353 | 28 |
| `protozoa` | 4 303 | 1 685 | 607 | 8 |
| `eiiix-1` | 850 | 380 | 18 | 601 |
| `eiiix-2` | 655 | 680 | 2 | 592 |
| `emu-classics` | 669 | 748 | 99 | 185 |
| `vintage` | 569 | 74 | 350 | 2 |
| `ditto-drums` | 948 | 0 | 0 | 0 |
| **total** | **10 274** | **3 569** | **1 429** | **1 416** |

Where **both** sets open at 92 the two ends disagree by a few bytes in either direction, and the larger is the one the stride follows — 920 records on `protozoa` where `end_L` is 8 bytes past `end_R`, 90 where it is 8 bytes short of it. The mirror is not always exactly 92 either: on 886 left-only records it is within a few bytes of it or arbitrary. Neither matters, because the rule never reads the set that did not open the audio.

**The two-channel exception, stated from the pointers alone:**

```
start_L == 92  and  start_R == end_L + 2  and  end_R - start_R == end_L - start_L
```

which is [ADR-0026](../adr/0026-the-record-declares-the-channel-count.md)'s three conditions without reference to the payload size — necessary, because the payload size is what is being computed from it.

#### Two measurements settle this, and neither is the pointer block agreeing with itself

**The stride to the next record.** `end_L + 2` equals the distance to the next record on 2 093 of `esi32-gm`'s records; `end_R + 2` equals it on 30.

**The bank header's declared run — a different field in a different structure.** [ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md) measured a bank's last record ending exactly at `0x30 + 74 + 0x34` on 72 banks, and *"exactly 92 bytes — one sample header — short of it"* on 19 more, and took the second population for a loose fit. It is this, seen from the bank header:

| Disc | banks with records | last record ends exactly at the run's end | reading `+34` as the length |
|---|---:|---:|---:|
| `esi32-gm` | 7 | **7** | 2 |
| `protozoa` | 15 | **15** | 0 |
| `eiiix-1` | 44 | **39** | 35 |
| `eiiix-2` | 44 | **39** | 37 |
| `emu-classics` | 19 | **16** | 8 |
| `vintage` | 13 | **13** | 4 |
| `ditto-drums` | 44 | **44** | 0 |
| **total** | **186** | **173** | **86** |

No bank on any disc is left 92 bytes short. `tests/test_discs.py` asserts these counts, because they are the independent half of the evidence and are exactly the sort of thing a later simplification removes without noticing.

**Do not derive one channel's pointers from the other's.** `loop_start_R == loop_start_L + P/2` holds exactly on `eiv-vitous`'s 828 records and on 1.2% of `esi32-gm`'s. Read the set whose start is 92 and use it.

`+18` is **not identified**. An earlier revision of this doc called it a u32 checksum and `docs/README.md` listed it undecoded; neither cited a measurement and neither is followed here. It is not needed for anything.

## Loop points

The loop is `(+38, +46)` read against `+22` — or `(+42, +50)` against `+26` on a record that declares no left channel. In frames: `(pointer − start) / 2`.

**Established by content, not by the structure fitting.** Two measurements on different evidence, the method [roland-s7xx.md](roland-s7xx.md) used for the S-7xx sustain loop, guards included — a minimum loop length of 64 frames and a window RMS at both ends of at least 15% of the sample's peak, because a metric that rewards silence will find plenty of it.

The **join** is `|x[E−1] − x[L]|` over the mean sample-to-sample step measured in a 64-frame window at each end. The **shape** test correlates the waveform at `L` against the waveform at `E`: the same phase of the same note correlates, a wrong start lands at a random phase. The control for both is *the same loop end with the start put somewhere else*, which is what isolates the start field.

| Disc | scored | shape *r* | control | join | seamless (<3×) | control seamless |
|---|---|---|---|---|---|---|
| `eiiix-1` | 512 | **+0.70** | +0.02 | 0.66 | 91% | — |
| `eiiix-2` | 526 | **+0.73** | −0.01 | 1.12 | 81% | — |
| `protozoa` | 723 | **+0.83** | −0.01 | 1.22 | 83% | — |
| `esi32-gm` | 16 | **+0.64** | +0.17 | 0.32 | 81% | — |
| `eiv-studio` | 1 051 | **+0.86** | −0.02 | 1.49 | 79% | 34% |
| `eiv-vitous` | 144 | **+0.68** | −0.06 | 2.30 | 64% | 25% |
| `eiv-analogia` | 34 | −0.00 | +0.02 | 2.44 | 53% | 25% |

The **end** cannot be isolated the same way: `+46` and `+30` sit six frames apart on most records, so no test separates them. What is established is the start, and that the pair splices.

`eiv-analogia` is stated as it came out. 441 of its 449 records pass every structural gate but only 34 carry audio loud enough at both ends to score, and those 34 show nothing. That is a lack of power rather than a refutation, and its loops rest on the rule the other six discs establish.

### A loop end past the audio is refused, not clamped

[akai-fs.md](akai-fs.md) and [roland-s7xx.md](roland-s7xx.md) both clamp a declared loop end back to the audio actually present, because a rip is routinely a little short of its directory. **Here the same move destroys the loop**, and `protozoa` shows it on one disc within one record shape:

| `protozoa`, one-channel records | count | shape *r* | control |
|---|---|---|---|
| loop end already inside the payload | 689 | **+0.86** | −0.04 |
| loop end past the payload, clamped back | 525 | **−0.10** | +0.01 |

Same disc, same shape, separated only by whether the end fits. A clamped end is a loop point the disc did not state, so a record whose loop end lies past its audio yields **no** loop ([ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md)).

That used to be most of why the reference disc yielded fewest, and the reason was not the loop rule. **The reader was 92 bytes short.** On about 2 200 of `esi32-gm`'s records `end_L` ran roughly 45 frames past the payload its own length field produced, and 95% of the disc was refused on it — because that length field is `end_R`, the right channel's end, and those records declare their audio on the left. An earlier revision of this doc left it open: *"Either the reader is 90 bytes short on those samples or the extent field means something else."* It was the reader ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)).

With the extent taken from the channel the record declares, the same loop ends fit inside the payload **without being clamped**, and `esi32-gm` goes from 107 loops of 2 265 samples to 1 778 of 2 635, `protozoa` from 1 689 to 5 244. That the counts move is not evidence. The newly admitted loops were scored the same way as the rest, with the same controls, and they splice:

| Disc | group | scored | shape *r* | control | join | seamless | control seamless |
|---|---|---|---|---|---|---|---|
| `esi32-gm` | loop newly admitted | 838 | **+0.87** | +0.01 | 1.25 | 87% | 36% |
| `esi32-gm` | record newly found | 130 | **+0.90** | −0.03 | 1.36 | 80% | 29% |
| `protozoa` | loop already produced | 905 | +0.85 | +0.02 | 1.35 | 83% | 38% |
| `protozoa` | loop newly admitted | 1 082 | **+0.82** | −0.01 | 1.07 | 90% | 32% |
| `protozoa` | record newly found | 330 | **+0.77** | −0.06 | 0.90 | 87% | 34% |
| `eiiix-1` | loop already produced | 413 | +0.96 | +0.02 | 1.03 | 90% | 36% |
| `eiiix-1` | record newly found | 133 | **+0.99** | −0.10 | 0.84 | 94% | 23% |
| `vintage` | record newly found | 250 | **+0.94** | −0.03 | 1.50 | 85% | 23% |

The window is the 256 frames *before* the loop start and before the loop end rather than after them: a loop of period `P` makes `x[t] ≈ x[t − P]`, and unlike the forward pairing that one still exists on a loop running to the last frame of the sample — which here is most of them.

The **record newly found** rows are the right-declared and zeroed-right-set records, and they answer the obvious worry about widening a signature that scans through megabytes of audio. A false hit inside PCM does not carry a loop that splices at +0.9 against a control at zero.

The scan for a better end that an earlier revision reported — a peak within ±2 frames of the declared end on 10% of `esi32-gm`'s records against about 3% for chance — was measuring the 92-byte shortfall, and is not repeated.

### The whole-extent "no loop" is written with a small inset, at both ends

A loop spanning the sample's whole declared extent is the format's **"no loop"**: the sampler fills the four loop pointers with the sample's own bounds when nothing set them, and emitting it writes a `smpl` chunk telling a DAW to loop the entire file. The bounds are not written at exactly frame 0 and the last frame — they are **inset by a small fixed amount at both ends**, `loop_start = start + C1` and `loop_end = end − C2` for a per-disc constant of a handful of bytes. `ditto-drums` writes `(12, 12)` on 898 of its records — frame 6 to six frames from the end — the two EIIIX discs write `(4, 4)`, and `esi32-gm`, `protozoa`, `eiv-vitous` and `eiv-analogia` write `(12, 10)`. A real loop's start is at an arbitrary musical position instead: on the loops this project already ships, the byte inset from the record's own start is a scattered 44, 136, 11 204, 52 536, never a fixed few.

Refusing only the frame-0 form shipped a loop over the entire file on **934 of `ditto-drums`'s 948 records**, and on nine other discs besides. Whether that inset population is a filled-in "no loop" or a real loop that happens to span the sample had to be measured — a sustained organ or string can legitimately loop over nearly its whole length, and deleting those to catch drum hits would destroy real loop points. It was measured against all ten reference discs, and the population is a "no loop" on every one.

The join and shape oracle above is the wrong instrument here, exactly as expected: a whole-extent loop starts within a few frames of 0 and ends within a few of the last, so there is almost no audio before its start and none after its end for the windowed correlation to work on. Two measurements that **do** apply to it separate the populations cleanly. The **end energy** — the RMS in a 64-frame window at the loop end, as a fraction of the sample's peak — is below 15 % on 70–100 % of the inset population, where a real loop ends that quietly on only 13–33 %: a loop is not a loop when it ends in silence. And where a record is loud enough at both ends to score, the join's **uniqueness** — that it splices where a random start against the same end does not, the signature of a chosen loop point — holds on 0–11 % of the inset population against 33–56 % of the real loops.

| Disc | refused | inset ends quiet | inset uniquely-splices | real-loop control |
|---|---:|---:|---:|---:|
| `esi32-gm` | 428 | 70 % | 11 % | 37 % |
| `protozoa` | 1 762 | 72 % | 10 % | 37 % |
| `eiiix-1` | 472 | 98 % | 1 % | 49 % |
| `eiiix-2` | 372 | 97 % | 2 % | 41 % |
| `emu-classics` | 302 | 88 % | 3 % | 36 % |
| `vintage` | 107 | 82 % | 5 % | 46 % |
| `ditto-drums` | 934 | 100 % | 0 % | 43 % |
| `eiv-analogia` | 443 | 97 % | 1 % | 33 % |
| `eiv-studio` | 337 | 87 % | 4 % | 41 % |
| `eiv-vitous` | 628 | 100 % | — | 56 % |

The last column is the same uniqueness measured on the loops this project already ships on that disc — the calibration of what a real loop looks like on this instrument — and the inset population sits far below it every time. `eiv-vitous` and `eiv-studio` are the check that matters most: [ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md) validated their loops by the shape test at +0.68 and +0.86, and those validated loops are the *real-loop* column here — they are kept. What is refused on those two discs is a separate whole-extent population that ends in silence. `eiv-analogia`'s loops never had independent evidence — ADR-0025 recorded that only 34 scored and those showed nothing — so refusing 443 of its 449 whole-extent "loops" takes nothing that was ever established.

So the guard refuses a loop whose bounds lie within `FULL_EXTENT_SLACK` frames of **both** ends, not only the start-0 case ([ADR-0030](../adr/0030-the-whole-extent-no-loop-is-refused-at-both-ends.md)). It is a structural rule — the loop is the record's own extent — justified by content, not a content test in the parser. It does not claim to catch every "no loop" a future generation might write, and on `esi32-gm` and `protozoa` a minority of the refused records (about 10 %) splice uniquely and could conceivably be a near-whole-extent loop the disc intended; they are refused with the rest because they are structurally the record's own bounds inset by that same fixed constant, and telling them apart would need a content measurement this project keeps out of the parser ([ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md)).

### There is no root key

**No byte of the 92 tracks the note written in the sample's own name.** Measured against the names themselves — `Piano E0`, `CP70 D#2`, `Arco Violin F#2` — over every byte position and every constant offset:

| Disc | named records | best byte matches |
|---|---|---|
| `esi32-gm` | 1 741 | 8% |
| `eiiix-1` | 917 | 6% |
| | | *chance, on constant-zero bytes* |

`+58` is the field that looks most like it and is the **sample rate** in another form: 64 096 ↔ 12 000, 64 184 ↔ 13 000, 64 266 ↔ 14 000, 64 388 ↔ 15 625.

The E3 keeps root key in its preset, and presets are not read. So an E-mu WAV carries its loop with `MIDIUnityNote` 60 — the RIFF neutral value, written because the field is mandatory and a loop cannot be carried without it. **60 is a placeholder, not a finding** ([ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md)).

## E-IV: the `E3S1` sample directory

E-IV banks have no header to locate them by. Most are reached through a chained `E3S1` sample directory, described here; the rest are native `FORM/E4B0` IFF banks whose samples are `E3S1` chunks, described in "The `FORM/E4B0` bank" below. `E3S1` has **two distinct uses** in the flat layout, which is why the tag count runs at roughly twice the record count:

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

## E-IV: the `FORM/E4B0` bank

A flat run of records indexed by a chained directory is not the only way an E-IV bank is stored. Across twelve discs, **170 banks of 788** are named by the folder directory, declare a non-zero length, and hold no flat `E3S1` directory at the address the allocation fit predicts — and every one of them holds a native `FORM/E4B0` IFF bank file there instead ([ADR-0032](../adr/0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)). The two are told apart by what sits at that address:

| At `512 × (unit × start + bias)` | Bank kind |
|---|---|
| a raw `E3S1` record (its 8-byte tag prefix) | flat bank, read through its chained directory |
| `FORM` … `E4B0` | native IFF bank, read through its chunks |

**The same per-disc allocation fit predicts both.** The `FORM` tag sits at exactly the block-aligned address a flat bank's first record prefix would — `base − 8`. So the fit measured from the flat sample banks (above) places the FORM banks with no new inference; the FORM banks carry no flat chain and cannot vote on it.

### The container

`FORM/E4B0` is IFF: the tag `FORM`, a big-endian u32 size, the form type `E4B0`, then a sequence of chunks. Each chunk is a four-byte id, a big-endian u32 size, and a body; an odd body is padded to a two-byte boundary. The chunks are `TOC1`, `E4Ma`, one or more `E4P1` presets, and one **`E3S1` chunk per sample** — whose body is an ordinary 92-byte sample record and its PCM, the same structure the flat path reads at `EIV_RECORD_OFFSET`. The chunk's big-endian size is the record length, playing the part the directory's big-endian length plays for a flat bank.

`eiv-studio`'s `Stein's Grand` is the worked example: a `FORM/E4B0` of eight `E3S1` chunks after one `E4P1`, `Stein Piano B 0` through `Stein Piano G#3`, 987 such records across that disc's 100 formerly-empty banks.

### The declared size understates the container

The `FORM` size is **short by 4 to 12 bytes** on every reference disc: the last `E3S1` chunk's body ends just past `FORM + 8 + size`, and the bytes after it are the next region's, which decode as a chunk of absurd size. So the declared size bounds where a chunk may *begin* — a chunk header past it is garbage — while a chunk's body is bounded by the image alone. Bounding the body by the declared size instead drops the last sample of most banks: 91 of `eiv-studio`'s alone.

### A `FORM` with no `E3S1` chunk is genuinely sample-free

Eight of the 170 hold a FORM with presets or text and no sample chunk: the four `Credits` text banks (`eiv-3d`, `eiv-studio-vol2` and the two others), and four `E-mu Systems 96` preset/globals banks on `eiv-studio`. These are correctly located and hold no audio, and are noted `the bank holds presets or text and no samples; listed only` — distinct from the `no sample directory` note, which is wrong for a bank that carries audio without a flat directory. The other 162 read: ~2 017 samples across the twelve discs, `eiv-studio` alone gaining 987 (2 822 → 3 809). None duplicates a sample already read from a flat bank.

`E4P1` presets — the key ranges, envelopes and root key — are **not** read, here or anywhere; the deliverable is the audio ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)).

## Stereo: the payload is split, not interleaved

**A previous revision of this section concluded "everything is mono". That conclusion is wrong, and the way it was wrong is worth more than the answer.**

What it measured was real: de-interleaving a payload as `LRLR` roughly **doubles** its mean sample-to-sample delta (ratio ≈ 0.5), which is what taking every other sample of a smooth mono signal does, and `esi32-gm`'s `Piano E0` scored 0.58 exactly like the E-IV records. That is a sound refutation of **interleaved** stereo. It says nothing about the layout the format actually uses.

The pointer block says what that layout is. `start_R == start_L + P/2` is a **block** split — all of the left channel, then all of the right — which de-interleaving cannot detect, because reading a block-split payload as mono gives one continuous waveform with a single join in the middle.

### The gate has three conditions

```
start_L == 92  and  P % 4 == 0
start_R == start_L + P / 2
end_L + 2 == start_R
```

`P` is the payload the record's own length field produces, and `end_L + 2` is where the left channel closes — the pointer names the first byte of the last word, so the extent runs two bytes past it.

**The third condition used to reject 65 records, and it now rejects none — because those 65 were a symptom of a different bug.** An earlier revision recorded that 2 721 records across seven discs satisfied the first two conditions and 65 failed the third: 19 on `protozoa`, 40 on `eiiix-1`, 6 on `eiiix-2`, each declaring a left channel that overlapped the right block or stopped well short of it. Every one of them was sized from `end_R` — the right channel's end — on a record that declares its audio on the left, so `P` came out at twice the record's length and `start_R` landed on `start_L + P/2` by arithmetic. Given the extent the record actually declares, none of the ten discs holds a contradicted record ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)).

`protozoa`'s trombones are the case that closes it. `Trom B2`, `Trom E3` and `Trom A3` are each written in two banks, and this doc recorded that the **first half of each is byte for byte a whole one-channel record of the same name** in `Vintage PresetsX` — 16 756 bytes against a 33 512-byte payload — with nothing on the disc matching the second half. With the right extent, `Proteus1PresetsX`'s `Trom B2` is 16 764 bytes and is **byte-identical to `Vintage PresetsX`'s and `Vintage InstrmtX`'s**, as are `Trom E3`, `Trom C5`, `Trom D4` and `Trom G4`. There was never a second half; the record was being read twice its length.

**The condition stays.** It is what makes the two-channel test exact when the extent is computed from the pointers alone — that test is this one restated — and a gate is not deleted for going quiet. It is now exercised synthetically only, and that is recorded rather than glossed.

**2 843 records pass all three**, which is what this project writes as stereo:

| Disc | stereo | of samples |
|---|---|---|
| `esi32-gm` | 28 | 2 635 |
| `protozoa` | 8 | 6 595 |
| `eiiix-1` | 601 | 1 248 |
| `eiiix-2` | 592 | 1 337 |
| `emu-classics` | 185 | 1 516 |
| `vintage` | 2 | 993 |
| `ditto-drums` | 0 | 948 |
| `eiv-analogia` | 279 | 449 |
| `eiv-studio` | 320 | 2 822 |
| `eiv-vitous` | 828 | 828 |

The four discs that had stereo before have exactly the numbers they had, which is the check that changing how long a record is did not change what shape it is.

### Measured directly, the selected halves are one performance

The instrument matters here, and the obvious one is confounded. Median RMS-envelope correlation between the two halves separates the populations —

| | `esi32-gm` | `eiiix-1` | `eiiix-2` | `protozoa` | `analogia` | `studio` | `vitous` |
|---|---|---|---|---|---|---|---|
| two channels, confirmed | **0.99** | **0.84** | **0.96** | 0.55 | **0.91** | **0.98** | **0.76** |
| one channel declared | 0.05 | 0.05 | 0.11 | 0.12 | 0.21 | 0.07 | — |

— but **a single decaying note's two halves both decay, and correlate at 0.94 without being two channels of anything.** On every disc a tail of one-channel records scores above 0.9 on this measure: `Piano Db3`, `Glockenspiel D5`, `Snare 2`. So two sharper instruments were used, each with a control on both sides.

**Fine structure** is the 64-frame RMS envelope divided by its own 1024-frame trend, so what is correlated is transients rather than the shape of the decay. **Best lag** is the peak normalised waveform cross-correlation over ±64 samples. The **positive control** is the twelve name-paired `-L`/`-R` records on `eiv-analogia` ([ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md)) — known-true stereo established by a mechanism the pointer block knows nothing about. The **negative control** is halves taken from two different records.

| | records | fine structure *r* | best lag *r* |
|---|---|---|---|
| positive control — name-paired pairs, `eiv-analogia` | 6 | **0.402** | **0.532** |
| negative control — two different records | 200 | 0.006 | 0.008 |
| confirmed, `esi32-gm` | 28 | 0.671 | 0.684 |
| confirmed, `eiiix-1` | 601 | 0.184 | 0.377 |
| confirmed, `eiiix-2` | 592 | 0.338 | 0.691 |
| confirmed, `protozoa` | 8 | 0.330 | 0.421 |
| confirmed, `eiv-analogia` | 279 | 0.343 | 0.430 |
| confirmed, `eiv-studio` | 320 | 0.667 | 0.768 |
| confirmed, `eiv-vitous` | 828 | 0.433 | 0.303 |
| **contradicted** — `end_L` past `start_R` | 20 | **0.05** | **0.012** |
| **contradicted** — `end_L` short of the split | 45 | **0.012** | **0.023** |

The confirmed records score with the positive control on all seven discs; the 65 the third condition rejects score with the negative control. `protozoa`'s eight are too few to establish anything on their own and rest on the other six discs.

Those last two rows were measured against the extent `+34` produces, and that population no longer exists — with the record sized from the channel it declares, no disc holds a contradicted record ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)). They are kept because they are what the third condition was established on: the halves it rejected were unrelated audio, measured, and that is why the condition is still there.

### The first block is the left channel

Structural: the pointer block is ordered `(start_L, start_R)` and `start_L` addresses the first block.

The only content evidence is weak and agrees with it. Of `eiv-analogia`'s twelve name-paired records, all **six** ending `-L` declare their single channel in the left-hand set and three of the six ending `-R` declare theirs in the right-hand set — nine of twelve consistent, **none contradicting**, *p* ≈ 0.09. Recorded for what it is: the decision rests on the field order, not on this ([ADR-0026](../adr/0026-the-record-declares-the-channel-count.md)).

### A one-channel record that is really stereo does not occur here

The inverse error was looked for. **Not one of the 12 017 records that did not declare the two-channel shape declared an extent of half its payload**, which is the structural signature it would leave. The 439 whose halves correlate above 0.9 by envelope show a midpoint z-jump of −0.27 to −0.41 — no discontinuity where a block join would be — and they are the decaying single notes above.

`eiiix-2` is the disc to check, because an earlier revision of this section gave it the weakest separation in the table at 0.59 for one-channel records. Under these instruments its high-envelope one-channel records score fine structure **−0.021**, which is the negative control, and its one-channel envelope median re-measures at **0.114** over 603 scored records. Both figures are recorded; the 0.59 is not reproduced by the measurement here and is not relied on either way.

### The loop points are unaffected

`(pointer − start) / 2` is a per-channel frame index either way: in the double-length mono file this format produced before D18 it landed in the left block, and in the interleaved file it is the frame number. All seven per-disc loop counts are unchanged across the fix, which is the check that the two decodes of one pointer block agree.

The two records anywhere whose declared loop end lay past its own channel — `Mbira A3` and `Mbira F3` on `eiiix-1` — were both among the 65 the third condition rejected, so they stayed mono and kept their loops. Both are ordinary one-channel records under D21's extent, and both still keep them.

### Name pairing is the other mechanism, and it is the rare one

E-IV discs *also* pair separate mono records into stereo by name, the way the rest of the collection does ([ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md)). Both mechanisms are real and they do not overlap: **14** samples across all ten discs are name-paired — six pairs on `eiv-analogia` and one on `ditto-drums` — against **2 843** whose own record declares two channels, and no sample is both. An earlier revision of this doc gave name pairing as the answer to how these discs do stereo, which is the rare case given as the rule.

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
| Sample records | 531 |
| Distinct names | 531 |
| Total record bytes | 8 248 316 |
| Bank declares (`0x30`, `0x34`) | sample area at 138 243, run of 8 248 316 |
| First record | `Piano E0`, rate 12 000, 146 852 bytes of PCM |

**The records fill the declared run exactly**, which they did not before D21: this table gave 452 records and 7 345 200 bytes, 903 116 short of a run nothing accounted for. 76 of the 531 declare their one channel on the right and were invisible to a left-hand signature; the rest were 92 bytes short each ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)).

Whole-disc listings, with the samples the record declares stereo:

| Disc | Volumes | Samples | Stereo |
|---|---|---|---|
| `esi32-gm` | 10 | 2 635 | 28 |
| `protozoa` | 16 | 6 595 | 8 |
| `eiiix-1` | 46 | 1 248 | 601 |
| `eiiix-2` | 46 | 1 337 | 592 |
| `emu-classics` | 22 | 1 516 | 185 |
| `vintage` | 16 | 993 | 2 |
| `ditto-drums` | 48 | 979 | 0 |
| `eiv-analogia` | 12 | 449 | 279 |
| `eiv-studio` | 230 | 3 809 | 320 |
| `eiv-vitous` | 44 | 852 | 828 |

**2 843 of 20 413**, and a stereo sample is still one sample: the stereo counts do not move when the channel count is read, only the file's shape does. `ditto-drums` gained 31 with D24 — its `PERCUSSION#1   X` recovered from a mistyped header name, from 948 — and two discs not in this reference table were pinned for the first time by the same recovery: `elements1mb` (102 volumes, 1 465 samples, `Electric Grand X`'s 9 recovered) and `heavy` (68 volumes, 870 samples, three banks recovered) ([ADR-0031](../adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)). **D25 moved the two E-IV sample counts** — `eiv-studio` 2 822 → 3 809, `eiv-vitous` 828 → 852 — by reading the `FORM/E4B0` banks above; the stereo counts did **not** move, because the recovered records are mono. `eiv-analogia` has no such bank and is the control: its three figures are exactly D18's.

Samples carrying a loop, of those totals:

| Disc | Samples | With a loop | |
|---|---|---|---|
| `esi32-gm` | 2 635 | 1 350 | 51% |
| `protozoa` | 6 595 | 3 482 | 53% |
| `eiiix-1` | 1 248 | 743 | 60% |
| `eiiix-2` | 1 337 | 892 | 67% |
| `emu-classics` | 1 516 | 1 133 | 75% |
| `vintage` | 993 | 846 | 85% |
| `ditto-drums` | 979 | 14 | 1% |
| `eiv-analogia` | 449 | 6 | 1% |
| `eiv-studio` | 3 809 | 3 029 | 80% |
| `eiv-vitous` | 852 | 208 | 24% |

**11 703 of 20 413** — D25's `FORM/E4B0` recovery moved `eiv-studio`'s loops 2 214 → 3 029 and `eiv-vitous`'s 198 → 208, on the samples it recovered; the loop is decoded from the same pointer block by the same rule, so a loop that moved would be arithmetic that drifted. `ditto-drums`'s 31 newly recovered records carry no loop (percussion one-shots), so the loop total is unchanged and only the sample total moved. These are D23's numbers: the whole-extent "no loop" is now refused at both ends rather than only where it starts at frame 0, so the loop-over-the-whole-file that every disc writes with a small fixed inset stops being emitted — `ditto-drums` from 948 to 14, `eiv-analogia` from 449 to 6, `eiv-vitous` from 826 to 198 ([ADR-0030](../adr/0030-the-whole-extent-no-loop-is-refused-at-both-ends.md), and "The whole-extent 'no loop'" above). The D21 revision's figures were `esi32-gm` 1 778, `protozoa` 5 244, `eiiix-1` 1 215, `eiiix-2` 1 264, `emu-classics` 1 435, `vintage` 953, `ditto-drums` 948, `eiv-analogia` 449, `eiv-studio` 2 551, `eiv-vitous` 826 — every one of them counting the no-loops. The **sample** counts, the stereo counts and every payload digest are unchanged across D23: only loop emission moved, which is what says the read path was not touched.

These are the regression baseline: any change to the shared record parser is a bug if they move. **They are now asserted by `tests/test_discs.py`, pinned by disc size** — a table in a document is a note, not a test, and two of these numbers were wrong for a release with a green suite. The suite also pins the **SHA-256 of every sample payload per disc**, because a count table cannot see a payload that shifted by a byte while staying the same length, and the **stereo counts** beside them, because the third condition of the gate is exactly the kind of thing a later simplification removes. On a stereo sample the suite additionally de-interleaves what was written and requires it to reproduce the disc's two blocks byte for byte: the audio moved, and it must be the same audio.

**These are D21's numbers and the previous revision's are all wrong**, on every EIII/ESI disc: `esi32-gm` 2 265, `protozoa` 5 852, `eiiix-1` 1 189 and `eiiix-2` 1 333, each of them a record extent taken from the wrong channel's end pointer ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)). The three E-IV rows did not move across D21 and were the control there: those discs size a record from their own big-endian directory and never read `+34`. D25 later moved `eiv-studio` and `eiv-vitous` for an unrelated reason — the `FORM/E4B0` recovery above — and `eiv-analogia`, which has no such bank, is still exactly where D18 left it.

`esi32-gm`'s 2 424 and `protozoa`'s 6 788 are what the revision before *that* gave, and both counted another bank's records; [ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md) has the accounting. `esi32-gm` is the instructive one: it was believed clean, and its last bank ran to the end of the image and was credited with 193 records belonging to the two banks in front of it.

Each of the seven EIII/ESI discs lists one index bank with a note and no samples, which is why their volume counts run one ahead of the banks that extract; `esi32-gm`, `eiiix-1` and `eiiix-2` also list the sampler's own code banks — `E3 Main Code`, `E3X Main Code` — which carry no bank header and are noted as such. On `eiv-studio`, the 100 banks that had no flat sample directory are the `FORM/E4B0` banks read by D25 above: 96 now extract, adding 987 samples, and the four `E-mu Systems 96` preset banks that carry no sample chunk stay noted. That disc's 901 `E4P1` presets remain unread — the deliverable is the audio ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)).

## Independent corroboration (mpc2emu)

Everything above was reverse-engineered from the ten reference discs alone, before we knew [lentferj/mpc2emu](https://github.com/lentferj/mpc2emu) existed. Its `docs/` directory — adopted as the Kurzweil oracle in [ADR-0036](../adr/0036-the-krz-bank-is-read-as-objects-and-verified-against-mpc2emu.md) — independently documents three of the formats here (`EIII_FORMAT.md`, `E4B_FORMAT.md`, `EMU3_ISO_FORMAT.md`), corpus- and hardware-confirmed against a different disc set. A second independent read is exactly the corroboration [CLAUDE.md](../../CLAUDE.md)'s "verify a constant against a real disc" rule wants; this section is the comparison. It is a source to cite the way we cite `emu3bm` and ConvertWithMoss, not a decode we depend on.

### The E-IV `FORM/E4B0` bank agrees field for field

`E4B_FORMAT.md` and "E-IV: the `FORM/E4B0` bank" above describe the same container down to the offsets, from two disjoint corpora:

| Fact | This doc | mpc2emu `E4B_FORMAT.md` |
|---|---|---|
| Container | `FORM` · BE u32 size · `E4B0`, then chunks; odd body padded to 2 | same |
| Chunk header | 4-char tag · BE u32 size · body | same |
| Sample chunk | one `E3S1` per sample, body is a 92-byte record + PCM | 94-byte header incl. a 2-byte index prefix, PCM after — the same bytes, the prefix counted in |
| `start_L` | `+22`, reads 92 (header length) | `start_l` at 22, "always 92" |
| `end_L` / loops / rate | `+30` / `+38`,`+46` / `+54` | `end_l` 30 · loop 38,46 · rate 54 |
| Loop end pointer | addresses the *last* word, so the record runs two bytes past it | "stores the frame **before** the last loop frame" — the same off-by-one, stated from the other side |
| Declared `FORM` size | short by 4–12 bytes; bounds where a chunk may begin, not its body | "size semantics differ subtly from spec", `form_size = filesize − 12` |

Where mpc2emu reaches past the audio it reaches into what [ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md) leaves to ConvertWithMoss: it decodes the `E4P1` presets, the 284-byte voice blocks and the 22-byte zone entries (key ranges, root key, pan) we deliberately do not read, and it identifies fields we leave as noise — the 2-byte prefix as a big-endian 1-based sample index, `+58` as a signed 1/64-semitone pitch offset (not a root key, which is consistent with "There is no root key" above), `+60` as mono/loop option flags, and an `EMSt` master-setup chunk. None of these is needed for the WAV; they are recorded here as leads, not adopted. Reading the channel count from mpc2emu's explicit `+60` options word rather than inferring it from the pointer sets ([ADR-0026](../adr/0026-the-record-declares-the-channel-count.md)) is the one that could simplify the decoder — a `src/` change for its own branch, not this docs pass.

`EIII_FORMAT.md` likewise agrees on the parts we share: a 92-byte sample header and byte-offset (not index) addressing. Its 96-byte bank header, 142-byte presets and 48-byte zones are the instrument layer, out of remit.

### The EMU3 filesystem: two structures we missed, and one real divergence

`EMU3_ISO_FORMAT.md` describes the header as a **fixed** geometry — superblock at block 0, FAT at blocks 2–6, root directory 7–10, dir-content 11–135, data 136+ — with a superblock checksum. Our "Header" section reads it instead as **variable** pointers (`0x08` folder table, `0x0C` its length, `0x10` first bank directory, "read it; never assume 9"). Probing all seven EMU3 `.iso` masters settles what is corroboration and what is divergence:

| Disc | `0x08` | `0x0C` | `0x10` | checksum holds | block 2 = FAT |
|---|---:|---:|---:|:--:|:--:|
| `esi32-gm` | 7 | 2 | 9 | yes | `0080 ff7f ff7f ff7f` |
| `eiiix-1` | 7 | 2 | 9 | yes | `0080 ff7f 0300 0400` |
| `eiiix-2` | 7 | 2 | 9 | yes | `0080 ff7f ff7f 0400` |
| `protozoa` | 6 | 6 | 12 | yes | `0080 0200 0300 0400` |
| `vintage` | 6 | 4 | 10 | yes | `0080 0200 0300 0400` |
| `emu-classics` | 6 | 4 | 10 | yes | `0080 ff7f ff7f ff7f` |
| `ditto-drums` | 9 | 6 | 15 | yes | `0080 ff7f ff7f ff7f` |

**Two of mpc2emu's structures are real and we never documented them.** The superblock **checksum** — the sum modulo 2¹⁶ of the 255 little-endian u16 words spanning `0x000`–`0x1FD`, stored at `0x1FE` — matches on 7 of 7 discs; it is a validity test for the header we do not have. And a real **FAT** begins at block 2 on every disc (`0x0080` then `0x7fff` end-of-chain markers and ascending next-cluster words), which is very likely the actual allocation mechanism the empirical `unit × start + bias` fit in "Locating a bank" and "Resolving a chain to an address" approximates. Deriving the bank/sample addresses from the FAT instead of the measured fit is the most promising lead in this comparison — again a `src/` change for its own branch.

**The one genuine divergence is the fixedness.** mpc2emu's block geometry is not fixed across our corpus: `0x08 ∈ {6, 7, 9}`, `0x0C ∈ {2, 4, 6}`, `0x10 ∈ {9, 10, 12, 15}`, so the FAT's length and the directory's origin move per disc. A fixed-geometry read (root dir at 7–10) would misplace `ditto-drums`, whose directory is at block 15. Our pointer read subsumes mpc2emu's here rather than contradicting it: mpc2emu's numbers are the values `esi32-gm`/`eiiix` happen to take, accurate for its own medium or corpus and not universal. **So there is nothing to correct upstream** — its structural facts are right and enrich us; only its "fixed" framing is corpus-specific, which is a difference in generality, not an error. (`E-MU Vintage Pro`, a `.bin`, is excluded from the table: it is a 2352-byte-sector image whose filesystem does not start at byte 0 ([ADR-0005](../adr/0005-probe-for-the-filesystem-origin.md)), so a raw read of byte 0 sees sector sync, not `EMU3` — a probe artifact, not a divergence.)

## Traps

- The EMU3 header carries a real superblock checksum at `0x1FE` (sum mod 2¹⁶ of the u16 words over `0x000`–`0x1FD`) and a FAT from block 2; the block geometry is **not** fixed. mpc2emu documents it as fixed — true for its corpus, not ours, where `0x10` takes four values. Read `0x08`/`0x0C`/`0x10`; never assume the geometry.
- `0x08` is the folder table, not a bank directory. Only the flags word tells them apart, and reading the wrong one gives a believable short listing.
- Names are padded with spaces **or** NULs. Requiring one silently drops banks.
- Contiguity of `start`/`len` is a coincidence on simple discs. It breaks on 41 of 46 banks on `eiiix-2`.
- The `start` field is not a byte address, and the allocation unit is not one value across discs.
- Sample records are found, not chained; the chain has gaps.
- The bank signature is not always `EMULATOR`. `protozoa` writes `EMU SI-32 v3` on two banks, and a bank nobody locates hands its region to the bank in front of it.
- One bank name can have two headers. `esi32-gm`'s duplicates sit *below* the directory's copy and `protozoa`'s sits *above* it, so neither "first" nor "last" is a rule.
- A header's `+16` name can be a mistyped copy of the directory's — `Electric Grand X` written `Eelectric GrandX`. Bind it by the address the placement predicts, gated on the name being within one normalised edit and unclaimed; never by address alone, or `ditto-drums`'s `E3 Main Code` binds the header its arithmetic lands on ([ADR-0031](../adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)).
- A bank's region holds more than the bank. Everything past `0x30 + 74 + 0x34` is the previous occupant's, and it is inside the region, so no bound between banks excludes it.
- The payload is little-endian. A sector-aligned measurement says otherwise and is wrong.
- The E-IV **sample directory** is big-endian, alone in the format. The trap runs both ways.
- The flags word is not a folder test. `eiv-studio` writes `0x0013` and `0x0018`, and requiring `0xFFFF` costs that disc 153 of its 230 banks.
- Each folder's bank directory must be bounded by the next folder's start block; they sit two blocks apart on `eiv-studio`.
- On E-IV the record's own length field is unusable and the directory's is authoritative. The EIII rule matches 0 of 5 349 consecutive pairs.
- An E-IV sample directory can appear twice. Deduplicate by address or every one of its records is listed twice.
- An E-IV bank with no flat `E3S1` directory at its predicted base is not empty. 170 of 788 across twelve discs are native `FORM/E4B0` IFF banks, samples as `E3S1` chunks inside; the same fit predicts both, and reading the chunks recovers ~2 017 samples ([ADR-0032](../adr/0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)).
- A `FORM/E4B0`'s declared size understates it by 4–12 bytes — the last `E3S1` chunk overruns it and garbage follows. Bound where a chunk may *begin* by the size, its body by the image; bounding the body by the size drops 91 of `eiv-studio`'s samples.
- A `FORM/E4B0` with no `E3S1` chunk (`Credits`, `E-mu Systems 96`) is genuinely sample-free and gets its own note, not the `no sample directory` one — that wording is wrong for a bank that carries audio without a flat directory.
- The paired length fields **are** a channel count, and the measurement that said otherwise tested interleaved stereo when the format splits into blocks. 2 843 samples are stereo.
- A channel count is not enough on its own. Require `end_L + 2 == start_R`. It rejected 65 records when the extent came from `+34`; it rejects none now, and it is what makes the extent's own two-channel test exact.
- The two halves of a decaying note correlate at 0.94 by RMS envelope, so that measure cannot tell a stereo pair from a single note. Divide the envelope by its own trend, or correlate the waveform at a lag.
- Name pairing is the *rare* mechanism here, not the rule: 14 samples across ten discs against 2 843 declaring two channels in the record.
- The sample record's fields are at `+22`, `+26`, `+30` … `+50`, not at `+24`, `+28`, `+32` … A four-byte stride begun at `+18` straddles two real fields at every step and reads as nine-digit noise.
- `+22` is a start pointer, not a header length. It reads 0 where a record declares no left channel, and requiring 92 drops a fifth of `eiv-studio` and every right-declared record on an EIII disc — 1 371 of them.
- **`+34` is not the record length.** It is the right channel's end, and it closes the record only where the right-hand set describes it: it is 92 bytes short on a mirror-92 record, zero on a record with the side unused, and a memory-frame address on some banks. Read the end of the set whose start is 92 ([ADR-0029](../adr/0029-a-record-is-closed-by-the-channel-it-declares.md)).
- A record may declare its one channel on the **right** on an EIII disc too, not only on E-IV. Scan for 92 at `+26` as well as at `+22`, or `vintage`'s `Juno Synths` reads as an empty bank.
- A bank's declared run is an independent check on the record extent, and it was already in this doc reading as a loose fit. If the last record of a bank stops one 92-byte header short of `0x30 + 74 + 0x34`, the extent is wrong, not the run.
- A loop end past the payload must be **refused**, not clamped back the way AKAI and Roland clamp theirs. Clamping turns a splice correlation of +0.86 into −0.10 on `protozoa`'s own records.
- The whole-extent "no loop" is written **inset by a fixed few bytes at both ends**, not at frame 0. Refusing only the start-0 case shipped a loop over the entire file on 934 of `ditto-drums`'s 948 records. It ends in silence and carries no uniquely-splicing loop point, and is refused within `FULL_EXTENT_SLACK` of both bounds (ADR-0030).
- There is no root key in the sample record. No byte tracks the note in the sample's name above chance, and `+58` — the field that looks most like one — is the sample rate.

## What `protozoa` taught, in one place

That disc was the awkward one throughout, and every awkwardness turned out to be the same thing seen from a different side.

Its two `4k` banks carry the third bank signature; nothing located them, so `Orbit Presets  X` and `Phatt Presets  X` were handed their regions and reported their records a second time. Its `Phatt Presets  X` is written twice, so the copy at the end of the image was discarded as a duplicate name and `Protozoa       X` ran to EOF. And every one of its banks carries the tail of a previous occupant inside its own region, which no bound between banks can reach.

The bank's own `0x30`/`0x34` answers all three, and the check is that every record the bound drops can be shown to be another bank's, at a constant shift — 264 of 264, 70 of 70, 59 of 59, 42 of 42, and so on for all fifteen located banks. `protozoa` now yields 16 volumes and 6 595 samples, with `Orbit Presets 4k` and `Phatt Presets 4K` extracting 558 and 255 under their own names where they previously listed empty. (Those were 5 852, 535 and 239 between ADR-0021 and ADR-0029; the difference is the record extent, not the bank bound.) ([issue #15](https://github.com/bmxcode/samplerdisc/issues/15), [ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md))
