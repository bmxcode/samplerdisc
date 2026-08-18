# Red Book audio CDs

Some discs in these collections are not CD-ROMs at all. `AMG - RUFF_CUTZ` is a plain audio CD with 96 tracks — the kind you would put in a hi-fi. There is no partition, no volume, no filesystem to walk, and a tool that goes looking for one reports the disc as unreadable when nothing is wrong with it.

## Recognising one

A cue sheet is required. Nothing in the bytes distinguishes CD audio from any other PCM, so without a cue there is no way to know where tracks begin — or that this is audio at all.

The test is: every `TRACK` in the cue is `AUDIO`, and the image size is a whole number of 2352-byte sectors.

## The sectors are the audio

A raw CD audio sector is **2352 bytes = 588 stereo frames of 16-bit little-endian PCM**, at 44 100 Hz. That is byte-for-byte what a WAV data chunk holds, so a track becomes a WAV by writing a header in front of it. No decoding, no conversion, no resampling — the same guarantee as the sampler path ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)).

Unlike a MODE1 data sector there is no sync pattern, no header and no ECC. All 2352 bytes are audio, which is why `looks_raw()` cannot detect these discs: there is nothing to detect.

## Track boundaries

`INDEX 01` gives each track's start as `MM:SS:FF` timecode, at **75 frames per second**, relative to the start of the file for a single-file rip:

```
lba = (minutes * 60 + seconds) * 75 + frames
```

A track runs from its own `INDEX 01` to the next track's, and the last runs to the end of the file. Byte offset is `lba * 2352`.

## Verified against `AMG - RUFF_CUTZ.bin`

| Quantity | Value |
|---|---|
| Size | 789 023 088 |
| Sectors | 335 469 — exactly, no remainder |
| Tracks | 96, all `AUDIO` |
| Total audio | 74.5 minutes |
| Track 1 | `01 Cyril Beats 100`, lba 0, 60.1 s |
| Track 2 | `02 User 135`, lba 4508 |

The cue titles carry the tempo (`01 Cyril Beats 100` is 100 BPM), which is worth keeping in the filename rather than renumbering.
