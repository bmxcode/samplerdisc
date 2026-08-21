# samplerdisc

[![CI](https://github.com/bmxcode/samplerdisc/actions/workflows/ci.yml/badge.svg)](https://github.com/bmxcode/samplerdisc/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

Convert vintage sampler CD-ROM images into uncompressed `.wav` files you can use anywhere. No proprietary disk-mounting software, no dead commercial tools, no dependencies beyond the Python standard library.

The point is to get these sounds **out of the hardware they were trapped in** — not into a different sampler's format. You get plain WAV: drag it into any DAW, load it in whatever sampler you already own, keep it for the next twenty years.

Thousands of 1990s sample libraries survive only as disc images built for hardware samplers — AKAI S1000/S3000, E-mu, Roland, Ensoniq. They are not ISO 9660: the sampler wrote its own filesystem straight onto the disc, so a modern computer mounts nothing and shows you an unreadable volume. `samplerdisc` reads those filesystems directly out of the image file and writes the samples back out as plain PCM WAV.

## Install

Python 3.11 or newer. No other dependencies — the whole tool is standard library.

```bash
uv tool install git+https://github.com/bmxcode/samplerdisc
```

Or with pip:

```bash
pip install git+https://github.com/bmxcode/samplerdisc
```

## Use

```bash
samplerdisc list  "Black II Black.bin"          # volumes and samples, without extracting
samplerdisc extract "Sound Library 1.mdx" ./out  # every sample to WAV
samplerdisc batch  ./discs ./out --manifest out/manifest.json
samplerdisc export-iso "Sound Library 1.mdx" ./library1.iso
```

You get one directory per disc, one per volume inside it:

```
out/AKAI.S3000.Sound.Library.1/
  3001 G.PF 2/
    PF BD 2F 0-L.wav            mono, exactly as stored
    PF BD 2F 0-R.wav
    stereo/
      PF BD 2F 0.wav            the -L/-R pair, rejoined
    original/                   only with --keep-originals
      B-GRAND PF.s3p            the program file, untouched
      PF BD 2F 0-L.s3s
```

Extraction writes one WAV per sample, grouped by volume. Where a disc stores stereo as split mono files — the AKAI `-L` / `-R` convention — you also get a joined stereo WAV, and the mono originals are kept alongside it rather than replaced.

The audio is a byte-for-byte copy: AKAI stores signed 16-bit little-endian PCM and so does WAV, so there is no resampling, no bit-depth change and no dithering anywhere in the process. Loop points, root key and tuning from the disc are written into the WAV's standard `smpl` chunk, so a DAW that understands them picks them up and one that doesn't sees an ordinary WAV.

`--keep-originals` additionally writes each sample and program out byte-for-byte as the sampler stored it, into an `original/` folder beside the WAVs. Two reasons to want it: programs hold the key ranges and envelopes, which a WAV cannot carry and which are otherwise left on the disc; and the files are named by the generation that wrote them — `.s3p`/`.s3s` for an S3000 disc, `.s1p`/`.s1s` for an S1000 — which is the shape [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) wants for turning programs into a playable instrument.

`batch` walks a directory of images and writes a JSON manifest of the run — what each disc contained, which samples were skipped and why. A disc that fails never stops the run, because a real collection has duds in it.

`export-iso` unwraps any supported container into a flat ISO without touching the filesystem inside. That is the escape hatch for a disc whose filesystem `samplerdisc` cannot yet read: the ISO can be handed to [akaiutil](https://sourceforge.net/projects/akaiutil/) or any other tool.

## Supported

**Containers** — `.mdx` (DAEMON Tools, *including compressed*), `.nrg` (Nero v1 and v2), `.bin` + `.cue` (raw 2352-byte CD sectors), `.iso` / `.img`, `.cdr`, `.tao`. Detection is by content signature, not by file extension, because these archives are named inconsistently.

**Audio CDs** — some of these discs are plain Red Book audio, not CD-ROMs. `samplerdisc` recognises them from the cue sheet and writes each track out as a stereo WAV, keeping the track titles (which usually carry the tempo). No filesystem is involved; the sectors already are the audio.

**Filesystems** — AKAI S1000/S3000 family, E-mu `EMU3` (EIIIX, ESI-32/4000, Emulator IV), Roland `S770 MR25A` (S-770, S-750, S-760), and plain ISO 9660 for discs whose payload is already WAV or AIFF.

**Audio payloads** — a WAV inside an ISO 9660 disc is copied out untouched. An AIFF is carried to WAV: its samples are big-endian and a WAV's are little-endian, so the bytes within each value are reversed and the values are left alone. Root key, tuning and loop points come across from the AIFF's `INST` and `MARK` chunks into the WAV's `smpl`.

Compressed `.mdx` is the piece no other open-source tool reads today. The format is documented byte by byte in [docs/formats/mdx.md](docs/formats/mdx.md), along with [`.nrg`](docs/formats/nrg.md), [raw CD sectors](docs/formats/rawcd.md), the [AKAI](docs/formats/akai-fs.md), [E-mu](docs/formats/emu3.md) and [Roland S-7xx](docs/formats/roland-s7xx.md) filesystems, and [audio CDs](docs/formats/audio-cd.md).

## Tested against

79 disc images from three archive.org collections — [retro-sample-cds](https://archive.org/details/retro-sample-cds), [archive-oldschoolscds](https://archive.org/details/archive-oldschoolscds) and [Best Service ProSamples](https://archive.org/details/best-service-pro-samples-vol.-12-dance-vocals-akai-1-cd). Fifty-two flat `.iso`/`.bin`, seventeen compressed `.mdx`, five raw CD images, two `.nrg`, one `.mds`/`.mdf` pair, two audio CDs.

| | |
|---|---|
| Discs converted | 72 of 79 |
| Samples | 89 125 |
| Stereo pairs rejoined | 15 796 |
| Audio CD tracks | 161 |
| Duplicate audio suppressed | 5 719 |
| Entries skipped (damage) | 97 |
| Time | 46 s |

By filesystem:

| | Discs | Samples | Stereo pairs | Skipped |
|---|---:|---:|---:|---:|
| AKAI | 44 | 56 394 | 14 449 | 97 |
| E-mu `EMU3` | 7 | 14 738 | 6 | 0 |
| ISO 9660 | 15 | 11 601 | — | 0 |
| Roland `S770 MR25A` | 5 | 6 392 | 1 341 | 0 |

Every WAV was checked against the disc it came from — **70 of 70 discs match exactly**, comparing multisets of SHA-256 over the PCM per disc rather than going via filenames, so duplicate names cannot mask a mismatch and no path is guessed. 89 125 payloads, zero mismatches. The two audio CDs are not in that count: their tracks are cut from a stream by a cue, so there is no run of bytes on the disc to compare a track against.

105 082 WAV files were written in all — the samples, the stereo joins and the audio CD tracks. None is unreadable and none is zero-length. **275 are silent for their whole length, and every one of them matches the disc exactly**: 267 are the blank `15G-KIT…Z` slots on `ProSamples vol.15`, six are on a Proteus library that ships `Dead Air` as a sample, and two are on a Roland disc. That is what the discs hold, not something the decoder did.

Sample rates run from 6 000 to 49 999 Hz across 1 047 distinct values. The odd ones are real — E-mu writes rates like 24 444 and 27 778, and AKAI uses 33 075 (¾ of 44 100) and 29 400 (⅔) to trade bandwidth for memory. They are carried through exactly as the disc states them and never rounded.

The 97 damage skips are almost all one thing: 92 payloads that do not begin with an AKAI sample header, concentrated on seven `.mdx` images. The rest are four implausible sample rates and one stereo pair whose halves declare 44 033 and 44 100, so the joiner refuses to fuse them and writes both mono halves instead.

The seven that do not convert are accounted for: one S-550 disc present as both `.iso` and `.nrg` — a different format from the S-7xx and not yet read ([ADR-0014](docs/adr/0014-one-backend-per-on-disc-format.md)) — two Digidesign SampleCell discs, one audio CD with no cue sheet present as both `.mdx` and `.cdr`, and one ISO 9660 disc holding E-mu `.EBL` banks rather than audio.

### The AIFF twins

The thirteen ISO 9660 ProSamples discs ship each sound twice, once as AIFF and once as WAV. 6 033 of the 7 498 AIFF hold audio that is already coming out as a WAV, and those are written once; the other 1 465 are converted, along with 314 whose AIFF carries a root key or a loop that its WAV twin does not. `vol.43` is the reason the check is on the audio and not the filename: its 1 386 AIFF all share a name with a WAV and **none of them share its audio**, being mastered a few frames longer ([ADR-0024](docs/adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)).

These discs are also the only place in this project where the correct output is known independently. Where a sound exists as both, the publisher's own WAV says what the AIFF conversion should produce — including the loop convention the AIFF spec leaves open, settled on 195 pairs out of 195.

## What doesn't work yet

- **Roland S-550, Ensoniq and Kurzweil filesystems.** `Roland LCD1.iso` opens `* ROLAND S-550 *`, which shares nothing with the S-7xx format ([ADR-0014](docs/adr/0014-one-backend-per-on-disc-format.md)); neither archive holds a second specimen to check a backend against. The container layer opens all of these, so `export-iso` gets you the sectors meanwhile. Each backend is a self-contained module ([ADR-0003](docs/adr/0003-brand-neutral-pluggable-backends.md)), so adding one touches nothing else.
- **Roland S-7xx discs come out as one flat volume.** The disc groups its samples through a volume → performance → patch → partial chain, and two of those four record formats are undecoded, so every sample is listed under the disc's own label instead. The four-character prefix in each name is the grouping you get ([ADR-0016](docs/adr/0016-the-s7xx-hierarchy-is-located-not-walked.md)).
- **Roland S-7xx sample rates are written as 44 100, not read from the disc.** No rate field has been found, and pitch cannot settle 44 100 against 22 050 because they differ by exactly an octave. Every disc measured is 44 100; a 22.05 kHz one would come out an octave high ([ADR-0018](docs/adr/0018-the-s7xx-sample-rate-is-measured.md)).
- **Emulator IV bank interiors.** E-IV discs list their folders and banks correctly — the directory is shared with EIIIX and ESI — but the inside of a bank is a different layout with only one specimen to hand, so those banks are listed and not extracted ([ADR-0015](docs/adr/0015-locate-banks-by-signature.md)).
- **A `.mds`/`.mdf` pair is read, but its descriptor is not parsed.** One pair has now been through it end to end, and it reads the `.mdf` and sniffs its geometry rather than parsing the `.mds` — correct for a single-track data disc, which is what these are. A multi-track or offset image would be read from byte 0 and come out wrong; the track table is unread. Please open an issue if you have such a disc.
- **`CUES` chunks in NRG** are not parsed; only `CUEX`. No disc using the older form was to hand to check the layout against.
- **An audio CD with no cue sheet cannot be split into tracks.** `samplerdisc info` tells you when a disc's content looks like Red Book audio, and `extract --assume-audio-cd` writes the whole stream as one WAV, but the track boundaries live in a cue, not in the bytes.
- **AIFF-C, and 8-bit AIFF, are refused rather than read.** AIFF-C may be compressed, and compressed data written out as PCM plays as noise while reporting nothing wrong. 8-bit AIFF is signed where 8-bit WAV is unsigned, so carrying it would change every sample value rather than reorder its bytes — which is the one thing this tool does not do ([ADR-0024](docs/adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)).
- **EXS24 and HALion instruments are kept, not read.** `--keep-originals` writes the `.exs` and `.fxp` files out byte for byte; turning them into a playable instrument is ConvertWithMoss's job.
- **AKAI S900, floppy images and the DD partition.** Use [akaiutil](https://sourceforge.net/projects/akaiutil/).

## If a disc doesn't work

Run `samplerdisc info` on it and open an issue with the output:

```bash
samplerdisc info "Some Disc.mdx"
```

`no recognised filesystem` means the container was understood and the filesystem inside it was not — usually a manufacturer with no backend yet, which is the useful case to hear about. Please don't attach the disc image; the `info` output plus the library name is enough to start.

## A note on ISOs

Converting a `.bin` to a `.iso` does **not** make an AKAI disc mountable. These discs are not ISO 9660 — there is no volume descriptor and your OS will still refuse them. What the conversion does is hand the sectors to a tool that understands the AKAI filesystem. That is what `export-iso` is for, and it works on `.mdx` and `.nrg` too, which `bin2iso` cannot open at all.

Some sample-CD collections mix genuine AKAI discs with libraries that were converted to Kontakt and burned back to `.bin`. Those second ones *are* ISO 9660 and do mount normally. `samplerdisc info` tells you which kind you have.

## Prior art, and what to use instead

**[ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)** (Jürgen Moßgraber, Java, LGPL-3.0) reads Akai S1000/S3000 ISO images, `.S3P` programs, MPC keygroups, NKI, SFZ and SoundFont 2, and converts them to SFZ, DecentSampler, Bitwig, MPC/Force, EXS and more. If you want a disc turned into a *playable multisample instrument* rather than plain WAVs, that is its job and it is excellent at it — use it instead of this. It does not open containers, so run `samplerdisc export-iso` first and point it at the result.

**[akaiutil](https://sourceforge.net/projects/akaiutil/)** (Klaus Michael Indlekofer) is the long-standing open-source reader for AKAI sampler filesystems, covering variants this project does not — S900, floppy geometries, the DD partition. [vintage-samplerCD-extractor](https://github.com/umikado/vintage-samplerCD-extractor) wraps it for macOS and Linux. akaiutil is the correctness oracle this project tests itself against.

`samplerdisc` exists for the layer underneath both: compressed `.mdx`, `.nrg` and raw `.bin` are containers neither tool opens, and that is where people get stuck.

Unrelated despite the name: `mdxtools` handles X68000 MDX *chiptune music* files, not disc images.

## Contributing

`docs/README.md` is the reading order for the codebase. The format documentation in `docs/formats/` is the expensive part of this project — layouts established from hex dumps, with constants verified against named discs — and it is worth reading before changing a parser.

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Test fixtures are synthetic and built in code. Disc images are never committed ([ADR-0008](docs/adr/0008-no-media-in-the-repo.md)); tests that need a real disc read `SAMPLERDISC_TEST_DISCS` and skip when it is unset.

## Changelog

[CHANGELOG.md](CHANGELOG.md) records what changed between releases and why.

## Legal

This tool ships no sample data. It converts discs you already own, and the sample libraries on them remain the property of their publishers. Nothing in this repository contains audio, disc images, or any part of a commercial library.

## License

MIT — see [LICENSE](LICENSE).
