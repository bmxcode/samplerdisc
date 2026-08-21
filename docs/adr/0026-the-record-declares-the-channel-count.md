# ADR-0026 · The record declares the channel count, and its own extents confirm it

**Status:** accepted · 2026-08-21

## Context

[ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) decoded the E-mu sample record's eight-pointer block and found a channel count in it: where `start_R == start_L + P/2` the payload is a **block** split — all of the left channel, then all of the right. It deliberately did not act on that, because acting on it moves audio and D17 was scoped to add metadata without touching a byte of payload. So this project shipped those samples as a mono WAV twice as long as the sound, with the right channel playing after the left instead of alongside it ([#32](https://github.com/bmxcode/samplerdisc/issues/32)).

It hid for two deliverables because the instrument that looked for it tested the wrong hypothesis. De-interleaving a payload as `LRLR` roughly doubles its sample-to-sample delta, which is what decimating a mono signal does — a sound refutation of *interleaved* stereo, and no evidence at all about a block split, which read as mono is one continuous waveform with a single join in the middle.

The E-IV discs also pair separate mono records into stereo by name, the way the rest of the collection does ([ADR-0017](0017-the-stereo-side-marker-is-a-character-class.md)). That is a **different mechanism** and a much rarer one: **12** samples across all seven reference discs are name-paired, against 2 656 whose record declares two channels, and no sample is both. Both being real is part of why one hid the other.

## Decision

**A two-channel record is one stereo sample: the two blocks are interleaved and written as a single stereo WAV in the volume's own directory. The channel count comes from the record and is confirmed by the record's own extents.**

### The gate has three conditions, and the third one had to be measured

```
start_L == DATA_START  and  len(payload) % 4 == 0
start_R == start_L + len(payload) // 2
end_L + 2 == start_R
```

The first two are the channel count ADR-0025 found. **The third is what says the record means it**: the left block must close exactly where the right one opens. 2 721 records across the seven discs satisfy the first two conditions and **65 of them fail the third** — 19 on `protozoa`, 40 on `eiiix-1`, 6 on `eiiix-2` — declaring a left channel that overlaps the right block or stops short of it.

Those 65 are not stereo, and the split has to reject them. The RMS envelope alone cannot see it, so two sharper instruments were used, with a control on each side:

| | records | envelope *r* | fine structure *r* | best lag *r* |
|---|---|---|---|---|
| **positive control** — the 6 name-paired `-L`/`-R` pairs on `eiv-analogia` | 6 | 0.954 | **0.402** | **0.532** |
| **negative control** — halves taken from two different records | 200 | 0.014 | **0.006** | **0.008** |
| selected, `esi32-gm` | 28 | 0.995 | 0.671 | 0.684 |
| selected, `protozoa` | 8 | 0.548 | 0.330 | 0.421 |
| selected, `eiiix-1` | 601 | 0.843 | 0.184 | 0.377 |
| selected, `eiiix-2` | 592 | 0.955 | 0.338 | 0.691 |
| selected, `eiv-analogia` | 279 | 0.908 | 0.343 | 0.430 |
| selected, `eiv-studio` | 320 | 0.983 | 0.667 | 0.768 |
| selected, `eiv-vitous` | 828 | 0.755 | 0.433 | 0.303 |
| rejected — `end_L` past `start_R` | 20 | 0.77 | **0.05** | **0.012** |
| rejected — `end_L` short of the split | 45 | 0.06 | **0.012** | **0.023** |

**Fine structure** is the 64-frame RMS envelope divided by its own 1024-frame trend, so what is correlated is transients rather than the decay; **best lag** is the peak normalised waveform cross-correlation over ±64 samples. Both were needed because the plain envelope is confounded: a single decaying note's two halves both decay and correlate at 0.94 without being two channels of anything, which is the same trap in a new place.

The positive control is the point. It is twelve records this pointer block knows nothing about, whose stereo-ness is established by an entirely separate mechanism, and the selected set scores with them while the 65 rejects score with two unrelated records.

`protozoa` is the disc to look at, because six of its rejects can be identified exactly. `Trom B2`, `Trom E3` and `Trom A3` are each written in two banks, and in all six the **first half is byte for byte the whole of a one-channel record of the same name** in `Vintage PresetsX`. Nothing matches the second half. Those payloads are twice their sound, which is why `start_R` lands on `start_L + P/2` at all — by arithmetic, not by declaration — and `end_L` says as much, closing 8 bytes past the halfway point rather than on it. Without the third condition they ship with an unaccounted-for second sound in the right channel.

The third condition also keeps D17 whole. The only two records on any disc whose declared loop end lies past its own channel — `Mbira A3` and `Mbira F3` on `eiiix-1` — are both rejects, so they stay mono and keep their loops. All seven per-disc loop counts survive the change untouched.

### The first block is the left channel

The pointer block is ordered `(start_L, start_R)` and `start_L` addresses the first block. That is structural and it is the whole of the argument.

The only content evidence available is weak, and it agrees. Of `eiv-analogia`'s twelve name-paired records, all **six** whose name ends `-L` declare their single channel in the left-hand pointer set, and three of the six ending `-R` declare theirs in the right-hand set — nine of twelve consistent, **none contradicting**, *p* ≈ 0.09. It is worth exactly what it is worth, and it is stated here so that nobody later mistakes it for the reason.

**A swap is inaudible in isolation and wrong forever**, which is why `tests/test_emu3.py` asserts it as a named claim rather than leaving it implicit in a slice index.

### One-channel records are left alone

The inverse error — a record that is stereo and declares one channel — was looked for and is not supported. **Not one** of the 12 017 records that do not declare the two-channel shape declares an extent of half its payload, which is the structural signature a hidden block split would leave. The 439 whose halves correlate above 0.9 by envelope show a midpoint z-jump of −0.27 to −0.41: there is no discontinuity where a block join would be, and their names are single decaying notes — `Piano Db3`, `Glockenspiel D5`, `Snare 2`.

`eiiix-2` is the disc that had to be checked, because the format doc gave it the weakest separation in the table at 0.59. Under the instruments above its high-envelope one-channel records score fine structure **−0.021**, which is the negative control, and its one-channel envelope median re-measures at **0.114** over 603 scored records. The gate is safe in that direction.

## Alternatives rejected

**Split on the channel count alone, without the extent check.** What [#32](https://github.com/bmxcode/samplerdisc/issues/32) and the format doc described, and it gives the round 2 721. Rejected on the measurement above: 65 of those records are two unrelated pieces of audio, and writing them as stereo is the failure this project cares most about — a file that opens, plays, and reports nothing wrong. It would also cost two real loops on `eiiix-1`, whose ends then lie past their own channel and must be refused.

**Write the mono halves alongside the stereo file, as [ADR-0007](0007-emit-mono-and-stereo.md) does.** The obvious precedent, and the one that had to be thought about rather than followed. ADR-0007's argument is specific: name pairing is a **heuristic**, a wrong pairing welds two unrelated sounds together, and the mono originals are how a user notices. Neither half of that transfers. The disc states the channel count in the record and the reader checks it against two further fields of the same record, so there is no guess to hedge against — and the "original" would not be an original: it is the concatenation this deliverable exists to stop writing, a file that is not a sound. Keeping it would also make "one record is one sample" false, and that sentence is load-bearing in three tests.

**Put the stereo file in `<out>/<volume>/stereo/`.** It is where the joined files go and it would need no new path logic. Rejected because that directory carries a meaning: *this file was assembled from two others whose names looked like a pair*. A natively-stereo record was never two files, and filing it there would tell a user the pairing had been guessed at when it was read. The directory stays for ADR-0017 joins, and a record that is stereo on the disc is written under its own name beside the mono ones.

**Decide stereo from the audio rather than from the record.** Correlate the halves per record and split where they agree. Superficially attractive because it is content over declaration, which is this project's discipline everywhere else ([ADR-0004](0004-detect-by-signature.md)). Rejected: it inverts what the discipline actually says. Content beats *declared text* — a filename, a name field — and here the declaration is structure, three fields of one record agreeing with the payload's own length. Worse, the instrument would be the confounded one: an envelope threshold set anywhere useful takes in hundreds of decaying single notes on `protozoa` alone. Measurement's job here was to check the gate, not to be the gate.

**Take the high-correlation one-channel records as stereo too.** Rejected on the evidence above: no structural support anywhere in 12 082 records, and the acoustic tail is explained by decay. If a disc ever does turn up with the inverse error, the thing to look for is an `end_L` covering half the payload while `start_R` reads zero — that is a real signature, and none exists today.

**Split at `end_L` rather than at `P/2` where the two disagree.** On the 45 records whose left block is *short* of the split, one could honour `end_L` and pad. Rejected: the halves are unrelated audio, so this would produce a stereo file whose right channel is another sound, differing from the loose gate only in length. Where the record contradicts itself, the answer is not to pick a side.

**Write the two blocks as separate mono files, `NAME-L` and `NAME-R`.** Lossless, and it would let `stereo.py` re-join them by name. Rejected as a round trip through the weaker mechanism: it would take a channel count the disc states, throw it away into a filename, and hand it to the heuristic ADR-0007 keeps originals against. It also invents names the disc does not carry, which is what [ADR-0017](0017-the-stereo-side-marker-is-a-character-class.md) refused for Roland.

## Consequences

**Good.** 2 656 of the 14 738 E-mu samples come out as the sound they are: 28, 601, 592, 8, 279, 320 and 828 across the seven discs, in the order the tables above and in [formats/emu3.md](../formats/emu3.md) use. `eiv-vitous` is all of it — 828 of 828, an orchestral string library that was entirely double-length mono. Their durations halve to the true one, and the CLI's verbose line stops reporting twice the length.

**Good, and asserted rather than claimed.** The per-disc payload SHA-256 does not move on any of the seven, because `read_file` is untouched and the audio written is a **permutation** of the same bytes — which the suite now checks directly by de-interleaving each stereo sample and comparing it to the two blocks the disc stored. The sample counts do not move either: one record is one sample, and only its channel count changed.

**Good.** Every loop count survives — 107, 1 157, 1 260, 1 689, 449, 2 551, 826 — and it survives *by construction* rather than by luck. `(pointer − start) / 2` is a per-channel frame index either way, the nesting check ADR-0025 already applies puts every loop inside the left block, and the two records that would have argued are rejects. A stereo sample's loop is now bounded by its channel, which is a tighter check than before.

**Bad.** `protozoa` falls from 27 stereo samples to 8, and 8 is too few to establish anything on its own — that disc's selected records score 0.33 on fine structure with an *n* of 8. Its stereo rests on the rule the other six discs establish, the same way `eiv-analogia`'s loops rest on the other six in ADR-0025.

**Bad, accepted.** Four records across `eiv-analogia` and `eiv-studio` have byte-identical halves. They are written as stereo, because the record declares two channels and this decision is that the record is the authority; a dual-mono file is a real thing a sampler can hold, and second-guessing it would mean deciding channel counts by comparing audio, which is the alternative rejected above.

**Watch for.** A generation that splits into blocks and writes a *third* record shape — one where `end_L` genuinely means something other than the left block's close. It would be refused silently and come out double-length mono, which is exactly the failure this deliverable fixed and exactly as quiet as it was before. The per-disc stereo counts in `tests/test_discs.py` are the tripwire: they are pinned as tightly as the sample counts, so a shape arriving or leaving has something to fail against.
