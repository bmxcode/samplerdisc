# E-mu `EMU3`

The filesystem E-mu wrote on CD-ROMs for the Emulator III, EIIIX, ESI-32, ESI-4000 and Emulator IV. The archives file these as separate generations; the disc does not. All seven reference discs write `EMU3` at byte 0 and share one directory format.

The *bank interior* is not shared. EIII/ESI banks carry a bank header and are located by it. E-IV banks carry none at all — not one `EMULATOR` string on any of the three E-IV discs — and reach their samples through an `E3S1` sample directory instead ([ADR-0020](../adr/0020-read-e-iv-through-its-sample-directory.md)).

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
| 34 | 4 | u32 LE `end_R` — the same field as the record length, **two short** of the distance to the next (EIII only) |
| 38 | 4 | u32 LE `loop_start_L` |
| 42 | 4 | u32 LE `loop_start_R` |
| 46 | 4 | u32 LE `loop_end_L` |
| 50 | 4 | u32 LE `loop_end_R` |
| 54 | 4 | u32 LE **sample rate** |
| 92 | … | sample data |

The signature — 92 at `+22`, a plausible rate, sixteen printable name bytes — is specific enough to scan megabytes of audio without false hits. On `esi32-gm`'s `8M GeneralMidi X` bank it yields **452 records with 452 distinct names** totalling 7.00 MiB inside a bank declaring 8 MiB.

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
| `esi32-gm` | 28 | 0 | 2 230 | 0 | 7 |
| `eiiix-1` | 601 | 40 | 380 | 0 | 168 |
| `eiiix-2` | 592 | 6 | 680 | 0 | 55 |
| `protozoa` | 8 | 19 | 5 791 | 0 | 34 |
| `eiv-analogia` | 279 | 0 | 146 | 8 | 16 |
| `eiv-studio` | 320 | 0 | 1 882 | 542 | 78 |
| `eiv-vitous` | 828 | 0 | 0 | 0 | 0 |
| **total** | **2 656** | **65** | **11 109** | **550** | **358** |

**"Contradicted" is a shape of its own and it must be rejected**, not counted as stereo: the record declares `start_R` half a payload on and then closes its left channel somewhere else. See "Stereo" below for what those 65 records turn out to hold. The "neither" column is records whose `start_R` is none of the three values — not a right-hand single channel, which is an ordinary record and is counted as one here. An earlier revision of this table folded those 550 into "neither", giving 620 for `eiv-studio` and 24 for `eiv-analogia`.

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

That is most of why the reference disc yields fewest. On about 2 200 of `esi32-gm`'s records `end_L` runs roughly 45 frames past the payload its own length field produces, and 95% of the disc is refused on it.

**Which of the two is right is open.** If the record's extent is correct, the reader is 90 bytes short on those samples. Scanning candidate ends across ±96 frames and taking the shape-test peak does *not* confirm it: the peak lands within ±2 frames of the declared end on **10%** of `esi32-gm`'s records and 20% of `protozoa`'s, where a uniform peak would give about 3%. Better than chance, nowhere near an answer. Nothing is changed on the strength of it.

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

**The third condition is not decoration.** 2 721 records across the seven discs satisfy the first two and **65 fail the third**: 19 on `protozoa`, 40 on `eiiix-1`, 6 on `eiiix-2`. They declare a left channel that overlaps the right block — `protozoa` writes `end_L` exactly 8 bytes past `start_R` on 18 records — or one that stops well short of it, as `eiiix-1`'s `LP Up Stroke` does at 24 766 bytes of a 36 402-byte half.

Those 65 are not stereo, and `protozoa` says what six of them are. `Trom B2`, `Trom E3` and `Trom A3` are each written in two banks, and in all six records the **first half is byte for byte the whole of a one-channel record of the same name** in `Vintage PresetsX` — 16 756 bytes of `Trom B2` against a 33 512-byte payload. Nothing on the disc matches the second half. The payload is twice the sound, so `start_R` lands on `start_L + P/2` by arithmetic rather than by declaration, and `end_L` is what gives it away: it closes the audio 8 bytes *past* the halfway point instead of on it.

**2 656 records pass all three**, which is what this project writes as stereo:

| Disc | stereo | of samples |
|---|---|---|
| `esi32-gm` | 28 | 2 265 |
| `eiiix-1` | 601 | 1 189 |
| `eiiix-2` | 592 | 1 333 |
| `protozoa` | 8 | 5 852 |
| `eiv-analogia` | 279 | 449 |
| `eiv-studio` | 320 | 2 822 |
| `eiv-vitous` | 828 | 828 |

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

### The first block is the left channel

Structural: the pointer block is ordered `(start_L, start_R)` and `start_L` addresses the first block.

The only content evidence is weak and agrees with it. Of `eiv-analogia`'s twelve name-paired records, all **six** ending `-L` declare their single channel in the left-hand set and three of the six ending `-R` declare theirs in the right-hand set — nine of twelve consistent, **none contradicting**, *p* ≈ 0.09. Recorded for what it is: the decision rests on the field order, not on this ([ADR-0026](../adr/0026-the-record-declares-the-channel-count.md)).

### A one-channel record that is really stereo does not occur here

The inverse error was looked for. **Not one of the 12 017 records that do not declare the two-channel shape declares an extent of half its payload**, which is the structural signature it would leave. The 439 whose halves correlate above 0.9 by envelope show a midpoint z-jump of −0.27 to −0.41 — no discontinuity where a block join would be — and they are the decaying single notes above.

`eiiix-2` is the disc to check, because an earlier revision of this section gave it the weakest separation in the table at 0.59 for one-channel records. Under these instruments its high-envelope one-channel records score fine structure **−0.021**, which is the negative control, and its one-channel envelope median re-measures at **0.114** over 603 scored records. Both figures are recorded; the 0.59 is not reproduced by the measurement here and is not relied on either way.

### The loop points are unaffected

`(pointer − start) / 2` is a per-channel frame index either way: in the double-length mono file this format produced before D18 it landed in the left block, and in the interleaved file it is the frame number. All seven per-disc loop counts are unchanged across the fix, which is the check that the two decodes of one pointer block agree.

The two records anywhere whose declared loop end lies past its own channel — `Mbira A3` and `Mbira F3` on `eiiix-1` — are both among the 65 the third condition rejects, so they stay mono and keep their loops.

### Name pairing is the other mechanism, and it is the rare one

E-IV discs *also* pair separate mono records into stereo by name, the way the rest of the collection does ([ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md)). Both mechanisms are real and they do not overlap: **12** samples across all seven discs are name-paired — six pairs, all on `eiv-analogia` — against **2 656** whose own record declares two channels, and no sample is both. An earlier revision of this doc gave name pairing as the answer to how these discs do stereo, which is the rare case given as the rule.

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
| Bank declares (`0x30`, `0x34`) | sample area at 138 243, run of 8 248 316 |
| First record | `Piano E0`, rate 12 000, 146 852 bytes of PCM |

Whole-disc listings, with the samples the record declares stereo:

| Disc | Volumes | Samples | Stereo |
|---|---|---|---|
| `esi32-gm` | 10 | 2 265 | 28 |
| `eiiix-1` | 46 | 1 189 | 601 |
| `eiiix-2` | 46 | 1 333 | 592 |
| `protozoa` | 16 | 5 852 | 8 |
| `eiv-analogia` | 12 | 449 | 279 |
| `eiv-studio` | 230 | 2 822 | 320 |
| `eiv-vitous` | 44 | 828 | 828 |

**2 656 of 14 738**, and a stereo sample is still one sample: the counts above do not move when the channel count is read, only the file's shape does.

Samples carrying a loop, of those totals:

| Disc | Samples | With a loop | |
|---|---|---|---|
| `esi32-gm` | 2 265 | 107 | 5% |
| `eiiix-1` | 1 189 | 1 157 | 97% |
| `eiiix-2` | 1 333 | 1 260 | 95% |
| `protozoa` | 5 852 | 1 689 | 29% |
| `eiv-analogia` | 449 | 449 | 100% |
| `eiv-studio` | 2 822 | 2 551 | 90% |
| `eiv-vitous` | 828 | 826 | 100% |

**8 039 of 14 738.** The two low ones are the discs that declare a loop end past the audio they carry, which is refused rather than clamped.

These are the regression baseline: any change to the shared record parser is a bug if they move. **They are now asserted by `tests/test_discs.py`, pinned by disc size** — a table in a document is a note, not a test, and two of these numbers were wrong for a release with a green suite. The suite also pins the **SHA-256 of every sample payload per disc**, because a count table cannot see a payload that shifted by a byte while staying the same length, and the **stereo counts** beside them, because the third condition of the gate is exactly the kind of thing a later simplification removes. On a stereo sample the suite additionally de-interleaves what was written and requires it to reproduce the disc's two blocks byte for byte: the audio moved, and it must be the same audio.

`esi32-gm`'s 2 424 and `protozoa`'s 6 788 are what the previous revision of this table gave, and both counted another bank's records; [ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md) has the accounting. `esi32-gm` is the instructive one: it was believed clean, and its last bank ran to the end of the image and was credited with 193 records belonging to the two banks in front of it.

Each of the four EIII/ESI discs lists one index bank with a note and no samples, which is why their volume counts run one ahead of the banks that extract; `esi32-gm`, `eiiix-1` and `eiiix-2` also list the sampler's own code banks — `E3 Main Code`, `E3X Main Code` — which carry no bank header and are noted as such. On `eiv-studio`, 100 of the 230 banks have no confirmed sample directory and are listed with a note rather than guessed at. That disc carries 901 `E4P1` presets, and preset-only banks are the likely explanation — it is not established, so it is not claimed.

## Traps

- `0x08` is the folder table, not a bank directory. Only the flags word tells them apart, and reading the wrong one gives a believable short listing.
- Names are padded with spaces **or** NULs. Requiring one silently drops banks.
- Contiguity of `start`/`len` is a coincidence on simple discs. It breaks on 41 of 46 banks on `eiiix-2`.
- The `start` field is not a byte address, and the allocation unit is not one value across discs.
- Sample records are found, not chained; the chain has gaps.
- The bank signature is not always `EMULATOR`. `protozoa` writes `EMU SI-32 v3` on two banks, and a bank nobody locates hands its region to the bank in front of it.
- One bank name can have two headers. `esi32-gm`'s duplicates sit *below* the directory's copy and `protozoa`'s sits *above* it, so neither "first" nor "last" is a rule.
- A bank's region holds more than the bank. Everything past `0x30 + 74 + 0x34` is the previous occupant's, and it is inside the region, so no bound between banks excludes it.
- The payload is little-endian. A sector-aligned measurement says otherwise and is wrong.
- The E-IV **sample directory** is big-endian, alone in the format. The trap runs both ways.
- The flags word is not a folder test. `eiv-studio` writes `0x0013` and `0x0018`, and requiring `0xFFFF` costs that disc 153 of its 230 banks.
- Each folder's bank directory must be bounded by the next folder's start block; they sit two blocks apart on `eiv-studio`.
- On E-IV the record's own length field is unusable and the directory's is authoritative. The EIII rule matches 0 of 5 349 consecutive pairs.
- An E-IV sample directory can appear twice. Deduplicate by address or every one of its records is listed twice.
- The paired length fields **are** a channel count, and the measurement that said otherwise tested interleaved stereo when the format splits into blocks. 2 656 samples are stereo.
- A channel count is not enough on its own. 65 records declare `start_R` half a payload on and then close `end_L` somewhere else; their halves are unrelated audio, and on `protozoa` the second half is another bank's record. Require `end_L + 2 == start_R`.
- The two halves of a decaying note correlate at 0.94 by RMS envelope, so that measure cannot tell a stereo pair from a single note. Divide the envelope by its own trend, or correlate the waveform at a lag.
- Name pairing is the *rare* mechanism here, not the rule: 12 samples across seven discs against 2 656 declaring two channels in the record.
- The sample record's fields are at `+22`, `+26`, `+30` … `+50`, not at `+24`, `+28`, `+32` … A four-byte stride begun at `+18` straddles two real fields at every step and reads as nine-digit noise.
- `+22` is a start pointer, not a header length. It reads 0 where a record declares no left channel, and requiring 92 drops a fifth of `eiv-studio`.
- A loop end past the payload must be **refused**, not clamped back the way AKAI and Roland clamp theirs. Clamping turns a splice correlation of +0.86 into −0.10 on `protozoa`'s own records.
- There is no root key in the sample record. No byte tracks the note in the sample's name above chance, and `+58` — the field that looks most like one — is the sample rate.

## What `protozoa` taught, in one place

That disc was the awkward one throughout, and every awkwardness turned out to be the same thing seen from a different side.

Its two `4k` banks carry the third bank signature; nothing located them, so `Orbit Presets  X` and `Phatt Presets  X` were handed their regions and reported their records a second time. Its `Phatt Presets  X` is written twice, so the copy at the end of the image was discarded as a duplicate name and `Protozoa       X` ran to EOF. And every one of its banks carries the tail of a previous occupant inside its own region, which no bound between banks can reach.

The bank's own `0x30`/`0x34` answers all three, and the check is that every record the bound drops can be shown to be another bank's, at a constant shift — 264 of 264, 70 of 70, 59 of 59, 42 of 42, and so on for all fifteen located banks. `protozoa` now yields 16 volumes and 5 852 samples, with `Orbit Presets 4k` and `Phatt Presets 4K` extracting 535 and 239 under their own names where they previously listed empty. ([issue #15](https://github.com/bmxcode/samplerdisc/issues/15), [ADR-0021](../adr/0021-a-bank-owns-the-run-its-header-declares.md))
