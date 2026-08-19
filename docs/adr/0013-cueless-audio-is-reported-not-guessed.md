# ADR-0013 · A cue-less audio disc is reported, and extracted only on request

**Status:** accepted · 2026-08-19

## Context

`Ew-040 PRO Samples 6 _ Bob Clearmountain Drums II` arrives as both `.mdx` and `.cdr`, with no cue sheet. The container reads it perfectly — the MDX decoder's output is byte-identical to the `.cdr` at every offset sampled — and then there is no filesystem, because the disc is a Red Book audio CD. It holds 659 runs of roughly two seconds of digital silence separating drum hits, and 59.8 minutes of 16-bit stereo PCM.

So the tool decoded 603 MB of audio flawlessly and had nothing to say about it beyond `no recognised filesystem`, which is the same message it gives for a container it got wrong.

Two things were available and neither was obviously right. [ADR-0009](0009-export-iso-escape-hatch.md) argues that refusing to hand over work that succeeded "throws away the part that worked, and that part is the part no other tool has" — which points at writing the audio out. But writing it out means *asserting* the disc is audio from a statistical judgement, and [formats/audio-cd.md](../formats/audio-cd.md) had already recorded that a cue is required because nothing in the bytes marks a track.

The measurement changed the shape of the problem. Content can be recognised even though track boundaries cannot: read as 16-bit LE stereo, audio CDs score 5.1–14.0 on a lag-1/lag-2 ratio and every sampler disc in the collection scores 0.52–1.01. A plain smoothness test does *not* do this — Roland sample data is smoother than real programme material — but the interleave test does, with a margin of 5× on medians.

## Decision

Recognising the content and extracting it are separated.

`samplerdisc info` reports what it sees. When no backend claims a disc and the stream gates as 16-bit 44.1 kHz stereo, it says so and names the flag. This costs the user nothing and never writes a file.

`samplerdisc extract --assume-audio-cd` writes the whole stream as a single WAV. It is opt-in, and the gate runs again as a check rather than as the decision — the flag is the user's assertion, and the tool confirms rather than obeys. A stream that does not look like stereo PCM is refused with a message.

Track splitting is not attempted. A cue remains required for tracks.

## Alternatives rejected

**Report only; never write the audio.** Safest, and it leaves `docs/formats/audio-cd.md` untouched. Rejected because it fails the ADR-0009 test: the container did its job, the bytes are in hand, and handing back nothing helps nobody. `export-iso` would give the user 603 MB of raw sectors they then have to know how to turn into a WAV — for a disc where the sectors *are* the WAV.

**Write the whole-disc WAV automatically whenever the gate fires.** More convenient, and the gate is accurate on every disc measured. Rejected on the asymmetry of being wrong. A false negative costs the user a flag; a false positive silently writes hundreds of megabytes of noise, with the tool reporting success — the exact failure class this project keeps meeting. Nine discs is not enough evidence to put a statistic in the write path unsupervised.

**Split on the silence gaps and emit one WAV per hit.** Most useful of all for a drum-hit CD — 659 gaps are clearly visible. Rejected: it reverses a documented finding on a heuristic with no ground truth, and a mis-cut is undetectable by the user. Where a cue exists, the existing track path already does this properly.

## Consequences

**Good.** The Clearmountain disc now explains itself: `info` reports the container decoded fully, no filesystem, content consistent with Red Book audio, and how to get it out. That is a complete answer where there was an ambiguous one.

**Good.** The gate doubles as the diagnostic for the all-stored MDX case. An image that is 100% stored is either incompressible content or a block size we could not measure, and asking whether the content looks like audio distinguishes them from inside the tool for the first time — see [formats/mdx.md](../formats/mdx.md).

**Bad.** A whole-disc WAV is one enormous file with no track structure. It is honest about that in the message it prints, but it is not a good deliverable — it is the raw material for one.

**Bad.** There is now a statistical judgement in the codebase where before there were only structural checks. It is confined to a disc no backend claimed, it is never consulted otherwise, and its measured margins are in [formats/audio-cd.md](../formats/audio-cd.md) — but it is a different kind of thing from a magic number, and it should not spread.

**Watch for.** The gate being reused as a filesystem probe, or being consulted before the backends have had their say. It answers "does this look like stereo PCM", which a sampler disc full of samples can approach; the interleave test is what holds it apart, and that margin is 5×, not 500×. Every new backend narrows the set of discs this ever runs on, which is the right direction.
