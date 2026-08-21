# ADR-0025 · The E-mu loop is decoded from the record; the root key is not there to decode

**Status:** accepted · 2026-08-21

## Context

Every other backend carries what its disc knows about a sample into the WAV's own `smpl` chunk — AKAI since D7, Roland since D13, AIFF since D16. The E-mu path carried none, so 14 738 samples across seven discs shipped as plain WAV. [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md) asks for exactly this and calls dropping it *data loss, not neutrality*.

It was deferred for a good reason: the 92-byte sample record is read by **one parser shared across all seven discs and two generations**, so decoding it risks moving output that four earlier deliverables pinned.

The eight fields `docs/README.md` listed as undecoded — `+18`, `+24`, `+28`, `+32`, `+36`, `+40`, `+44`, `+48` — are not fields. They are a four-byte stride started at the wrong place, and a `u32` read at `+28` straddles two real fields, which is why they dump as nine-digit noise. The record carries an **eight-pointer block at `+22`, `+26`, `+30`, `+34`, `+38`, `+42`, `+46`, `+50`**: a start, an end, a loop start and a loop end, per channel, each a byte offset from the record's own start naming the first byte of a 16-bit word. The full layout and every disc it was checked against are in [formats/emu3.md](../formats/emu3.md).

Three things the project already recorded fall out of that reading at no cost, which is the strongest argument that it is right:

- **`OFF_SAMPLE_HEADER_LEN` was never a header length.** It is `start_L`, and it reads 92 because the header is 92 bytes and the audio begins immediately after it. The format doc recorded that this field "reads 92 on most E-IV records and **0 on 547 of `eiv-studio`'s** — those carry 92 at `+26` instead" and left it as an oddity. Those records declare no left channel. It is not a broken field, it is a different value of a working one.
- **`RECORD_LEN_BIAS = 2` stops being a bias.** `+34` is `end_R`, which addresses the *last word* rather than one past it, so the record ends two bytes further on.
- **`+34 == 2 × (+30) − 90`**, which the "Everything is mono" section reported without explaining, is `end_R = end_L + P/2` written out.

## Decision

**Decode the loop from the pointer block. Do not decode a root key, because the record does not carry one. Write the `smpl` chunk for the loop alone.**

### The loop is established by content, on six discs and three publishers

The oracle is the one [formats/roland-s7xx.md](../formats/roland-s7xx.md) used for the S-7xx sustain loop, guards included. Two tests on different evidence: the **join**, `|x[E−1] − x[L]|` over the mean step measured in a window at each end; and the **shape**, the correlation of the waveform at `L` against the waveform at `E`, which is the stronger instrument here.

| Disc | Publisher | scored | shape *r* | control | join | control | seamless | control |
|---|---|---|---|---|---|---|---|---|
| `eiiix-1` | E-mu | 512 | **+0.70** | +0.02 | 0.66 | — | 91% | — |
| `eiiix-2` | E-mu | 526 | **+0.73** | −0.01 | 1.12 | — | 81% | — |
| `protozoa` | E-mu | 723 | **+0.83** | −0.01 | 1.22 | — | 83% | — |
| `esi32-gm` | E-mu | 16 | **+0.64** | +0.17 | 0.32 | — | 81% | — |
| `eiv-studio` | Producer Series | 1 051 | **+0.86** | −0.02 | 1.49 | 5.29 | 79% | 34% |
| `eiv-vitous` | Miroslav Vitous | 144 | **+0.68** | −0.06 | 2.30 | 7.21 | 64% | 25% |
| `eiv-analogia` | Producer Series | 34 | −0.00 | +0.02 | 2.44 | 5.36 | 53% | 25% |

The control is the same loop end with the start put somewhere else, which is the only thing that isolates the *start* — the end cannot be isolated the same way, because `+46` and `+30` sit six frames apart on most records and no test can separate them.

`eiv-analogia` is stated as it came out. 441 of its 449 records pass the gates but only 34 carry audio loud enough at both ends to score, and those 34 show nothing. That is a lack of power, not a refutation, and analogia's loops rest on the rule the other six discs establish rather than on its own evidence. [ADR-0020](0020-read-e-iv-through-its-sample-directory.md)'s independence requirement is still met without it: two E-mu-published generations, Producer Series through `eiv-studio`, and Vitous.

### A loop end past the audio is refused, not clamped

This is the one place the format parts company with the rest of the project, and it is the finding that made the measurement work at all. AKAI and Roland both **clamp** a declared end back to the audio present, because a rip is routinely a little shorter than its directory claims.

Doing that here destroys the loop, and `protozoa` proves it on a single disc within a single record shape:

| `protozoa`, mono-shaped records | count | shape *r* | control |
|---|---|---|---|
| loop end already inside the payload | 689 | **+0.86** | −0.04 |
| loop end past the payload, clamped back | 525 | **−0.10** | +0.01 |

Same disc, same shape, separated only by whether the end fits. A clamped end is a loop point the disc did not state. So the end is a **gate**: a record whose loop end lies past its audio yields no loop.

That is most of why `esi32-gm` — the format doc's own reference disc — yields only **107 loops of 2 265 samples**. On almost every record it declares an extent about 45 frames longer than the payload the record's own length field produces. Which of the two is right is not established here and is not guessed at.

### The root key is not in the record

No byte of the 92 tracks the note written in the sample's own name. Across **1 741 named records on `esi32-gm` the best byte matches at any constant offset on 8%**, and 917 on `eiiix-1` on 6% — chance, and the "winners" are constant-zero bytes. `+58` looked promising and turned out to track the sample **rate**: 64 096 ↔ 12 000, 64 184 ↔ 13 000, 64 266 ↔ 14 000, 64 388 ↔ 15 625.

The E3 keeps root key in its preset. `E4P1` presets are not read and `docs/README.md` already says so.

So `Emu3Sample.pitch` is `None`, always — the same value [sample/aiff.py](../../src/samplerdisc/sample/aiff.py) gives an AIFF with no `INST` — and `write_wav` writes the `smpl` chunk for the loop with `MIDIUnityNote` 60. The chunk has no way to say "no root key"; the field is mandatory. **60 is the neutral value, not a finding**, and it is recorded as such here and in the format doc.

## Alternatives rejected

**Derive the root key from the sample name.** `Piano E0` → 28, `CP70 D#2` → 51; it would cover 1 741 of `esi32-gm`'s records and reads as a free win. Rejected, and it is the most important rejection here. A name is a label someone typed; this project's whole discipline is content over declared text ([ADR-0004](0004-detect-by-signature.md)), and the same reasoning already made `_pinned_disc` identify a disc by size rather than by filename. Worse, the output would be **indistinguishable from a decoded field** — nothing downstream could tell a root key the disc stated from one this tool inferred from a string, which is the failure mode [ADR-0012](0012-a-probe-must-confirm-a-file.md) exists to prevent.

**Write no `smpl` chunk without a root key.** Strictly conservative, and it changes nothing for any other backend. Rejected: it would measure 8 039 loops, document them, and then ship none of them, on the strength of a field the format does not have. ADR-0011 wants what the disc knows carried; the disc knows the loop.

**Clamp the loop end, as AKAI and Roland do.** Consistent with the rest of the project and it would raise `esi32-gm` from 107 loops to about 2 262. Rejected on the `protozoa` measurement above: the clamped loops score −0.10 against a control of −0.01, which is to say they are not loops. This is a case where consistency across backends would have been consistency in the wrong thing.

**Emit the right-hand pointer set as a second loop.** On a two-channel record both sets name the same loop, in each half. Rejected as duplication: one loop in the audio, listed once.

**Trust the declared extent over the record length on `esi32-gm`.** Its `end_L` runs about 45 frames past the payload on ~2 200 records, so reading 90 more bytes would let those loops through. Rejected: the shape test does **not** peak at the declared end when the extra audio is read — 10% within ±2 frames on `esi32-gm`, against 20% on `protozoa` — so nothing confirms that the reader is short. Changing the extent would also move every payload on two discs, which is exactly the shared-parser risk this deliverable was deferred over. It is recorded as open in [formats/emu3.md](../formats/emu3.md) instead.

## Consequences

**Good.** 8 039 of 14 738 E-mu samples now carry their loop points: 107, 1 157, 1 260, 1 689, 449, 2 551 and 826 across the seven discs. They were on the disc, they are lost when the disc is, and they cost a chunk a DAW may ignore.

**Good, and asserted.** The change is additive by construction — nothing in it touches `read_file` or the offset arithmetic — and the disc-backed suite now pins the **SHA-256 of every sample payload per disc** rather than only the counts. All seven are unchanged from the release before D17. A count table cannot see a payload that shifted by a byte while staying the same length; a digest can.

**Bad, and the headline.** `esi32-gm` is the format doc's reference disc and gets loops on 5% of its samples. The reference bank `8M GeneralMidi X` is largely among them. Refusing is the right call on the measurement, but a reader coming to the doc will find its worked example is the disc that yields least.

**Bad.** The pointer block was decoded from these seven discs and the two record shapes they show. A generation that writes a third shape gets no loops and nothing says so — it is one more case of a gate that is silent when it declines.

**Watch for.** The gates loosening. Every one of them — the end inside the audio, the minimum loop length, the whole-extent rejection — exists because a plausible alternative was measured and found to be wrong on real data. The minimum-length guard in particular is [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)'s bargain held up: a metric that rewards silence will find plenty of it on a sampler disc, and the Roland record says so from its own experience.

## What this exposes about ADR-0020

[ADR-0020](0020-read-e-iv-through-its-sample-directory.md) rejected "treat the paired length fields as a channel count" on a measurement, and **that measurement tested the wrong hypothesis.** It de-interleaved payloads as `LRLR` and found the roughness roughly doubled, which is what decimating a mono signal does — a sound conclusion about *interleaved* stereo. The pointer block says the layout would be **block** split, all left then all right, which de-interleaving cannot detect.

Measured directly, on the records whose pointers declare two channels, the two halves are the same performance. Median RMS-envelope correlation between them, per disc, against the same measurement on records declaring one channel:

| | `esi32-gm` | `eiiix-1` | `eiiix-2` | `protozoa` | `analogia` | `studio` | `vitous` |
|---|---|---|---|---|---|---|---|
| two channels declared | **0.99** | **0.71** | **0.95** | **0.55** | **0.91** | **0.96** | **0.82** |
| one channel declared | 0.13 | 0.16 | 0.59 | 0.26 | 0.21 | 0.22 | — |

Those samples are stereo, and this project currently writes each as a double-length mono WAV. `eiiix-2`'s one-channel figure of 0.59 is the weakest separation and is left standing rather than explained away; `protozoa` has only 18 two-channel records with enough audio to score.

Nothing in D17 changes that — fixing it moves audio, which is the one thing this deliverable must not do. It is written up in [formats/emu3.md](../formats/emu3.md) and left open for a deliverable of its own. The loop frames decoded here survive it unchanged: `(pointer − start) / 2` is a per-channel frame index either way.

> **D18 acted on this in [ADR-0026](0026-the-record-declares-the-channel-count.md), and every loop count above survived it.** One correction to the paragraph above: the channel count alone selects 2 721 records and 65 of those are not stereo — their own `end_L` contradicts the split — so 2 656 are written as stereo. `protozoa`'s weak 0.55 is those false positives, 19 of its 27. The two records anywhere whose loop end lies past its own channel are both among the 65, which is why 107, 1 157, 1 260, 1 689, 449, 2 551 and 826 are unchanged rather than nearly unchanged.
