# The Kurzweil `.KRZ` object bank

The Kurzweil `KMSI` disc is FAT16 ([kurzweil.md](kurzweil.md)), and every file on it is a `.KRZ` object bank. This document is the layer inside that file: a bank is not a sample but a bundle of Kurzweil *objects* — programs, keymaps and samples — sharing one pool of raw PCM, and this is where the audio, its rate, root key and loop actually live. The filesystem doc gets you to the bank; this gets you the samples inside it. The audio is carried to WAV by `sample/kurzweil.py`; the bank is read by `fs/kurzweil.py`.

Everything below is measured against the two `Best Service - Gigapack I & II (Kurzweil)` discs — CD 1 (684 702 480 bytes, 106 banks) and CD 2 (684 744 816 bytes, 189 banks) — and cross-checked byte for byte against an independent K2000 reader, [lentferj/mpc2emu](https://github.com/lentferj/mpc2emu)'s `krz_parser`, which reads the same format for the same family (K2000/K2500/K2600). That correspondence is the strong evidence this format doc rests on: 548 of 548 samples across a spread of twelve banks decoded to byte-identical PCM and the same rate. Where a field's *meaning* beyond "the reader agrees" is stated, mpc2emu's own hardware-confirmed notes are the source.

## Why this format needed a document

D28 read the FAT16 filesystem and stopped at the bank, because a `.KRZ` is opaque from outside: it opens with a four-byte `PRAM` tag and then a big-endian structure that looks like neither a directory of samples nor a flat audio file. The expensive knowledge is that it is **three cross-referencing object kinds in one address space** — a sample's audio is a slice of a shared pool addressed by absolute word offset, its length is not stored but recovered from the *next* sample's offset, its rate is a nanosecond period rather than a frequency, and a stereo sample can be either one two-channel object or a pair of `\x7f`-named mono ones. Read the pool as a flat file and you get one 600 MB blob; read a sample's stored "end" as its audio end and you truncate every looped sample at its loop. None of that is visible once the parser works.

## Endianness

Everything in a `.KRZ` is **big-endian**: the K-series is a 68k/PowerPC machine. That includes the PCM, which is 16-bit signed big-endian — the one place this differs from every other sample format the tool reads (AKAI, E-mu and EBL are little-endian and copied verbatim). It is byte-swapped to little-endian for the WAV, the same carry an AIFF payload gets and for the same reason ([ADR-0024](../adr/0024-the-aiff-twin-is-converted-and-deduplicated.md), [ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)).

## Bank layout

A bank is a 32-byte header, a run of length-prefixed object records, a zero end-marker, and then one contiguous region of raw PCM the sample objects point into.

| Region | Where |
|---|---|
| Header | bytes `0x00`–`0x20` |
| Object directory | from `0x20`, records back to back |
| End marker | a big-endian `int32` = 0 |
| PCM pool | from the byte offset the header names (`osize`) |

### Header (32 bytes)

| Offset | Size | Field | Value |
|---|---|---|---|
| `0x00` | 4 | magic | `PRAM` |
| `0x04` | u32 BE | `osize` | byte offset where the PCM pool begins — equivalently, the byte just past the object directory's end marker |

The pool holds `(file_size − osize) / 2` frames. `file_size` is the bank's own size from its FAT directory entry, so the pool's length is known without reading it — which is how the backend enumerates a bank's samples from its front matter alone and leaves the megabytes of audio on the disc until a sample is extracted.

### Object record

Each record opens with its own length, negated, so a reader walks the directory by adding `−blocksize` until the value is non-negative (the end marker).

| Offset (from record) | Size | Field | Notes |
|---|---|---|---|
| `0x00` | i32 BE | `blocksize` | **negative**; `−blocksize` is the record's total length. `≥ 0` ends the directory |
| `0x04` | u16 BE | `hash` | packed type and id — see below |
| `0x06` | u16 BE | `size` | an inner length; unused by this reader, which walks on `blocksize` |
| `0x08` | u16 BE | `ofs` | `name_len + 3` (odd name) or `+ 4` (even); the object body starts at `record + 8 + ofs` |
| `0x0A` | ≤16 | `name` | latin-1, NUL-terminated, **capped at 16** — a name that fills the field has no terminator, and reading to `ofs` (padded and rounded) returns block bytes as if they were name characters |

The `hash` packs the object type and id. For every object this reader touches the `0x8000` bit is set, and then the type is the top six bits and the id the low ten: `type = hash >> 10`, `id = hash & 0x3FF`. A **sample** is type 38 (`0x9800 + id`); programs are 36 (`0x9000+`) and keymaps 37 (`0x9400+`), and this reader touches neither — they hold the key ranges and envelopes a WAV cannot, and turning them into a playable instrument is [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)'s job ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)). The whole bank is kept verbatim under `--keep-originals` so ConvertWithMoss, which reads `.KRZ`, has it.

## The sample object

A sample object's body is a 12-byte `KSample` header followed by one 32-byte `Soundfilehead` per channel.

### `KSample` (12 bytes)

| Offset (from body) | Size | Field | Notes |
|---|---|---|---|
| `0x00` | u16 BE | `baseID` | `1` on every real sample |
| `0x02` | u16 BE | `numHeaders` | channel count **minus one**: `0` mono, `1` stereo, and `> 1` for a group of mono samples at different root keys |
| `0x04` | u16 BE | `headersOfs` | `8` — the first `Soundfilehead` is at body `0x0C` |
| `0x06` | u8 | `flags` | **bit 0 is the stereo flag** |

A header count above one is *not* proof of stereo. Only `flags` bit 0 means stereo (two planar channels); a multi-header object with the bit clear is several mono samples sharing one object, each its own header and root key. This reader emits the stereo case as one two-channel WAV and each mono header as its own WAV.

### `Soundfilehead` (32 bytes, one per channel)

| Offset | Size | Field | Notes |
|---|---|---|---|
| `0x00` | u8 | `rootkey` | MIDI note the sample plays at — written to the WAV `smpl` chunk |
| `0x01` | u8 | `flags` | `0x40` = the header carries loaded PCM; **`0x80` clear = looped, set = one-shot** |
| `0x08` | i32 BE | `sampleStart` | first PCM word, an absolute frame offset into the pool |
| `0x10` | i32 BE | `sampleLoopStart` | loop start frame |
| `0x14` | i32 BE | `sampleEnd` | for a looped sample the **loop end**, not the audio end (see below) |
| `0x1C` | u32 BE | `samplePeriod` | sample period in **nanoseconds** = `round(1e9 / rate)` |

A header without the `0x40` bit is an empty slot — the `NewSample` default the sampler leaves behind — and is skipped.

### PCM extent: recovered from the neighbour, not stored

`sampleEnd` is the *loop* end, so a sample's true audio length is not in its own header. It is recovered as the start offset of the next loaded sample anywhere in the pool: a sample runs from its `sampleStart` to the next start above it, capped at the pool. This is exact because the pool is packed with no gaps, and it correctly keeps the decay tail a looped sample plays *past* its loop end. The next start is a hard ceiling the reader never reads past — whether `sampleEnd` is an inclusive last frame or already exclusive is mixed across real files, so loop points are clamped to the extent rather than ever allowed to steal a neighbour's PCM.

### Sample rate

The rate is stored as `samplePeriod`, an integer nanosecond period, so `1e9 / period` does not invert back to a round number — a 44 100 Hz sample reads as 44 101. The reader snaps to the nearest of 8000 / 11025 / 16000 / 22050 / 24000 / 32000 / 44100 / 48000 / 96000 within ±2 Hz, and keeps a genuinely in-between rate (Kurzweil sampled at rates like 30 000 too) as read. This matches ConvertWithMoss and mpc2emu.

### Root key and loop go into the WAV

Unlike E-mu, whose sample record carries no root key ([ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md)), a Kurzweil sample object carries `rootkey`, so the WAV's `smpl` chunk gets a real MIDI unity note rather than the neutral 60. A one-shot (the `0x80` flag) writes no loop; a looped sample writes `[sampleLoopStart, sampleEnd]` made sample-relative, dropped only if it does not run forwards or is shorter than 64 frames.

### Stereo is planar

A stereo object stores the whole left channel then the whole right — planar, not interleaved — each addressed by its own header's `sampleStart`, with the second start exactly one channel-length past the first. The reader interleaves the two for the WAV. This is one of the two ways a Kurzweil stereo sample appears; the other is a pair of mono objects named `…\x7fL` / `…\x7fR`, which the stereo joiner pairs on the `0x7f` byte the same way it pairs Roland and AKAI halves ([ADR-0017](../adr/0017-the-stereo-side-marker-is-a-character-class.md)). Both produce a two-channel WAV.

## Verified constants

CD 2, `DR CY R4.KRZ` (3 052 136 bytes), first sample object `CYM:Ride38`:

| Quantity | Value |
|---|---|
| `osize` (pool start) | `0x2B5C` (11 100) |
| Pool frames | 1 520 518 |
| First sample `sampleStart` | 0 |
| Sample type hash | `0x98C8` (type 38, id 200) |

Corners that pin the edges of the format: CD 2's `DRUM KIT.KRZ` (1012 bytes) is a program bank with no sample object at all, listed with a note and carrying no audio; CD 1's `SYN DIG1.KRZ` carries a single-object stereo sample (`flags` bit 0), and mpc2emu reads its channels the same two-channel way; `PIA 2 AC.KRZ` on CD 1 samples a piano at 44 100 Hz with a real sustain loop and root keys that follow the note in the name.

## Census

| Disc | Banks | Sample objects | Stereo objects | Sample-free banks |
|---|---|---|---|---|
| CD 1 | 106 | 3 846 | 12 | 0 |
| CD 2 | 189 | 6 637 | 0 | 1 (`DRUM KIT`) |

## Oracle

There is no publisher render of these banks to check against, as the EBL disc had ([emu-ebl.md](emu-ebl.md)). The independent check is [lentferj/mpc2emu](https://github.com/lentferj/mpc2emu)'s `krz_parser`, a separate reader of the same K2000 object format: pointed at a bank it returns each sample as little-endian PCM with a rate, exactly this backend's output. Across a spread of twelve CD 1 banks, every sample this backend decodes is one mpc2emu decodes to byte-identical PCM and the same rate — 548 of 548, matched on content so mpc2emu's own naming of unreferenced samples cannot cause a spurious miss. The env-gated `test_kurzweil_samples_match_the_mpc2emu_reader` reproduces it against a checkout ([ADR-0036](../adr/0036-the-krz-bank-is-read-as-objects-and-verified-against-mpc2emu.md)).

## Reference discs

| Short name | File | Size (bytes) |
|---|---|---|
| gigapack-cd1 | `Best Service - Gigapack I & II CD1 (Kurzweil).bin` | 684 702 480 |
| gigapack-cd2 | `Best Service - Gigapack I & II CD 2 (Kurzweil).bin` | 684 744 816 |
