# DAEMON Tools MDX

`.mdx` is DAEMON Tools' single-file disc image: the descriptor that would be a `.mds` and the data that would be a `.mdf`, merged. The variant that matters here is the **compressed** one, which no other open-source tool reads — libmirage's MDS parser handles plain `.mdx` and stops at this.

Verified against `s3000-lib1` (264 088 447 bytes).

## Header

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 16 | `"MEDIA DESCRIPTOR"` |
| `0x10` | 2 | version — `02 00` here |
| `0x12` | 26 | `"(C) 2000-2011 DT Soft Ltd."` |
| `0x30` | 8 | u64 LE, offset of the trailing MDS descriptor — `264087807` |
| `0x38` | 8 | u64 LE, `192` |

**The payload starts at `0x40`, not at the `192` in the field at `0x38`.** That field looks exactly like a data offset and is not one. Starting at `192` lands mid-stream and the first inflate fails with `invalid stored block lengths`, which reads like a corrupt file rather than a wrong offset.

The payload runs from `0x40` up to the descriptor offset from `0x30`. The descriptor itself — 640 bytes here — is high-entropy and did not yield to inflate at any alignment. **It is not needed.** Everything required to decode the image comes from the block chain.

## Block chain

The payload is a chain of blocks, each expanding to the same fixed size. They sit back to back with no index, no length prefix and no per-block header — the chain is walked by decoding, not by lookup.

**The block size is not universal and must be read off the image.** Most discs use 32768, but `AMG - Vince Clarke Lucky Bastard AKAI.mdx` uses **32160** for all 17 624 of its blocks. Nothing in the header announces it. Hard-coding 32768 makes every block fail the size check, fall through to the stored path, and the image then decodes to garbage that presents as *an unrecognisable filesystem* rather than as an error — the same silent class of failure as the NRG pregap.

So: decode the first block with no size expectation, and take its length as the size for the rest. A leading stored block leaves nothing to measure, in which case 32768 is the fallback and the stored/compressed ratio is what shows the problem.

## Sector stride: subchannel data

32160 is not a whole number of 2048-byte sectors, and that is the clue. **It is 15 × 2144** — 2048 bytes of user data followed by **96 bytes of subchannel**.

So an MDX payload holds one of two strides, and nothing in the header says which:

| Block size | Stride | Layout |
|---|---|---|
| 32768 | 2048 | 16 plain sectors |
| 32160 | 2144 | 15 sectors, each 2048 + 96 subchannel |

Divisibility settles it, because the block size is always a whole number of whichever stride is in use. Try 2048 first; 32160 is not divisible by it, and 32768 is not divisible by 2144.

Getting the block size right but the stride wrong is its own silent failure: every sector lands 96 bytes further out than the last, so the filesystem walks off its 8192-byte block boundaries and the disc reads as empty. The confirmation that 2144 is correct is that AKAI sample headers then land exactly on multiples of 8192 — they do not otherwise.

The 96 bytes are a constant `00 40 00 00 ...` pattern on a data track, which is what subchannel P/Q looks like when there is nothing to encode. They are discarded.

A block is one of two things:

- a self-terminating **raw DEFLATE** stream — `zlib.decompressobj(-15)`, no zlib or gzip wrapper;
- **stored**: exactly 32768 literal bytes, used when compression did not pay. In practice these are blocks of raw PCM.

Nothing in the file marks which is which, so the decoder classifies by attempting the decode. Accept a block as compressed only when all three hold:

1. the decompressor reached EOF,
2. it emitted exactly 32768 bytes,
3. it consumed **fewer than 32768** bytes.

The third condition is what makes this safe rather than lucky. A stored block only exists because compressing it produced no saving, so any genuine compressed block consumes less than its output. Without that guard, a run of PCM that happens to parse as valid DEFLATE would be silently misread. See [ADR-0006](../adr/0006-mdx-blocks-classified-by-decode-attempt.md).

## Verified constants

Walking `s3000-lib1` from `0x40`:

| Quantity | Value |
|---|---|
| Block size | 32 768 |
| Blocks | 16 526 |
| Compressed | 16 522 |
| Stored | 4 |
| Walk terminates at | `264087807` — exactly the descriptor offset |
| First stored block at | `0x9E9060E` |
| Decoded output | 541 508 537 bytes |
| First 8 bytes of output | `00 14 00 00 05 0d 0a 1a` |

The walk landing *exactly* on the descriptor offset was the decisive evidence while working the format out — a strict walker with no stored-block fallback either errored or terminated on the byte, so hitting `264087807` proved the chain had been followed correctly.

**It is not a runtime check.** Once a decoder has the stored-block fallback, exact termination is a loop invariant: a stored block consumes `min(32768, remaining)`, so the last one always absorbs precisely what is left, whatever went wrong earlier. A decoder that asserts on it is asserting on arithmetic it just performed.

What does show a misparse is the **ratio of stored to compressed blocks**. A wrong payload offset makes nearly every block fail to inflate, so the counts inverted from the 4-in-16 526 below are the signal to watch. `samplerdisc info` prints both.

For comparison, `AMG - Vince Clarke Lucky Bastard AKAI.mdx`: block size 32 160, 17 624 blocks, 17 622 compressed, 2 stored.

Output is **2048-byte cooked sectors** — no sync pattern, no header, no ECC. Scanning the decoded stream for the CD sync pattern `00 FF×10 00` finds nothing.

## The tail

The final chunk is 17 337 bytes and does not inflate, so it is taken as stored. That makes the total 541 508 537, which is not a multiple of 2048 — remainder 953.

This is a known, accepted loose end. Those trailing bytes fall outside any block the filesystem's allocation table marks in use, so no sample data is lost. **Trim the output to a whole sector count; do not fail on it.** A stricter decoder that refuses non-sector-aligned totals would reject a disc that extracts perfectly.

## Traps

- The payload offset is `0x40`, not the `192` at `0x38`.
- Raw DEFLATE (`-15`), not zlib-wrapped — `zlib.decompress` on its own will not do it.
- The block size varies between images. Measure it; do not assume 32768.
- No block index exists. Do not go looking for one; the 640-byte descriptor is too small to hold ~16 500 entries and does not decode.
- The consumed-length guard is load-bearing. Dropping it is undetectable until a disc silently extracts noise.
