# ADR-0024: Convert AIFF, and drop the twin only when it says nothing new

**Status:** accepted

## Context

The Best Service ProSamples discs come in two kinds. Sixteen are AKAI. Thirteen are ISO 9660 discs holding plain audio, and every one of those carries **the same sounds twice**: a `PS-nn AIFF …` tree beside a `PS-nn WAV …` tree, matching file counts, matching stems.

Extraction copied both out untouched. That is 7 926 WAV and 7 498 AIFF from thirteen discs — and 6 033 of the AIFF hold audio that is already coming out of the same disc as a WAV. A user got each of those sounds twice, at double the disk, with the second copy in a format the README calls a gap: *"AIFF payloads are copied, not converted."*

So there were two questions, and they turned out to be one. Converting the AIFF closes the stated gap. Whether to then write it is the real decision, because on these discs the conversion mostly produces a file the user already has.

Three things the discs settled before the decision could be made:

**The audio really is identical.** Matched by hashing the PCM rather than by name: 6 033 of 7 498. Where both sides carry a loop, the loop agrees exactly, on 195 of 195 pairs; where both carry a root key, it agrees on 198 of 198.

**On one disc it is identical nowhere.** `vol.43` ships 1 386 AIFF and 1 386 WAV under matching names, and **not one pair shares its audio** — the AIFF are mastered a few frames longer, 17 638 bytes against 17 616 on `43e-01chh01`. Two masterings of one take.

**On 314 pairs the AIFF knows something the WAV does not.** Those AIFF carry an `INST` chunk — root key, tuning, a sustain loop — and their WAV twins carry no `smpl` chunk at all. The audio is the same; the files are not.

## Decision

**Convert AIFF to WAV, and skip it only when its audio has already been written *and* it carries nothing the written file lacks.**

Three parts, each answering one of the findings:

1. **The WAV is written verbatim, the AIFF is converted.** The disc's own WAV is preferred where there is a choice: it is the publisher's file and carries the `smpl`, `acid` and `LIST` chunks a conversion would have to rebuild.
2. **The twin is recognised by its audio, never by its name.** A `sha256` of the PCM, not of the file — the two trees differ in their metadata chunks and agree on every audio byte.
3. **A twin that carries a root key or a loop the written WAV lacks is written too.** Same audio is not the same file.

A suppressed twin is reported as a `Skipped` naming the file that already holds the audio, and counted apart from damage in both the summary and the manifest.

On the collection: 5 719 duplicates suppressed, 1 779 AIFF written — 1 465 with no twin at all, 314 carrying metadata their twin lacks.

## Rejected

**Write both trees.** The simplest rule, and it doubles 8 GB of output for no extra sound. The duplication is not the user's to sort out afterwards: the two files have different names in different folders and nothing in either says they are the same take.

**Write the disc's WAV and never convert.** Cheapest, and wrong three ways. It drops the 1 465 AIFF with no WAV twin, it drops all 1 386 of vol.43 — where the AIFF are a different mastering, not a copy — and it leaves the README's stated gap open for the next disc that ships AIFF alone.

**Deduplicate by name.** What the file counts suggest and what vol.43 refutes: 1 386 files that share a name with a WAV and share nothing else. A name-based rule discards a whole disc's worth of audio and reports nothing.

**Prefer the AIFF and drop the WAV wherever both exist.** Symmetrical, and loses more: 1 704 pairs have a `smpl` on the WAV side and no `INST` on the AIFF side, against 314 the other way. Neither side is reliably richer, which is why the rule compares the two files rather than picking a format.

**Merge the AIFF's metadata into the copied WAV.** Strictly the best output — one file, all the information — and it means rewriting the publisher's file. A verbatim copy is checkable against the disc, and every other format here is checked that way. Writing a second file costs 314 files out of 26 365 and keeps that property.

**Treat the byte swap as forbidden by [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md).** The rule there is that audio is copied, not converted — no resampling, no bit-depth change, no dithering. Reversing the bytes within a sample value changes no value, loses no precision, and is exactly reversible; running it twice returns the input. It is a re-ordering, and the same argument does not extend to 8-bit, where AIFF is signed and WAV is unsigned: carrying that means adding 128 to every sample, so `sample/aiff.py` refuses 8-bit rather than blurring the line.

**Wait for a second publisher's discs before deciding.** These are thirteen discs from one publisher, and the shape may not generalise. It does not need to: the rule is stated over what the *files* contain, not over what Best Service did. A disc with no duplicates triggers nothing.

## Consequences

`sample/aiff.py` joins `sample/`, and `sample/__init__.py` no longer claims that no module there converts anything — it says what is re-ordered and why that is not the same.

`wav.read_header` exists, so a copied WAV reports its real rate and length. Every ISO 9660 payload used to come back as 0 Hz and 0 frames — 15 424 files across thirteen discs whose manifest entry said nothing about the audio.

`Skipped` grows a `duplicate` flag and `DiscReport` a `duplicates` count. Without it a clean disc reads as a broken one: `vol.42` reported *"skipped 423 damaged or unreadable entries"* when all 423 were sounds already written.

The oracle in `tests/test_discs.py` is the part worth keeping. Every other format here is tested by comparing output against the bytes it came from, which proves the payload was copied and says nothing about whether it was understood. Here the publisher shipped an independent answer 6 033 times, and it is what settled the loop convention rather than leaving it a guess — see [formats/aiff.md](../formats/aiff.md).
