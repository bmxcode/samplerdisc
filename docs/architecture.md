# Architecture

## The shape

A sampler disc image is three independent problems stacked on top of each other, and the entire design is about keeping them independent.

```
  file on disk        .mdx  .nrg  .bin+.cue  .iso  .mds+.mdf
        │
        ▼
  container/          decompress, de-interleave, find the track
        │             ── knows nothing about music ──
        ▼
  flat 2048-byte sectors
        │
        ▼
  fs/                 partitions, volumes, files
        │             ── one module per sampler ──
        ▼
  sample/             header + PCM payload
        │
        ▼
  wav.py stereo.py    WAV out
```

The layers are independent because the real world is. An AKAI library ships as `.mdx` on one site and `.nrg` on another. An E-mu disc arrives in the same containers as an AKAI one. Sector geometry, compression and pregaps have nothing to do with which manufacturer wrote the filesystem inside. Solve each layer once and every combination comes free; entangle them and you write the same container code again for the next manufacturer.

That is why `container/` may not contain a brand name, a sample-header check, or any AKAI constant ([ADR-0003](adr/0003-brand-neutral-pluggable-backends.md)).

## Layer 1 — containers

`open_image(path)` returns a `SectorImage` exposing `read(offset, length)` over cooked 2048-byte sectors. Four implementations: `MdxImage`, `NrgImage`, `RawCdImage` and `FlatImage`. A `.mds`/`.mdf` pair is not a fifth class: `open_mds()` finds the `.mdf` beside the descriptor, sniffs its geometry the way a bare `.bin` is sniffed, and returns a `RawCdImage` or a `FlatImage` carrying `kind = "mdsmdf"`. The descriptor is read only far enough to identify it and is otherwise not parsed, so a multi-track or offset image would be read from byte 0 — correct for the single-track data discs these are, and confirmed on the one pair in hand.

Dispatch is on **content signature**, not extension ([ADR-0004](adr/0004-detect-by-signature.md)). The head is checked for `MEDIA DESCRIPTOR` and the CD sync pattern, the tail for `NER5`/`NERO`. `MEDIA DESCRIPTOR` alone does not settle it: the merged `.mdx` and the split `.mds` share those 16 bytes and are separated by the major version at `0x10`, so the split form is tested first and at least 17 bytes are read before deciding ([mdx.md](formats/mdx.md)). The `.mds` extension survives only as a tiebreak for a descriptor written by something that does not use this magic; a cooked image with no cue sheet falls through to `FlatImage`.

Only two containers do real work. `MdxImage` walks a chain of DEFLATE and stored blocks with no index ([mdx.md](formats/mdx.md), [ADR-0006](adr/0006-mdx-blocks-classified-by-decode-attempt.md)). `RawCdImage` de-interleaves 2352-byte sectors down to their 2048-byte payload ([rawcd.md](formats/rawcd.md)). `NrgImage` is mostly a footer parse, but it is the one that proved filesystems do not always start at byte 0 ([nrg.md](formats/nrg.md)).

## The origin probe

Between layers 1 and 2 sits the step that is easy to leave out and expensive to omit.

The container reports where its track starts. That is not necessarily where the filesystem starts: a Nero image includes 150 sectors of zeroed pregap, and hybrid discs carry an ISO 9660 track ahead of the sampler partition. So the image layer scans candidate offsets and asks each registered backend's `probe()` whether it recognises what it sees, and the resolved origin is explicit and logged.

Getting this wrong does not raise. It reports an empty disc ([ADR-0005](adr/0005-probe-for-the-filesystem-origin.md)), which is why the resolved origin has its own test rather than being covered incidentally.

## Layer 2 — filesystems

Every backend implements one interface:

```python
class Backend:
    name: str
    def probe(image, offset) -> bool: ...           # cheap, specific
    def volumes(image, offset) -> Iterable[Volume]  # Volume -> Iterable[File]
```

`probe()` runs at every candidate offset during origin detection, so it must be cheap, and specific enough not to match zeros or audio.

`fs/akai.py` walks `Partition → Volume → File` ([akai-fs.md](formats/akai-fs.md)). AKAI caps a partition at 512 MB, so a large disc carries several — walk the table rather than assuming one. `fs/iso9660.py` covers discs whose payload is already WAV or AIFF, which is a meaningful share of the archives.

Damaged input degrades rather than crashing: entries whose start block or size fall outside the image are skipped and logged. Several of these rips have tail damage, and a disc yielding 400 of 420 samples is a good outcome.

## Layer 3 — samples, and why there is no conversion

AKAI sample payloads are signed 16-bit little-endian mono PCM. A WAV data chunk holds signed 16-bit little-endian PCM.

So `sample/` parses a 150-byte header for the rate, the length and the name, and `wav.py` writes a header followed by the bytes. **There is no resampling, no bit-depth change, no dithering and no format conversion anywhere in this project** — output is bit-identical to what the sampler stored, and that is a property worth defending against future helpfulness.

`stereo.py` reconstructs stereo from the `-L`/`-R` naming convention, writing the joined file *alongside* the mono originals rather than replacing them, because the pairing is a name heuristic and heuristics should not be destructive ([ADR-0007](adr/0007-emit-mono-and-stereo.md)).

## When a layer has no answer

`export-iso` unwraps any container to a flat image without consulting the filesystem ([ADR-0009](adr/0009-export-iso-escape-hatch.md)). It is what a user gets when their disc is a container we understand holding a filesystem we do not — which, given E-mu and Roland discs sit in the same archives, is the expected case for a while.
