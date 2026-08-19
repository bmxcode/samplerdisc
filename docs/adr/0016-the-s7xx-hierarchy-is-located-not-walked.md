# ADR-0016 · The S-7xx object hierarchy is located, not walked

**Status:** accepted · 2026-08-20

## Context

A Roland S-7xx disc has five object classes — volume, performance, patch, partial, sample — each with its own directory at a fixed block and its own parameter records elsewhere. Samples live in **one flat, global directory**: 890 entries on `lcdp05`, 1 972 on `l-cdx-01`. Nothing in that directory says which volume a sample belongs to. The grouping exists only in the chain above it.

Both ends of that chain are decoded. Volume parameter records at block 2156 carry a `0xFFFF`-terminated list of u16 performance indices at `+32`. Partial parameter records at block 3756 are 128 bytes with four 16-byte slots, each opening with a u16 sample index or `0xFFFF` — on `lcdp05`, partial `STR:Mute Vln MAA` references sample 0, `STR:Vln Mt1 G_4`, which is the muted violin it is named for. The **performance and patch records in between are not decoded.**

So a `Volume` could be one S-7xx volume with its samples gathered through four record formats, two of which are guesses. Or it could be the disc.

The deliverable is DAW-ready WAV ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)), not a playable multisample instrument. The hierarchy is exactly the part a *sampler* needs and a WAV does not: key ranges, layers, part assignments. What a WAV needs — root key, loop points, rate — is in the sample's own parameter record, which is decoded.

## Decision

**One `Volume`, named from the `ID<n>:` label at `0x100`, holding every sample on the disc.** The hierarchy is recorded in [../formats/roland-s7xx.md](../formats/roland-s7xx.md) as located-not-walked, with the two decoded ends written down, so a later deliverable starts from evidence rather than from a hex editor.

## Alternatives rejected

**Walk volume → performance → patch → partial → sample and emit one `Volume` per S-7xx volume.** The right answer for a user browsing a disc, and the grouping is genuinely there. Rejected on the project's standing preference for one verified format over two guessed ones: it needs the performance and patch records, which are located and undecoded, and its failure mode is a *plausible-but-wrong grouping* — samples filed under the wrong instrument, which reads as a slightly odd library rather than as a bug. The same argument as [ADR-0015](0015-locate-banks-by-signature.md) for the E-IV interior.

**Group by the four-character name prefix.** `STR:`, `BRS:`, `GTR:`, `KIK:` are right there in every name and cost nothing to split on. Rejected because it is a name heuristic standing in for a structure that actually exists, and on the disc that would most benefit it is simply wrong: all 13 of `lcdp05`'s volumes are `STR:`, so it yields one group and calls it thirteen. Where the prefix is useful it is already in the filename.

**Emit one `Volume` per S-7xx volume with no files, plus a flat one holding the samples.** Shows the structure honestly without guessing the mapping. Rejected because a volume with no files and no explanation is the exact signature the disc-backed suite treats as a broken probe ([ADR-0012](0012-a-probe-must-confirm-a-file.md)), and giving thirteen of them a note apiece would make every Roland listing mostly noise.

## Consequences

**Good.** Every sample on the disc comes out, named as the disc names it, with its own root key and loops. Nothing depends on an undecoded record.

**Good.** The finding is preserved rather than discarded. The volume→performance list and the partial→sample slots are written down with the evidence that identified them, which is most of the remaining work for whoever wants the grouping.

**Bad.** A user with a 1 972-sample disc gets 1 972 files in one directory. The four-character prefix in each name is the only grouping they get, and it is a prefix rather than a directory.

**Watch for.** The temptation to decode the middle two records *just enough* to group. The sample layer already showed what that costs: the parameter record's field 32 looked like a length, behaved like one on 6 363 of 6 392 samples, and silently emitted 26-byte WAVs on the rest. A patch record that is right most of the time would misfile samples with nothing reporting it.
