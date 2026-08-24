# ADR-0030 · The whole-extent "no loop" is refused at both ends

**Status:** accepted · 2026-08-24

## Context

[Issue #41](https://github.com/bmxcode/samplerdisc/issues/41). `sample/emu3.py` refuses a loop spanning a sample's whole declared extent, because that span is the E-mu format's *"no loop"*: the sampler fills the four loop pointers with the sample's own bounds when nothing set them, and emitting it writes a `smpl` chunk telling a DAW to loop the entire file. The guard was `a == 0 and b >= extent − FULL_EXTENT_SLACK` — sixteen frames of slack at the **end** and an exact zero required at the start.

The discs do not write those bounds at frame 0. They write them **inset by a small fixed amount at both ends**: `loop_start = start + C1`, `loop_end = end − C2` for a per-disc constant of a handful of bytes. `ditto-drums` writes `(12, 12)` — frame 6 to six frames from the end — on 898 of its records; the two EIIIX discs write `(4, 4)`; `esi32-gm`, `protozoa`, `eiv-vitous` and `eiv-analogia` write `(12, 10)`. So the frame-0 guard never fired, and every one of these discs shipped a loop over the whole file — **934 of `ditto-drums`'s 948 records** most visibly, a disc of drum kits whose every WAV asked a DAW to loop the entire hit.

This was left out of [ADR-0029](0029-a-record-is-closed-by-the-channel-it-declares.md)/D21 deliberately, so that the loop counts moved for one reason at a time. It is D23's alone.

Widening the guard to `a <= FULL_EXTENT_SLACK` is the obvious move and is **not** obviously right. A sustained organ or string can legitimately loop over nearly its whole length, and a rule that deletes those to catch drum hits destroys real loop points to hide a heuristic. What separates a filled-in "no loop" from a real whole-extent loop had to be measured, not assumed.

## What the discs show

Measured against all ten reference discs. The join and shape oracle of [formats/emu3.md](../formats/emu3.md) is the wrong instrument here, exactly as the issue warned: a whole-extent loop starts within a few frames of 0 and ends within a few of the last, so there is almost no audio before its start and none after its end for the windowed correlation to work on. Two measurements that **do** apply separate the populations on every disc.

**End energy.** The RMS in a 64-frame window at the loop end, as a fraction of the sample's peak, is below 15 % on 70–100 % of the inset population — the loop ends in silence — where a real loop ends that quietly on only 13–33 %. A loop is not a loop when it ends in silence.

**Uniqueness of the splice.** Where a record is loud enough at both ends to score, the join splices seamlessly where a random start against the same end does not — the signature of a chosen loop point — on 0–11 % of the inset population against 33–56 % of the loops this project already ships. The right-hand column is that same measurement on the disc's real loops: the calibration of what a real loop looks like on this instrument, and the inset population sits far below it every time.

| Disc | refused | inset ends quiet | inset uniquely-splices | real-loop control |
|---|---:|---:|---:|---:|
| `esi32-gm` | 428 | 70 % | 11 % | 37 % |
| `protozoa` | 1 762 | 72 % | 10 % | 37 % |
| `eiiix-1` | 472 | 98 % | 1 % | 49 % |
| `eiiix-2` | 372 | 97 % | 2 % | 41 % |
| `emu-classics` | 302 | 88 % | 3 % | 36 % |
| `vintage` | 107 | 82 % | 5 % | 46 % |
| `ditto-drums` | 934 | 100 % | 0 % | 43 % |
| `eiv-analogia` | 443 | 97 % | 1 % | 33 % |
| `eiv-studio` | 337 | 87 % | 4 % | 41 % |
| `eiv-vitous` | 628 | 100 % | — | 56 % |

**Structure agrees with content.** The inset bounds are the record's own extent inset by a *fixed* constant — the signature of an auto-filled field. A hand-set loop start is at an arbitrary musical position: on the loops this project already ships, the byte inset from the record's start is a scattered 44, 136, 11 204, 52 536, never a fixed few. So the population the guard refuses is also the one the structure marks as unauthored.

**`eiv-vitous` and `eiv-studio` are the check that matters.** [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) validated their loops by the shape test at +0.68 and +0.86, and those validated loops are the *real-loop* column above — they are the `narrow` population, and they are **kept**. What is refused on those two discs is a separate whole-extent population that ends in silence. `eiv-analogia`'s loops never had independent evidence — ADR-0025 recorded that only 34 scored and those showed nothing — so refusing 443 of its 449 takes nothing that was ever established.

## Decision

**Refuse a loop whose bounds lie within `FULL_EXTENT_SLACK` frames of both ends, not only the start-0 case.** One line in `sample/emu3.py`:

```python
if a <= FULL_EXTENT_SLACK and b >= extent - FULL_EXTENT_SLACK:
    continue
```

`FULL_EXTENT_SLACK` stays 16 frames: every inset observed is at most 12 frames (`d_start` of 24 bytes) at the start and 7 at the end, so 16 covers them with margin. The rule fires only when a loop is within the slack of **both** bounds, so a real loop that merely begins near the front, or merely ends near the back, is untouched — the only records at risk are those whose loop *is* the record's own extent.

The rule is **structural** — the loop is the record's own bounds — and the measurement justifies it rather than living in the parser. This is the same discipline as everywhere else in the project ([ADR-0004](0004-detect-by-signature.md), [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md)): a content test decides what a rule should be, and the shipped rule reads declared structure.

## Alternatives rejected

**Leave the guard at `a == 0`.** Ships the bug on ten discs, `ditto-drums` worst of all.

**A content guard: refuse a whole-extent loop only where its end is in silence.** This keeps the loud-ended inset loops, which is attractive on `esi32-gm` and `protozoa` where ~10 % of the refused population splices uniquely. Rejected: it puts an RMS measurement of the audio into the shipping parser, which is exactly the coupling [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md)'s "watch for: the gates loosening" warns against — a loop decode that depends on the loudness of the sample is a decode that fails silently and differently on the next disc. And the loud-ended remainder is not clearly real: it splices seamlessly at random starts nearly as often as at the whole-extent bound, which is a sustained tone that would splice anywhere, not a chosen loop point.

**Refuse only bounds matching each disc's dominant `(C1, C2)` inset.** More precise on paper. Rejected: it needs a per-disc constant fitted from the data and carried in the parser, and the constants — `(4, 4)`, `(12, 10)`, `(12, 12)` — are close enough to a real near-whole loop's that the fit buys nothing the simple both-ends slack does not. One structural rule beats ten fitted ones.

**Widen the end slack instead / raise `FULL_EXTENT_SLACK`.** Misreads the bug. The end already had its slack; it was the start that was pinned to exactly 0. Sixteen frames is enough at both ends and there is no evidence for more.

## Consequences

**Good.** The whole-extent "no loop" stops being emitted on all ten discs. `ditto-drums` goes from 948 loops to 14, `eiv-analogia` from 449 to 6, `eiv-vitous` from 826 to 198 — the drum and no-loop discs shed almost all of theirs, and the melodic discs keep most: `emu-classics` 1 435 → 1 133, `vintage` 953 → 846.

**Good, and asserted.** No audio moved. `read_file` and the offset arithmetic are untouched, so every per-disc payload digest in `tests/test_discs.py` is unchanged, and the sample and stereo counts with them. Only the loop-count column moved, on every disc, and the suite pins the new numbers.

**Bad, and the headline.** Every EIII/ESI and E-IV loop count moves. Anyone who extracted an E-mu disc before this got a `smpl` chunk looping the whole file on a large fraction of its samples — harmless where a DAW ignores `smpl`, wrong where it does not. The audio was always right; the loop metadata was not.

**Stated cost.** On `esi32-gm` and `protozoa` about 10 % of the refused records splice uniquely and could conceivably be a near-whole-extent loop the disc intended. They are refused with the rest because they are structurally the record's own bounds inset by the same fixed constant, and separating them would need the content test this project keeps out of the parser. This is the one place the rule may take a real loop, and it is recorded rather than hidden.

**Watch for.** A generation that writes its "no loop" some other way — a different inset, or a genuine frame-0-to-last span — is not caught by this and gets a whole-file loop with nothing to say so. The rule catches the form ten discs write, not every form the format could.
