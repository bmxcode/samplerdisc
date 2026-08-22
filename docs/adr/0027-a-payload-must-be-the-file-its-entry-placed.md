# ADR-0027 · An AKAI payload must be the file its entry placed, and its header length is the generation the entry declares

**Status:** accepted · 2026-08-22

## Context

[Issue #23](https://github.com/bmxcode/samplerdisc/issues/23), raised while settling #17, says an AKAI sample payload whose header disagrees with its directory entry is extracted silently — as a WAV that opens, plays, and is somebody else's audio. It names nine files on `AMG - Kickin' Lunatic Beats 2 AKAI CD1`, proposes four tests, and asks for a sweep across the collection before deciding what a failure should do.

**The sweep says the bug does not reproduce.** Across all 44 AKAI discs and 56 490 sample entries, 96 payloads disagree with their entry and **all 96 are already refused**. The nine named files are among them. Nothing is extracted silently, and nothing ever was: `_looks_like_header` has been testing the id, the valid byte and the name's decodability since D3, and `parse` has been testing the rate. Three and a half of #23's four tests were already there and nobody had noticed, including the person who wrote the issue.

The 96 are also, exactly, the 96 skips the README already reported — 92 "do not begin with an AKAI sample header" plus four "implausible sample rates". Not a disjoint set, not a near-miss: the same files. So the deliverable as briefed had nothing to add.

What it did have was the false-positive case to rule out first, which the issue's own wording pointed at: *the S3000 192-byte header variant exists, and a check keyed to 150 that fires on every S3000 disc is what to rule out first.* Ruling it out found the defect underneath.

### The S3000 header is not a variant to be aware of; it is a quarter of the collection, read wrong

**13 451 of the 56 490 AKAI samples carry a 192-byte header and were read as though it were 150.** Three independent structures agree on it and none of them knows about the others:

- **The directory says so.** Every one of the 13 451 is a file whose type byte has the high bit set — the S3000-family flag that already names a kept original `.s3s` rather than `.s1s`. The split is perfect: 13 451 high-bit files at 192, 42 989 low-bit files at 150, and no disc mixing the two rules.
- **The payload says so.** The directory's declared size equals `words × 2 + header_len` on **56 430 of 56 430** payloads readable at all — 13 441 at 192 and 42 989 at 150. The 60 that fail that identity are the damaged ones, and every one of them fails an identity test too.
- **The bytes say so.** At 150 on `AKAI.S3000.Sound.Library.2`'s `NPF E0` sit 21 zero bytes and then a repeating `00 0a ff ff 22 a8 00 aa ff ff …` — structurally identical across samples, which audio is not. Real waveform starts at 192.

The consequence is not an error, which is why it survived four deliverables. `frames` came out right, the WAV opened, its length was within 0.1 %, and the payload-versus-output check the README ran compared the output against the same wrong offset. What actually shipped was a WAV **beginning with 42 bytes of header read as PCM** — a burst of roughly ±20 000 lasting 0.24 ms, an audible click on the attack — **missing the last 21 frames** of the sound, and carrying every loop point 21 frames out of alignment. On nine discs: `AKAI.S3000.Sound.Library.1`–`7`, `East Connexion Piano` and `AMG - Now CD-Rom for (AKAI)`.

`HEADER_LEN_S3000 = 192` was declared in `sample/akai.py` and never read by anything. The format doc said "S3000 discs **may** use a 192-byte header variant. Branch on the id and valid bytes rather than assuming 150" — and that advice is wrong twice over: the variant is not conditional, and those two bytes do not carry the answer. `0x80` appears on 42 989 samples at 150 and 13 410 at 192.

### 31 healthy samples were being thrown away for a bit

Of the 96 refusals, **31 fail on the valid byte alone**: `0x81` on 29 samples of `Library.2` and `0x9c` on two of `Library.1`. Their id is 3, their name matches the directory exactly, their rate is a normal 44 100 or 22 050, and their word count agrees with the declared size at 192. `0x80` is a flag inside a byte and was being tested as the whole byte.

### What the four tests are actually worth

Over the 65 that remain once the flag is read as a flag:

| Test | Fires | Fires **alone** |
|---|---:|---:|
| id `!= 3` | 61 | 1 |
| valid, no `0x80` bit | 60 | 0 |
| name `!=` the entry's | 60 | **0** |
| rate outside 4000–50000 | 58 | 4 |

**The name comparison — the one thing #23 was actually about — detects nothing the others miss.** Every payload whose name disagrees also has a wrong id and a cleared valid flag, because on these images the displacement lands mid-audio, and mid-audio does not look like a header.

### The failures cluster, which is what says the check is right

**60 of the 65 are a run to the end of one volume.** Not a scatter, and not spread thinly across healthy discs.

| Disc | Mismatches | Where | Partitions declared / present |
|---|---:|---|---|
| `Best Service - Alpha Dance II` | 21 | `AC.DRUMLOOPS`, last 21 of 22 | **6 / 6** |
| `Best Service - Alpha Dance I` | 15 | `ATTACK BANK2`, last 15 of 18 | 5 / 4 |
| `Kickin' Lunatic Beats 2 CD1` | 9 | `13-TRACK 06`, last 9 of 20 | 11 / 1 |
| `AKAI.S3000.Sound.Library.5` | 7 | `SURDO`, last 7 of 13 | 9 / 3 |
| `AKAI.S3000.Sound.Library.1` | 4 | `3084 B.BEAT6` last 3 of 8; one rate | 13 / 13 |
| `AMG - Global Trance Mission 2` | 3 | `AMBIENT PAD2`, last 3 of 6 | 9 / 4 |
| `AKAI.S3000.Sound.Library.2` | 3 | three isolated rate bytes — 0, 519, 519 | 13 / 13 |
| `AKAI.S3000.Sound.Library.3` | 1 | `VOLUME 001`, its only file | 13 / 13 |
| `Audio Factory - Classical Wild Takes` | 1 | `VOLUME 002`, last of 2 | 11 / 6 |
| `AMG - Loop Soup` | 1 | `SOUP 101-103` #27 — the format doc's known one | 9 / 9 |

The other 34 AKAI discs have none at all, `Advance Orchestra`'s 2 236 samples included.

The falsifying case the sweep was meant to find turns out to be a finding instead. `Alpha Dance II` declares six partitions and holds all six, and still loses 21 of one volume's 22 samples as a tail run; `Library.1` and `Library.3` are the same shape. That is **a run of blocks lost inside a partition**, which the partition table cannot see because no header goes missing — 25 files on three `.mdx` images, a sibling of [#25](https://github.com/bmxcode/samplerdisc/issues/25) and invisible to it.

## Decision

**A payload must be the file its directory entry placed, and the header length in front of it is the generation that entry declares.**

Five parts.

**The identity is checked, against the entry, at parse time.** The id must be 3, the valid byte must carry `0x80`, the name must decode, and where the entry supplied a name the payload's must equal it. All four are kept.

**The header length comes from the directory's type-byte high bit.** 192 on the S3000 family, 150 on the S1000 one. Placed by one structure and confirmed by another, the shape [ADR-0020](0020-read-e-iv-through-its-sample-directory.md), [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) and [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md) already use — here the confirmation is the payload's own word count against the declared size, and it is asserted per disc in `tests/test_discs.py` rather than re-derived per sample at runtime.

**`valid` is read as a flag, `& 0x80`, not as a byte.** Measured safe on its own: no payload anywhere in the collection has the `0x80` bit set, an id of 3 and a plausible rate except the 31.

**A refusal is a `Skipped` carrying a `mismatch` flag, counted apart in the summary and the manifest.** [ADR-0024](0024-the-aiff-twin-is-converted-and-deduplicated.md)'s precedent one step on: a duplicate is not damage, and a payload that is a good sample under the wrong name is not the same news as a payload that is mid-audio. The reason names **every** field that disagrees rather than the first, because what they disagree about together is the diagnosis. The four rate refusals keep `mismatch=False`: on all four the id, the flag and the name agree with the directory, so those *are* the files their entries placed, with one field unusable.

**The declared name and the generation reach the parser through `AkaiBackend.parse_sample`.** Both are the directory's knowledge, not the payload's, and the shared extract path may not learn what an AKAI type byte means ([ADR-0003](0003-brand-neutral-pluggable-backends.md)). `Emu3Backend` and `RolandS7xxBackend` already carry parameters across this way for the same reason.

## Alternatives rejected

**Close #23 as not reproducing and ship nothing.** Defensible on the counts — the check adds no behaviour on this collection, and the S3000 header could have been a separate deliverable. Rejected because the two are one piece of work: the header length was found by ruling out the check's false-positive case, and the 31 samples the flag relaxation admits are only safe to admit because the identity check is there. Shipping a check that certifies payloads agree with their entries while 13 451 of them are read 42 bytes early would have been the worse outcome of the two.

**Drop the name comparison, since it catches nothing the other three miss.** Numerically it is dead weight: 60 fires, 0 unique. Rejected on what it asks rather than on what it caught. The other three ask whether the payload is *a* sample; only this one asks whether it is *this* sample, which is the entire failure class #23 named and the one [#25](https://github.com/bmxcode/samplerdisc/issues/25) will raise when a short image's partitions are recovered and a displacement lands on a real header rather than mid-audio. It costs one string comparison. The honest form of this is not to remove it but to say plainly that it has no positives on real data and is exercised only synthetically — which the test docstring and the format doc both do.

**Choose the header length by solving `size == words × 2 + H` at runtime.** The same identity that verifies the rule, used to apply it, and it would need no directory knowledge in the parser. Rejected for turning a field the disc *states* into arithmetic between two structures — the register [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) settled — and because it answers nothing exactly when it is needed: on the 60 damaged payloads neither length solves it, so the fallback would be the generation bit regardless. A rule that consults the declared field only when it cannot be checked is worse than one that consults it always.

**Branch on the id and valid bytes, as the format doc advised.** Rejected on measurement: `0x80` appears on 42 989 samples at 150 and 13 410 at 192, and the id is 3 on both. The advice predates anyone having counted, and it is corrected in the format doc rather than left standing beside the new text.

**Sniff bytes 150–191 for the header's own pattern.** It is distinctive and constant across samples. Rejected for the reason [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md) refused scanning for the partition header: a pattern that sample data can reproduce is not evidence, and here there is a declared field that is right 13 451 times out of 13 451.

**Add `0x81` and `0x9c` to a set of accepted valid bytes.** One line, and it admits exactly the 31. Rejected as a table of two observed values standing in for what the field is. A third disc with a third low-bit combination would be discarded silently, and the discarding would look like damage.

**Refuse only, and never relax the flag.** The conservative reading, and it keeps throwing away 31 samples whose every other field is correct — including 29 consecutive `1015 E.PF`, `1051 VL+PIZ` and `1054CHO HARP` entries that are plainly a library's own multisamples. Rejected: "the byte is not exactly 0x80" was never a finding, it was an assumption from three reference discs.

**Write a mismatched payload out under the payload's own name instead of the entry's.** Recovers audio rather than refusing it, and on a displaced image the payload's name is arguably the truer one. Rejected on the data: the name does not decode at all on 54 of the 60, and decodes to `0C0B0B0B0A0`-style noise on the other six. There is no name there to prefer.

**A `--force` flag to extract mismatches anyway.** Rejected as an option nothing on the shelf would use: all 65 are unusable, and an escape hatch whose only effect is to write 65 known-bad files is a maintenance cost with no user.

**A third result shape beside `Extracted` and `Skipped`.** The strongest signal, and it was seriously considered because [ADR-0012](0012-a-probe-must-confirm-a-file.md)'s lesson is that an unexplained absence is itself a failure signature. Rejected because a mismatch *is* a subset of not-written: every consumer — `cli`, `batch`, the manifest — would grow a branch to say something the existing shape says with one boolean, and `Skipped.duplicate` established that boolean's precedent one deliverable ago.

**Fix `Alpha Dance II` and the other two discs' mid-partition damage here.** 25 files, and the shape is now understood. Rejected as a different deliverable: recovering them means locating a volume's blocks by something other than the chain the map declares, which is the search [ADR-0022](0022-a-volume-is-explained-by-the-allocation-map.md) and [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md) both refused. It gets an issue.

## Consequences

**Good, and the headline.** 13 451 samples on nine discs stop carrying 42 bytes of header at the front of their audio, stop losing their last 21 frames, and get their loop points back in alignment. Every WAV from `AKAI.S3000.Sound.Library.1`–`7`, `East Connexion Piano` and `AMG - Now CD-Rom for (AKAI)` changes. Anyone who extracted those discs should do it again.

**Good.** 31 samples that were being discarded as damage now extract. The collection goes from 89 125 samples to **89 156**, AKAI from 56 394 to **56 425**, and AKAI stereo joins from 14 449 to 14 461 — the extra pairs completing because both halves are now present.

**Good.** The audio is verified against an independent structure per sample: `entry.size == words × 2 + header_len` holds on **56 425 of 56 425** accepted payloads, and `tests/test_discs.py` asserts it, along with each WAV's PCM being the disc's own bytes from that offset. The suite had nothing of the kind for AKAI — the E-mu and Roland paths both did — which is why a 42-byte slip survived four deliverables in a green suite.

**Good.** The whole-collection payload check is re-established rather than inherited: 70 of 70 discs, **89 156 WAVs, zero whose audio is not on the disc it came from**. That claim was true before this change against the wrong offset, which is precisely what made it worthless.

**Bad, and stated plainly.** #23 was open for a day and describes a bug that was not there. The nine files it names were being refused the whole time, with a message — "payload does not start with an AKAI sample header" — that was true and told nobody which of four things was wrong or that a directory entry was involved at all. That is the part worth keeping from the issue: the refusal existed and said nothing useful, so nobody checked whether it existed.

**Bad.** The name comparison ships with zero positives on real data. It is the reason the deliverable was requested and it is the least load-bearing line in it, and no amount of measurement can change that until a disc arrives whose displacement lands on a header. It is exercised synthetically and the test says so.

**Watch for.** A disc whose type byte's high bit does not mean the generation. The bit is doing more work now than it was: before this it named a file `.s3s` rather than `.s1s`, which is cosmetic, and now it decides where the audio starts. A disc that sets it wrongly would produce samples 42 bytes off in one direction or the other — and the word-count assertion in the suite is what would catch it, per disc, which is why that assertion is over every AKAI disc rather than over the pinned eight.

**Watch for.** The 60 payloads on complete-looking images. `Alpha Dance II`, `Library.1` and `Library.3` are damaged inside a partition the table calls whole, so "declared equals present" is not a clean bill of health and must not start being read as one.
