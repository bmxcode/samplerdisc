# ADR-0034 · Each EIII/ESI directory entry binds its own header, not its name's

**Status:** accepted · 2026-08-31

## Context

[ADR-0015](0015-locate-banks-by-signature.md) finds an EIII/ESI bank by its own `EMULATOR` header, which repeats the directory's bank name. [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) settled how a name written twice picks *which* of two headers a directory entry meant — the placement fit `header address == unit × start + bias` — and [ADR-0031](0031-a-bank-binds-the-near-named-header-its-placement-predicts.md) extended that instrument to bind a header whose name the mastering mistyped. All three are implemented in `_bank_offsets`, and all three keyed its result on the exact bank **name**.

That keying is the bug [#47](https://github.com/bmxcode/samplerdisc/issues/47) records, and [ADR-0031](0031-a-bank-binds-the-near-named-header-its-placement-predicts.md) named it in its "Deliberately not claimed" section: where a directory lists **one name twice**, both entries look up the single name key and resolve to one header, so the same records are read and written under each entry. It is a different failure from the five ADR-0031 recovers — it reads the same audio *twice* rather than *nothing* — and it left the D24 pins for two discs carrying the double-count.

Two discs show it, and they are two different shapes:

| Disc | Name written twice | Headers wearing it | The second entry's predicted address holds |
|---|---|---|---|
| `elements1mb` | `Harpsichord    X` | **two** — `0x017cb500`, `0x036525c0` | a real `Harpsichord    X` header (11 records / 13) |
| `heavy` | `HvyGtr Maj.Open` | **one** — `0x122dcd00` | a real `EMULATOR 3X` header named `               X` (blank) |

`elements1mb` is the simple case: the disc holds two genuinely different `Harpsichord    X` banks — one of 11 records, one of 13 — and the name key collapsed them onto whichever the placement fit wrote last, listing its 13 twice. `heavy` is the case ADR-0031 flagged as the second mystery: the directory writes `HvyGtr Maj.Open` twice but only one header wears the name, and the second entry's placement points at a header whose 16-byte name field is blanked to spaces and the conventional trailing `X`. That blank-named header is a real 6.3 MB `EMULATOR 3X` bank holding six `MajOpen …` records — **byte for byte the same audio** the named header holds, the same duplicate-library pattern as `protozoa`'s `EMU SI-32` `4k` banks, with the name field zeroed rather than re-typed.

## Decision

**`_bank_offsets` is keyed by directory entry, not by bank name.** Each entry resolves independently, so two entries that share a name bind to their respective headers instead of collapsing onto one.

The resolution per entry is the same instrument as before, applied per entry:

**A name written once binds as it always did** — to its single header, or, where the disc holds two headers of that name, to the one the placement fit predicts ([ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md)). This is the overwhelming common case and no reference disc moves on it.

**A name written twice binds each entry to the header at its own predicted address.** The two entries have different `start` fields, so the fit predicts a different address for each, and each takes the header sitting there. On `elements1mb` the two `Harpsichord    X` entries split onto their two headers and read 11 records and 13 — two banks, not one listed twice.

**A header a name-mismatch cannot confirm is not bound.** `heavy`'s first `HvyGtr Maj.Open` entry predicts the blank-named header's address, and its name — `X` once normalised — confirms nothing, so the entry keeps its note rather than binding by address alone. This is [ADR-0031](0031-a-bank-binds-the-near-named-header-its-placement-predicts.md)'s rule unchanged: the placement says *which* header, the name says *whether it is the one*, and a blank name says nothing. The near-name recovery still runs for every unbound entry, so the five mistyped-header banks are unaffected; the blank name is a dozen edits from `HvyGtr Maj.Open` and fails its gate.

## Alternatives rejected

**Deduplicate the two entries down to one bank.** The smallest-looking change, and it is wrong on `elements1mb`: the two `Harpsichord    X` entries are two *different* banks, 11 records and 13, that the disc deliberately ships as separate directory entries. Collapsing them keeps one and silently drops the other's audio. The double-listing is not a duplicate entry to remove; it is two real entries the name key failed to tell apart.

**Assign the two entries to the two headers by directory order.** On `elements1mb` it happens to work, because the entries and the headers sort the same way. Rejected because the placement fit is what the project already trusts to say which header an entry means ([ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md)), and order is an accident the fit is not: `eiiix-2`'s `start` values are scattered rather than sorted, and a disc that writes its duplicate-name headers out of directory order would be read backwards. Binding by position is the arithmetic ADR-0015 refused, one layer in.

**Bind `heavy`'s first entry to the blank-named header — recover the six samples.** The audio is right there, and its record names are `MajOpen …`, so a human reads it as the bank. Rejected twice over. First, its header name confirms nothing, and binding by address alone is exactly what [ADR-0031](0031-a-bank-binds-the-near-named-header-its-placement-predicts.md) rejected: a blank slot at a predicted address that happens to hold audio is how another bank's samples get handed to the wrong entry, and the near-name gate exists to stop it. Second, and decisively here: the blank header's six records are **byte-identical** to the six the *other* `HvyGtr Maj.Open` entry already yields from the named header, so binding it would not recover six new samples — it would re-create the double-listing this record exists to remove. The honest outcome is a note, and no audio is lost, because the same bytes are written once under the named entry.

**Confirm the blank header by matching its record names to the bank name.** `MajOpen E` plainly belongs to `HvyGtr Maj.Open`, and a rule that reads the records inside a candidate header and checks their names against the directory entry would bind it. Rejected for this deliverable as a new confirmation instrument the project has not measured: it is a different kind of evidence from the `+16` name the whole design confirms a bank by, it would need calibrating against every reference disc before it could be trusted not to bind a neighbour, and on the one disc that motivates it the audio is a duplicate already written. Left as the open question below, to be settled if a disc turns up whose blank-named header holds audio nothing else yields.

## Consequences

**Good.** The two discs stop double-listing. `elements1mb` reads its two `Harpsichord    X` banks as the distinct 11- and 13-record banks they are (1 465 → 1 463; the two arms previously both read the 13). `heavy` reads `HvyGtr Maj.Open` once (870 → 864, with six fewer loops and six fewer stereo), and its second entry is now noted rather than silently listing another entry's records.

**Good.** No two volumes claim one record on any disc. `test_protozoa_gives_each_bank_its_own_records` asserts that invariant, and it holds across the collection — the double-count was the one place it did not.

**Good.** No reference disc otherwise moves. The entry-keyed map is identical to the name-keyed one on every disc with no duplicate directory name, which is every pinned disc except these two; `eiv-studio`, whose four `E-mu Systems 96` entries share a name, is a `FORM/E4B0` E-IV disc whose banks never carried an `EMULATOR` header and so never entered this map — its counts and payload digest are byte-for-byte unchanged.

**Watch for.** A disc that lists a name twice and shows **no** placement rule — fewer than three agreeing single-header banks. Its two entries cannot be told apart and both stay unbound with a note, which is the honest floor rather than a guess; none of the ten reference discs is that disc.

**Deliberately not claimed.** `heavy`'s blank-named 6.3 MB header is characterised — a real `EMULATOR 3X` bank, byte-identical to the named `HvyGtr Maj.Open`, its name field blanked by the mastering — but not *recovered by name*, because on this disc its audio duplicates a bank already read. A disc whose blank-named header holds audio nothing else yields would make the record-name confirmation above worth measuring; until one appears, that stays a note and not a binding ([#47](https://github.com/bmxcode/samplerdisc/issues/47)).
