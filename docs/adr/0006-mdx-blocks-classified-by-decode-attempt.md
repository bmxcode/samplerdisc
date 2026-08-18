# ADR-0006 · MDX blocks are classified by decode attempt, guarded by consumed length

**Status:** accepted · 2026-08-18

## Context

A compressed `.mdx` payload is a chain of blocks, each expanding to exactly 32768 bytes. Most are raw DEFLATE streams. A few — 4 of 16 526 in `s3000-lib1` — are **stored**: 32768 literal bytes, written when compression produced no saving, which in practice means raw PCM.

Nothing in the file says which is which. There is no index, no length prefix, no per-block header. The 640-byte trailing descriptor is far too small to hold ~16 500 entries and does not decode at any alignment tried.

The chain was established empirically: blocks sit exactly back to back, and a strict walker — one with no stored-block fallback, which therefore either errored or terminated on the byte — walked `s3000-lib1` from `0x40` and stopped precisely on the descriptor offset, 264 087 807.

## Decision

Classify by attempting the decode. Accept a block as compressed only when the decompressor reaches EOF, emits exactly 32768 bytes, **and consumed fewer than 32768 bytes**. Otherwise take 32768 literal bytes and continue.

## Alternatives rejected

**Keep looking for the block index.** A real format usually has one, and decoding-to-discover feels like guessing. Rejected after the descriptor was shown not to decode and the arithmetic ruled out it holding an index. Continuing to search costs time against a format whose author had no reason to store what the decoder can derive — DEFLATE streams are self-terminating, so a sequential decoder needs no index.

**Attempt inflate and fall back on exception alone**, without the consumed-length guard. This is the obvious implementation and it works on all three reference discs. Rejected because the guard is the only thing separating *correct* from *lucky*. A stored block exists precisely because compressing it saved nothing, so any genuine compressed block consumes less than its 32768-byte output. Without the check, a run of PCM that happens to parse as valid DEFLATE emitting exactly 32768 bytes is silently misread — and the corruption surfaces as noise in an extracted WAV, with nothing upstream reporting a problem.

## Consequences

**Good.** No dependency on an index that may not exist. Decoding is a single forward pass, and the index it builds is small enough to keep while the decoded image is not.

**Note what this costs.** Adding the stored fallback destroyed the verification that established the format in the first place. Exact termination became a loop invariant — a stored block absorbs whatever remains, so the walk always lands on the descriptor offset no matter what went wrong earlier. The fallback that makes the decoder work is the same change that makes it unable to tell you it is working.

**Bad.** Decoding is attempt-then-maybe-discard, so a stored block costs a failed inflate. Irrelevant at 4 blocks in 16 526.

**Bad.** There is no cheap runtime integrity check. The closest available signal is the ratio of stored to compressed blocks: a wrong payload offset makes nearly every block fail to inflate, inverting the 4-in-16 526 seen on a good disc. `samplerdisc info` prints both counts for that reason.

**Watch for.** Anyone simplifying the three-part acceptance test. Each part is load-bearing, and dropping the consumed-length check is undetectable until a disc silently extracts noise. Equally, anyone re-adding an assertion that the chain ends on the descriptor offset and believing it verifies something.
