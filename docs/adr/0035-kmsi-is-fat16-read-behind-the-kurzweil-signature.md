# ADR-0035 · KMSI is FAT16, read behind the Kurzweil signature

**Status:** accepted · 2026-09-01

## Context

The two `Best Service - Gigapack I & II (Kurzweil)` discs are opened by the `rawcd` container but claimed by no filesystem: `find_origin` returns `None` and they read as empty. Byte 0 of the cooked stream is a boot sector whose OEM field reads `KMSI` (Kurzweil Music Systems Inc.), the native disc format of the K2000/K2500 family and the "Ensoniq and Kurzweil backends" gap in `docs/README.md` ([#60](https://github.com/bmxcode/samplerdisc/issues/60)).

Reverse-engineering the two discs turned up a fact that shapes the whole deliverable: the KMSI "native format" is not a bespoke allocation scheme at all. It is a plain **FAT16** filesystem — a standard BPB, two FATs, a fixed 512-entry root, 36 342 clusters of 16 KB — with 512-byte logical sectors packed four to a cooked 2048-byte sector. The only thing that marks it as Kurzweil's rather than any other FAT is the `KMSI` OEM label. See [docs/formats/kurzweil.md](../formats/kurzweil.md) for the measured layout.

The files on it are all `.KRZ` object banks — 106 on CD 1, 189 on CD 2, every one beginning with the tag `PRAM`. A `.KRZ` is not a bare sample: it is a big-endian bundle of Kurzweil objects (programs, keymaps and samples) with its own internal format. So this format sits at the intersection of two layers the project keeps separate — a filesystem (FAT16) and a sample-bearing file inside it (`.KRZ`) — and the question was how far one deliverable reaches.

This mirrors the AKAI split exactly: D2 was "filesystem backend + `list`", D3 was "sample → WAV". This is the D2-equivalent for Kurzweil.

## Decision

**A `KMSI` disc is read by a FAT16 reader in `fs/kurzweil.py`, gated on the Kurzweil OEM signature, and this deliverable lists the `.KRZ` bank files without opening them.**

The module is a filesystem backend like any other: a `probe()` that resolves the origin for free (ADR-0005), a `volumes()` that walks the FAT16 directory tree into one flat volume, and a `read_file()` that follows the cluster chain. Each `.KRZ` is listed with kind `bank` and written verbatim by `--keep-originals` with its `.krz` suffix. The audio inside a bank is left for a follow-up ([#60](https://github.com/bmxcode/samplerdisc/issues/60)).

Detection is by the `KMSI` OEM string (ADR-0004), and the probe confirms a real file the way ADR-0012 requires: it follows the first directory entry to its first cluster and checks the bytes there begin with `PRAM`, the tag every `.KRZ` bank on both discs opens with. A magic plus a pointer is structure; the pointer is followed and the thing it points at confirmed.

The module is named `kurzweil` — the brand — rather than `kmsi` — the on-disc signature. ADR-0014 names a backend after the format the disc declares about itself, and `emu3` follows that literally; but `akai` is brand-named, the tracking issue and the `docs/README.md` gap both call this "the Kurzweil backend", and there is exactly one Kurzweil on-disc format in hand. If a second, differently-signed Kurzweil format appears it becomes a separate backend, not a second parser behind this probe (ADR-0014).

## Alternatives rejected

**A generic `fs/fat.py` that reads any FAT and lets the container or a later layer decide it is Kurzweil.** The filesystem *is* generic FAT16, so this looks like the honest factoring. Rejected because the detection cannot be: a bare "a FAT is present" probe is exactly the loose probe ADR-0004 and ADR-0005 exist to forbid — it would claim any DOS or hybrid disc with a FAT in front of it, at whatever offset the scan first found a plausible BPB, and the failure is silent (a mis-claimed disc that "almost parses"). What identifies these discs is the `KMSI` label and the `PRAM`-led bank behind it, both Kurzweil facts, and brand facts live in `fs/`, never in `container/` (ADR-0003). The FAT16 reading itself is small and lives inside the one backend that has a specific reason to trust it; a second FAT-based format, if one turns up, can share code then, on evidence, rather than now on a guess.

**Crack the `.KRZ` object table in the filesystem backend and list the samples inside each bank.** The task says "list its samples", and a human reading the disc wants the sounds, not the banks. Rejected because a `.KRZ` is a distinct format — a big-endian object bundle — and reverse-engineering it is its own deliverable, the D3 to this D2. Folding it in would put a second, unrelated parser behind one `probe()` and make the deliverable unbounded. The filesystem layer's honest unit here is the file, and the file is a bank; the samples are one layer deeper and are deferred with a specimen already in hand to build against ([#60](https://github.com/bmxcode/samplerdisc/issues/60)).

**Read the FAT type from the boot sector's `FAT16   ` hint at `0x36` rather than computing it.** Simpler, and it is where FAT records its own type. Rejected because both reference discs leave that field blank — it is a hint, not a header, and the FAT specification says to compute the type from the cluster count regardless. The backend computes 36 342 clusters and concludes FAT16 from the count; the blank hint would have made a field-reading probe decline a disc it reads perfectly.

## Consequences

**Good.** The two Gigapack discs resolve to the `kurzweil` backend at offset 0 and list their 106 and 189 `.KRZ` banks; `info` and `list` route to it with no change to `cli.py`, because a backend that implements `probe()` is discovered through the registry (ADR-0003, ADR-0005). The collection's first Kurzweil specimens go from "container reads it, filesystem does not" to fully listed.

**Good.** `read_file` is checked against an independent FAT walk over a spread of both discs, byte for byte, and CD 1's 12 fragmented banks make that a real test of chain-following rather than of contiguity.

**Deliberately not claimed.** The audio inside a `.KRZ` bank. The bank is a big-endian object container and its samples are uncompressed 16-bit PCM, but enumerating the objects and turning them into WAV is the follow-up, not this deliverable ([#60](https://github.com/bmxcode/samplerdisc/issues/60)). Until then a `.KRZ` is listed and kept verbatim, and `parse_sample` refuses it with a reason rather than mis-reading a bank as an AKAI sample.

**Deliberately not claimed.** Ensoniq. No Ensoniq disc is present locally, so that half of the gap stays deferred against a specimen that does not yet exist (ADR-0003).

**Watch for.** A Kurzweil disc that is not FAT16 — a FAT12 floppy image, or a later FAT32 volume. The reader declines it rather than misreading it, which is the honest floor; such a disc would extend or fork the backend on evidence. None in hand is that disc.
