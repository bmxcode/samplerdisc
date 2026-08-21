# Changelog

Notable changes to `samplerdisc`. Format-level findings live in [docs/formats/](docs/formats/); decisions and their rejected alternatives live in [docs/adr/](docs/adr/). This file records what changed for someone using the tool.

## Unreleased

### Added

- **AIFF payloads are converted, not copied out as `.aiff`.** An AIFF's samples are big-endian and a WAV's are little-endian, so the bytes within each value are reversed and the values are left alone — a re-ordering, exactly reversible, with no resampling or change of depth. Root key, tuning and the sustain loop come across from the AIFF's `INST` and `MARK` chunks into the WAV's `smpl`. ([docs/formats/aiff.md](docs/formats/aiff.md), [ADR-0024](docs/adr/0024-the-aiff-twin-is-converted-and-deduplicated.md))

  AIFF-C is refused rather than guessed at — its payload may be compressed, and compressed data written out as PCM opens, plays as noise and reports nothing wrong. 8-bit is refused too: AIFF stores it signed and WAV unsigned, so carrying it would mean adding 128 to every sample, which is a change to the values and not to their order. Nothing in the collection is either.

  **The loop convention was not guessed.** An AIFF marks its loop with two `MARK` positions and the spec does not say whether the frame at the second is played. The Best Service ProSamples discs carry a WAV of every sound beside the AIFF, and a WAV states its loop in a `smpl` chunk where the end *is* inclusive — so the two files answer the question about each other. On **195 of 195** pairs carrying a loop on both sides, the end marker is exclusive; on all **198** carrying an `INST`, the root key matches exactly.

- **Duplicate audio on a disc is written once.** The thirteen ISO 9660 ProSamples discs ship each sound twice, as a full AIFF tree beside a full WAV tree — 7 926 WAV and 7 498 AIFF, of which **6 033 hold audio already coming out as a WAV**. Those are now reported as duplicates naming the file that holds the audio, instead of being written a second time. ([ADR-0024](docs/adr/0024-the-aiff-twin-is-converted-and-deduplicated.md))

  Matched on the audio, never on the filename, and `vol.43` is why: its 1 386 AIFF all share a name with a WAV and **not one shares its audio**, being mastered a few frames longer — 17 638 bytes against 17 616 on `43e-01chh01`. A name-based rule would have discarded that whole disc and said nothing.

  A twin is also kept where it carries something the written file lacks. On **314** pairs the AIFF has a root key and a loop and the WAV has no `smpl` chunk at all; the audio is the same and the files are not.

- **EXS24 and HALion instruments are kept by `--keep-originals`.** `.exs`, `.fxp` and `.fxb` classify as programs, joining the vocabulary AKAI programs already used — they hold the key ranges and envelopes a WAV cannot carry, which is the argument [ADR-0011](docs/adr/0011-the-deliverable-is-daw-ready-wav.md) already made, and they are the shape [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) reads. Roughly 2 200 across the collection, previously dropped.

- **Every partition of an AKAI disc is read, not just the first.** An AKAI disc is a disk image — several partitions laid end to end — and the walk stopped at the one the origin resolved to. Across the 44 AKAI discs on the shelf that is the difference between **448 volumes and 14 670 files** and **2 154 volumes and 68 997 files**; the collection goes from 872 volumes and 56 662 files to **2 578 and 110 989**. `Loop Soup` alone goes from 7 volumes to 60. ([docs/formats/akai-fs.md](docs/formats/akai-fs.md), [ADR-0023](docs/adr/0023-partitions-come-from-the-table-the-disc-declares.md), [#22](https://github.com/bmxcode/samplerdisc/issues/22))

  The partitions are not guessed at. The disk declares them, in a table at `0x4500` of the first partition: a count, that many sizes in blocks, then the disk's total. All 44 discs carry one and on all 44 the sizes sum to the total. A partition is read only where a header sits at the position the table gives and restates the size the table gave it.

  Of the 44 174 samples this adds, **44 101 (99.83 %)** carry a payload header whose name matches the directory entry that placed them — the same rate as the partitions already being read. Partition 1's numbers do not move on any disc, and are pinned per disc so they cannot.

- **`list` says how many partitions the disc declares and how many the image holds.** `Kickin' Lunatic Beats 2 CD1` declares eleven and holds one: that image is short of the disc it was made from, and the ten missing partitions were previously an absence with nothing to see. ([ADR-0023](docs/adr/0023-partitions-come-from-the-table-the-disc-declares.md))

- **Emulator IV discs extract their samples.** All three E-IV discs in the reference collection previously listed their banks with correct names and yielded nothing; they now give **449, 2 822 and 828 samples**. E-IV banks carry no `EMULATOR` header — not one occurrence across 1.2 GB — and are reached through a chained `E3S1` sample directory instead, whose big-endian length is what sizes each sample. ([docs/formats/emu3.md](docs/formats/emu3.md), [ADR-0020](docs/adr/0020-read-e-iv-through-its-sample-directory.md))

  [ADR-0015](docs/adr/0015-locate-banks-by-signature.md) held this back deliberately and conditionally, on the grounds that one specimen cannot distinguish a format from that disc's quirks. Three discs from two publishers met the condition, and the third earned its place: two constants that hold perfectly on the two Producer Series discs fail outright on the Miroslav Vitous one, and a two-disc study would have written one of them down as fact.

  The four EIII/ESI discs are byte-for-byte unchanged — 2 424, 1 189, 1 333 and 6 788 samples — which is the check that the shared record parser was not disturbed. Two of those four numbers were themselves wrong, for a different reason, and are corrected below.

- **`protozoa`'s two Formula 4000 banks extract.** `Orbit Presets 4k` and `Phatt Presets 4K` open with `EMU SI-32 v3` where every other bank on that disc opens with `EMULATOR 3X`. Nothing recognised the signature, so neither was located — and an unlocated bank is not merely unread, it is also not a boundary, so the bank in front of each was handed its region too. They now give **535 and 239 samples** under their own names. ([docs/formats/emu3.md](docs/formats/emu3.md), [ADR-0021](docs/adr/0021-a-bank-owns-the-run-its-header-declares.md))

- **The AKAI partition's block allocation map is read.** At `0x70A`, one u16 per block, as many as the partition declares at `0x00`. It is the disc's own record of what every block holds, and it is verified rather than merely plausible: a file's chain length and the size its directory entry declares come from two different structures, and across all 44 AKAI discs they agree for **14 607 of 14 607 files**, exactly. `tests/test_discs.py` asserts that per disc, so an AKAI image that starts decoding wrongly now has something to fail against instead of presenting as a disc with less on it. ([docs/formats/akai-fs.md](docs/formats/akai-fs.md), [ADR-0022](docs/adr/0022-a-volume-is-explained-by-the-allocation-map.md))

### Changed

- **AKAI samples extract under their partition**: `out/partition-1/VOLUME 001/…` where it was `out/VOLUME 001/…`, on every AKAI disc including single-partition ones. Volume names repeat across a disc's partitions — nearly every one has a `VOLUME 001` — so a flat layout put two libraries' audio in one directory under `_2` suffixes with nothing saying which was which. The batch manifest keys volumes by partition and name for the same reason. ([ADR-0023](docs/adr/0023-partitions-come-from-the-table-the-disc-declares.md))

### Fixed

- **An AKAI volume that lists nothing now says why, in the disc's own words.** Ten volumes across three discs listed empty with no explanation, which is exactly the [ADR-0012](docs/adr/0012-a-probe-must-confirm-a-file.md) signature — it reads as an empty volume rather than as a wrong answer. Each now carries a note naming the block and what the partition's allocation map says is in it: file data on `Advance Orchestra` ×4 and the OMI disc, a free block on `Kickin' Lunatic Beats 2 CD1`, and — for four more on that disc — a block the disc says *is* a volume directory and the image has none at. ([#16](https://github.com/bmxcode/samplerdisc/issues/16), [#17](https://github.com/bmxcode/samplerdisc/issues/17), [ADR-0022](docs/adr/0022-a-volume-is-explained-by-the-allocation-map.md))

  **No volume or file count moves anywhere** — 872 volumes and 56 662 files across the collection, before and after, unchanged to the number. That is the point rather than a happy accident: the map explains an emptiness and never gates a listing, because the one-line fixes that *do* gate cost real audio. Rejecting volumes whose type byte is 0 discards four volumes carrying 63 files, and trusting the map as an allocation flag discards those and every volume on every S3000 and CD3000 disc besides.

- **The AKAI volume entry's type is read as a byte.** It was unpacked with the start block as one `<HH`, making the type a u16 — wrong, and it inflated the value by 256 per volume on the one disc that sets the byte at 13. Nothing read the type, and `start` at 14 was never affected, so no disc listed differently at any point; the field is now correct and documented, with volume types 1, 3 and 7 identified as S1000, S3000 and CD3000.

- **A folder table whose entries do not say `0xFFFF` is no longer discarded.** `Producer Series Vol. 1 – Studio Essentials` writes flags `0x0013` and `0x0018` on its first two folder entries. The walk required `0xFFFF`, aborted on entry 0, found no folders at all and silently fell back to the single bank directory the header points at — **77 banks of the 230 that disc has**, with no error and a listing that looked complete. The folder table does not need the test: the header pointer already says what it is.
- **Each folder's bank directory is bounded by the next folder's start block.** They sit two to six blocks apart on that disc, so an unbounded walk ran out of one directory and into the next, reporting the neighbour's banks a second time.
- **An E-mu bank no longer reports its neighbour's samples as its own.** A bank was bounded by the next located bank header, and a bank's region holds more than the bank: mastering writes a bank image into a fixed region and whatever was there before survives past its end. It is now bounded by the record run its own header declares at `0x30`/`0x34`, which the disc states and no bound drawn between banks can substitute for. ([ADR-0021](docs/adr/0021-a-bank-owns-the-run-its-header-declares.md), [#15](https://github.com/bmxcode/samplerdisc/issues/15))

  **Two sample counts move, and both old numbers were wrong.** `protozoa` goes from 6 788 to **5 852** and `esi32-gm` from 2 424 to **2 265**. Every record dropped was shown to be another bank's, at a constant offset — 264 of 264 for `Vintage+InstrmtX`, 70 of 70 for `Phatt Presets  X`, and so on for all fifteen of `protozoa`'s located banks. If you extracted either disc before, some of what you got was duplicated audio filed under the wrong bank; `eiiix-1`, `eiiix-2` and the three E-IV discs are unchanged.

  `esi32-gm` was not suspected — the issue records it as unaffected. Its last bank ran to the end of the image and was credited with 193 records belonging to the two banks in front of it, and separately, two of its banks are written twice on the disc and the older revision was the copy being read. Where one name has two headers, the reader now takes the one the directory placed.

- **The bank-count baselines are asserted rather than written down.** The whole-disc figures in the format doc are now a table in `tests/test_discs.py`, pinned by disc size. They were the stated regression guard for the shared record parser and nothing checked them, which is how two of them shipped wrong.
- **A bank with no header on an EIII/ESI disc says so in its own terms.** `E3 Main Code` and `E3X Main Code` — the sampler's operating system, occupying a bank slot — were told they had "no sample directory", naming an E-IV structure those discs do not use.

- **Every audio file copied off an ISO 9660 disc was reported as 0 Hz and 0 frames.** Nothing read the payload's header, so 15 424 files across thirteen discs came back with a manifest entry that said nothing about the audio. `wav.read_header` now reads the real rate and length. It walks to the end of the file rather than stopping at `data`, because a `smpl` chunk is written after the audio as often as before it.
- **An original kept from an ISO 9660 disc was named twice over.** `original_suffix` appends the suffix a backend supplies, which is right for a sampler filesystem — names there carry no extension — and gave `BONGOS M.exs.exs` for a filesystem whose names already do. The ISO 9660 backend now supplies the file's own extension, and the suffix is not appended when the name already ends in it. Without both halves every kept `.exs` landed in `original/` renamed `.bin`: the bytes survived and nothing would open them.
- **A clean disc reported itself as a damaged one.** `Skipped` covered both an entry lost to damage and an entry deliberately not written, and the summary called every one of them damage — `vol.42` printed *"skipped 423 damaged or unreadable entries"* when all 423 were sounds already written under another name. Duplicates are now counted and reported apart, in the summary and in the batch manifest.
- **`--keep-originals` no longer calls its output "AKAI files"** in the summary. An ISO 9660 disc keeps EXS24 and HALion instruments through the same path.

- **The README's "Tested against" figures were two deliverables out of date, and disagreed with `docs/README.md`.** They still described the run before D15 read every AKAI partition — 69 of 79 discs and 47 742 samples against the 72 of 79 and 89 125 the collection now yields — and the byte-identity check was quoted at 22 320 and 40 244 payloads in two different places on the same page. Both are re-measured over all 79 images, along with the rate spread (1 047 distinct values, 6 000–49 999 Hz, where the page said 908 and 6 000–48 000) and the whole-file silence count (275, where it said ten).

- **The partition total quoted across the docs was one too many.** `docs/formats/akai-fs.md` and three comments in `fs/akai.py` said the 44 AKAI discs hold **276** partitions. Measured twice by separate routes, the table declares 384 and **275** are present in the images — and 275 is what `len(list(partitions(...)))` sums to, the same expression `test_akai_discs_list_their_volumes_and_files` already pins per disc for nine of them. The figures beside it are unaffected and were re-checked: 2 154 volumes and 68 997 files, both exact. The earlier 276 could not be reproduced. [ADR-0023](docs/adr/0023-partitions-come-from-the-table-the-disc-declares.md) keeps its original wording, being a historical record.

### Known limits

- **The ISO 9660 directory hierarchy is not preserved.** A disc's audio is written flat into one directory per volume, so `PS-34 AIFF …/056_Ballad de Boo/34a-bas-56Dmin.aif` becomes `34a-bas-56Dmin.wav` and the folder that grouped it by tempo is gone. Nothing is lost on these discs — Best Service named every file uniquely, and all thirteen list zero collisions after flattening — but a disc that reused a basename would rely on `unique_path` suffixing it.

- **AIFF-C is refused, and no disc exercises a reader for it.** Nothing in the collection is AIFF-C, so there is nothing to check one against; a compressed payload written out as PCM would open, play as noise, and report nothing wrong. Same for 8-bit AIFF, where the sign convention differs from WAV's and carrying it would change the sample values.

- **`AMG - Kickin' Lunatic Beats 2 AKAI CD1.mdx` is an incomplete image, and nine of the 669 files it yields are wrong.** It is short of the disc it was made from by four 32 KB blocks, so everything past the first gap has slid: the last nine files of `13-TRACK 06` extract audio belonging to other samples, with payload headers that no longer match the names their directory gives them. The container decodes every block the file does contain correctly — the file is not a complete copy of the disc, which two independent structures agree on. Nothing detects this yet; that is [#23](https://github.com/bmxcode/samplerdisc/issues/23). If you have extracted that disc, treat its last volume with suspicion, and prefer a fresh rip.
- **A declared partition the image has no header at is skipped, never searched for.** Nine of the 44 AKAI discs are short of the disc they were made from, and on those the missing header sits *earlier* — displaced by a whole number of the container's own 32 KB blocks, accumulating down the disc, from 4 blocks on `Best Service - Alpha Dance I` to 7 288 on `AKAI.S3000.Sound.Library.7`. Roughly fifteen thousand readable files stay unread on those images, which is deliberate rather than a gap in the walk: a search would find their partitions, and the audio inside a short image is displaced by the same missing blocks that moved the header — the nine wrong files above are the standing evidence of what displaced audio extracts as. `list` prints how many partitions the disc declares against how many the image holds, so the shortfall is a stated fact and not an absence. ([docs/formats/akai-fs.md](docs/formats/akai-fs.md), [ADR-0023](docs/adr/0023-partitions-come-from-the-table-the-disc-declares.md), [#25](https://github.com/bmxcode/samplerdisc/issues/25))
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
