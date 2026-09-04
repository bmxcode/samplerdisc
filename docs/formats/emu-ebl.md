# E-mu Emulator X `.EBL`

The sample banks Emulator X-3 -- E-mu's Windows software sampler -- writes, as they appear inside an ISO 9660 disc rather than as a sampler's own filesystem. An `.EBL` is one sample: an IFF `FORM` wrapper around uncompressed 16-bit PCM, sitting in an `.exb` bank folder beside a `SamplePool`. This is a different layer entirely from the `EMU3` filesystem in [emu3.md](emu3.md): that is written straight to a CD by an EIIIX/ESI/E-IV, this is an ordinary file an ISO 9660 backend already finds.

## Why this format needed a document

It looked like the note said it would be: an IFF wrapper around PCM, so a header walk and a copy. Three things the bytes corrected. The two public descriptions of the format disagree with each other and with the disc on endianness. The audio does not start at a fixed offset -- the header before it is variable-width, so the offset is computed, not assumed. And the audio the file *claims* to hold ends at its loop trailer, not the end of the file, so a decoder that reads to the end is one frame long on every sample that carries a loop.

A fourth thing a *second* bank corrected, after the first shipped (D33 → #73). Three of the constants read cleanly off Vintage Pro turned out to be that one bank's values, not the format's: the channel count taken from the two spans' equality inverts on the next bank; the audio's 8-byte pad is 4 bytes wide there; and the mono length `V4 − V3 + 2` yields 0. What generalises -- verified byte-for-byte against two banks' publisher renders -- is read instead: the channel byte of `V12`, the audio anchored at `V2`, and the length taken to the trailer (or the end of the file). The lesson the project already knew, paid for again: a constant is only as trustworthy as the number of discs it was checked against.

## The census

*Verified across all 1 061 `.EBL` on Digital Sound Factory's Vintage Pro -- the one EBL **disc** in hand -- and cross-checked against a second **bank**, E-mu Classic Series Vol 13 Dance 2000 (1 608 loose `.ebl`, a local validation input, never a disc; ADR-0033):*

| | Value | Vintage Pro | Dance 2000 |
|---|---|---|---|
| Wrapper | `FORM` … `E5B0TOC2` | 1 061 | 1 608 |
| Bit depth | 16 | 1 061 | 1 608 |
| Channels | 1 (mono) | 1 061 | 972 |
| | 2 (stereo) | **0** | **636** |
| Loop trailer | present | 849 | 0 |
| | absent | 212 | 1 608 |

Vintage Pro alone carries 282 distinct sample rates -- 24 000, 32 000, 47 360, 48 139, 42 193 -- and only 27 of its files are 44 100. Three facts the two banks settle together. **The rate is not a constant**, so it is read from the record; the record is also the authority when a render was hand-normalised (a few Dance 2000 files whose record says 44 001 were rendered at 44 100). **The channel count is not a constant either** -- Vintage Pro happens to be all mono, but Dance 2000 is 972 / 636, and that 636 is exactly the count of stereo FLAC in its render. **And stereo now converts**: its interleave is checked against that render byte-for-byte (#57, [ADR-0041](../adr/0041-stereo-ebl-is-interleaved-and-verified-by-the-render.md); see *Stereo* below). The channel split is read the same way on both banks -- from `V12`, not from the spans (see below).

The disc's 1 062nd file is `Vintage Pro.exb` itself, the 5.9 MB bank definition -- the instrument layer (keygroups, zones), which is read for naming and not converted (ADR-0011).

## Layout

Big-endian outer headers, little-endian data headers. Offsets below are into the file.

| Offset | Size | Field | Endian |
|---|---|---|---|
| 0x00 | 4 | `FORM` | — |
| 0x04 | 4 | File size − 8 | **big** |
| 0x08 | 8 | `E5B0TOC2` | — |
| 0x10 | 4 | 78 | big |
| 0x14 | 4 | `E5S1` (first section) | — |
| 0x18 | 4 | Section size | big |
| 0x1C | 4 | Absolute offset of the second section (98 here) | **big** |
| 0x20 | 2 | Zeros | — |
| 0x22 | 64 | Name, UTF-16LE, space-padded | little |

The header up to the second section is **not a fixed size** -- a bank writes a few bytes more or fewer -- so the field at 0x1C gives where the second `E5S1` section begins rather than leaving it to be assumed. On Vintage Pro it is 98 (`0x62`); on other banks it is not.

The second section is 14 bytes -- `E5S1`, a size, six more -- and the fixed-layout **data-description block** follows it.

### The data-description block (176 bytes)

| Offset in block | Size | Field |
|---|---|---|
| 0 | 64 | Name, UTF-16LE (a copy of the one above) |
| 64 | 4 | V1 |
| 68 | 4 | **V2 — audio anchor** (`audio_start = block + V2 − 4`) |
| 72 | 4 | **V3 — per-channel length** (`V3 − V2` bytes; anchors the stereo split from the end) |
| 76–96 | 24 | V4–V9 |
| 100 | 4 | **Sample rate** |
| 104 | 4 | V11 |
| 108 | 4 | **V12 — channel / format field** |
| 112 | 64 | Comment, UTF-16LE |

All twelve numeric fields are little-endian.

**The audio offset is `block + V2 − 4`, computed, not fixed.** `V2` records the pad before the audio (`V2 − 180` bytes of it): 188 on Vintage Pro → `block + 184` (an 8-byte pad), 184 on Dance 2000 → `block + 180` (a 4-byte pad). D33's fixed `block + 184` was Vintage Pro's pad mistaken for the format's; `block + V2 − 4` matches the render-verified start on every file of both banks. The pad is not reliably zero -- loop metadata leaks into it -- so it cannot be found by scanning for silence.

**The channel count is the channel byte of `V12` -- `(V12 >> 16) & 0xFF`.** `0x03` is stereo; `0x01` is the common mono value, and `0x02` is a second mono sub-type (38 files on Vintage Pro -- the `Vox3*` and `Finger Bass` samples -- all verified mono against the render). So the test is **equality to `0x03`**, not inequality to `0x01`: reading it the other way would misclassify those 38 as stereo. The sibling byte `(V12 >> 8) & 0xFF` is `0x02`, the 16-bit sample width. This is the discriminator that agrees with both banks' renders -- 0 stereo on Vintage Pro, 636 on Dance 2000, the latter matching its 636 stereo FLAC exactly.

**The spans do not give the channel count.** D33 read two spans (`V3 − V2`, `V5 − V4`) and called equal spans mono, unequal stereo. That inverts between banks: Vintage Pro has `V3 − V2 = 0` on every file, and on Dance 2000 the stereo files have *equal* spans and the mono files *unequal* ones. The spans are not a reliable channel signal and are no longer read as one.

**The name is UTF-16LE, not UTF-8.** Both public descriptions call it UTF-8; the bytes are `45 00 50 00 …` = `E·P·…`. It is the sample's real name -- `EP4MKIIL A0`, `909 Tom Low`, `Happy Hat` -- and it is what the output WAV is named after, because the ISO 9660 names are a bare sequence (`Vintage ProSL001.ebl` … `SL1062`) that would tell a user nothing.

### The length, from the end

The audio runs from `audio_start` to the start of the `EXLZ` loop trailer, or to the end of the file when there is no loop. That end is the length the renders agree with: it reproduces Vintage Pro's `V4 − V3 + 2` on all 1 061 files (849 looped, 212 not) and Dance 2000's per-channel `V3 − V2` on all 1 608 -- exactly, no off-by-one.

There is no single header field that holds the length: the "large" field sits in `V4` on Vintage Pro and in `V3` on Dance 2000, which is why any fixed-slot formula (`V4 − V3 + 2`, or `V3 − V2`) is right on one bank and wrong on the other. Anchoring the end at the trailer sidesteps the question, and it degrades safely -- a truncated rip simply ends sooner. Reading to the end of the file regardless would instead be one frame long on every looped file, since the trailer follows the audio.

### The loop trailer (optional, last 40 bytes)

Present on 849 of the 1 061 on Vintage Pro (and on none of Dance 2000). It begins exactly where the audio ends -- that is what makes it the length anchor above. `EXLZ`, then `INFO` and `MARK` sub-chunks, all sizes and flags little-endian:

| From `EXLZ` | Size | Field |
|---|---|---|
| +0 | 4 | `EXLZ` |
| +4 | 4 | 0x20 |
| +8 | 4 | `INFO` |
| +12 | 12 | 8, 1, 1 |
| +24 | 4 | `MARK` |
| +28 | 4 | 8 |
| +32 | 4 | Loop start frame |
| +36 | 4 | Loop end frame |

The start and end are frame positions, little-endian. Every loop measured ends several frames short of the audio (typically end = frames − 6), never at the last frame -- so whether the end frame is played or is one-past is an inaudible one-frame question that no render we can check settles. The end is taken as **exclusive**, the convention `SampleLoop` uses for every other format here, and the WAV writer makes it inclusive as the RIFF `smpl` spec requires. This is the one part of the format not pinned by the oracle, because a FLAC render carries no loop metadata.

## The audio is copied, not converted

An `.EBL` payload is already signed 16-bit little-endian PCM -- exactly a WAV data chunk. So a mono sample is written out byte-for-byte, no value altered and no byte reordered, unlike [AIFF](aiff.md). A stereo sample needs the one conversion the format could demand -- interleaving the two blocks -- and no value is altered there either: the left and right samples are the record's own, only reordered from `LLLL…RRRR` to `LRLR` (see *Stereo* below).

## Stereo

The format stores stereo non-interleaved -- a whole left block then a whole right block (`LLLL…RRRR`), equal and contiguous -- recognised by its `V12` channel byte, `0x03`. Each block is **`V3 − V2` bytes**, the same per-channel length that bounds a mono file, so the audio is `2 · (V3 − V2)` bytes total and the two blocks are interleaved to `LRLR` with the shared `stereo.interleave` -- the same call the [EMU3](emu3.md) backend uses for its block-split stereo, and the same one that joins AKAI's `-L`/`-R` pairs.

**The split is anchored from the end, not the front.** The obvious reading -- take the mono path's `audio_start = block + V2 − 4` and split the span at its midpoint -- is right on Dance 2000 and **two bytes wrong on the grand banks**. There the true audio begins at `block + V2 − 6`: the front anchor lands two bytes into the first left sample, and every frame after it is shifted, which an interleave then scrambles across both channels. What holds on every bank is the length and the end: per-channel is `V3 − V2`, the audio ends at the `EXLZ` trailer or EOF (as for mono), so the left block starts at `audio_end − 2 · (V3 − V2)`. `left = payload[start : start + (V3 − V2)]`, `right = payload[start + (V3 − V2) : audio_end]`. A truncated rip, whose lost tail would pull that from-the-end start off the front of the file, falls back to a front-anchored midpoint split so it degrades from the tail rather than the head.

An off-by-a-channel interleave -- a swap, a mis-split -- opens, plays as noise, and reports nothing wrong, so this is exactly the step that has to be verified rather than assumed: `stereo.interleave(left, right)` reproduces the stereo render **byte-for-byte on every uniquely-named stereo file** across four banks -- Dance 2000 and the three grands -- the order and the block boundary both confirmed against the publisher's own audio. The loop and channel count come straight off the record (ADR-0026: the record declares the channel count), the loop's frames the per-channel count the WAV `smpl` chunk carries. Verified and shipped in [#57](https://github.com/bmxcode/samplerdisc/issues/57) ([ADR-0041](../adr/0041-stereo-ebl-is-interleaved-and-verified-by-the-render.md)).

## The oracle

The check that proves the bytes were understood rather than merely copied. mattetti's [e-mu-soundbanks](https://github.com/mattetti/e-mu-soundbanks) rendered the whole Vintage Pro bank to FLAC -- 1 057 files -- so the publisher's own audio is an independent statement of what a conversion should produce, the [ADR-0024](../adr/0024-the-aiff-twin-is-converted-and-deduplicated.md) pattern one step removed (a render of the same disc rather than a twin on it).

*Verified: every `.EBL` on the disc decoded and matched by its header name to a render.*

| | Count |
|---|---|
| Sample rate exact | **1 007 / 1 007** |
| PCM byte-for-byte exact | **1 007 / 1 007** |
| Header name used twice on the disc (cannot match one render) | 4 |
| Header name normalises differently to the render's filename | 50 |

The 4 that fall out are the disc's four duplicate names (`Kick 9`, `Kick SP ff`, `ArpSquareA1`, `ArpSquareD#1`, each written twice) -- the extractor writes both, disambiguated by `unique_path`; the oracle simply cannot tell which render is which. Nothing in the 1 007 is off by a frame, a byte, or a hertz.

The oracle is FLAC and stdlib cannot decode it, so the check reads it with `soundfile` -- test tooling only. The shipped converter stays pure-Python (ADR-0001). The renders are copyrighted DSF audio and mattetti's licence is unstated, so they are never committed (ADR-0008): the check is gated on `SAMPLERDISC_EBL_ORACLE` and skips without it.

### The second bank (Dance 2000)

The one disc is one bank, and one bank's constants can be that bank's rather than the format's -- which is exactly what D33 shipped. So the generalised reader (#73) is held to a *second* bank's render: E-mu Classic Series Vol 13 Dance 2000, obtained as loose `.ebl` from archive.org's `emuexbsoundbanks` and paired with mattetti's render (1 605 FLAC, 636 stereo). It is a **local validation input, never a disc and never committed** (ADR-0033) -- so, unlike Vintage Pro, the test reads it as a plain directory of files, gated on `SAMPLERDISC_EBL_DANCE_INPUT` and `SAMPLERDISC_EBL_DANCE_ORACLE`, skipping without them.

*Verified:* every `.ebl` classifies to the channel its render carries (972 mono, 636 stereo -- the 636 matching the render's stereo FLAC exactly), and every uniquely-named file whose render was not hand-normalised (a few, e.g. `Snare 2`, resampled 44 001 → 44 100) decodes PCM byte-for-byte -- 816 mono files raw and 375 stereo files interleaved. The mono path is pinned on two banks and the stereo interleave on the one that has stereo, each against the publisher's own render (#57).

The interleave is checked wider still: Giga Schimme Grand (120 stereo), EW PS18 Steinberg Grand (449 stereo, 441 rendered) and Studio Grand (408 stereo) -- mattetti's entirely-stereo grands -- are read the same way when their loose `.ebl` and renders are present, gated on `SAMPLERDISC_EBL_BANKS` and `SAMPLERDISC_EBL_RENDERS`. A publisher render is a subset of the input (a bank ships a few more `.ebl` than were rendered), so the reader's stereo count is checked to be **at least** the render's stereo-FLAC count, and every uniquely-named file that matches by name and rate is byte-exact -- the two-byte from-the-front error that the end anchor fixes was found precisely here, on the grands. The interleave is thus proven on sustained piano, not only Dance 2000's drums.

## Reference disc

| Short name | File | Size |
|---|---|---|
| Vintage Pro | `Digital Sound Factory - E-MU Vintage Pro.bin` | 45 558 240 |
