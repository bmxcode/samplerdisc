# Raw CD sectors

A CD sector on the disc is 2352 bytes. A `MODE1` data sector spends 2048 of those on user data and the rest on sync, header and error correction. Ripping tools either keep all 2352 (*raw*) or keep only the 2048 (*cooked*).

Everything above the container layer expects cooked 2048-byte sectors, so raw images are de-interleaved on read.

Verified against `black2black` (622 049 904 bytes).

## Sector layout

| Offset | Size | Contents |
|---|---|---|
| 0 | 12 | Sync — `00 FF FF FF FF FF FF FF FF FF FF 00` |
| 12 | 3 | Address, BCD minute/second/frame |
| 15 | 1 | Mode |
| 16 | **2048** | **User data** |
| 2064 | 288 | EDC / ECC |

Cooking is `sector[16:16+2048]`.

## Detection

The sync pattern at offset 0 of the file is the signature. It is 12 bytes and does not occur by chance, so it is a safe test even on a file with a misleading extension.

`.bin`, `.tao` and `.cdr` all show up holding raw sectors, and `.img` is used for both raw and cooked. Sniff; do not trust the name ([ADR-0004](../adr/0004-detect-by-signature.md)).

## Cue sheets

A sibling `.cue` names the track mode. `black2black`:

```
FILE "TZAMGB2BAK1.BIN" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
```

`MODE1/2352` is raw; `MODE1/2048` is cooked. Where a cue is present it is authoritative for sector size and for which track holds data. Where it is absent — and it often is, since the `.bin` gets copied around on its own — fall back to sniffing the sync pattern.

## Verified constants

| Quantity | Value |
|---|---|
| File size | 622 049 904 |
| Sector size | 2352 |
| Sectors | 264 477 — exactly, no remainder |
| Track mode | `MODE1/2352` |
| Filesystem origin | 0 |

The size dividing exactly by 2352 is a useful sanity check: a raw image with a remainder has been truncated or has a header someone forgot to mention.

## Not ISO 9660

`black2black` carries the AKAI filesystem starting at sector 0. There is no ISO 9660 volume descriptor, no 32 KB system area, nothing a modern OS will mount. Cooking the image and looking for `CD001` finds nothing — that is expected, not a fault.
