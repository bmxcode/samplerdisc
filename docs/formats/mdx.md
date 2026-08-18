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

The payload is a chain of blocks. Each expands to exactly **32768 bytes**. They sit back to back with no index, no length prefix and no per-block header — the chain is walked by decoding, not by lookup.

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
| Blocks | 16 526 |
| Compressed | 16 522 |
| Stored | 4 |
| Walk terminates at | `264087807` — exactly the descriptor offset |
| First stored block at | `0x9E9060E` |
| Decoded output | 541 508 537 bytes |
| First 8 bytes of output | `00 14 00 00 05 0d 0a 1a` |

That the walk lands *exactly* on the descriptor offset is the strongest available check that the chain was followed correctly, and it is worth asserting on any new image.

Output is **2048-byte cooked sectors** — no sync pattern, no header, no ECC. Scanning the decoded stream for the CD sync pattern `00 FF×10 00` finds nothing.

## The tail

The final chunk is 17 337 bytes and does not inflate, so it is taken as stored. That makes the total 541 508 537, which is not a multiple of 2048 — remainder 953.

This is a known, accepted loose end. Those trailing bytes fall outside any block the filesystem's allocation table marks in use, so no sample data is lost. **Trim the output to a whole sector count; do not fail on it.** A stricter decoder that refuses non-sector-aligned totals would reject a disc that extracts perfectly.

## Traps

- The payload offset is `0x40`, not the `192` at `0x38`.
- Raw DEFLATE (`-15`), not zlib-wrapped — `zlib.decompress` on its own will not do it.
- No block index exists. Do not go looking for one; the 640-byte descriptor is too small to hold ~16 500 entries and does not decode.
- The consumed-length guard is load-bearing. Dropping it is undetectable until a disc silently extracts noise.
