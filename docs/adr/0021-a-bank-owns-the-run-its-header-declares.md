# ADR-0021 · An EIII/ESI bank owns the record run its own header declares

**Status:** accepted · 2026-08-20

## Context

[ADR-0015](0015-locate-banks-by-signature.md) settled how an E-mu bank is *found*: by its own `EMULATOR` header, which repeats the directory's bank name, rather than by arithmetic on the directory's `start` field. That still holds. What it also settled, in one sentence and without a measurement behind it, is how a bank *ends*: *"A bank ends where the next located bank begins."*

That bound is wrong in both directions, and [issue #15](https://github.com/bmxcode/samplerdisc/issues/15) is what made it visible. On `protozoa`, three banks were credited with a neighbour's records — `Orbit Presets  X` reported 1 077 where its 8 MiB holds 539, with 541 duplicated names. The duplicated names are the tell, and they are the same tell as the twice-written E-IV directory in [ADR-0020](0020-read-e-iv-through-its-sample-directory.md).

Measuring it turned up three separate things, each of which breaks the rule on its own.

**A bank's region holds more than the bank.** Mastering writes a bank image into a fixed region and whatever was there before survives past its end. Every record past the declared end of a bank on `protozoa` is another bank's record at a *single constant shift* — 265 of 265 for `Vintage+InstrmtX`, 71 of 71 for `Phatt Presets  X`, 63 of 63 for `Protozoa       X`, and so on across every bank on the disc. No bound drawn *between* banks can exclude any of it, because it is inside the region the bank was given.

**Two banks on `protozoa` have a header that was not recognised.** `Orbit Presets 4k` and `Phatt Presets 4K` open with `EMU SI-32 v3` where their neighbours open with `EMULATOR 3X` — same layout, same fields, same records. They were not located at all, so each was invisible as a bank *and* absent as a boundary, which is why the bank in front of each swallowed its region and reported its records twice.

**Three headers on two discs are written twice.** `_bank_offsets` kept the first hit for each name. `esi32-gm` keeps an older revision of `2.5M Drums+SFX X` and `1.3M Drums+SFX X` in a region its directory allocates to nobody and *below* the banks the directory points at; `protozoa` keeps a second `Phatt Presets  X` above them. Taking the first header of a name reads an older revision on one disc; taking the last reads a truncated copy on the other.

The fourth finding is the one that decides the shape of the fix. The bank header's `0x30` and `0x34` are not decoration: **`0x30` is the offset of the sample area and `0x34` is the length of the record run measured from its first record**, which sits exactly 74 bytes in on 107 of the 110 populated banks of the four EIII/ESI reference discs and never any earlier. The run's far end lands on the last record just as tightly: it ends exactly at `0x30 + 74 + 0x34` on 72 banks and exactly 92 bytes — one sample header — short of it on 19 more. The run also reproduces the reference bank the format doc pins: `8M GeneralMidi X`, 452 records, 452 distinct names, 7 345 200 bytes, first record `Piano E0` at 12 000 Hz — unchanged to the byte.

## Decision

**A located bank owns the records that start inside the run its own header declares, and nothing else that happens to lie in its region.**

Three parts, each measured:

**The run is the bound.** `[0x30, 0x30 + 74 + 0x34)` gates where a record may *start*. The next bank header on the disc still gates how far the read may go, so a header damaged in a rip declares a run that is clipped rather than one that reaches into the next bank. Neither bound is sufficient alone.

**A record's payload may run past the declared end.** The run's far end is tight on 91 of the 110 populated banks and loose on the other 19 — 11 whose last record overshoots it, 8 whose run has slack after the last record. Eight records across `eiiix-1` and `eiiix-2` start inside the run and extend beyond it, and they are real: requiring a record to *fit* costs those eight and moves both EIIIX baselines. So the run gates where a record starts, and never where its audio ends.

**`EMU SI-32` is a bank header.** Matching the family prefix rather than the full 16 bytes, because the version suffix is a ROM revision and the name at `+16` — which has to match a directory entry — is what confirms the hit.

**Where one name has two headers, the directory's placement decides.** `header address == unit × start + bias` is fitted from the headers already located by signature, and used *only* to arbitrate. It is exact where it is asked: 45 of 45 on `eiiix-1` and `eiiix-2`, 14 of 14 on `protozoa`, 6 of 6 on `esi32-gm`. Only names with a single header may vote — a name written twice is the question, so it cannot also be the evidence — and a fit corroborated by fewer than three banks is refused, leaving the first header of each name as the answer.

This is the same shape [ADR-0020](0020-read-e-iv-through-its-sample-directory.md) already uses for E-IV: fit an allocation unit per disc, then never *place* anything with it, only confirm something located independently. ADR-0015's objection was to arithmetic that puts a bank where no header agrees. Nothing here does that.

## What this costs, stated plainly

`0x34` was previously read **only after a walk had already come back empty**, as the reason for an emptiness already observed. That separation is now gone: the field bounds the walk, so a bank declaring zero is empty by construction and the note that follows restates the bound instead of corroborating it independently. [ADR-0012](0012-a-probe-must-confirm-a-file.md) is about exactly that kind of self-agreement, and this is a real loss.

It is taken deliberately, because the alternative was measured. `Protozoa       X` declares `0x34 == 0` and its region holds 63 records — and all 63 carry names from the Phatt banks, at a constant shift of one allocation unit, with its own first record at `+0x5f73` where every populated bank on the disc starts at `0x30 + 74`. Reporting them attributes another bank's audio to the disc's index bank. Refusing to read `0x34` as a bound cannot avoid that; no bound between banks can.

What survives is the half that matters: a bank that declares sample data and yields none still gets **no** note, because there the emptiness is genuinely unexplained and has to stay visible.

## Alternatives rejected

**Bound by `at + unit × length` from the directory entry.** It fixes all three `protozoa` banks and agrees with the next-header bound on 11 of that disc's 14 located banks. Rejected because it is the weaker instrument: it is arithmetic on a field ADR-0015 already found unreliable, it needs the per-disc unit before it can say anything, and — decisively — it does not exclude the stale tails, which are inside the declared extent. It also cannot make `Protozoa       X` empty: bounded to its one declared unit it still reports 62 of the Phatt banks' records.

**Deduplicate `_bank_offsets` by address rather than by name.** The smaller, safer-looking half, and it was the issue's own suggestion. Rejected as insufficient rather than wrong: it fixes `Protozoa       X`'s bound and does nothing for the two `4k` banks, which have no `EMULATOR` header to deduplicate. It also leaves `esi32-gm` reading an older revision of two banks, because "first by address" is not a rule, it is an accident of which copy the mastering wrote first.

**Keep the next-located-header bound and drop records whose name repeats one already seen.** Attractive because duplicated names are how the bug was found. Rejected: the discs themselves repeat names. `protozoa` really does carry two `Agogo Bell` records at different extents, `esi32-gm`'s `2.5M Drums+SFX X` carries 22 repeats inside its own declared run, and a rule that deletes them deletes real audio to hide a bound that is still wrong.

**Treat the `4k` banks as a different bank interior and keep listing them with a note.** The conservative reading, and the one the issue left open. Rejected on the evidence: the `EMU SI-32 v3` header carries the same name at `+16`, the same directory index at `+0x20` and the same `0x30`/`0x34` pair as its `EMULATOR 3X` neighbours, and `Orbit Presets 4k`'s region is 97.98% byte-identical to `Orbit Presets  X`'s. It is not a different interior. It is the same interior under a Formula 4000 ROM's name, and listing it with a note would be withholding 774 samples the disc plainly offers.

**Widen the header match to any `EMU`-prefixed printable field.** Would catch a fourth variant unseen. Rejected: a false hit becomes a boundary that silently truncates the bank before it, which is the failure this record exists to remove. A fourth variant instead shows up as a bank with no header and a note — visible, and the note now names the structure that is missing.

## Consequences

**Good.** Every record dropped is accounted for. Across `protozoa`'s 15 located banks, each one is another bank's record at a constant shift: 264 of 264, 70 of 70, 59 of 59, 42 of 42, and so on. Nothing is dropped that could not be shown to belong somewhere else.

**Good.** The two `4k` banks extract — 535 and 239 samples under their own names, where they previously listed empty with a note borrowed from the E-IV case.

**Good.** `eiiix-1` and `eiiix-2` do not move: 1 189 and 1 333, unchanged, and the three E-IV discs are untouched at 449, 2 822 and 828. Those five are the check that the shared record parser was not disturbed.

**Bad, and the headline.** `esi32-gm` moves from 2 424 to 2 265 and `protozoa` from 6 788 to 5 852. Both old numbers counted another bank's records; `esi32-gm`'s were not previously suspected, and the issue records it as unaffected. It is not — its last bank ran to the end of the image and was credited with 193 records that belong to the two banks before it. Both counts are now pinned by a disc-backed test rather than by a table in a document, which is why the doc's baseline was able to be wrong for a release.

**Watch for.** A disc whose `0x34` is damaged or zero on a bank that really holds audio. It will list empty with a note saying the header declares no sample area, and the note will be true about the header and wrong about the bank. Before this record that disc would have listed its neighbour's samples instead, which is not better, but it is a different wrong and someone may meet it.

> **D21 read the other half of the run.** This record measured the last record of a bank ending exactly at `0x30 + 74 + 0x34` on 72 banks and "exactly 92 bytes — one sample header — short of it on 19 more", and took the second population as a loose fit. It is not: those banks were sized from the right channel's end pointer on a record that declares its audio on the left, which is 92 bytes short by construction. Under [ADR-0029](0029-a-record-is-closed-by-the-channel-it-declares.md) the fit is exact on 173 of 186 banks across ten discs and **no bank is 92 short on any of them**. Nothing here changes: the run is still the bound, it still gates where a record starts and never where its audio ends, and the four sample counts this record moved move again for a different reason.
