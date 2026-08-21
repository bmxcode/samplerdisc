# ADR-0020 · Read E-IV through its `E3S1` sample directory

**Status:** accepted · 2026-08-20 · supersedes [ADR-0015](0015-locate-banks-by-signature.md)

## Context

[ADR-0015](0015-locate-banks-by-signature.md) decided that an E-mu bank whose interior is not recognised is listed rather than guessed at, and it made that conditional in as many words: *"Extraction waits for a second E-IV disc."* The reasoning was that one specimen cannot distinguish a format from that disc's quirks, and that a wrong record boundary yields WAVs that play as noise with nothing reporting a problem.

**The condition is met.** Three E-IV discs are in hand, from two publishers: `eiv-analogia` and `eiv-studio` are both Producer Series and may share a mastering run, and `eiv-vitous` is a different publisher entirely and serves as the independence check.

With three specimens the interior resolves. E-IV banks carry no `EMULATOR` header — not one occurrence on any of the three discs — but they carry something better: a per-bank sample directory of 32-byte `E3S1` entries, each with a name, a length and a running offset, chained by

```
position[i+1] == position[i] + length[i] + 10
```

with an index that increments alongside it. The full layout is in [formats/emu3.md](../formats/emu3.md).

The third disc earned its place. Two constants that hold perfectly on Producer Series fail on Vitous — `+30` with a bias of four sizes 74% of `eiv-studio`'s records and **0%** of Vitous's — and a two-disc study would have written one of them down as fact.

## Decision

**Read E-IV banks through the `E3S1` sample directory, and bind a directory to a bank only where an independently located chain confirms it.**

Three things follow from that, and each is the same rule applied at a different layer.

**The chain bounds the bank, not arithmetic.** A break in the running offset or in the index is a bank boundary. Both halves are self-checking, so the split is exact. Segmenting on physical adjacency instead — the obvious reading — gives 935 runs for `eiv-studio`'s banks, because that disc scatters its entries rather than packing them.

**The directory sizes the sample, not the record.** The record's own length field is unusable on E-IV: the EIII rule matches 0 of 5 349 consecutive pairs across the three discs, and no other offset survives all three. The directory's big-endian length matches every sample on all three.

**A bank with no confirmed directory is listed, not guessed at.** 100 of `eiv-studio`'s 230 banks come out named and empty, carrying a note. This is ADR-0015's own mechanism, kept and still load-bearing.

## Alternatives rejected

**Keep the ADR-0015 position and wait for a fourth disc.** Thirteen more E-IV discs sit in `archive-oldschoolscds`. Rejected: the condition ADR-0015 set was a *second* specimen and there are three, from two publishers, with the disagreements between them already found and resolved in Vitous's favour. A rule that can never be satisfied is not a condition, it is a refusal.

**Place banks by arithmetic on `start`.** This is what ADR-0015 rejected, and it is still rejected. The allocation unit is 2048 blocks on `eiv-analogia` and 1024 on the other two, with a per-disc bias, and no header field predicts either. What is done here is different in the way that matters: the fit is *measured from chains that were already located and confirmed*, and is then used only to decide which bank an already-located chain belongs to. A wrong fit binds nothing rather than binding wrongly. Two guards keep that true — the fit needs two agreeing chains, since one pair is satisfied by every candidate unit, and a fit that puts any bank at a negative address is rejected, since the fit shifted by one whole unit would hand each bank the samples of the bank before it.

**Locate E-IV records by signature, as the EIII walk does.** Scanning for header-length 92 is how EIII banks are read and it looked like it would transfer. Rejected on measurement: that field reads 0 on 547 of `eiv-studio`'s records, so the scan silently drops a fifth of the disc, and it finds records with no way to say which bank they belong to. The directory answers both questions at once.

**Add an `EMU4` backend.** Rejected under [ADR-0014](0014-one-backend-per-on-disc-format.md). It is one on-disc format — same magic, same header, same folder and bank directories — and only the bank interior differs. Two backends would duplicate the whole directory layer to express one branch.

**Treat the paired length fields as a channel count.** `+34 == 2 × (+30) − 90` on both EIII and E-IV looks exactly like a mono/stereo flag, and building a stereo path on it was planned. Rejected on measurement: de-interleaving a payload as stereo roughly doubles its sample-to-sample delta, which is what decimating a smooth mono signal does, and the known-good `esi32-gm` `Piano E0` scores the same as every E-IV record. Everything is mono. E-IV pairs samples into stereo the way the rest of the collection does, by name ([ADR-0017](0017-the-stereo-side-marker-is-a-character-class.md)).

> **This rejection is overturned by [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md); the rest of this record stands.** The measurement above is sound about *interleaved* stereo and tested the wrong hypothesis: the format splits into blocks — all of the left channel, then all of the right — which de-interleaving cannot detect. The two halves of a record whose pointers declare two channels are the same performance, correlating at 0.99, 0.96 and 0.95 by RMS envelope on three discs against 0.13–0.26 for one-channel records. The paired fields *are* a channel count. Nothing else here depends on it: bank binding, the chain and the directory's length are untouched.

## Consequences

**Good.** Three discs that could only be listed now extract: 449, 2 822 and 828 samples. The four EIII/ESI counts are unchanged, which is the check that the shared record parser was not disturbed.

**Good.** `eiv-studio` also gains its folder table. Its first two folder entries carry flags `0x0013` and `0x0018` rather than `0xFFFF`, which aborted the folder walk on entry 0 and fell back to a single directory — 77 banks of the 230 the disc has. That was a live bug on every release since D12, visible only on a disc that listed and did not extract.

**Bad.** Opening an E-IV disc costs a second pass over the image, on top of the `EMULATOR` scan. It runs only when a bank actually needs it, so an all-EIII disc does not pay for it.

**Bad.** The allocation unit is fitted rather than read, and a disc with only one sample-bearing bank will not bind at all. Accepted: the failure is a bank that lists without extracting, which is visible and explained, rather than a bank whose contents are wrong, which is not.

**Watch for.** The fit is the one piece of inference in the path. Every guard on it exists because a plausible alternative was found to be wrong on real data, and loosening any of them re-opens a silent failure. If a fourth disc does not bind, suspect the fit before suspecting the chain.
