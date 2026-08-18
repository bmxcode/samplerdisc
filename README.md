# samplerdisc

Convert vintage sampler CD-ROM images into uncompressed `.wav` files you can use anywhere. No proprietary disk-mounting software, no dead commercial tools, no dependencies beyond the Python standard library.

The point is to get these sounds **out of the hardware they were trapped in** — not into a different sampler's format. You get plain WAV: drag it into any DAW, load it in whatever sampler you already own, keep it for the next twenty years.

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

The audio is a byte-for-byte copy: AKAI stores signed 16-bit little-endian PCM and so does WAV, so there is no resampling, no bit-depth change and no dithering anywhere in the process. Loop points, root key and tuning from the disc are written into the WAV's standard `smpl` chunk, so a DAW that understands them picks them up and one that doesn't sees an ordinary WAV.

`--keep-originals` additionally writes each sample and program out byte-for-byte as the sampler stored it, into an `original/` folder beside the WAVs. Two reasons to want it: programs hold the key ranges and envelopes, which a WAV cannot carry and which are otherwise left on the disc; and the files are named by the generation that wrote them — `.s3p`/`.s3s` for an S3000 disc, `.s1p`/`.s1s` for an S1000 — which is the shape [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) wants for turning programs into a playable instrument.

`batch` walks a directory of images and writes a JSON manifest of the run — what each disc contained, which samples were skipped and why. A disc that fails never stops the run, because a real collection has duds in it.

`export-iso` unwraps any supported container into a flat ISO without touching the filesystem inside. That is the escape hatch for a disc whose filesystem `samplerdisc` cannot yet read: the ISO can be handed to [akaiutil](https://sourceforge.net/projects/akaiutil/) or any other tool.

## Supported

**Containers** — `.mdx` (DAEMON Tools, *including compressed*), `.nrg` (Nero v1 and v2), `.bin` + `.cue` (raw 2352-byte CD sectors), `.iso` / `.img`, `.mds` + `.mdf`. Detection is by content signature, not by file extension, because these archives are named inconsistently.

**Filesystems** — AKAI S1000/S3000 family, and plain ISO 9660 for discs whose payload is already WAV or AIFF. E-mu, Roland, Ensoniq and Kurzweil are the planned next backends; each is a self-contained module, so adding one touches nothing else.

Compressed `.mdx` is the piece no other open-source tool reads today. The format is documented byte by byte in [docs/formats/mdx.md](docs/formats/mdx.md).

## A note on ISOs

Converting a `.bin` to a `.iso` does **not** make an AKAI disc mountable. These discs are not ISO 9660 — there is no volume descriptor and your OS will still refuse them. What the conversion does is hand the sectors to a tool that understands the AKAI filesystem. That is what `export-iso` is for, and it works on `.mdx` and `.nrg` too, which `bin2iso` cannot open at all.

Some sample-CD collections mix genuine AKAI discs with libraries that were converted to Kontakt and burned back to `.bin`. Those second ones *are* ISO 9660 and do mount normally. `samplerdisc info` tells you which kind you have.

## Prior art, and what to use instead

**[ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)** (Jürgen Moßgraber, Java, LGPL-3.0) reads Akai S1000/S3000 ISO images, `.S3P` programs, MPC keygroups, NKI, SFZ and SoundFont 2, and converts them to SFZ, DecentSampler, Bitwig, MPC/Force, EXS and more. If you want a disc turned into a *playable multisample instrument* rather than plain WAVs, that is its job and it is excellent at it — use it instead of this. It does not open containers, so run `samplerdisc export-iso` first and point it at the result.

**[akaiutil](https://sourceforge.net/projects/akaiutil/)** (Klaus Michael Indlekofer) is the long-standing open-source reader for AKAI sampler filesystems, covering variants this project does not — S900, floppy geometries, the DD partition. [vintage-samplerCD-extractor](https://github.com/umikado/vintage-samplerCD-extractor) wraps it for macOS and Linux. akaiutil is the correctness oracle this project tests itself against.

`samplerdisc` exists for the layer underneath both: compressed `.mdx`, `.nrg` and raw `.bin` are containers neither tool opens, and that is where people get stuck.

Unrelated despite the name: `mdxtools` handles X68000 MDX *chiptune music* files, not disc images.

## Legal

This tool ships no sample data. It converts discs you already own, and the sample libraries on them remain the property of their publishers. Nothing in this repository contains audio, disc images, or any part of a commercial library.

## License

MIT — see [LICENSE](LICENSE).
