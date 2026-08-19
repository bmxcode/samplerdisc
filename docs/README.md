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
| D12 | E-mu `EMU3` backend ([ADR-0014](adr/0014-one-backend-per-on-disc-format.md), [ADR-0015](adr/0015-locate-banks-by-signature.md)) | done; E-IV lists only |

Against the three reference discs: 687 samples, 95 stereo pairs, 380 loops, one skipped entry.

## What is not done

- **Roland S-770.** `AMG - Now CD-ROM (Roland).iso` in the archive.org collection is one; sector 0 reads `S770 MR25A`. Deferred until more Roland discs are to hand, so a backend can be checked against several rather than reverse-engineered from one.
- **E-mu, Ensoniq and Kurzweil backends.** The archives are full of these discs and the containers already open them; each needs a module in `fs/` and nothing else ([ADR-0003](adr/0003-brand-neutral-pluggable-backends.md)).
- **`.mds`/`.mdf` is unverified.** No reference pair was available, so geometry is sniffed from the `.mdf` rather than read from the descriptor. See [formats/mdx.md](formats/mdx.md) for the merged form, which *is* verified.
- **CUES chunks in NRG.** Only `CUEX` is parsed; `CUES` encodes position as MSF and no disc using it was available to check the layout against.
- **AIFF payloads on ISO 9660 discs are copied, not converted.** They come out as `.aiff`.
