# AIFF

Apple's Audio Interchange File Format, as it appears on the ProSamples discs — the payload inside an ISO 9660 disc rather than a sampler format. The standard is well documented elsewhere and this file does not restate it. What it records is what these discs actually contain, and the two questions the spec leaves open that the discs answered.

## Why this format needed a document at all

An AIFF is a WAV with the bytes the other way round, and that sounds like it needs no notes. It needed three: which variants are on the discs (one, uniformly), whether the loop end marker is inclusive (it is not, and the spec does not say), and where a conversion may stop being a conversion (at the sign convention, not before).

## The census

*Verified across 780 AIFF sampled from all 13 ISO 9660 ProSamples discs:*

| | Value | Count |
|---|---|---|
| Form type | `AIFF` | 780 |
| | `AIFC` | **0** |
| Bit depth | 16 | 780 |
| Sample rate | 44 100 | 780 |
| Channels | 2 | 410 |
| | 1 | 370 |
| Chunks present | `COMM`, `SSND` | 780 |
| | `minf`, `elmo` (Sound Designer II leftovers) | 60 |
| | `MARK` + `INST` | 53 |
| | `APPL` | 49 |

Every one is uncompressed. Nothing in the collection is AIFF-C, so nothing here is written against a compressed payload, and `sample/aiff.py` refuses `AIFC` rather than guessing that its `sowt`/`ima4`/`ulaw` compression type is one it could pass through.

## Layout

A `FORM` container: `FORM`, a big-endian length, the form type `AIFF`, then chunks. Every chunk is a four-character id, a big-endian length, and a body padded to an even length — **the pad byte is not counted in the declared length**, which is the usual off-by-one in a chunk walk.

### `COMM` — what the audio is

| Offset | Size | Meaning |
|---|---|---|
| 0 | 2 | Channel count |
| 2 | 4 | Frames |
| 6 | 2 | Bits per sample |
| 8 | 10 | Sample rate, 80-bit IEEE 754 extended |

The rate field is a sign bit, a 15-bit exponent biased by 16 383, and a **64-bit mantissa with an explicit leading bit** — unlike a `double`, where the leading bit is implied. The value is `mantissa × 2^(exponent − 16383 − 63)`.

Compute it in integer arithmetic, as a shift. A `double` holds 53 bits of mantissa and this field has 64, so `mantissa * 2.0 ** shift` is lossy for exactly the values this field carries. It rounds 44 100 correctly and is not guaranteed to for every rate; `44 033` — which `ProSamples vol.20` really contains — is the kind of number that makes the difference visible.

### `SSND` — the audio

| Offset | Size | Meaning |
|---|---|---|
| 0 | 4 | Offset: a gap of this many bytes before the audio begins |
| 4 | 4 | Block size, for alignment |
| 8 + offset | — | The samples, big-endian, interleaved |

**The offset field is a gap, not a position.** Reading from `body[8:]` and ignoring it shifts the audio by up to a block, which produces a file that opens, plays as noise and reports nothing wrong. All the discs here use 0; the field is honoured anyway because a wrong answer here is invisible.

### `MARK` — named positions

A `uint16` count, then that many markers: a `int16` id, a `uint32` frame position, and a Pascal string — a length byte followed by that many characters, **the two together padded to an even length**. So a one-character name occupies two bytes and needs no pad; a three-character name occupies four and needs one. Getting this wrong shifts every marker after the first.

### `INST` — how to play it

| Offset | Size | Meaning |
|---|---|---|
| 0 | 1 | `baseNote` — the root key, MIDI |
| 1 | 1 | `detune`, in cents, signed |
| 2–7 | 6 | Key and velocity range, gain |
| 8 | 2 | Sustain loop `playMode` — 0 none, 1 forward, 2 alternating |
| 10 | 2 | Sustain loop begin: a **marker id**, not a position |
| 12 | 2 | Sustain loop end: a marker id |
| 14 | 6 | Release loop, same shape |

The loop points are one indirection away: `INST` names two markers and `MARK` holds their frame positions.

## The end marker is exclusive

**This is the finding.** The AIFF spec says a loop runs between two markers and does not say whether the frame at the end marker is played. Guess wrong and every loop in the collection is one frame long in the wrong direction — inaudible on a long sustain, and wrong.

It did not have to be guessed. Best Service mastered these discs with a WAV of every sound beside the AIFF, and a WAV states its loop in a `smpl` chunk, where the end **is** inclusive. So the two files answer the question about each other.

*Verified across 195 pairs that carry a loop on both sides — 175 on `prosamples-42`, 20 on `prosamples-45`:*

| Reading | Agrees with the twin's `smpl` |
|---|---|
| end marker is exclusive (`end − 1`) | **195 of 195** |
| end marker is inclusive | 0 of 195 |

The same pairs settle the root key: on all 198 AIFF that carry an `INST`, `baseNote` equals the twin's `smpl` MIDI unity note exactly.

That convention — an exclusive `end`, made inclusive by the WAV writer — is the one `SampleLoop` already used for AKAI. Nothing had to change to accommodate AIFF; the disc confirmed the choice already made.

## The trees are not always the same audio

Each of these discs carries a `PS-nn AIFF …` tree and a `PS-nn WAV …` tree with the same file count and matching stems. On most discs they are the same sounds. On one they are not.

*Verified, matching by audio rather than by name:*

| Disc | AIFF | WAV | AIFF whose audio is also a WAV |
|---|---:|---:|---:|
| `prosamples-37` | 992 | 992 | 992 |
| `prosamples-55` | 1 302 | 1 302 | 1 302 |
| `prosamples-42` | 423 | 851 | 423 |
| `prosamples-45` | 850 | 850 | 850 |
| **`prosamples-43`** | **1 386** | **1 386** | **0** |

Every one of vol.43's AIFF has a same-named WAV and not one of them holds the same audio: the AIFF are mastered a few frames longer. `43e-01chh01.aif` carries 17 638 bytes of audio against the WAV's 17 616 — eleven frames, at the same rate, in the same channel count. They are two masterings of one take, not two containers for one file.

Across all 13 discs: 7 498 AIFF, of which 6 033 share their audio with a WAV on the same disc and 1 465 do not.

## What may be changed, and what may not

Carrying an AIFF to a WAV reverses the bytes within each sample value. That is a re-ordering: the values are untouched, no rate or depth changes, and running it twice returns the original bytes exactly.

**8-bit is where that stops being true.** AIFF stores 8-bit samples signed and WAV stores them unsigned, so carrying one to the other means adding 128 to every sample — a change to the values, not to their order. `sample/aiff.py` refuses 8-bit for that reason rather than doing it quietly. 16-bit and 24-bit are both pure reversals and are carried. Nothing in the collection is other than 16-bit.

## Reference discs

| Short name | File | Size |
|---|---|---|
| `prosamples-42` | `Best Service ProSamples vol.42 - Session Instruments [AIFF, EXS24, HALion, WAV] 1CD.iso` | 263 153 664 |
| `prosamples-43` | `Best Service ProSamples vol.43 - Real Drum Kits [AIFF, EXS24, HALion, WAV] 1CD.iso` | 414 228 480 |
| `prosamples-45` | `Best Service ProSamples vol.45 - Techno ID [AIFF, EXS24, HALion, WAV] 1CD.iso` | 433 889 280 |
