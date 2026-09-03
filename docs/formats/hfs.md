# HFS behind an Apple Partition Map — Digidesign SampleCell

The SampleCell card was a Macintosh NuBus/PCI sampler, so its libraries shipped not as a sampler-native disc but as ordinary Mac removable media: a magneto-optical cartridge carrying an Apple Partition Map, an `Apple_HFS` partition, and inside it a standard Macintosh HFS (not HFS+) volume. The audio is plain **AIFF**. Nothing here is proprietary to a sampler — this is a general-purpose filesystem, read for the same reason ISO 9660 is ([iso9660.md](iso9660.md), [ADR-0009](../adr/0009-export-iso-escape-hatch.md)): the disc still arrives wrapped in a container nothing else opens.

Verified against `sonic-images-v1` and `sonic-images-v2` (the two OMI *Universe of Sounds* SampleCell discs). Every constant below is asserted in `tests/test_discs.py`, and every data fork the reader returns is byte-for-byte identical to what `machfs` — an independent pure-Python HFS reader — returns for the same volume.

## The three layers, and where each begins

A whole-disk image, numbered in **512-byte Apple blocks** throughout (not the container's 2048-byte cooked sector).

```
block 0            Apple Driver Descriptor Record (DDR)
block 1 …          Apple Partition Map (APM), one 512-byte entry per block
<part start> …     the Apple_HFS partition: boot blocks, MDB, then the volume
```

### Block 0 — Driver Descriptor Record

| Field | Offset | Bytes | `sonic-images-v1` |
|---|---|---|---|
| `sbSig` | 0 | 2 | `0x4552` (`'ER'`) |
| `sbBlkSize` | 2 | 2 (BE) | 512 |
| `sbBlkCount` | 4 | 4 (BE) | 576 983 |

`'ER'` alone is two bytes and would match a run of audio. The probe is `'ER'` **and** `sbBlkSize == 512` **and** a `'PM'` partition map directly behind it with a sane entry count — a combination nothing but an Apple disk carries ([ADR-0005](../adr/0005-probe-for-the-filesystem-origin.md)).

### Block 1 on — Apple Partition Map

Each entry is one 512-byte block, big-endian:

| Field | Offset | Bytes | Meaning |
|---|---|---|---|
| `pmSig` | 0 | 2 | `0x504D` (`'PM'`) |
| `pmMapBlkCnt` | 4 | 4 | number of map entries (read from the first entry) |
| `pmPyPartStart` | 8 | 4 | partition start, in 512-byte blocks |
| `pmPartBlkCnt` | 12 | 4 | partition length, in 512-byte blocks |
| `pmPartName` | 16 | 32 | e.g. `M/O a`, `Macintosh` |
| `pmParType` | 48 | 32 | e.g. `Apple_HFS`, `Apple_Driver` |

The map is **read, never assumed** — the two discs differ, and that is the whole point of parsing it rather than hard-coding an offset:

```
sonic-images-v1   Apple          Apple_partition_map   start 1        63 blocks
                  Silverlining   Apple_Driver          start 64       32 blocks
                  M/O a          Apple_HFS             start 96       576 400 blocks
                  Extra          Apple_Free            start 576 496  487 blocks

sonic-images-v2   Macintosh      Apple_HFS             start 32       576 966 blocks
```

Only `Apple_HFS` partitions carry a filesystem; the map's own entry, the disk driver (`Silverlining`) and free space do not.

## The HFS volume

### Master Directory Block

Two 512-byte blocks into the partition (`part_start·512 + 1024`), big-endian:

| Field | Offset | Bytes | `v1` | `v2` |
|---|---|---|---|---|
| `drSigWord` | 0 | 2 | `0x4244` (`'BD'`) | `0x4244` |
| `drNmAlBlks` | 18 | 2 | 57 637 | — |
| `drAlBlkSiz` | 20 | 4 | 5 120 | 4 608 |
| `drAlBlSt` | 28 | 2 | 19 | — |
| `drVN` | 36 | 1+27 | `Sonic Images V1` | `Sonic Images V2` |
| `drXTFlSize` | 130 | 4 | extents-overflow file size |  |
| `drXTExtRec` | 134 | 12 | its first three extents |  |
| `drCTFlSize` | 146 | 4 | catalog file size |  |
| `drCTExtRec` | 150 | 12 | its first three extents |  |

An extent record is three `(startBlock, blockCount)` pairs, both 16-bit, in **allocation blocks**. An allocation block *N* sits at `(part_start + drAlBlSt)·512 + N·drAlBlkSiz` from the disc origin. `drSigWord` is `'BD'` for HFS; an HFS+ volume would read `H+` and is out of scope (none in hand).

### Catalog B\*-tree

The catalog file (read through `drCTExtRec`) is a B\*-tree of fixed-size nodes. Node 0 is the header node; leaves are chained forward. The reader walks the **leaf chain**, not the index, since it wants every record, not one:

- **Header node** — node type `0x01`. Two fields are used: `bthNodeSize` (offset 14+18) and `bthFNode`, the first leaf (offset 14+10).
- **Node descriptor** (14 bytes) — `ndFLink` (4, next node), `ndBLink` (4), `ndType` (1; `0xFF` = leaf), `ndNHeight` (1), `ndNRecs` (2).
- **Records** are found through the tail offset table: a 2-byte offset per record, stored in reverse from the node's end (`node[nodeSize − 2·(r+1)]`). Record *r* spans `offset[r] … offset[r+1]`.

A catalog record is a key then a datum. Key: `keyLen` (1), reserved (1), `parentID` (4), then a Pascal name string (`macRoman`), the whole padded so the datum starts on an even boundary.

**Folder record** (datum type `0x01`): `dirDirID` at datum offset 6. Kept as `dirID → (parentID, name)`, which is all the path reconstruction needs — a file's path is its name walked up the parent chain to the root (CNID 2).

**File record** (datum type `0x02`):

| Field | Datum offset | Bytes | Use |
|---|---|---|---|
| Finder type (`fdType`) | 4 | 4 | classify: `AIFF`, `SCin`/`SCsi`/`MixD`, `Sd2f` |
| `filFlNum` (CNID) | 20 | 4 | key into the extents-overflow tree |
| `filLgLen` | 26 | 4 | data-fork logical length (bytes to keep) |
| `filRLgLen` | 36 | 4 | **resource**-fork logical length (Sound Designer II parameters) |
| `filExtRec` | 74 | 12 | the data fork's first three extents |
| `filRExtRec` | 86 | 12 | the **resource** fork's first three extents |

The resource-fork length is `filRLgLen` at **36**, the logical length — not `filRPyLen` at 40, which is the physical length rounded up to a whole allocation block and would append padding. The data fork makes the same distinction (`filLgLen` at 26, not `filPyLen` at 30). A fork's fork type in the extents-overflow key is `0x00` for the data fork and `0xFF` for the resource fork.

A fork longer than three extents is continued in the **extents-overflow B\*-tree** (same node layout), keyed by `(forkType, CNID, startAllocationBlock)`. On these once-written cartridges files are contiguous and this is empty, but it is read so a fragmented fork is never silently truncated.

## What is read, and what is not

The catalog file count is the whole of it — `sonic-images-v1` declares **926** files, `sonic-images-v2` **404**, which the reader reproduces exactly. By Finder type:

| Type | `v1` | `v2` | Handled as |
|---|---:|---:|---|
| `AIFF` | 832 | 288 | `aiff` — converted to WAV through the existing path ([aiff.md](aiff.md), [ADR-0024](../adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)) |
| `SCin` / `SCsi` / `MixD` | 89 | 86 | `program` — SampleCell instrument, setup and mix documents; kept with `--keep-originals`, left to ConvertWithMoss ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)) |
| `Sd2f` | 0 | 24 | `sd2` — Sound Designer II, converted to WAV (see below) |
| Finder/system | 5 | 6 | `file` — Desktop DB/DF, TeachText, a read-me |

### Sound Designer II

**The audio is the data fork; the resource fork holds only the parameters.** The project long assumed the reverse — that SDII kept its audio in the resource fork — which turns out to be wrong, and which is why these files went unread through D32 ([ADR-0040](../adr/0040-sound-designer-ii-is-decoded-from-the-data-fork.md)). On `sonic-images-v2` each of the 24 `Sd2f` files has a **large data fork** (847 KB – 1.29 MB) of plain **big-endian, interleaved PCM** — which the backend already read — and a **tiny 1184-byte resource fork** carrying three `STR ` (trailing space) resources, each an ASCII decimal **Pascal string**:

| Resource | Id | Value on this disc | Meaning |
|---|---|---|---|
| `STR ` | 1000 | `"2"` | sample size, in **bytes** (2 → 16-bit) |
| `STR ` | 1001 | `"44100.000000"` | sample rate, in Hz (a float string) |
| `STR ` | 1002 | `"2"` | channel count (2 → stereo) |

All 24 are uniformly 16-bit, 44 100 Hz, stereo. The audio is carried to WAV by reversing the bytes within each sample (big-endian to little-endian), the same and only change AIFF gets — byte order, never sample values ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md), [ADR-0024](../adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)). SD2 stereo is already interleaved in the data fork, so no channel de-planing is needed.

**The resource fork container** is a standard Macintosh resource map: a 16-byte header (`dataOffset`, `mapOffset`, `dataLength`, `mapLength`, all big-endian), a data section where each resource is `[4-byte length][body]`, and a map whose type list (`typeListOffset` at `mapOffset + 24`) points to per-type reference lists (12-byte entries: id, name offset, a 3-byte data offset into the data section). The decoder enumerates the `STR ` type and reads ids 1000/1001/1002.

**Loop points and a root key are not read.** The fork also carries Digidesign region/loop resources (`sdLL`, `sdDD`), but there is no open decoder or a render to verify one against, so the loop is left out rather than guessed ([ADR-0025](../adr/0025-the-loop-is-decoded-the-root-key-is-not.md)) — `sdLL` on the first file even looks like a loop (two in-range frame values), which is exactly why it is left for a specimen that can confirm it.

## The oracle

`machfs` (pure Python, `uv run --with machfs`) reads the same HFS volume with no shared lineage, so agreement on all ~900 forks per disc is a real cross-check of the B-tree walk and extent resolution — the [emu-ebl.md](emu-ebl.md)/[kurzweil-krz.md](kurzweil-krz.md) oracle pattern. `test_hfs_forks_match_an_independent_reader` checks **both** forks: every data fork (the AIFF audio) and every resource fork (the SDII parameters) matches `machfs` byte for byte, including the 24 resource forks on `sonic-images-v2`. The SDII decode has a second, self-contained oracle in `test_hfs_sd2_files_decode_and_match_the_disc`: because the audio is a verbatim byte-swap of the data fork, our little-endian PCM swapped back to big-endian equals `machfs`'s `obj.data` exactly — the "payload is the disc's own bytes" check AKAI uses, needing no Mac fork magic. Both stand in for the host's own `hdiutil`, which on current macOS reports *no mountable file systems* for these images: Apple dropped read support for legacy HFS (HFS+ only), so `hdiutil` parses the partition map and then cannot mount the volume. The tests gate on `machfs` being installed and skip otherwise.
