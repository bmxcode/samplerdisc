# Formats

What the bytes mean. These documents exist because the expensive part of this project was never the code — it was working out the layouts below from hex dumps of 1.6 GB of disc images, and every one of those findings becomes invisible the moment it is compiled into a parser.

Without these docs, the next session re-derives the MDX block chain by hexdumping 264 MB. With them, the parser is mechanical.

| Document | Format |
|---|---|
| [mdx.md](mdx.md) | DAEMON Tools `.mdx`, including the compressed variant |
| [nrg.md](nrg.md) | Nero `.nrg`, v1 and v2 |
| [rawcd.md](rawcd.md) | Raw CD sectors — `.bin` + `.cue`, `.tao`, `.cdr` |
| [akai-fs.md](akai-fs.md) | AKAI S1000/S3000 filesystem and sample header |
| [emu3.md](emu3.md) | E-mu `EMU3` filesystem — EIIIX, ESI/Formula 4000, E-IV |
| [roland-s7xx.md](roland-s7xx.md) | Roland `S770 MR25A` filesystem — S-770, S-750, S-760 |
| [kurzweil.md](kurzweil.md) | Kurzweil `KMSI` filesystem — FAT16, K2000/K2500, `.KRZ` object banks |
| [kurzweil-krz.md](kurzweil-krz.md) | The `.KRZ` object bank interior — samples, rates, loops in one big-endian pool |
| [iso9660.md](iso9660.md) | ISO 9660 and Joliet — discs whose payload is already audio |
| [aiff.md](aiff.md) | AIFF — the payload inside those discs, and the one format carried rather than copied |
| [emu-ebl.md](emu-ebl.md) | E-mu Emulator X `.EBL` sample banks — a sample format inside an ISO 9660 disc |
| [audio-cd.md](audio-cd.md) | Red Book audio CDs — no filesystem at all |

## How to read the constants

Every number quoted as *verified* was measured against a named disc, and has a matching assertion in the test suite. If you change a parser and a documented constant no longer holds, one of the two is wrong — do not adjust the number to make a test pass without establishing which.

The reference discs are not in this repository ([ADR-0008](../adr/0008-no-media-in-the-repo.md)). They are:

| Short name | File | Size |
|---|---|---|
| `s3000-lib1` | `AKAI.S3000.Sound.Library.1.mdx` | 264 088 447 |
| `black2black` | `TZAMGB2BAK1.bin` + `.cue` | 622 049 904 |
| `loopsoup` | `AMG - Loop Soup AKAI.nrg` | 542 419 100 |
| `clearmountain` | `Ew-040 PRO Samples 6 _ Bob Clearmountain Drums II.mdx` (+ `.cdr`) | 632 731 056 |
| `lcdp05` | `Roland - LCDP05 Solo Strings.iso` | 130 344 960 |
| `edirol-brass` | `Edirol - Brass Section vol.1 - Solos (Roland Sxx CD-ROM).iso` | 162 271 232 |
| `northstar` | `NorthStar - Global Instruments - Volume 1 (S7xx).iso` | 296 032 256 |
| `amg-now` | `AMG - Now CD-ROM (Roland).iso` | 681 140 224 |
| `l-cdx-01` | `Roland - L-CDX-01 - Rhythm Section Instruments (Roland Sxx CD-ROM).iso` | 629 149 696 |
| `vintage-pro` | `Digital Sound Factory - E-MU Vintage Pro.bin` + `.cue` | 45 558 240 |
| `bsbssd2` | `Best Service - Brass Super Section (CD2).bin` + `.cue` | 539 584 080 |
| `prosamples-42` | `Best Service ProSamples vol.42 - Session Instruments [AIFF, EXS24, HALion, WAV] 1CD.iso` | 263 153 664 |
| `prosamples-43` | `Best Service ProSamples vol.43 - Real Drum Kits [AIFF, EXS24, HALion, WAV] 1CD.iso` | 414 228 480 |
| `prosamples-45` | `Best Service ProSamples vol.45 - Techno ID [AIFF, EXS24, HALion, WAV] 1CD.iso` | 433 889 280 |
| `gigapack-cd1` | `Best Service - Gigapack I & II CD1 (Kurzweil).bin` + `.cue` | 684 702 480 |
| `gigapack-cd2` | `Best Service - Gigapack I & II CD 2 (Kurzweil).bin` + `.cue` | 684 744 816 |

Point `SAMPLERDISC_TEST_DISCS` at a directory containing them to run the disc-backed tests. The scan recurses, so pointing it at the collection root rather than one folder is fine.

`tests/test_discs.py` pins some of these discs and asserts exact counts against them. It finds each one **by size in bytes, not by filename**, so renaming a disc on the shelf no longer switches its test off — and a pinned disc that is absent from an otherwise-populated collection now fails rather than skips. A shelf with no discs at all still skips everything, which is the case that has to keep working for anyone without the collection.

The practical arrangement is a second directory holding just the discs the tests and these docs depend on — on one filesystem, `ln` rather than `cp` makes it free — and pointing `SAMPLERDISC_TEST_DISCS` at that. A full run over it should report **no skips**; a skip means a disc the docs rely on is not there. Keep it outside any git working tree ([ADR-0008](../adr/0008-no-media-in-the-repo.md)), and beside the main collection rather than inside it: the same disc reachable twice under one root is two files of identical size, which the duplicate check reports as an error.

Two of these were renamed on disk in August 2026 and appear under their old names in [CHANGELOG.md](../../CHANGELOG.md) and [ADR-0019](../adr/0019-prefer-joliet-names.md), which are historical records and were left alone: `bsbssd2` was `BSBSSD2.bin`, and `AMG - Ruff Cutz.bin` was `AMG - RUFF_CUTZ.bin`. A disc-backed test that keys on a filename **skips** when it does not match, so a rename disables it silently — `test_iso9660_discs_list_every_file_under_a_distinct_path` was skipping on `bsbssd2` for exactly this reason.
