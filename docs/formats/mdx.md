# DAEMON Tools MDX

`.mdx` is DAEMON Tools' single-file disc image: the descriptor that would be a `.mds` and the data that would be a `.mdf`, merged. The variant that matters here is the **compressed** one, which no other open-source tool reads — libmirage's MDS parser handles plain `.mdx` and stops at this.

Verified against `s3000-lib1` (264 088 447 bytes).

## The magic does not identify the format

**`"MEDIA DESCRIPTOR"` is shared with the split `.mds`.** The merged image and the standalone descriptor of a `.mds`/`.mdf` pair open with the same 16 bytes, so the magic answers "DAEMON Tools wrote this" and nothing more. **The major version at `0x10` is the discriminator:**

| | Bytes at `0x00` | `0x10` | `0x11` |
|---|---|---|---|
| Merged `.mdx` | `MEDIA DESCRIPTOR` | `02` | `00` or `01` |
| Split `.mds` | `MEDIA DESCRIPTOR` | `01` | `04` |

Three merged images (`s3000-lib1`, `vince-clarke`, `clearmountain`) read `02`; the one split pair in hand, `Back In Time Records Korg Universe vol.1 1CD AKAI`, reads `01 04`.

This was got wrong, and the failure is worth recording because it looks nothing like its cause. Detection tested the magic first and fell through to the `.mds` extension only afterwards, so **the extension branch was unreachable for any genuine `.mds`** and every one went to the MDX parser. That parser then read the u64 at `0x30` — which in a split descriptor is not a descriptor offset and not anything — got `0`, and reported:

```
samplerdisc: ...: implausible descriptor offset 0
```

A file the tool supports, refused by the parser for a different format, with a message that describes neither. Detection is by signature (ADR-0004), so the fix is the version byte rather than the extension: the split form is tested first, the extension survives only as a tiebreak for a descriptor written by something that does not use this magic.

Read at least 17 bytes before deciding. A 16-byte read is exactly the magic and one byte short of the answer.

## Header

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 16 | `"MEDIA DESCRIPTOR"` — **shared with `.mds`, see above** |
| `0x10` | 2 | version; `0x10` is the major and is what separates merged from split |
| `0x12` | 26 | copyright notice |
| `0x30` | 8 | u64 LE, offset of the trailing MDS descriptor |
| `0x38` | 8 | u64 LE, **not** the payload offset |

Two generations are in the wild, and they differ only in this header:

| | `s3000-lib1` | `clearmountain` |
|---|---|---|
| Version at `0x10` | `02 00` | `02 01` |
| Notice at `0x12` | `(C) 2000-2011 DT Soft Ltd.` | `© 2000-2015 Disc Soft Ltd.` |
| Descriptor offset at `0x30` | `264087807` | `632728048` |
| Field at `0x38` | `192` | **`2560`** |
| Descriptor length | 640 | 3008 |

**The payload starts at `0x40` on both, not at the value in the field at `0x38`.** That field looks exactly like a data offset and is not one. On the 2011 image, starting at `192` lands mid-stream and the first inflate fails with `invalid stored block lengths`, which reads like a corrupt file rather than a wrong offset.

The 2015 image is what settles it. One wrong value in a plausible-looking field could be a coincidence; the same field holding a *different* wrong value on another image cannot be. `0x40` was confirmed on it independently, by diffing the decoded stream against a `.cdr` of the same disc: the two are byte-identical with the payload taken from `0x40`, at a delta of exactly 64.

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

A wrong payload offset makes nearly every block fail to inflate, so the **ratio of stored to compressed blocks** moves — and for a payload that is expected to compress, an inversion of the 4-in-16 526 below is worth looking at. `samplerdisc info` prints both counts.

**But an all-stored image is not evidence of a misparse.** That was claimed here, and on ADR-0006, and it is wrong as stated. `Ew-040 PRO Samples 6 _ Bob Clearmountain Drums II.mdx` decodes as 0 compressed and 19 310 stored, and is completely correct: the disc is a Red Book audio CD, and PCM does not deflate. Every block was stored because storing was the right answer.

So the ratio only says something about a payload you expect to compress. All-stored has two causes and the counts cannot separate them:

- the content genuinely does not compress — audio, or a disc full of raw PCM;
- the block size is wrong, so every compressed block failed the size check and was taken literally.

**The discriminator is a second view of the same disc**, not a statistic inside the container. For the Clearmountain disc that was a `.cdr` of the same title: `MdxImage.read()` output matched it byte for byte at every offset sampled, which no misparse survives. A filesystem being found is the other second view, and a cheaper one. Failing both, `samplerdisc info` reports the state rather than a verdict — see *The all-stored case* below.

For comparison, `AMG - Vince Clarke Lucky Bastard AKAI.mdx`: block size 32 160, 17 624 blocks, 17 622 compressed, 2 stored.

Output is **2048-byte cooked sectors** — no sync pattern, no header, no ECC. Scanning the decoded stream for the CD sync pattern `00 FF×10 00` finds nothing.

## The all-stored case

The block size is read off the first block, which only works when the first block is compressed. When it is stored there is nothing to measure, `DEFAULT_BLOCK_SIZE` is assumed, and `block_size_measured` records that it was assumed.

For an image that is stored throughout, this does not matter, and the reason is worth stating because it is not obvious: stored blocks consume `min(block_size, remaining)` and emit exactly what they consume, so whatever the block size, the blocks partition the payload contiguously and the output is the payload verbatim. The Clearmountain image decodes correctly with an assumed 32 768 that is almost certainly not the size its writer used.

For a *mixed* image whose lead-in is stored and whose body is compressed at a size other than 32 768, it would matter — every compressed block would fail the size check and be taken literally. That case has no specimen. What can be said is that it cannot fail silently: a wrong block size makes every compressed block fail, so the image presents as all-stored with `block_size_measured` false, and `info` says so.

**Searching the payload for the first real DEFLATE stream is the obvious fix and is not one.** Scanning a 2 MB window of ordinary CD audio at byte alignment turns up **167 byte runs that inflate cleanly** and terminate. A forward scan would therefore pick a plausible, wrong block size on a disc that decodes perfectly today — trading a silent failure never observed for one we would introduce. Reporting the state costs nothing and is honest about what the container can and cannot know.

## The tail

The final chunk is 17 337 bytes and does not inflate, so it is taken as stored. That makes the total 541 508 537, which is not a multiple of 2048 — remainder 953.

This is a known, accepted loose end. Those trailing bytes fall outside any block the filesystem's allocation table marks in use, so no sample data is lost. **Trim the output to a whole sector count; do not fail on it.** A stricter decoder that refuses non-sector-aligned totals would reject a disc that extracts perfectly.

## The split form: `.mds` + `.mdf`

Same writer, two files: the descriptor in the `.mds` and the payload, uncompressed, in the `.mdf` beside it. One pair has been seen — `Back In Time Records Korg Universe vol.1 1CD AKAI   .mds` (486 bytes; the three spaces before the extension are part of the name) with a 612 195 024-byte `.mdf`.

**The descriptor is not parsed, and for a single-track data disc it does not need to be.** Geometry is sniffed off the `.mdf` exactly as a bare `.bin` is: a sync pattern at byte 0 means raw 2352-byte sectors, otherwise cooked 2048. On this pair the `.mdf` is raw, and 612 195 024 / 2352 = **260 287 sectors** exactly, which then carries an AKAI filesystem at offset 0 — five volumes, 159 files. Opening the `.mds` and opening the `.mdf` directly give the same stream, sector for sector.

What the descriptor holds, observed on this specimen and *not* relied on by any code:

| Offset | Value | Reading |
|---|---|---|
| `0x10` | `01 04` | version 1.4 |
| `0x58` | `6a ff ff ff` | −150, a session starting before the pregap |
| `0x5C` | `bf f8 03 00` | 260 287 — the `.mdf`'s sector count, independently |
| `0x1D0` | `e0 01 00 00` | offset of the filename below |
| `0x1E0` | `2a 2e 6d 64 66 00` | `"*.mdf"` — the data file, by pattern rather than by name |

`0x5C` agreeing with the arithmetic on the `.mdf` is the useful part: it is a second, independent statement of the same geometry, and it says the sniff is right on this disc rather than merely self-consistent. It is recorded here and not read, because one specimen is enough to check an answer against and not enough to commit a struct layout to.

The track table is the thing that is still unread, and it is what a multi-track or offset image would need — such an image is currently read from byte 0. There is a run of 0x50-byte blocks from `0x70` carrying what look like the `A0`/`A1`/`A2` lead-in entries and then a track, but the field meanings were not confirmed and are deliberately not written down here. If you have a disc that needs them, work them out against it and add them.

## Traps

- The payload offset is `0x40`, not the value at `0x38` — `192` on a 2011 image, `2560` on a 2015 one, and neither is it.
- Raw DEFLATE (`-15`), not zlib-wrapped — `zlib.decompress` on its own will not do it.
- The block size varies between images. Measure it; do not assume 32768.
- No block index exists. Do not go looking for one; the 640-byte descriptor is too small to hold ~16 500 entries and does not decode.
- The consumed-length guard is load-bearing. Dropping it is undetectable until a disc silently extracts noise.
- The magic is not the format. A split `.mds` opens with the same 16 bytes; check the byte at `0x10` before routing, and read past 16 bytes so it is there to check.
