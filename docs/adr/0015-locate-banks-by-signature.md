# ADR-0015 · Locate E-mu banks by signature; list what cannot be read

**Status:** accepted · 2026-08-19

## Context

The `EMU3` bank directory gives every bank a name, a `start` and a `length`. The obvious reading is that `start` is an address in some unit, and finding the unit is a matter of measurement.

It was measured, from the gcd of consecutive bank-header offsets, and it is not one number:

| Disc | Unit |
|---|---|
| `esi32-gm`, `eiiix-1`, `eiiix-2` | 256 KiB |
| `protozoa` | 1 MiB |

No header field predicts which. `0x2c` equals 2048 on `protozoa` — exactly 1 MiB in 512-byte blocks — and equals 8 on the discs where the answer is 512. The layout does not follow `start` consistently either: on `esi32-gm` two adjacent banks differ by 24 in `start` and by 8 units on the disc.

A second problem sits underneath. EIII/ESI banks open with an `EMULATOR 3X` header carrying the bank name; `eiv-analogia` contains no `EMULATOR` string anywhere in 294 MB. The top-level directory is shared across all five discs, and the bank interior is not. Samples live in the interior.

This is the situation [ADR-0012](0012-a-probe-must-confirm-a-file.md) is about, one layer down: arithmetic that *nearly* works, on data where being wrong produces a plausible listing rather than an error.

## Decision

**Locate banks by their own header, not by arithmetic on `start`.** The `EMULATOR` header repeats the directory's bank name verbatim, so matching on it is exact and self-checking. A bank ends where the next located bank begins; the directory's `length` is not used as a bound either.

This is [ADR-0004](0004-detect-by-signature.md) applied a layer down — content over declared position, for the same reason.

**A bank whose interior is not recognised is listed, not guessed at.** `eiv-analogia`'s 12 banks come out with their real names and no files, carrying a note saying why. Extraction waits for a second E-IV disc.

That note is load-bearing. A volume with no files and no explanation is the signature of a probe that matched something it should not have, and the disc-backed suite asserts exactly that. Without an explicit marker the two cases are indistinguishable to anything but a human reading the names.

## Alternatives rejected

**Keep looking for the unit.** A field somewhere probably does encode it, and five discs is a small sample. Rejected on cost against benefit: the signature scan is exact today on every disc, and a rule derived from five discs would be a rule that fails silently on the sixth in a way nobody notices — the failure would be a bank reading its neighbour's samples, which looks like a longer listing, not like a bug.

**Use `start` with a per-disc unit sniffed from the first bank.** Cheaper than a full scan, and it would work on all five. Rejected: it is the same class of inference that produced the wrong endianness on this format, and it inherits the `esi32-gm` case where physical spacing does not track `start` at all.

**Reverse-engineer the E-IV interior from the one disc available.** Tempting — the directory is already understood and there is real audio behind it. Rejected under the project's own standing preference for one verified format over two guessed ones. One specimen cannot distinguish the format from that disc's quirks, and a wrong record boundary yields WAVs that play as noise with nothing reporting a problem.

**Report the E-IV disc as unreadable.** Honest and simple. Rejected because it throws away work that succeeded: the folder table, the bank directory and 12 correct names are all in hand, and they are what a user needs to know the disc is understood and only partly supported. This is the [ADR-0009](0009-export-iso-escape-hatch.md) argument.

## Consequences

**Good.** Bank location is exact rather than inferred, and it degrades honestly: a bank with no header is not found, rather than found in the wrong place.

**Good.** The E-IV disc is usable today for what it can be — `list` shows its structure, `export-iso` hands over the sectors — and the gap is stated rather than implied.

**Bad.** Opening a disc costs a full scan for the bank magic, roughly a pass over the image. It is a few seconds on a 300 MB disc and it happens once.

**Bad.** A bank whose header is missing or damaged is invisible to extraction even on an EIII/ESI disc, where arithmetic might have found it. Accepted: the failure is a bank that does not appear, which is visible, rather than a bank whose contents are wrong, which is not.

**Watch for.** The scan being reused as a probe. It reads the whole image; `probe()` runs at every candidate offset during origin detection and must stay cheap. They are deliberately separate.
