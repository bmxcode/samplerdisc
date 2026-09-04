# ADR-0041: Stereo `.EBL` is interleaved once a render can check the interleave

**Status:** accepted

## Context

[ADR-0033](0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md) shipped the mono `.EBL` path and **refused stereo with a reason** (its decision part 3). Not because the layout was unknown -- the format stores stereo non-interleaved, a whole left block then a whole right block (`LLLL…RRRR`), and the reference implementation reads it across ~42 000 files -- but because *our* output was checked by nothing. The one EBL disc in hand, Vintage Pro, is 1 061 files and every one is mono, so there was no stereo-in / known-good-out pair to check an interleave against. An L/R swap or an off-by-a-block split opens, plays as noise, and reports nothing wrong: the silent failure this project guards against everywhere. ADR-0033 named the gap, located the render outputs, and said picking it up would be "verification and interleaving, not rediscovery."

Two things have since closed the gap.

**The reader was generalised (#73).** D33's EBL constants turned out to be Vintage Pro's values, not the format's -- the channel test, the audio pad and the length formula each misfire on a second bank. The generalised reader reads the channel count from the `V12` byte, anchors the audio at `V2`, and bounds the length at the `EXLZ` trailer or EOF, verified byte-for-byte on two banks. Crucially, that same end-anchored span bounds **both** channels of a stereo record, since stereo stores one block after the other.

**A stereo input paired with a render now exists.** archive.org's `emuexbsoundbanks` ships E-mu Classic Series Vol 13 Dance 2000 as loose `.ebl`, and its bank name matches mattetti's render folder character-for-character -- 636 stereo FLAC. Used strictly as a local validation input, never a disc and never committed (ADR-0033's "on a disc" line still holds; this does not open a loose-bank mode). It is the stereo half ADR-0033 lacked.

## Decision

**Interleave a stereo `.EBL`'s two blocks into a stereo WAV, because a render now verifies the interleave. Reverse ADR-0033's stereo refusal; keep everything else it decided.**

- The channel count is the record's, off `V12` (ADR-0026). Each of the two equal, contiguous blocks is `V3 − V2` bytes -- the same per-channel length that bounds a mono file -- so the audio is `2 · (V3 − V2)` and, since it ends at the `EXLZ` trailer or EOF (as for mono), the left block starts at `audio_end − 2 · (V3 − V2)`. `left = payload[start : start + (V3 − V2)]`, `right = payload[start + (V3 − V2) : audio_end]`.
- **The split is anchored from the end, not the front, because the front is two bytes wrong on some banks.** Reusing the mono path's `audio_start = block + V2 − 4` and splitting the span at its midpoint is exact on Dance 2000 but lands two bytes into the first sample on the grand banks (their audio begins at `block + V2 − 6`), shifting every frame and scrambling the interleave. The length `V3 − V2` and the trailer/EOF end hold on every bank, so anchoring the start from the end sidesteps the per-bank pad. A truncated rip -- whose lost tail would drag the from-the-end start off the front of the file -- falls back to a front-anchored midpoint split, degrading from the tail not the head.
- The two blocks are interleaved to `LRLR` with the shared `stereo.interleave` -- the same call the EMU3 backend uses for its block-split stereo and the AKAI joiner uses for `-L`/`-R` pairs, not a new rule. No value is altered; the samples are the record's own, only reordered. The loop is carried in per-channel frames, the unit the WAV `smpl` chunk uses.
- This is verified the way the mono path is: `stereo.interleave(left, right)` reproduces the stereo render **byte-for-byte on every uniquely-named stereo file** across four banks, order and block boundary both confirmed. The check is wired into `tests/test_discs.py`, gated on the same `SAMPLERDISC_EBL_DANCE_*` env vars, and widened to mattetti's entirely-stereo grands (Giga Schimme, EW PS18 Steinberg Grand, Studio Grand) under `SAMPLERDISC_EBL_BANKS`/`SAMPLERDISC_EBL_RENDERS`. A render is a subset of the input, so the reader's stereo count must be **at least** the render's own stereo-FLAC count and every matched file must be byte-exact.

## Rejected

**Keep refusing stereo until a stereo *disc* turns up.** This was ADR-0033's stance, correct when nothing checked the output. It is now the same mistake ADR-0033 rejected for mono: a second disc would show the format is stable, but a render shows the decoder is *right*, which is the stronger fact and the one the doubt actually needed. Deferring would leave 636 files per bank unread to satisfy a rule a render already serves.

**Split the mono path's front-anchored span at its midpoint.** This was the first cut, and it is exact on Dance 2000 -- but the grand banks' audio starts two bytes earlier than `block + V2 − 4` predicts, so the midpoint of that span is off by a sample and the interleave scrambles both channels. The bug is invisible without a stereo render, which is exactly why one was required before shipping. Anchoring the start at `audio_end − 2 · (V3 − V2)` uses only lengths and the end, both of which hold on every bank, and the render check caught the front-anchor error the moment the grands were added.

**Open a loose-`.exb` bank mode to reach more stereo banks.** The stereo banks are read here only as local validation inputs, exactly as mattetti's `data/` is. Serving bare bank folders is the source-6 trap ADR-0033 part 4 refused and is not reopened: the container layer stays the reason this tool exists.

## Consequences

**Good.** A stereo `.EBL` now converts to a stereo WAV instead of being skipped -- 636 files on Dance 2000, and the entirely-stereo grands in full -- named from the header and carrying the loop, with no value altered.

**Good.** The interleave is pinned to the publisher's own render in `tests/test_discs.py`, not to the bytes it came from, and on more than one bank. A broken interleave (an L/R swap, a mis-split) fails the check rather than shipping silent noise.

**Neutral.** Vintage Pro is unaffected -- it has no stereo files -- so the mono path and its render check are unchanged.

**Watch for.** A stereo bank whose two blocks are *not* equal length (a trailing partial block, say). The `V3 − V2` split assumes they are, which every measured file bears out; `stereo.interleave` pads a short side rather than crashing, but a systematically unequal bank would need a second length field, and the render check is what would catch it.
