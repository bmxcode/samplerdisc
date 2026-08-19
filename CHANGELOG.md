# Changelog

Notable changes to `samplerdisc`. Format-level findings live in [docs/formats/](docs/formats/); decisions and their rejected alternatives live in [docs/adr/](docs/adr/). This file records what changed for someone using the tool.

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
