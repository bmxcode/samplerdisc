# Kurzweil `KMSI` disc filesystem

The native disc format of the Kurzweil K2000/K2500 family is a plain **FAT16** filesystem. Its boot sector carries the OEM name `KMSI` (Kurzweil Music Systems Inc.) where a DOS-formatted disc would carry `MSDOS5.0` or a `mkfs` string, and that eight-byte label is the only thing that says a given FAT was written by a Kurzweil rather than by anything else. The files on it are `.KRZ` object banks; this doc is the FAT16 layer that finds them, and [kurzweil-krz.md](kurzweil-krz.md) is the separate layer for what is inside a bank.

Everything below is measured against the two `Best Service - Gigapack I & II (Kurzweil)` discs — CD 1 (684 702 480 bytes, 291 115 raw sectors) and CD 2 (684 744 816 bytes, 291 133) — read end to end. They are the collection's first Kurzweil specimens. Where a constant is called "on both discs" it means byte-identical across the two, which is weak evidence of the format against one disc's quirk and is said honestly as such until a third specimen exists.

## The 512-in-2048 packing

The BPB declares 512-byte logical sectors, but a CD sector holds 2048 bytes of user data. The FAT filesystem is a byte-contiguous image over the container's cooked stream: four 512-byte FAT sectors to one 2048-byte cooked sector, logical sector *L* at cooked byte *L* × 512. The `rawcd` container already did the 2352 → 2048 de-interleave (ADR-0003), so this layer never sees the raw sector; it addresses the cooked stream in 512-byte units from the filesystem origin. The declared image is 1 163 264 × 512 = 595 591 168 bytes, which fits inside the 291 115 × 2048 = 596 203 520 bytes of cooked user data with ~597 KB to spare — the arithmetic that confirms the packing is contiguous and not one-FAT-sector-per-CD-sector.

The filesystem origin is byte 0 of the cooked stream on both discs; there is no pregap. It is still probed for, never assumed (ADR-0005).

## Boot sector — the BPB

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 3 | jump, `e9 00 00` on both discs (a near jump; `eb xx 90` is the other legal FAT form) |
| `0x03` | 8 | **OEM name, `KMSI    `** — the detection signature |
| `0x0B` | u16 LE | bytes per logical sector, **512** |
| `0x0D` | u8 | sectors per cluster, **32** → a 16 KB cluster |
| `0x0E` | u16 LE | reserved sectors, **1** (the boot sector itself) |
| `0x10` | u8 | number of FATs, **2** |
| `0x11` | u16 LE | root-directory entries, **512** (a fixed root, as FAT12/16 has) |
| `0x13` | u16 LE | total sectors (16-bit), **0** → use the 32-bit field |
| `0x15` | u8 | media descriptor, **0xF8** (fixed disk) |
| `0x16` | u16 LE | sectors per FAT, **142** |
| `0x20` | u32 LE | total sectors, **1 163 264** |
| `0x26` | u8 | extended boot signature, **0x29** → the volume-id/label/type fields that follow are present |
| `0x2B` | 11 | volume label — **blank** on both discs (all zero) |
| `0x36` | 8 | filesystem-type hint — **blank** on both discs (not `FAT16   `); the type is computed, never read from here |

## FAT geometry, worked on the reference discs

Both discs hold the same geometry. Reserved 1, two FATs of 142 sectors, a 512-entry root of 32 sectors:

| Region | First logical sector | Cooked byte |
|---|---|---|
| FAT 1 | 1 | `0x200` |
| FAT 2 | 143 | `0x11E00` |
| Root directory | 285 | `0x23A00` |
| Data (cluster 2) | 317 | `0x27A00` |

Clusters are numbered from 2. The data region is 1 163 264 − 317 = 1 162 947 sectors, so `(1 162 947) ÷ 32 = 36 342` clusters. That count is between 4 085 and 65 525, so the volume is **FAT16** — fewer would be FAT12 and more FAT32, and each packs its allocation table differently. This backend reads FAT16 only and declines anything else rather than misread a FAT12 table with FAT16 arithmetic (ADR-0035).

## Directory entries — 32 bytes, 8.3

| Offset | Size | Meaning |
|---|---|---|
| `0x00` | 8 | name, space-padded (`0x00` here ends the directory; `0xE5` is a free slot; a leading `0x05` escapes a real `0xE5`) |
| `0x08` | 3 | extension, space-padded |
| `0x0B` | u8 | attributes — `0x08` volume label, `0x10` directory, `0x0F` a VFAT long-name fragment (skipped) |
| `0x1A` | u16 LE | first cluster (the high word at `0x14` is 0 on FAT16) |
| `0x1C` | u32 LE | file size in bytes |

CD 1 lists 106 entries, CD 2 lists 189, every one a `.KRZ` file at the root — no subdirectories and no volume-label entry on either disc. A subdirectory is a cluster chain like any file and is followed and walked in turn; neither reference disc exercises that, but the format allows it and a flat-root reader would silently drop it.

## The FAT chain is followed, never assumed contiguous

Files are fragmented. On CD 1, 12 of the 106 banks have a non-contiguous cluster chain — `CH BACK5.KRZ` starts at cluster 15 654 in the middle of an otherwise-ascending run — so a reader that assumed contiguity would splice a neighbour's audio onto those banks. `read_file` follows the FAT16 chain from the directory's first cluster, coalescing a contiguous run into one read, bounded three ways: by the end-of-chain marker (`≥ 0xFFF8`), by the table's own range, and by a visited set against a corrupt table that loops. A short read at the tail is a damaged disc, not an error — the caller gets what the disc still holds.

## The `.KRZ` file — an object bank

Every one of the 295 files across both discs begins with the four-byte tag `PRAM` — the 1012-byte `DRUM KIT.KRZ` on CD 2 included. A `.KRZ` is not a bare sample: it is a bundle of Kurzweil objects (programs, keymaps and samples), big-endian, with embedded object names (`HAL:CHRD 1` inside `CH GRG 2.KRZ`). Each bank is a **volume** whose files are its sample objects, and the whole bank is also listed as one `program` so `--keep-originals` writes it out with its own `.krz` suffix. The bank interior — how a sample's audio, rate, root key and loop are read out of the shared pool — is its own layer, documented in [kurzweil-krz.md](kurzweil-krz.md) (D29, [ADR-0036](../adr/0036-the-krz-bank-is-read-as-objects-and-verified-against-mpc2emu.md)).

## What a probe confirms

The OEM name is specific — no non-Kurzweil FAT carries `KMSI`, so a probe keyed on it will not claim a DOS CD, a run of zeros or a stretch of audio. But a magic plus a directory pointer is still only structure (ADR-0012), so the probe follows through: it reads the root directory, finds the first real file (a plausible 8.3 name, a first cluster in range, a non-zero size), and confirms the bytes it points at begin with `PRAM`. A boot sector over a zeroed root, or a first file that is not a `.KRZ` bank, is declined.

## Verified constants

CD 1, first entry `CH GRG 2.KRZ`:

| Quantity | Value |
|---|---|
| First cluster | 2 (cooked byte `0x27A00`) |
| Declared size | 5 967 472 bytes |
| Leading tag | `PRAM` |
| Suffix written | `.krz` |

Corners that pin the edges of the format: CD 1's smallest bank is `BR SHAK1.KRZ` at 341 574 bytes; CD 2's is `DRUM KIT.KRZ` at 1 012 bytes, and it still leads with `PRAM`. CD 1 lists 106 banks, CD 2 lists 189; both volumes are unlabelled and so are named `KMSI`.
