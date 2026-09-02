# ADR-0039 · SampleCell is read as HFS behind an Apple Partition Map

**Status:** accepted · 2026-09-03

## Context

Two discs in the collection — the OMI *Universe of Sounds* SampleCell volumes — read as `no recognised filesystem`. The working assumption had been that `ER` at byte 0 was an unknown sampler magic. It is not: it is the Apple Driver Descriptor Record. These are Digidesign SampleCell libraries, and SampleCell was a Macintosh NuBus/PCI sampler, so its libraries shipped as ordinary Mac media — a magneto-optical cartridge with an Apple Partition Map, an `Apple_HFS` partition, and inside it a standard Macintosh HFS volume whose payload is plain AIFF ([formats/hfs.md](../formats/hfs.md), [issue #2](https://github.com/bmxcode/samplerdisc/issues/2)).

So this is a filesystem-layer question with nothing new at the sample layer, and it is a genuine scope decision rather than an obvious yes. HFS is a general-purpose Macintosh filesystem, not a sampler filesystem. The argument *against* reading it is that anyone with a Mac, `hfsutils`, or 7-Zip can already open these — unlike an AKAI or E-mu disc, where nothing else will — and issue #2 leaned, on those grounds, toward documenting it and not building it: two specimens, one library, both readable elsewhere.

## Decision

Build it: a `fs/hfs.py` backend that parses the Apple Partition Map, walks the HFS catalog B\*-tree, and yields each file with its data-fork extents, classified so an AIFF entry rides the existing conversion path unchanged. This reverses the lean in issue #2, and two facts settle the reversal.

First, it is the same case already made for ISO 9660 ([ADR-0009](0009-export-iso-escape-hatch.md), and the `fs/iso9660.py` docstring): a meaningful share of these collections are not sampler-format discs, but they still arrive wrapped in a `.nrg`, a compressed `.mdx` or a raw `.bin` that neither ConvertWithMoss nor `akaiutil` opens. "Read it with another tool" assumes the other tool can see past the container, and for these images it cannot — the container layer is the part that is genuinely ours. Reading them costs one module and nothing at the sample layer, and it takes two discs from "the tool reports nothing" to converted, which is the project's whole point.

Second — and this is what tips a close call — the verification is free and total. `machfs`, a pure-Python HFS reader with no shared lineage with this code, reads the same volume, and every one of the ~900 data forks per disc it returns is byte-for-byte identical to what this backend returns. That is the [ADR-0033](0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md)/[ADR-0036](0036-the-krz-bank-is-read-as-objects-and-verified-against-mpc2emu.md) oracle bar met in full, so the backend is not read from one disc on faith.

Two boundaries the backend deliberately holds, each degrading with a note rather than guessing ([ADR-0012](0012-a-probe-must-confirm-a-file.md)):

- **Sound Designer II (`Sd2f`) is listed, not read.** Its audio lives in the HFS *resource* fork, with the rate and width in a resource beside it — a different format from the flat-PCM data-fork AIFF this reads, and writing a resource fork out as PCM would open, play as noise, and report nothing wrong. The 24 on `sonic-images-v2` are named in a `list` and skipped by extraction. Resource forks in general are not read — the same call ISO 9660 makes for the associated-file records that are a resource fork under the data file's name.
- **SampleCell instrument documents (`SCin`, `SCsi`, `MixD`) are kept, not interpreted.** They carry the key ranges and zone maps a WAV cannot, so they are kept under the existing `program` vocabulary with `--keep-originals` and left to ConvertWithMoss ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)), exactly as EXS24 and E-IV presets are.

## Alternatives rejected

**Document it and do not build it** — the lean in issue #2. Rejected for the two reasons in the Decision: the ISO 9660 precedent already answered "but another tool can read it" (it cannot read past the container), and the free `machfs` oracle removes the usual reason to hesitate on a general-purpose filesystem read from few specimens. The counter — only two discs, one library — argues against *inventing* a format from one disc, not against reading a fully documented one that a second implementation confirms byte-for-byte.

**Parse only the Apple Partition Map and hand the HFS partition to `export-iso`.** Cheaper, and it would let a user mount the extracted partition elsewhere. Rejected: it stops one step short of the deliverable — the user still needs a second HFS tool — and the AIFF conversion, dedup and naming this project already does would be thrown away. `export-iso` remains the escape hatch for a partition type with no backend; HFS now has one.

**Read Sound Designer II too.** Tempting for completeness. Rejected for now: the resource-fork format is a separate reverse-engineering effort, the 24 files are one corner of one disc, and shipping an unverified resource-fork PCM reader is exactly the silent-noise failure the project refuses. Left as a follow-up issue.

## Consequences

**Good.** Two discs that read as empty now convert; the SampleCell libraries are freed from a filesystem no sampler tool opens. The backend is one module and a `register()` call ([ADR-0003](0003-brand-neutral-pluggable-backends.md)) with nothing added at the sample layer, and it is verified byte-for-byte against an independent reader across every fork on both discs.

**Bad.** The oracle is `machfs`, not the host: current macOS dropped legacy-HFS read support, so `hdiutil` parses the partition map and then reports *no mountable file systems* for these images. The oracle test therefore depends on a pip-installable package and skips where it is absent, like the EBL and KRZ oracles before it.

**Watch for.** An HFS+ disc (`drSigWord` `H+`) or a Sound Designer II library that carries audio nothing else on the disc does. The first is refused at the MDB signature and would need its own work; the second is the reason `Sd2f` is listed rather than read, and a disc that made it worth building is the thing to look for before building it.
