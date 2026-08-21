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

Across the local collection, by listing: 71 of 79 images claimed, 2 578 volumes, 110 989 files, 77 620 of them samples. The AKAI discs are 44 of those images and 68 997 of those files, read across 275 partitions — before D15 they were 14 670 files, because only the partition at the origin was read.

## What is not done

- **Roland S-550.** `Roland LCD1.iso`/`.nrg` opens `* ROLAND S-550 *` and is a different format from the S-7xx entirely ([ADR-0014](adr/0014-one-backend-per-on-disc-format.md)). Neither archive holds a second specimen, so it stays deferred rather than being reverse-engineered from one disc.
- **Ensoniq and Kurzweil backends.** The archives are full of these discs and the containers already open them; each needs a module in `fs/` and nothing else ([ADR-0003](adr/0003-brand-neutral-pluggable-backends.md)).
- **65 records declare two channels and are not stereo.** They put `start_R` half a payload on and then close `end_L` somewhere else, and their halves measure as unrelated audio. Six of `protozoa`'s are explained — their first half is byte for byte a whole one-channel record of the same name in another bank, so the payload is twice the sound — and the rest are not. They come out mono, which is right, but *what they hold* is unestablished on `eiiix-1`'s 40, `eiiix-2`'s 6 and thirteen of `protozoa`'s ([formats/emu3.md](formats/emu3.md), [ADR-0026](adr/0026-the-record-declares-the-channel-count.md)).
- **`esi32-gm` and `protozoa` declare a longer extent than their record length gives.** On about 2 200 records of one and 3 800 of the other, `end_L` runs some 45 frames past the payload `+34` produces. Either the reader is 90 bytes short on those samples or the extent field means something else; the splice test does not settle it — a scan for the true loop end peaks within ±2 frames of the declared one on 10% and 20% of records, against about 3% for chance. Those records are refused a loop rather than given a clamped one, and nothing is changed on the strength of an unsettled measurement.
- **No root key for E-mu.** It is not in the sample record: no byte of the 92 tracks the note in the sample's own name above chance, over 1 741 named records of `esi32-gm` and 917 of `eiiix-1`. The E3 keeps it in the preset, and presets are not read — see the `E4P1` entry below. E-mu WAVs carry their loop with the RIFF neutral root key of 60 ([ADR-0025](adr/0025-the-loop-is-decoded-the-root-key-is-not.md)).
- **`E4P1` presets are not read.** The three E-IV discs carry 916, 901 and 284 of them. On `eiv-studio` 100 of 230 banks have no sample directory and are listed with a note; preset-only banks are the likely explanation, and it is not established.
- **The `.mds` track table is unread.** One real pair now reads end to end, but geometry is sniffed from the `.mdf` rather than taken from the descriptor, so a multi-track or offset image would be read from byte 0. What the one specimen's descriptor holds is written down in [formats/mdx.md](formats/mdx.md) without being relied on.
- **CUES chunks in NRG.** Only `CUEX` is parsed; `CUES` encodes position as MSF and no disc using it was available to check the layout against.
- **EXS24 and HALion instruments are kept, not read.** `--keep-originals` writes the `.exs` and `.fxp` files out byte for byte, because they hold the key ranges and envelopes a WAV cannot. Nothing parses them, and nothing should: turning them into a playable instrument is [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)'s job ([ADR-0011](adr/0011-the-deliverable-is-daw-ready-wav.md)).
- **AIFF-C is refused rather than read.** Its payload may be compressed, and compressed data written out as PCM opens, plays as noise and reports nothing wrong. No disc in the collection has one, so there is nothing to check a reader against ([ADR-0024](adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)).
- **8-bit AIFF is refused.** AIFF stores 8-bit signed and WAV unsigned, so carrying one to the other changes every sample value rather than reordering its bytes. That is the line ADR-0024 draws; nothing in the collection is other than 16-bit.
