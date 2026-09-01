# Documentation

These docs exist so a future session — yours, mine, or a contributor's — can make decisions without re-deriving them. That means recording **intent, rejected options, and what the bytes mean**, not just current state.

## Reading order

For a new session, in this order:

1. **[../README.md](../README.md)** — the problem and the idea, in one page.
2. **[architecture.md](architecture.md)** — the three layers, and why keeping them independent is the whole design.
3. **[../CLAUDE.md](../CLAUDE.md)** — the rules for working in this repo.
4. **[formats/](formats/)** — what the bytes mean. Read the doc for the format you are touching, before you touch it.
5. **[adr/](adr/)** — decisions already made, and what was rejected to make them. Skim the index; read the ones your change touches.

## What lives where

| Document | Answers | Written when |
|---|---|---|
| [architecture.md](architecture.md) | How is it put together? | Updated as the shape changes |
| [formats/](formats/) | What do the bytes mean? | When a layout is established against a real disc |
| [adr/](adr/) | Why this and not that? | The moment an alternative is rejected |
| GitHub issues | What is this deliverable, exactly? | Before its code |

## The distinction that matters

A **format doc** records what is true about a file layout. It is a finding, verified against a named disc, and it changes only when the finding was wrong.

An **ADR** records a choice this project made where it could have chosen otherwise. It argues.

`0x40` is where the MDX payload starts — that is a format doc. *Classifying blocks by decode attempt rather than hunting for an index* is a choice with a rejected alternative — that is an ADR. When a format doc starts justifying itself, the argument belongs in an ADR.

## Why `formats/` gets its own directory

The expensive part of this project was never the code. It was establishing, from hex dumps, that the MDX payload starts at `0x40` rather than the plausible-looking `192` in the header, that its blocks carry no index, and that a Nero image hides its filesystem behind 307 200 bytes of pregap.

All of that vanishes into a working parser. Six months on, the code says *what* it does and nothing about *how anyone knew* — and the only way back is another afternoon with a hex editor and 1.6 GB of disc images. The format docs are the durable half of the work.

## The deliverables

| # | What it is | Status |
|---|---|---|
| D0 | Repo, toolchain, CI, documentation system | done |
| D1 | Container layer + `export-iso` | done |
| D2 | AKAI filesystem backend + `list` | done |
| D3 | AKAI sample → WAV + `extract` | done |
| D4 | Stereo joiner | done |
| D5 | `batch` + JSON manifest | done |
| D6 | ISO 9660 backend | done |
| D7 | Loop points, root key and tuning in the WAV `smpl` chunk ([ADR-0011](adr/0011-the-deliverable-is-daw-ready-wav.md)) | done |
| D8 | `--keep-originals` for samples and programs | done |
| D9 | Red Book audio CD tracks → WAV | done |
| D10 | A probe must confirm a file ([ADR-0012](adr/0012-a-probe-must-confirm-a-file.md)) | done |
| D11 | MDX generations, the all-stored case, cue-less audio ([ADR-0013](adr/0013-cueless-audio-is-reported-not-guessed.md)) | done |
| D12 | E-mu `EMU3` backend ([ADR-0014](adr/0014-one-backend-per-on-disc-format.md), [ADR-0015](adr/0015-locate-banks-by-signature.md)) | done |
| D13 | Roland `S770 MR25A` backend ([ADR-0016](adr/0016-the-s7xx-hierarchy-is-located-not-walked.md), [ADR-0017](adr/0017-the-stereo-side-marker-is-a-character-class.md), [ADR-0018](adr/0018-the-s7xx-sample-rate-is-measured.md)) | done |
| D14 | E-mu Emulator IV bank extraction ([ADR-0020](adr/0020-read-e-iv-through-its-sample-directory.md)) | done |
| D15 | Every partition of an AKAI disc, from the table it declares ([ADR-0023](adr/0023-partitions-come-from-the-table-the-disc-declares.md)) | done |
| D16 | AIFF payloads converted, deduplicated against their WAV twin, and EXS24/HALion instruments kept ([ADR-0024](adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)) | done |
| D17 | E-mu loop points in the WAV `smpl` chunk ([ADR-0025](adr/0025-the-loop-is-decoded-the-root-key-is-not.md)) | done |
| D18 | E-mu stereo samples decoded from the record's channel count ([ADR-0026](adr/0026-the-record-declares-the-channel-count.md)) | done |
| D19 | An AKAI payload must be the file its entry placed, and the S3000 header is 192 bytes ([ADR-0027](adr/0027-a-payload-must-be-the-file-its-entry-placed.md)) | done |
| D20 | The partitions eight short AKAI images displaced, found by an anchored search ([ADR-0028](adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md)) | done |
| D21 | An E-mu record is closed by the channel it declares, and found by either one ([ADR-0029](adr/0029-a-record-is-closed-by-the-channel-it-declares.md)) | done |
| D23 | The E-mu whole-extent "no loop" is refused at both ends, not only at frame 0 ([ADR-0030](adr/0030-the-whole-extent-no-loop-is-refused-at-both-ends.md)) | done |
| D24 | An EIII/ESI bank binds the near-named header its placement predicts, recovering five banks a mistyped header name hid ([ADR-0031](adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)) | done |
| D25 | The E-IV `FORM/E4B0` bank is read through its `E3S1` chunks, recovering the audio of 162 of 170 banks that stored it in an IFF container ([ADR-0032](adr/0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)) | done |
| D26 | E-mu Emulator X `.EBL` sample banks converted when a disc carries them, verified byte-for-byte against the publisher's render ([ADR-0033](adr/0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md)) | done |
| D27 | An EIII/ESI directory entry binds its own header, so a name written twice stops double-listing one bank's records ([ADR-0034](adr/0034-each-directory-entry-binds-its-own-header.md)) | done |
| D28 | Kurzweil `KMSI` filesystem backend + `list` — the K2000/K2500 native disc format is FAT16, and its `.KRZ` banks are listed ([ADR-0035](adr/0035-kmsi-is-fat16-read-behind-the-kurzweil-signature.md)) | done |

Across the local collection, by listing: 96 of 104 images claimed, 4 270 volumes, 161 213 files, 126 361 of them samples. The AKAI discs are 45 of those images and 86 487 of those files, read across 318 partitions — 279 where the disk's table puts them and 39 displaced by blocks the rip lost. Before D15 they were 14 783 files, because only the partition at the origin was read.

## What is not done

- **70 declared AKAI partitions are still unread, and 60 of them are not absent.** A header is there and it is inside a partition already being read — 31 would overlap one, 29 land exactly on one. `Best Service - Alpha Dance I` is the whole disc's worth of that: its one displaced partition sits four blocks inside partition 4, so the disc recovers nothing at all. Reading them would mean putting one run of bytes under two partitions' bookkeeping, and this project has no field that says how much shorter than its declared size a partition preceding a gap really is ([ADR-0028](adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md), [#25](https://github.com/bmxcode/samplerdisc/issues/25)). The other 10 have no header at any position the search may look at.
- **104 AKAI files are displaced inside a partition the table calls complete.** `Best Service - Alpha Dance II` declares six partitions and holds all six, and 21 of `AC.DRUMLOOPS`'s 22 samples are somebody else's audio; `AKAI.S3000.Sound.Library.5`'s recovered partitions lose 23 the same way. The rip dropped a run of blocks *inside* a partition rather than the blocks a header sat on, so nothing in the partition table registers a gap. **The mechanism is now measured rather than supposed: 103 of the 104 are sitting intact, carrying their entry's own name, a whole number of container blocks earlier.** They are still refused and named rather than written ([ADR-0027](adr/0027-a-payload-must-be-the-file-its-entry-placed.md)); recovering them would mean locating a volume's blocks by something other than the chain the allocation map declares, which is the search [ADR-0022](adr/0022-a-volume-is-explained-by-the-allocation-map.md) and [ADR-0023](adr/0023-partitions-come-from-the-table-the-disc-declares.md) both refused, and unlike a partition a file has no declared position to search back from ([#35](https://github.com/bmxcode/samplerdisc/issues/35), [ADR-0028](adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md)).
- **The AKAI payload name check still has no positives on real data.** It is the test that separates *"this payload is a sample"* from *"this payload is **this** sample"*, and across all 44 discs it now fires 104 times and never once without the id and valid tests having fired too. D20 was the deliverable expected to change that — a displacement landing exactly on another sample's header is the case it exists for, and recovering 15 808 more samples from displaced partitions produced none. It remains exercised only synthetically ([ADR-0027](adr/0027-a-payload-must-be-the-file-its-entry-placed.md)).
- **What wrote the stale partition headers in free space is unestablished.** `ProSamples vol.14` carries 148 byte-identical copies of one, `vol.12` 86, and `Global Trance Mission 2` three distinct ones repeated 288, 58 and 19 times, every one in a block the allocation map calls free. Filler from the mastering and a header from an earlier state of the disk both fit. It matters only as the reason a partition header may never be scanned for, and for that the reading does not need settling ([ADR-0028](adr/0028-a-displaced-partition-is-anchored-quantised-and-floored.md)).
- **What the AKAI valid byte's low bits mean is unestablished.** `0x81` on 29 samples and `0x9c` on two, against `0x80` on 56 397. The `0x80` flag is the sample-is-valid bit and the rest is unread; three combinations on two discs is not enough to read them from.

- **Roland S-550.** `Roland LCD1.iso`/`.nrg` opens `* ROLAND S-550 *` and is a different format from the S-7xx entirely ([ADR-0014](adr/0014-one-backend-per-on-disc-format.md)). Neither archive holds a second specimen, so it stays deferred rather than being reverse-engineered from one disc.
- **The audio inside a Kurzweil `.KRZ` bank is not converted.** D28 reads the Kurzweil `KMSI` filesystem — it is FAT16, and both `Gigapack I & II (Kurzweil)` discs list their `.KRZ` banks ([ADR-0035](adr/0035-kmsi-is-fat16-read-behind-the-kurzweil-signature.md)) — but a `.KRZ` is a big-endian bundle of Kurzweil objects, not a bare sample. Enumerating the samples inside a bank and turning them into WAV is a separate format layer, the D3 to D28's D2, with a specimen already in hand to build against ([#63](https://github.com/bmxcode/samplerdisc/issues/63)).
- **Ensoniq backend.** The archives are full of these discs and the containers already open them; the backend is a module in `fs/` and nothing else ([ADR-0003](adr/0003-brand-neutral-pluggable-backends.md)). No Ensoniq disc is present locally to verify one against, so it stays deferred against a specimen that does not yet exist.
- **No root key for E-mu.** It is not in the sample record: no byte of the 92 tracks the note in the sample's own name above chance, over 1 741 named records of `esi32-gm` and 917 of `eiiix-1`. The E3 keeps it in the preset, and presets are not read — see the `E4P1` entry below. E-mu WAVs carry their loop with the RIFF neutral root key of 60 ([ADR-0025](adr/0025-the-loop-is-decoded-the-root-key-is-not.md)).
- **`E4P1` presets are not read.** The twelve E-IV discs carry hundreds of them each — 901 on `eiv-studio` alone. A preset holds the key ranges, envelopes and root key a WAV cannot, and turning it into a playable instrument is [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)'s job, not ours ([ADR-0011](adr/0011-the-deliverable-is-daw-ready-wav.md)). What was deferred *with* the presets — the **sample audio** of 170 banks that came back empty — is now read: those banks store their samples in a native `FORM/E4B0` IFF container rather than a flat directory, and D25 walks the container and extracts them, recovering ~2 017 samples across the twelve discs ([ADR-0032](adr/0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)). The eight banks that hold a `FORM` with presets or text and no sample chunk — four `Credits` banks and four `E-mu Systems 96` preset banks — stay listed with a note of their own, which is accurate: they carry no audio.
- **A blank-named EIII/ESI header is characterised but not recovered by name.** D27 fixed the duplicate-directory-name double-listing — `located` is now keyed by directory entry, so `Harpsichord    X` on `Vol. 10 – Elements of Sound 1MB` and `HvyGtr Maj.Open` on `Vol. 17 – Heavy Guitars` each bind their own header ([ADR-0034](adr/0034-each-directory-entry-binds-its-own-header.md), [#47](https://github.com/bmxcode/samplerdisc/issues/47)). What remains open is the `heavy` pair's first arm: its predicted address holds a real 6.3 MB `EMULATOR 3X` header whose name field is blanked, carrying six `MajOpen …` records that are **byte-identical** to the named bank's. It is left noted rather than bound by address alone ([ADR-0031](adr/0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)), and because its audio duplicates a bank already read, nothing is lost. A disc whose blank-named header held audio nothing else yields would make confirming a header by its *record* names worth measuring; none in hand does.
- **The `.mds` track table is unread.** One real pair now reads end to end, but geometry is sniffed from the `.mdf` rather than taken from the descriptor, so a multi-track or offset image would be read from byte 0. What the one specimen's descriptor holds is written down in [formats/mdx.md](formats/mdx.md) without being relied on.
- **CUES chunks in NRG.** Only `CUEX` is parsed; `CUES` encodes position as MSF and no disc using it was available to check the layout against.
- **EXS24 and HALion instruments are kept, not read.** `--keep-originals` writes the `.exs` and `.fxp` files out byte for byte, because they hold the key ranges and envelopes a WAV cannot. Nothing parses them, and nothing should: turning them into a playable instrument is [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)'s job ([ADR-0011](adr/0011-the-deliverable-is-daw-ready-wav.md)).
- **AIFF-C is refused rather than read.** Its payload may be compressed, and compressed data written out as PCM opens, plays as noise and reports nothing wrong. No disc in the collection has one, so there is nothing to check a reader against ([ADR-0024](adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)).
- **8-bit AIFF is refused.** AIFF stores 8-bit signed and WAV unsigned, so carrying one to the other changes every sample value rather than reordering its bytes. That is the line ADR-0024 draws; nothing in the collection is other than 16-bit.
- **Stereo `.EBL` is refused, not converted.** The format stores stereo non-interleaved (`LLLL…RRRR`), and stereo banks exist — but the one EBL disc in hand, Vintage Pro, is 1 061 mono files, and no stereo `.EBL` is available paired with a render to verify an interleave against. A stereo record is skipped with a reason rather than converted by an unverified rule; the render outputs for the stereo banks are already located (mattetti's `E-MU Sounds/`), so picking it up is interleaving and verification, not rediscovery ([#57](https://github.com/bmxcode/samplerdisc/issues/57), [ADR-0033](adr/0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md), [formats/emu-ebl.md](formats/emu-ebl.md)).
- **The E-mu `.exb` bank definition is not read.** Vintage Pro's `.exb` holds the preset key ranges and zone mappings the same way an E-IV preset does; it is listed and, like EXS24 and `E4P1` presets, left to [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) rather than converted ([ADR-0011](adr/0011-the-deliverable-is-daw-ready-wav.md)).
