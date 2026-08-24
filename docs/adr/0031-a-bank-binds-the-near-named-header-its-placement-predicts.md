# ADR-0031 · A bank binds the near-named header its placement predicts

**Status:** accepted · 2026-08-24

## Context

[ADR-0015](0015-locate-banks-by-signature.md) settled that an EIII/ESI bank is *found* by its own `EMULATOR` header, which repeats the directory's bank name, and [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) settled how a name written twice is disambiguated: fit `header address == unit × start + bias` from the headers already located by signature, and use it *only* to say which of two same-named headers a directory entry meant. `_bank_offsets` implements both by keying `located` on the exact bank name.

[Issue #43](https://github.com/bmxcode/samplerdisc/issues/43) is the case that keying on the exact name cannot reach. Five named banks across three discs claimed a volume, found no header for their directory name and read nothing — `Electric Grand X` on `Vol. 10 – Elements of Sound 1MB`, `PERCUSSION#1   X` on `Vol. 16 – Ditto Drums`, and `HvyGtr FX5     X`, `Misc Gtr FX 2MbX`, `HvGtrFdBkTxtr2Mb` on `Vol. 17 – Heavy Guitars`. Each carried the ADR-0012 note `no bank header found for this bank; listed only`, so the invariant held — but unlike the 28 `E3 Main Code`/`E3X Main Code` operating-system slots that share it, these are named like ordinary sample banks.

Measured against the discs, every one has a real header sitting at *exactly* the address ADR-0021's placement fit predicts, carrying real audio named after the bank — but its own 16-byte name field at `+16` is a corrupted copy of the directory name:

| Disc | Directory name | Header `+16` name | Records | First record |
|---|---|---|---:|---|
| `elements1mb` | `Electric Grand X` | `Eelectric GrandX` | 9 | `ELEC GRAND  _000` |
| `ditto-drums` | `PERCUSSION#1   X` | `PERCUSSION #1  X` | 31 | `TAMB BRASS` |
| `heavy` | `HvyGtr FX5     X` | `HvyGtr FX5    XX` | 2 | `Gtr FX 11` |
| `heavy` | `Misc Gtr FX 2MbX` | `Misc Gtr FX 2mbX` | 6 | `Gtr Feedback Shr` |
| `heavy` | `HvGtrFdBkTxtr2Mb` | `HvGtrFdBkTxtr2M ` | 1 | `Gtr FeedbackLoop` |

The corruptions are a shifted space, a case change, or a single doubled or dropped character — an edit of at most one once the name is lowercased and its spaces stripped. `_bank_headers` finds these headers (their `+16` names are plausible), but `_bank_offsets` never binds them to a directory entry, because the directory says `Electric Grand X` and the header says `Eelectric GrandX`.

They are not the operating-system slots and not index banks. An OS slot has no header at all where it points; an index bank declares a zero-length run. These declare a run, hold audio, and name it for the bank.

## Decision

**A directory entry that no header names exactly binds the header sitting at the address its placement predicts, when that header carries a near-copy of the entry's name and no other entry already claims it.**

Three gates, each measured:

**The header must sit exactly at the predicted address.** `want = unit × start + bias`, the same fit ADR-0021 already computes, requiring the same three agreeing single-header banks before it says anything. A disc that has shown no placement rule recovers nothing and keeps the note. Nothing is *placed*: a bank whose predicted address holds no header binds nothing.

**The header's name must be a near-copy.** Normalise both names — lowercase, strip spaces — and require a Levenshtein distance of at most one. Every one of the five is a distance of zero or one; the OS-slot collisions below are a dozen. The name is what confirms the hit, exactly as in ADR-0015 — the placement only says which header, and the name says it is the right one.

**The header must be unclaimed.** A bank may never bind a header that a name-matched entry already owns. This is the gate that decides `ditto-drums`: `E3 Main Code`'s predicted address lands on the `Ditto Drums    X` index bank's header and `E3X Main Code`'s lands on `DAVE W  KIT1   X`'s — both real banks the directory names elsewhere. The name gate rejects them (`e3maincode` is nothing like `dittodrumsx`), and the unclaimed gate is the belt to that suspenders.

This is [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md)'s instrument used one step wider: from *which of two headers wearing this exact name* to *the near-named header this entry points at*. Downstream nothing changes — a recovered entry flows through the same `_declared_run` and record walk, bounded by the same next-header cap, and a recovered bank with records gets no note while one that recovers nothing keeps it, so [ADR-0012](0012-a-probe-must-confirm-a-file.md) still holds.

## Alternatives rejected

**Bind by the predicted address alone, without a name gate.** The smallest change, and it recovers all five. Rejected on `ditto-drums`, measured: `E3 Main Code` and `E3X Main Code` are real slots on every EIII disc, and their predicted addresses fall on the `Ditto Drums    X` and `DAVE W  KIT1   X` headers. Address alone would hand each OS slot another bank's audio under the wrong name — the exact failure ADR-0015 exists to prevent, one layer in. The unclaimed gate catches these two, but a future disc whose OS slot points at an *orphan* stale header would slip through it; the name gate is what makes the rule safe rather than lucky.

**Widen the exact-name match to a fuzzy match everywhere in `_bank_offsets`.** Tempting, because it would need no placement. Rejected: it reopens the whole of ADR-0015. A fuzzy match between a directory name and *any* header on the disc would, on a disc full of `Gtr FX 11`-style near-identical names, bind a bank to a neighbour that is one edit away and holds different audio. The placement is what makes the near-name safe — it is only ever consulted at the one address the disc itself points the entry at.

**Leave them listed with the note.** The conservative reading, and the state issue #43 filed. Rejected on the evidence: the header is there, at the predicted address, carrying `ELEC GRAND` and `TAMB BRASS` and `Gtr Feedback`. Listing them empty withholds 49 samples the disc plainly offers, on the strength of a one-character typo the mastering left in a name field.

**Correct the header name to the directory's and match.** Would also work. Rejected as the wrong shape: it invents an authority the disc does not grant. The directory name and the header name disagree, and this project does not get to decide the header's is wrong — only that the two are the same bank. Binding by address with a near-name gate says exactly that and no more.

## Consequences

**Good.** Five banks that read nothing now read their records: `elements1mb` gains 9, `ditto-drums` 31, `heavy` 9 — 49 samples across three discs, each named for its bank.

**Good.** No reference disc moves. Simulated across all ten EMU3 reference discs and the three size-twins in the collection, the recovery binds nothing: every bank on those discs either matches a header exactly or has no header at its predicted address. The change fires only where a name was mistyped.

**Good.** The OS-code slots stay noted. `E3 Main Code` and `E3X Main Code` are refused by the name gate and the unclaimed gate together, so the note still names exactly the slots that hold an operating system and no audio.

**Watch for.** A disc that mistypes a header name by *more* than one normalised edit. It will list empty with the note, which is the honest floor — visible, and recoverable if a later disc shows the corruption is systematic enough to widen the threshold against.

**Deliberately not claimed.** Two discs here list a bank name **twice** in the directory — `Harpsichord    X` on `elements1mb`, `HvyGtr Maj.Open` on `heavy` — and because `located` is keyed by name both entries resolve to one header and double-list the same records. That is a different mechanism from the five (it reads the same audio twice, not nothing), one arm of it points at a real but blank-named header, and it is left to [#47](https://github.com/bmxcode/samplerdisc/issues/47). This record recovers a header the directory names once and mistypes; it does not touch a name the directory writes twice.
