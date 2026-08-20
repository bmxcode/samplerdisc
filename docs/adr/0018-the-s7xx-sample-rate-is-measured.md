# ADR-0018 · The S-7xx sample rate is 44 100 by measurement, not by a field

**Status:** accepted · 2026-08-20

## Context

Every other rate this project writes is read off the disc. AKAI stores it at offset 138 of the sample header; E-mu stores it at offset 54 of the sample record. Both are verified against named discs, and rates like 33 075 and 24 444 come through exactly because they are *read*, never assumed.

**No rate field has been identified on a Roland S-7xx disc.** The 48-byte sample parameter record is fully accounted for — five 24.8 addresses, a cluster count, a loop-mode byte, an original key, and three fields that are zero on all 6 392 samples measured. The only remaining candidate with the low cardinality a rate flag would have is the u16 at offset 36, values `{0, 1, 2, 4, 5, 6}`, and it does not correlate with measured pitch at all.

The obvious way to settle it is to measure the pitch of the recorded waveform against the original-key byte. That was done, and **it cannot settle it**, for a reason worth stating plainly: 44 100 and 22 050 differ by exactly one octave. That is the interval pitch estimation resolves worst, and the interval an original key can itself be wrong by. Any method that octave-corrects its estimates destroys the distinction it was meant to measure — the estimates all snap to 44 100 and prove nothing.

What the measurement *does* establish is the fine structure. Every ratio measured lands within a few percent of an exact power of two — 0.486, 0.959, 0.977, 0.988, 0.998, 1.924, 1.956, 1.980 — so **all samples share one rate, and it is 44 100 × 2ᵏ**. Anything like 32 000 or 48 000 is excluded. `edirol-brass` puts 93% of its chromatic samples at ×1.0. The S-770 records at 44.1 and 22.05 kHz, so two candidates remain and the majority picks the first.

## Decision

**Write 44 100, as a named constant with the measurement and its limits in the docstring, and say so in the format doc.** Do not infer a rate per sample, and do not offer an override.

## Alternatives rejected

**Refuse to extract until the field is found.** Consistent with reading every other rate off the disc, and it would never emit a wrong one. Rejected because it throws away 6 392 samples that are otherwise completely understood — located, byte-identical, with correct root keys and loop points — over a value that is right on every disc anyone has produced. This is the [ADR-0009](0009-export-iso-escape-hatch.md) argument: hand over what succeeded and state the gap.

**A `--rate` override.** Cheap, and it puts the decision with the user. Rejected because it asks a question the user cannot answer. Nothing on the disc, in its label, or in any sampler's UI tells them which rate a library was recorded at, and a flag implies the tool knows of a case where the default is wrong. It does not.

**Infer the rate per sample from its pitch and its original key.** Uses the evidence actually available and would adapt to a 22.05 kHz disc automatically. Rejected as the worst option: the inference is exactly the one shown above to be unreliable at the octave, so it would introduce per-sample errors on discs that are currently uniformly correct — trading a stated, uniform assumption for a silent, variable one.

## Consequences

**Good.** Every S-7xx sample extracts, with a rate that is right on all nine reference discs.

**Bad, and stated rather than implied.** A 22.05 kHz S-7xx disc would come out at double speed. Nothing would report it. No such disc has been seen, and the fine-structure result says such a disc would be *uniformly* at half rate rather than mixed — so the failure is a whole library an octave up, which is audible immediately, not a scattering of wrong samples that is not.

**Mitigating, slightly.** The root key does go into the `smpl` chunk and is verified, so a sample loaded into a DAW plays at the pitch it is mapped to. A user with such a disc would hear it against a keyboard rather than having to measure it.

**Watch for.** A rate field turning up in the *partial* or *patch* record rather than the sample record. Those are located and undecoded ([ADR-0016](0016-the-s7xx-hierarchy-is-located-not-walked.md)), and a machine that records at two rates has to store it somewhere. If one is found, this decision is superseded, not amended.
