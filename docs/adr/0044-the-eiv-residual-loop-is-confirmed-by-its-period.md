# ADR-0044 · The E-IV residual loop is confirmed by its period, not its forward window

**Status:** accepted · 2026-09-05 · relates to [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md), [ADR-0030](0030-the-whole-extent-no-loop-is-refused-at-both-ends.md)

## Context

[Issue #50](https://github.com/bmxcode/samplerdisc/issues/50). The E-IV loop is decoded from the record's own eight-pointer block, the one structure the format otherwise distrusts on E-IV ([ADR-0020](0020-read-e-iv-through-its-sample-directory.md) reads the record's *length* from its directory entry instead). Every other E-mu disc's loops are confirmed by content — the forward shape/join oracle of [formats/emu3.md](../formats/emu3.md), which correlates the waveform *after* the loop start against the waveform *after* the loop end. On `eiv-analogia` that oracle has **no power**: the disc's loops are overwhelmingly the whole-extent "no loop", which ends within a few frames of the last, so there is almost no audio after the loop end for a forward window to work on. [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) recorded it exactly — 441 of 449 records pass every gate, only 34 were loud enough at both ends to score, and those 34 showed nothing — and after D23 ([ADR-0030](0030-the-whole-extent-no-loop-is-refused-at-both-ends.md)) refused the whole-extent form the disc keeps **six** loops, emitted entirely on the rule the other reference discs establish, with no per-record confirmation of their own.

The question this deliverable answers is the one the issue poses: can *another* metric score those six survivors, or does E-IV loop emission on this disc simply rest on borrowed evidence? [formats/emu3.md](../formats/emu3.md) already carries the candidate. The loops D21 newly admitted on `esi32-gm` and `protozoa` were confirmed not by the forward window but by the **256 frames *before* the loop start and before the loop end**: a loop of period `P` makes `x[t] ≈ x[t − P]`, and that pairing still exists on a loop running to the last frame — which is exactly the near-whole-extent shape the forward window cannot reach.

## What the disc shows

Measured on all six of `eiv-analogia`'s residual loops, with the same guards the shipped parser and the doc oracle use — a 256-frame window and a 15%-of-peak loudness gate on the end window, because a metric that rewards silence finds plenty of it on a sampler disc.

The control is **not** a wrong loop *start*, which is what isolates the start on a musically-positioned loop. On a sustained near-whole-extent tone the lead-in self-correlates at any period multiple, so a wrong start scores high and separates nothing — the first measurement of this deliverable confirmed it, with wrong-start "controls" scattered from +0.01 to +0.70. The control that works is **lag sensitivity**: the correlation must peak at `P` and fall away at off-period lags (`a + f·P` for `f` a fraction of the period). A chosen period is a local maximum; a self-similar texture is flat across lags.

| `eiv-analogia` residual loop | period *P* (frames) | *r* at lag *P* | best off-period lag | outcome |
|---|---:|---:|---:|---|
| `Usnotthem Chorus` | 127 347 | **+0.99** | +0.84 | confirms |
| `Trilling Sound` | 249 616 | **+1.00** | +0.26 | confirms |
| `The Lost Chord 1` | 212 474 | **+1.00** | +0.71 | confirms |
| `The Lost Chord 2` | 250 761 | **+0.99** | +0.79 | confirms |
| `Conscience Call` | 338 751 | +0.16 | +0.26 | flat — no period structure |
| `Got Scratch?` | 239 951 | — | — | end below the loudness gate |

Four of the six splice at their own period as a clear local maximum, where the forward window said nothing. `Conscience Call` scores flat at every lag — a "no loop" whose start (frame 13 061) sits just past D23's start-side slack, so the whole-extent refusal did not catch it. `Got Scratch?` ends below 15% of its own peak: it cannot be scored, and a loop ending in near-silence is the same signature [ADR-0030](0030-the-whole-extent-no-loop-is-refused-at-both-ends.md) reads as a "no loop".

**Calibrated, so the instrument is not rubber-stamping analogia.** The same metric run on `eiv-studio`'s real, forward-confirmed loops (the ones [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) validated at +0.86) marks the period a clear local maximum on **57%** of its scorable emitted loops, against a null instrument's near-zero. The window that vindicates analogia's four survivors first works where the forward oracle already did.

## Decision

**Confirm the E-IV near-whole-extent loop by the period / pre-start window, and wire that confirmation into the suite as a disc-local oracle rather than into the parser.** `tests/test_discs.py` pins every emitted loop on `eiv-analogia` by name and outcome — the four that confirm, `Conscience Call` flat, `Got Scratch?` unscorable — and calibrates the metric on `eiv-studio`. It is [numpy](https://numpy.org)-gated (`pytest.importorskip`) and disc-gated, like the `soundfile` and `machfs` oracles, so it skips under the stdlib-only `verify` run and adds no dependency to what ships ([ADR-0001](0001-pure-python-stdlib-only.md)).

This is the discipline the rest of the project already follows ([ADR-0004](0004-detect-by-signature.md), [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md), [ADR-0030](0030-the-whole-extent-no-loop-is-refused-at-both-ends.md)): a content measurement decides what is true, and nothing about the audio decode depends on it. `sample.loops` is what the extractor already emits; the oracle reads it, it does not gate it.

## Alternatives rejected

**The forward window.** It is the instrument that has no power here, which is the whole of issue #50. A near-whole-extent loop leaves no audio after its end, so the correlation cannot be computed. Kept for every other disc, where it works; not the instrument for this one.

**A wrong-start control.** The natural analogue of the forward oracle's control, and wrong. For a sustained near-whole-extent tone the pre-start lead-in self-correlates at any period multiple, so a wrong start lands on high correlation and isolates nothing — measured, and the controls came back scattered and high. Lag sensitivity — is `P` a local maximum — is what a wrong-start control cannot see.

**Drop `Conscience Call` (and `Got Scratch?`) from emission.** The period metric refutes `Conscience Call` outright and cannot vouch for `Got Scratch?`, so refusing them looks principled. Rejected as out of scope: it is a change to *what ships*, moving a pinned loop count (6 → 4) and adding new emission logic — refuse a near-whole-extent loop by its own period — that would need its own measurement across all ten discs and its own ADR, exactly the shared-parser risk [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) was deferred over. This deliverable is a measurement and an honesty pass, not a feature. The two are documented and named; their emission is untouched.

**Do nothing, and state the borrowed evidence in the docs.** The issue's other branch, and the honest outcome *if* nothing could score the survivors. Something can. Recording "borrowed evidence" when four of the six now carry the disc's own confirmation would understate what was found; the honest outcome is the confirmation, with the residual narrowed to two named records.

## Consequences

**Good.** Four of `eiv-analogia`'s six loops stop resting on borrowed evidence — they are confirmed on the disc itself, by a metric calibrated to have power where the forward oracle does not. The residual honesty gap is narrowed from "the whole disc's loop emission" to two named records, and surfaced in `docs/README` "What is not done" the way the extent gaps are, which is what [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) recorded but never surfaced.

**Good, and asserted.** No shipped code changed. `sample.loops`, the payload digests, the loop and stereo counts in `tests/test_discs.py` are all untouched — the oracle reads what the extractor already produces. The pinned per-name outcomes are a regression net: a future change that quietly confirms `Conscience Call`, or loses one of the four, fails the suite.

**Bad, and named.** `Conscience Call` and `Got Scratch?` are still emitted with a loop the disc cannot vouch for — one refuted by the period test, one unscorable because it ends in silence. Keeping them is the deliberate cost of not changing emission in a measurement pass; they are documented rather than hidden.

**Watch for.** The calibration floor. The suite asserts the period metric confirms at least half of `eiv-studio`'s scorable loops, which is what says the instrument still has power. A future change that quietly weakens the metric could drop analogia's four to "flat" and pass everything else; the calibration arm is there so that the instrument is proven on known-good loops in the same run that judges the unknown ones.
