# samplerdisc

Convert vintage sampler CD-ROM images into uncompressed `.wav` files. No proprietary disk-mounting software, no dead commercial tools, no dependencies beyond the Python standard library.

Thousands of 1990s sample libraries survive only as disc images built for hardware samplers — AKAI S1000/S3000, E-mu, Roland, Ensoniq. They are not ISO 9660: the sampler wrote its own filesystem straight onto the disc, so a modern computer mounts nothing and shows you an unreadable volume. `samplerdisc` reads those filesystems directly out of the image file and writes the samples back out as plain PCM WAV.

## Install

```bash
uv tool install samplerdisc
```

## Use

```bash
samplerdisc list  "Black II Black.bin"          # volumes and samples, without extracting
samplerdisc extract "Sound Library 1.mdx" ./out  # every sample to WAV
samplerdisc batch  ./discs ./out --manifest out/manifest.json
samplerdisc export-iso "Sound Library 1.mdx" ./library1.iso
```

Extraction writes one WAV per sample, grouped by volume. Where a disc stores stereo as split mono files — the AKAI `-L` / `-R` convention — you also get a joined stereo WAV, and the mono originals are kept alongside it rather than replaced.

`export-iso` unwraps any supported container into a flat ISO without touching the filesystem inside. That is the escape hatch for a disc whose filesystem `samplerdisc` cannot yet read: the ISO can be handed to [akaiutil](https://sourceforge.net/projects/akaiutil/) or any other tool.

## Supported

**Containers** — `.mdx` (DAEMON Tools, *including compressed*), `.nrg` (Nero v1 and v2), `.bin` + `.cue` (raw 2352-byte CD sectors), `.iso` / `.img`, `.mds` + `.mdf`. Detection is by content signature, not by file extension, because these archives are named inconsistently.

**Filesystems** — AKAI S1000/S3000 family, and plain ISO 9660 for discs whose payload is already WAV or AIFF. E-mu, Roland, Ensoniq and Kurzweil are the planned next backends; each is a self-contained module, so adding one touches nothing else.

Compressed `.mdx` is the piece no other open-source tool reads today. The format is documented byte by byte in [docs/formats/mdx.md](docs/formats/mdx.md).

## Prior art

[akaiutil](https://sourceforge.net/projects/akaiutil/) by Klaus Michael Indlekofer is the serious open-source reader for AKAI sampler filesystems, and covers far more variants than this project does today — including the S900 and floppy formats. [vintage-samplerCD-extractor](https://github.com/umikado/vintage-samplerCD-extractor) wraps it for macOS and Linux. `samplerdisc` exists because neither reads compressed `.mdx` or `.nrg`, and because a stdlib-only Python tool is easier to install and to extend to other manufacturers. akaiutil remains the correctness oracle this project tests itself against.

Unrelated despite the name: `mdxtools` handles X68000 MDX *chiptune music* files, not disc images.

## Legal

This tool ships no sample data. It converts discs you already own, and the sample libraries on them remain the property of their publishers. Nothing in this repository contains audio, disc images, or any part of a commercial library.

## License

MIT — see [LICENSE](LICENSE).
