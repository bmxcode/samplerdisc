# Nero NRG

`.nrg` stores the image data first and a chunk footer last. **The footer must be parsed.** Treating an NRG as "an ISO with some junk on the end" is the obvious shortcut and it fails on real discs — see *The pregap* below.

Everything in NRG is **big-endian**, including on the little-endian machines that wrote it.

Verified against `loopsoup` (542 419 100 bytes).

## Finding the footer

Two versions, distinguished by a magic at a fixed distance from the end of the file:

| Version | Magic at | Then |
|---|---|---|
| v2 | `EOF-12` | `NER5`, followed by u64 BE offset of the first chunk |
| v1 | `EOF-8` | `NERO`, followed by u32 BE offset of the first chunk |

Check v2 first: a v1 magic cannot appear at `EOF-12`, but reading 8 bytes where 4 were written silently produces a plausible-looking huge offset.

## Chunks

From the first-chunk offset to the end of the file, a sequence of `ID` (4 bytes) + u32 BE length + body:

| ID | Meaning |
|---|---|
| `CUEX` / `CUES` | Track list as cue entries. `CUEX` is the 32-bit-LBA form |
| `DAOX` / `DAOI` | Disc-at-once track descriptors — **this is the one that matters** |
| `SINF` | Session info: track count |
| `MTYP` | Medium type |
| `END!` | Terminator, zero length |

`loopsoup` has its footer at `542418944`, 156 bytes long, holding `CUEX`, `DAOX`, `SINF`, `MTYP`, `END!`.

### CUEX

8 bytes per entry: adr/control, track number, index, pad, then s32 BE LBA. Control `0x41` is a data track, `0x01` audio. Track `0xAA` is the lead-out.

`loopsoup`: one data track, lead-out LBA `0x409FF` = 264 703.

### DAOX

The body is a header followed by one block per track.

Header: u32 size, `upc[14]`, pad, toc type, first track, last track. Then a **42-byte** block per track.

Verified field positions **within the `DAOX` body**, for `loopsoup`'s single track:

| Offset | Size | Value | Meaning |
|---|---|---|---|
| 34 | 2 | `2048` | sector size |
| 48 | 8 | `307200` | track start, byte offset into the file |
| 56 | 8 | `542418944` | track end, byte offset |

Sector size is either 2048 (cooked, as here) or 2352 (raw) and decides whether sectors need de-interleaving — see [rawcd.md](rawcd.md).

## The pregap

**`loopsoup` includes the 150-sector pregap at the start of the file.** Bytes `0 … 307199` are zeros. The filesystem begins at **307200**, where the AKAI partition header `00 1e 00 00 05 0d 0a 1a` sits.

The arithmetic closes exactly, which is how you know this is the real explanation and not a coincidence:

```
264703 (lead-out LBA) + 150 (pregap) = 264853 sectors
264853 × 2048                        = 542418944 = the DAOX track end
```

A parser that assumes the data starts at byte 0 reads 307 200 zeros, finds no filesystem, and reports an **empty disc rather than an error**. That silence is why [ADR-0005](../adr/0005-probe-for-the-filesystem-origin.md) makes origin detection explicit and why it has its own test.

Take the track start from `DAOX`. Fall back to `CUEX` LBAs plus 150 only when `DAOX` is absent.

## Verified constants

| Quantity | Value |
|---|---|
| Footer offset | `542418944` |
| Footer length | 156 |
| Sector size | 2048 |
| Track start | `307200` |
| Track end | `542418944` |
| Lead-out LBA | 264 703 |
| Total sectors | 264 853 |
| Filesystem origin | `307200` |
