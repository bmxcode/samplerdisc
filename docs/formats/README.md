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

Point `SAMPLERDISC_TEST_DISCS` at a directory containing them to run the disc-backed tests.
