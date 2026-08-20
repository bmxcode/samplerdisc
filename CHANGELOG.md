# Changelog

Notable changes to `samplerdisc`. Format-level findings live in [docs/formats/](docs/formats/); decisions and their rejected alternatives live in [docs/adr/](docs/adr/). This file records what changed for someone using the tool.

## Unreleased

### Added

- **Emulator IV discs extract their samples.** All three E-IV discs in the reference collection previously listed their banks with correct names and yielded nothing; they now give **449, 2 822 and 828 samples**. E-IV banks carry no `EMULATOR` header — not one occurrence across 1.2 GB — and are reached through a chained `E3S1` sample directory instead, whose big-endian length is what sizes each sample. ([docs/formats/emu3.md](docs/formats/emu3.md), [ADR-0020](docs/adr/0020-read-e-iv-through-its-sample-directory.md))

  [ADR-0015](docs/adr/0015-locate-banks-by-signature.md) held this back deliberately and conditionally, on the grounds that one specimen cannot distinguish a format from that disc's quirks. Three discs from two publishers met the condition, and the third earned its place: two constants that hold perfectly on the two Producer Series discs fail outright on the Miroslav Vitous one, and a two-disc study would have written one of them down as fact.

  The four EIII/ESI discs are byte-for-byte unchanged — 2 424, 1 189, 1 333 and 6 788 samples — which is the check that the shared record parser was not disturbed. Two of those four numbers were themselves wrong, for a different reason, and are corrected below.

- **`protozoa`'s two Formula 4000 banks extract.** `Orbit Presets 4k` and `Phatt Presets 4K` open with `EMU SI-32 v3` where every other bank on that disc opens with `EMULATOR 3X`. Nothing recognised the signature, so neither was located — and an unlocated bank is not merely unread, it is also not a boundary, so the bank in front of each was handed its region too. They now give **535 and 239 samples** under their own names. ([docs/formats/emu3.md](docs/formats/emu3.md), [ADR-0021](docs/adr/0021-a-bank-owns-the-run-its-header-declares.md))

### Fixed

- **A folder table whose entries do not say `0xFFFF` is no longer discarded.** `Producer Series Vol. 1 – Studio Essentials` writes flags `0x0013` and `0x0018` on its first two folder entries. The walk required `0xFFFF`, aborted on entry 0, found no folders at all and silently fell back to the single bank directory the header points at — **77 banks of the 230 that disc has**, with no error and a listing that looked complete. The folder table does not need the test: the header pointer already says what it is.
- **Each folder's bank directory is bounded by the next folder's start block.** They sit two to six blocks apart on that disc, so an unbounded walk ran out of one directory and into the next, reporting the neighbour's banks a second time.
- **An E-mu bank no longer reports its neighbour's samples as its own.** A bank was bounded by the next located bank header, and a bank's region holds more than the bank: mastering writes a bank image into a fixed region and whatever was there before survives past its end. It is now bounded by the record run its own header declares at `0x30`/`0x34`, which the disc states and no bound drawn between banks can substitute for. ([ADR-0021](docs/adr/0021-a-bank-owns-the-run-its-header-declares.md), [#15](https://github.com/bmxcode/samplerdisc/issues/15))

  **Two sample counts move, and both old numbers were wrong.** `protozoa` goes from 6 788 to **5 852** and `esi32-gm` from 2 424 to **2 265**. Every record dropped was shown to be another bank's, at a constant offset — 264 of 264 for `Vintage+InstrmtX`, 70 of 70 for `Phatt Presets  X`, and so on for all fifteen of `protozoa`'s located banks. If you extracted either disc before, some of what you got was duplicated audio filed under the wrong bank; `eiiix-1`, `eiiix-2` and the three E-IV discs are unchanged.

  `esi32-gm` was not suspected — the issue records it as unaffected. Its last bank ran to the end of the image and was credited with 193 records belonging to the two banks in front of it, and separately, two of its banks are written twice on the disc and the older revision was the copy being read. Where one name has two headers, the reader now takes the one the directory placed.

- **The bank-count baselines are asserted rather than written down.** The whole-disc figures in the format doc are now a table in `tests/test_discs.py`, pinned by disc size. They were the stated regression guard for the shared record parser and nothing checked them, which is how two of them shipped wrong.
- **A bank with no header on an EIII/ESI disc says so in its own terms.** `E3 Main Code` and `E3X Main Code` — the sampler's operating system, occupying a bank slot — were told they had "no sample directory", naming an E-IV structure those discs do not use.

### Known limits

- **100 of `Studio Essentials`'s 230 banks list without extracting.** They have no confirmed sample directory, and carry a note saying so rather than being guessed at. That disc holds 901 `E4P1` presets and preset-only banks are the likely explanation — likely is not established, so it is not claimed.
- **An E-mu bank whose `0x34` is damaged will list empty and say the header declares no sample area.** The field bounds the walk now, so the note that follows an empty bank restates that bound rather than corroborating it independently — the note is true about the header and would be wrong about the bank. The alternative was measured and is worse: `protozoa`'s index bank would be credited with 63 of the Phatt banks' records. ([ADR-0021](docs/adr/0021-a-bank-owns-the-run-its-header-declares.md))
- **Loop points and root key are still absent from E-mu WAVs.** Eight fields in the 92-byte sample header are undecoded and some are very likely those. Decoding them changes the *shared* record parser and would alter every E-mu sample already extracted, so it is its own piece of work rather than a rider on this one.
- **The E-mu sample record has no channel count.** The paired length fields at `+26`/`+30` and `+34`/`+50` look exactly like one — `+34 == 2 × (+30) − 90` on both EIII and E-IV — and measurement says otherwise: de-interleaving any of these payloads as stereo roughly doubles its sample-to-sample delta, the known-good `Piano E0` included. Everything is mono, and stereo pairs are joined by name as on every other format.

## 0.3.0 — 2026-08-20

### Added

- **Roland S-7xx discs read.** The `S770 MR25A` filesystem — S-770, S-750 and S-760 — is now a backend, verified against nine discs spanning every system-disk lineage the archives hold: Ver. 1.04, 1.06, 2.19, 2.21, 2.25 and the S-760's 2.23Y and 2.24s. Five read end to end; four more were confirmed by range-fetching four regions each. The five local ones yield **6 392 samples and 1 341 stereo pairs with nothing skipped**, every payload byte-identical to its disc. Root key and loop points travel into each WAV's `smpl` chunk. ([docs/formats/roland-s7xx.md](docs/formats/roland-s7xx.md))

  These discs previously reported "no recognised filesystem". If you shelved a Roland disc on that basis, try it again.

- **Stereo pairs are rejoined on every format, not just AKAI.** Roland marks the two halves of a stereo sound with byte `0x7F` before the `L`/`R` rather than a hyphen, and the joiner only knew about hyphens — so `northstar`, where 1 110 of 1 284 samples are one half of a pair, came out entirely mono. The separator is now a character class. ([ADR-0017](docs/adr/0017-the-stereo-side-marker-is-a-character-class.md))

### Known limits

- **A Roland disc comes out as one flat volume.** Its samples are grouped through a volume → performance → patch → partial chain; the middle two record formats are undecoded, and guessing them would misfile samples with nothing reporting it. Every sample is listed under the disc's own `ID<n>:` label instead. ([ADR-0016](docs/adr/0016-the-s7xx-hierarchy-is-located-not-walked.md))
- **The `.mds` track table is still unread.** Geometry is sniffed from the `.mdf` — sync pattern means raw sectors, otherwise cooked — which is correct for the single-track data discs these are, and confirmed against the one pair in hand. A multi-track or offset image would be read from byte 0 and come out wrong.
- **Roland sample rates are written as 44 100 rather than read.** No rate field has been identified, and measuring pitch cannot separate 44 100 from 22 050 because they differ by exactly one octave — the interval pitch estimation resolves worst and an original key can itself be wrong by. All nine reference discs measure 44 100. A 22.05 kHz disc would come out an octave high, uniformly, with nothing reporting it. ([ADR-0018](docs/adr/0018-the-s7xx-sample-rate-is-measured.md))

### Fixed

- **ISO 9660 discs are read through Joliet, so long filenames survive.** `Digital Sound Factory - E-MU Vintage Pro` listed 1 062 files under 1 002 paths: MagicISO caps its 8.3 short names at twelve characters in total and lets the `~N` counter eat the extension, so **61 separate files all came back as `VINTAG~0.EXB/SAMPLE~0/VINTA~1000.E`**. The disc carried a Joliet descriptor with the real names — `Vintage Pro.exb/SamplePool/Vintage ProSL001.ebl` and so on, all 1 062 distinct — the whole time. Where a disc has Joliet it is now the name space we walk. ([docs/formats/iso9660.md](docs/formats/iso9660.md), [ADR-0019](docs/adr/0019-prefer-joliet-names.md))

  Nothing was lost to this: `unique_path` was already suffixing collisions, and `BSBSSD2` — the only other ISO 9660 disc tested — extracts byte-for-byte identically to before, because its short names were already unique. What changes is that listings and filenames now carry the disc's own capitalisation, spacing and extensions rather than an uppercase approximation.

- **Apple resource forks were extracted as if they were audio.** Bit 2 of an ISO 9660 directory record marks an *associated file* — a second record wearing the data file's name and pointing somewhere else, which Apple-mastered discs use for the resource fork. Thirteen discs in the reference collection carry them, and on each one the number of duplicated paths equalled the number of flagged records exactly: 1 388 of ProSamples vol. 43's 4 189, 359 of vol. 52's, 115 of vol. 40's. Nothing was lost — `unique_path` suffixes — but 8 590 bytes of fork metadata came out as an `.aif` beside the real 2 MB sample, a file that opens, plays as noise and reports nothing wrong. Records flagged `0x04` are now skipped, and all fifteen ISO 9660 discs list zero duplicate paths.
- **A damaged Joliet descriptor no longer takes the disc down with it.** Preferring Joliet is a decision about names, not about whether a disc reads; a supplementary descriptor with a bad root extent used to discard an intact primary tree and report an empty disc. The walk now falls back.
- **An ISO 9660 volume label stops at the first NUL.** The field is meant to be space-padded; MagicISO NUL-terminates it and leaves the buffer's previous contents behind. Vintage Pro was reported as `VintagePro 57`, the `57` two stray bytes of its volume set identifier `20101002_0257`. It is `VintagePro`.

- **A `.mds`/`.mdf` pair was refused.** The split `.mds` descriptor opens with the same `MEDIA DESCRIPTOR` magic as a merged `.mdx`, and detection tested that magic before it tested anything else — so every real `.mds` went to the MDX parser and came back as `implausible descriptor offset 0`, and the `.mds` branch of the detector was unreachable for the input it exists for. The major version at `0x10` tells the two apart — `01` split, `02` merged — and is now what routes them, by signature rather than by extension ([ADR-0004](docs/adr/0004-detect-by-signature.md), [docs/formats/mdx.md](docs/formats/mdx.md)).

  The first pair to be tried on it, `Back In Time Records Korg Universe vol.1`, reads as 260 287 sectors carrying an AKAI filesystem — five volumes, 159 files. If you have a `.mds`/`.mdf` disc that this tool refused, try it again.

- `--no-stereo` described the pairing as "-L/-R" in `extract` and `batch`, which is now only half the story.

## 0.2.0 — 2026-08-19

### Fixed

- **The AKAI probe claimed discs that were not AKAI.** `samplerdisc info` reported an E-mu `EMU3` disc and a Digidesign SampleCell disc as `akai` at confident, wrong offsets (3 465 216 and 5 496 832). Neither raised; each produced volumes named things like `010000000000` with zero files in every one, which reads as an empty disc rather than as an error. The probe tested the volume directory for *structure* and never asked whether a volume held a file. It does now. Measured across 40 discs, the fix changed exactly two resolved origins — both the false positives — and left all 22 genuine AKAI discs untouched. ([ADR-0012](docs/adr/0012-a-probe-must-confirm-a-file.md))

  If you triaged a collection with 0.1.0, re-run `samplerdisc info`: some discs were labelled with the wrong manufacturer.

- **A mislabelled AKAI disc now reads.** `OMI - Sonic Images Universe Of Sounds Vol.1`, filed by its archive as a Roland S-770 disc, is AKAI — 28 volumes, 636 samples. It was being shadowed by the probe bug above.

### Added

- **E-mu `EMU3` filesystem support**, covering EIIIX, ESI-32, ESI-4000/Formula 4000 and Emulator IV. The archives sell these as separate generations; the disc format is one thing at the directory level. Extraction works for EIII/ESI banks. Emulator IV discs list their folders and banks correctly but do not extract — the bank interior is a different layout with one specimen available, and one disc cannot tell a format from a quirk. ([docs/formats/emu3.md](docs/formats/emu3.md), [ADR-0014](docs/adr/0014-one-backend-per-on-disc-format.md), [ADR-0015](docs/adr/0015-locate-banks-by-signature.md))

- **`extract --assume-audio-cd`** writes a whole disc as one stereo WAV, for a Red Book disc that arrives without a cue sheet. Track boundaries still need a cue — they are not in the bytes — but whether the *content* is CD audio can be measured, and `samplerdisc info` now says so when it is. The flag is your assertion and the tool re-checks it rather than obeying, because a false positive writes hundreds of megabytes of noise and reports success. ([ADR-0013](docs/adr/0013-cueless-audio-is-reported-not-guessed.md))

- **`samplerdisc info` explains an all-stored MDX.** An image where every block is stored is either incompressible content or a block size that could not be measured, and the two look identical from inside the container. It now reports which it knows and which it does not.

- **Opt-in disc-backed tests** via `SAMPLERDISC_TEST_DISCS`, which ADR-0008 has described since the first commit and nothing implemented. They assert an invariant that holds for any collection rather than a table of one person's filenames: no backend may claim a disc and then produce nothing.

### Changed

- A volume that a backend recognises but deliberately cannot extract now carries a note saying why, and `list` prints it. Without that, "listed but not extractable" and "the probe matched garbage" are indistinguishable to anything but a person reading the names.

- Extraction dispatches sample parsing through the backend instead of assuming AKAI, keeping format knowledge out of the shared path ([ADR-0003](docs/adr/0003-brand-neutral-pluggable-backends.md)).

### Documentation

- `docs/formats/mdx.md`: a second MDX generation is documented (2015, `Disc Soft Ltd.`, version `02 01`), and the claim that an inverted stored/compressed ratio signals a misparse is corrected. An image of a Red Book audio CD is legitimately 100 % stored, because PCM does not deflate. ADR-0006's decision is unaffected and carries a pointer rather than an edit.
- `docs/formats/audio-cd.md`: what a cue-less audio disc looks like, with the measured margins.
- `docs/formats/emu3.md`: new, including the traps — the folder table that reads as a bank directory, names padded with NULs rather than spaces, and a payload whose endianness inverts if you sample it at sector boundaries.

### Known gaps

Roland (S-770 and S-550), Ensoniq and Kurzweil filesystems are not read yet. Emulator IV banks list but do not extract. `.mds`/`.mdf` remains untested — no specimen has been found across three collections.

## 0.1.0 — 2026-08-18

First public release. Containers (`.mdx` including compressed, `.nrg`, raw CD `.bin`/`.cue`, `.iso`, `.cdr`, `.tao`), the AKAI S1000/S3000 filesystem, ISO 9660, Red Book audio CDs, WAV output with loop points and root key in the `smpl` chunk, stereo rejoining, `batch` with a JSON manifest, and `export-iso` as the escape hatch.
