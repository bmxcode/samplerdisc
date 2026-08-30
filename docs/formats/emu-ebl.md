# E-mu Emulator X `.EBL`

The sample banks Emulator X-3 -- E-mu's Windows software sampler -- writes, as they appear inside an ISO 9660 disc rather than as a sampler's own filesystem. An `.EBL` is one sample: an IFF `FORM` wrapper around uncompressed 16-bit PCM, sitting in an `.exb` bank folder beside a `SamplePool`. This is a different layer entirely from the `EMU3` filesystem in [emu3.md](emu3.md): that is written straight to a CD by an EIIIX/ESI/E-IV, this is an ordinary file an ISO 9660 backend already finds.

## Why this format needed a document

It looked like the note said it would be: an IFF wrapper around PCM, so a header walk and a copy. Three things the bytes corrected. The two public descriptions of the format disagree with each other and with the disc on endianness. The audio does not start at a fixed offset -- the header before it is variable-width, so the offset is computed, not assumed. And the audio the file *claims* to hold is stated indirectly, as the gap between two header fields, so a decoder that reads to the end of the file is one frame long on every sample that carries a loop.

## The census

*Verified across all 1 061 `.EBL` on the one disc in hand -- Digital Sound Factory's Vintage Pro:*

| | Value | Count |
|---|---|---|
| Wrapper | `FORM` … `E5B0TOC2` | 1 061 |
| Bit depth | 16 | 1 061 |
| Channels | 1 (mono) | 1 061 |
| | 2 (stereo) | **0** |
| Sample rate | distinct values | **282** |
| | 44 100 | 27 |
| | most common (24 000) | 165 |
| Loop trailer | present | 849 |
| | absent | 212 |

Two facts the census settles before anything else. **The rate is not a constant.** Vintage Pro carries 282 distinct rates -- 24 000, 32 000, 47 360, 48 139, 42 193 -- and only 27 of its files are 44 100. A decoder that assumed a rate would be wrong far more often than right, so the rate is read from the record. **Every file is mono.** The format stores stereo, but no `.EBL` on this disc uses it, and no stereo `.EBL` is available paired with a known-good render to check an interleave against -- so a stereo record is refused rather than converted (see *Stereo* below).

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
| 68 | 4 | V2 — channel-1 span start |
| 72 | 4 | V3 — channel-1 span end |
| 76 | 4 | V4 — channel-2 span start |
| 80 | 4 | V5 — channel-2 span end |
| 84–96 | 16 | V6–V9 |
| 100 | 4 | **Sample rate** |
| 104–112 | 12 | V11, V12 |
| 112 | 64 | Comment, UTF-16LE |

All twelve numeric fields are little-endian. The audio begins **8 bytes past the end of the block** -- past a short run of padding that is 8 bytes wide on every file measured, on two banks -- so `audio_start = block + 184`.

**The name is UTF-16LE, not UTF-8.** Both public descriptions call it UTF-8; the bytes are `45 00 50 00 …` = `E·P·…`. It is the sample's real name -- `EP4MKIIL A0`, `909 Tom Low`, `Happy Hat` -- and it is what the output WAV is named after, because the ISO 9660 names are a bare sequence (`Vintage ProSL001.ebl` … `SL1062`) that would tell a user nothing.

### The channel spans, and the mono length

`Channel1 = V3 − V2`, `Channel2 = V5 − V4`. Equal spans mean mono, and the mono audio length is stated apart, as **V4 − V3 + 2**. On `Vintage ProSL001` that is 46 244 − 188 + 2 = 46 058 bytes = 23 029 frames, which is exactly what the publisher's render carries. Unequal spans mean a whole left block then a whole right block (`LLLL…RRRR`).

Reading to the end of the file instead is wrong by design: a file with a loop has a 42-byte trailer after the audio, and even without one the `V4 − V3 + 2` length is the authority the render agrees with.

### The loop trailer (optional, last 42 bytes)

Present on 849 of the 1 061. `EXLZ`, then `INFO` and `MARK` sub-chunks, all sizes and flags little-endian:

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

An `.EBL` payload is already signed 16-bit little-endian PCM -- exactly a WAV data chunk. So a mono sample is written out byte-for-byte, no value altered and no byte reordered, unlike [AIFF](aiff.md). The interleaving that stereo would need is the only conversion the format could demand, and it is deferred.

## Stereo

The format stores stereo non-interleaved, and stereo `.EBL` exist -- other banks (Studio Grand, EW PS18 Steinberg Grand) are entirely stereo. But **Vintage Pro, the only EBL disc in hand, is 1 061 mono files**, and the reference renders that could verify an interleave (mattetti's `E-MU Sounds/`) ship without their EBL inputs for any stereo bank -- the three input banks that do ship (PROcussion, SP-1200, Vintage Keys) are all mono. So there is no stereo-in / known-good-out pair to check the `LLLL…RRRR` → interleaved conversion against.

Rather than convert by a rule nothing has verified -- an off-by-a-channel interleave opens, plays as noise, and reports nothing wrong -- a stereo record is **refused with a reason** and reported as skipped (ADR-0026: the record declares the channel count). Supporting it is left to a stereo specimen with an oracle ([#57](https://github.com/bmxcode/samplerdisc/issues/57)).

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

## Reference disc

| Short name | File | Size |
|---|---|---|
| Vintage Pro | `Digital Sound Factory - E-MU Vintage Pro.bin` | 45 558 240 |
