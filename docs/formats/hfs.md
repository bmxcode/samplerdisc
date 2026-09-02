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
| `filExtRec` | 74 | 12 | the data fork's first three extents |

A fork longer than three extents is continued in the **extents-overflow B\*-tree** (same node layout), keyed by `(forkType, CNID, startAllocationBlock)`. On these once-written cartridges files are contiguous and this is empty, but it is read so a fragmented fork is never silently truncated.

## What is read, and what is not

The catalog file count is the whole of it — `sonic-images-v1` declares **926** files, `sonic-images-v2` **404**, which the reader reproduces exactly. By Finder type:

| Type | `v1` | `v2` | Handled as |
|---|---:|---:|---|
| `AIFF` | 832 | 288 | `aiff` — converted to WAV through the existing path ([aiff.md](aiff.md), [ADR-0024](../adr/0024-the-aiff-twin-is-converted-and-deduplicated.md)) |
| `SCin` / `SCsi` / `MixD` | 89 | 86 | `program` — SampleCell instrument, setup and mix documents; kept with `--keep-originals`, left to ConvertWithMoss ([ADR-0011](../adr/0011-the-deliverable-is-daw-ready-wav.md)) |
| `Sd2f` | 0 | 24 | `sd2` — Sound Designer II, listed only (see below) |
| Finder/system | 5 | 6 | `file` — Desktop DB/DF, TeachText, a read-me |

**Sound Designer II is listed, not read.** SDII keeps its audio in the HFS *resource* fork, with the sample rate and width in a resource beside it — a different and harder format than the flat-PCM data-fork AIFF this backend reads. The 24 `Sd2f` files on `sonic-images-v2` are named in a `list` and skipped by extraction rather than written as noise ([ADR-0039](../adr/0039-samplecell-is-read-as-hfs-behind-an-apple-partition-map.md)). Resource forks in general are not read, the same call ISO 9660 makes for the associated-file records that are an Apple resource fork wearing the data file's name.

## The oracle

`machfs` (pure Python, `uv run --with machfs`) reads the same HFS volume with no shared lineage, so agreement on all ~900 data forks per disc is a real cross-check of the B-tree walk and extent resolution — the [emu-ebl.md](emu-ebl.md)/[kurzweil-krz.md](kurzweil-krz.md) oracle pattern. It stands in for the host's own `hdiutil`, which on current macOS reports *no mountable file systems* for these images: Apple dropped read support for legacy HFS (HFS+ only), so `hdiutil` parses the partition map and then cannot mount the volume. `test_hfs_forks_match_an_independent_reader` gates on `machfs` being installed and skips otherwise.
