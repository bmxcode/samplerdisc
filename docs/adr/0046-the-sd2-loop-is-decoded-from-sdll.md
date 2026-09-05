# ADR-0046 · The Sound Designer II loop is decoded from `sdLL`, confirmed by the Digidesign spec and the disc's own splice

**Status:** accepted · 2026-09-05

## Context

D33 read the 24 `Sd2f` files on `sonic-images-v2` — audio from the data fork, rate/width/channels from the resource fork's three `STR ` resources — but shipped **no loop** ([ADR-0040](0040-sound-designer-ii-is-decoded-from-the-data-fork.md), [issue #75](https://github.com/bmxcode/samplerdisc/issues/75)). The resource fork carries a Digidesign `sdLL` loop resource whose first file "even looks like a loop (two in-range frame values)", but [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) forbids decoding a loop without an oracle: an off-by-units or off-by-a-field loop opens, plays, and reports nothing wrong. D33 had no oracle for `sdLL`, so it deferred it against "a specimen whose loop can be confirmed."

That oracle now exists, and it is the first of the three the issue named: **a Digidesign specification for the `sdLL`/`sdDD` layout.** The Sound Designer II File Format document (© Digidesign 1988–1990), recovered from the Wayback Machine copy of `lim.di.unimi.it/IEEE/DGDES/SDII.HTM` (the live page is gone), gives every field, its width, and its units. `sdLL` is an 8-byte header — `Version` (Int, 1), `HScale` and `VScale` (Int, unused), `NumLoops` (Int) — followed by `NumLoops` × a 14-byte `LoopRecord`: `LoopStart` and `LoopEnd` (LongInt, "reference to start/end **sample frame** of this loop"), `LoopIndex` (Int, `1..NumLoops`), `LoopSense` (Int, `117` forward / `118` alternating), `Channel` (Int, `0..NumChannels-1`), all big-endian. `sdDD` is a `DocumentDataRecord` of display and session state (comments, zoom, cursor), carrying no audio loop.

## Decision

**Decode the loop from `sdLL` and carry it into the WAV `smpl` chunk. Do not decode a root key, because `sdLL` carries none.**

`sample/sd2.py` reads the id-1000 `sdLL` body, takes `NumLoops` from the header and reads that many records, and keeps a loop only where it lies inside the audio (`0 <= LoopStart < LoopEnd <= frameCount`) — a truncated or out-of-range resource yields no loop rather than an invented one, the degrade-don't-crash stance the rest of the module already takes. The frame positions are **per-channel and identical across an interleaved stereo file**, so one record becomes one WAV loop, not one per channel — the same "one loop in the audio, listed once" ADR-0025 settled for E-mu's two pointer sets. `Channel` records which channel the loop was authored on and does not change the frame index. `pitch` stays `None` and the `smpl` chunk keeps `MIDIUnityNote` 60, exactly as the E-mu path does: the neutral value, not a finding. `extract._convert_sd2` already passed `loops=_wav_loops(sample)`, so once `sample.loops` is populated the loop flows through unchanged.

### The interpretation is confirmed three ways

This is a stronger basis than the E-mu loops shipped on, which had no spec at all — only content correlation.

1. **The specification** states the field widths and, decisively, the **units: sample frames**, which is the exact ambiguity ADR-0025 exists to guard against.
2. **Structural self-consistency on 24/24.** Read against the disc, every `sdLL` is exactly 22 bytes = `8 + 14×1` with **zero trailing bytes**, `Version` 1, `NumLoops` 1, `LoopSense` **117** on all 24, `LoopIndex` 1, `Channel` 0 or 1 (in range, and varying — a real field, not a constant), and every `LoopStart < LoopEnd ≤ frameCount`. A wrong field layout cannot land all of these at once; that they all fall out at no cost is the same argument ADR-0025 made from the E-mu pointer block.
3. **Content corroboration on the disc itself.** The [emu3.md](../formats/emu3.md) forward shape/join oracle — the 256 frames at the loop start correlated with the recorded continuation past the loop end, which for a periodic instrument tone is the same waveform one period-multiple later — confirms **21 of the 24** loops at *r* ≥ 0.9 (23 at *r* ≥ 0.6). The forward window has power here precisely because SDII samples keep audio past the loop end, unlike the near-whole-extent `eiv-analogia` loops that needed the period window ([ADR-0044](0044-the-eiv-residual-loop-is-confirmed-by-its-period.md)).

### The few weak loops are emitted and named, not gated out

Three loops — `F#2 Gtr Str`, `E1 Gtr Str`, `Obiestack C2`, inharmonic guitar and stack sounds whose start does not periodically predict their post-end audio — score below the *r* ≥ 0.9 confirm bar (only `F#2 Gtr Str` below *r* ≥ 0.6). All 24 are emitted anyway. The spec confirms the *interpretation* identically for all 24 — same version, same one-record structure, same forward sense — so a low forward-shape score is a **lack of power on that sample, not evidence of a wrong loop**, and refusing it would be refusing on tool power rather than on the disc. This is the stance ADR-0025 and ADR-0044 already take, still emitting `eiv-analogia`'s `Conscience Call` and `Got Scratch?`. The three are pinned by name in `tests/test_discs.py`, so a regression that drops a currently-confirmed loop below the bar breaks the set.

### The end convention is documented, not guessed

`LoopEnd` is the loop's inclusive end frame; the decoder stores it as an exclusive `end` and the WAV writer makes it inclusive again for RIFF. Whether the intended end is `LoopEnd`, `LoopEnd-1` or `LoopEnd+1` is **below audio resolution** — the forward splice scores identically at all three — so the ≤1-frame ambiguity is recorded here and in [formats/hfs.md](../formats/hfs.md) rather than pretended away.

## Alternatives rejected

**Emit only the content-confirmed subset** (ship ~21, refuse the rest), the way `esi32-gm` ships loops on a fraction of its samples ([ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md)). Rejected: that refusal was on a *measurement that a clamped loop end was not a loop* — evidence the loop was wrong. Here the evidence runs the other way: the spec confirms the interpretation for all 24 identically, and the weak three differ only in how much power a forward window has on that timbre. Gating them out would ship a confusing split on one disc for no gain in correctness, and it contradicts ADR-0044's own precedent of emitting unscorable loops.

**Defer for want of a per-file content oracle**, holding out for a published render of these exact loops (the EBL/KRZ pattern). Rejected: the issue names "a Digidesign spec for the `sdLL`/`sdDD` layout (field widths, units, the meaning of the leading count fields)" as acceptance path #1, and it is in hand and confirmed against the disc. No render of a 1990s SampleCell library's loops exists to wait for.

**Read a root key from `sdDD` or the sample name.** Rejected: `sdDD` holds no root key (it is document/display state), and inferring pitch from the sample name is the labelled-text inference ADR-0025 rejected for E-mu — output indistinguishable from a decoded field.

## Consequences

**Good.** The 24 `sonic-images-v2` SDII WAVs now carry their loop points, which a DAW may honour and any may ignore ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)). The loop was on the disc and is lost when the disc is. The `sdLL` layout is written down in [formats/hfs.md](../formats/hfs.md) with the recovered source, so the next session inherits the fact, not another hex-editor afternoon.

**Good, and asserted.** The change is additive — `_convert_sd2` and the audio path are untouched — and the `machfs` byte oracle (D32/D33) still pins every fork byte-for-byte, so the audio digests do not move.

**Bad, and named.** Three loops rest on the spec and structural consistency without their own forward-shape confirmation, because the instrument has no power on their timbre. They are emitted and pinned by name, the same residual ADR-0044 carries for `eiv-analogia`.

**Watch for.** A SampleCell disc whose `sdLL` carries `NumLoops > 1`, an alternating (`118`) sense, or a non-`Sd2f` shape. The reader handles all three by construction (it reads the count, maps `118` to the RIFF alternating type, and range-gates each record), but only the single-forward-loop case is exercised on a real disc — the rest is synthetic until a second SDII specimen turns up.
