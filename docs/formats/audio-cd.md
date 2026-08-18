# Red Book audio CDs

Some discs in these collections are not CD-ROMs at all. `AMG - RUFF_CUTZ` is a plain audio CD with 96 tracks — the kind you would put in a hi-fi. There is no partition, no volume, no filesystem to walk, and a tool that goes looking for one reports the disc as unreadable when nothing is wrong with it.

## Recognising one

A cue sheet is required **to extract tracks**. Nothing in the bytes says where a track begins, so without a cue there are no boundaries to cut on.

The test is: every `TRACK` in the cue is `AUDIO`, and the image size is a whole number of 2352-byte sectors.

### Without a cue

"There is no way to know this is audio at all" was too strong, and a disc in the collection disproved it. `Ew-040 PRO Samples 6 _ Bob Clearmountain Drums II` arrives as `.mdx` and `.cdr` with no cue in sight, decodes perfectly, and then has no filesystem to walk — which is indistinguishable from a container we got wrong, unless something looks at the content.

Two statistics separate CD audio from a sampler payload, measured over a dozen windows spread across the image and taken as medians. Read the stream as 16-bit LE stereo, then compare a lag-1 step against a lag-2 step:

| | lag-1 / lag-2 | lag-2 / mean |
|---|---|---|
| Audio CDs (3 discs) | **5.1 – 14.0** | 0.10 – 0.25 |
| Sampler discs (6 discs, AKAI / E-mu / Roland) | **0.52 – 1.01** | 0.14 – 1.61 |
| Uniform noise | ~1.0 | ~1.33 |

The first column is the one that works, and the reason is structural rather than statistical. In interleaved stereo a lag-1 step hops between channels and a lag-2 step moves along one channel, so lag-1 differences dominate. Mono sample data read as stereo inverts that — lag-1 is one step in time, lag-2 is two — which pins it near 0.5.

**A smoothness test alone is not enough**, and this is the trap. `Roland LCD1` carries 12-bit sample data and `Roland - LCDP05` carries 16-bit, both smooth enough to score better on the second column than a real audio CD does. Only the interleave test tells them apart.

This recognises *content*, not track structure. It is used to explain a disc that yielded no filesystem, and to sanity-check `extract --assume-audio-cd`, which writes the whole stream as one WAV. It never runs on a disc a backend claimed. See [ADR-0013](../adr/0013-cueless-audio-is-reported-not-guessed.md).

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
