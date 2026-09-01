# ADR-0036 · The `.KRZ` bank is read as objects, its audio big-endian, verified against mpc2emu

**Status:** accepted · 2026-09-02

## Context

D28 ([ADR-0035](0035-kmsi-is-fat16-read-behind-the-kurzweil-signature.md)) read the Kurzweil `KMSI` FAT16 filesystem and listed its `.KRZ` banks, and deliberately stopped there: a `.KRZ` is not a bare sample but a big-endian bundle of objects, and cracking it was left as the D3-to-that-D2 ([#63](https://github.com/bmxcode/samplerdisc/issues/63)). This is that deliverable — turning a bank into WAV.

Reverse-engineering the two `Gigapack I & II (Kurzweil)` discs established the bank interior, written up in [docs/formats/kurzweil-krz.md](../formats/kurzweil-krz.md): a `PRAM` header, a directory of length-prefixed objects (programs, keymaps, samples), and one shared pool of 16-bit **big-endian** PCM the sample objects address by absolute word offset. Three facts shaped the reader. A sample's audio length is not stored — its header's `sampleEnd` is the *loop* end — so it is recovered from the next sample's offset in the pool. Its rate is a nanosecond period, not a frequency. And a Kurzweil sample object, unlike an E-mu one, carries a root key.

Two questions then had to be answered. First, how far the sample layer reaches into the bank: a `.KRZ` also holds programs and keymaps, which are instrument definitions. Second, and unusually for this project, how to *verify* the decode. There is no publisher render of these banks as there was for EBL ([ADR-0033](0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md)); the plan was to hunt for an external oracle first and fall back to internal consistency, and the hunt found one — [lentferj/mpc2emu](https://github.com/lentferj/mpc2emu), an independent Python reader of the same K2000 object format, whose `KRZ_FORMAT.md` is corpus- and hardware-confirmed.

## Decision

**Read the `.KRZ` as its object structure — a bank is a volume, its sample objects are the volume's files — decode each sample's big-endian PCM pool slice to a WAV with its own rate, root key and loop, and verify the decode byte for byte against mpc2emu.**

1. **A bank is a volume; its sample objects are files.** `fs/kurzweil.py` walks a bank's object directory and yields one `File` per sample (`kind="sample"`), mirroring the E-IV `FORM/E4B0` bank exactly ([ADR-0032](0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)): the filesystem layer enumerates, the sample layer decodes one payload. The extent, rate, root and loop travel on the `File`, read from the directory, never sniffed from the audio.

2. **The PCM is big-endian, so it is byte-swapped for the WAV** — the one sample format the tool reads that is not little-endian, carried the way an AIFF is and for the same reason ([ADR-0024](0024-the-aiff-twin-is-converted-and-deduplicated.md), [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)). No sample value is otherwise altered.

3. **A sample's audio extent is the next sample's start, not its own stored end.** The header end is the loop end; using it would truncate every looped sample at its loop. The next start is a hard ceiling never read past, and loop points are clamped to it rather than trusted.

4. **The root key is read and written, because the object carries one.** This is where Kurzweil differs from E-mu, whose sample record has no root and takes the neutral 60 ([ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md)). The rate is decoded from the stored nanosecond period and snapped to the nearest standard rate within ±2 Hz.

5. **Stereo is decoded both ways it occurs.** A single two-channel object is planar (whole left, whole right) and is interleaved here; a pair of `\x7f`-named mono objects is joined by the existing stereo joiner ([ADR-0017](0017-the-stereo-side-marker-is-a-character-class.md)). Both yield a two-channel WAV.

6. **Programs and keymaps are not converted; the whole `.krz` is kept.** They hold the key ranges and envelopes a WAV cannot, which is [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss)'s job ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)). `--keep-originals` writes the whole bank out — one `program` file per volume — because ConvertWithMoss reads `.KRZ` directly; the raw per-sample pool slice, a headerless fragment, is not kept.

7. **The decode is verified byte for byte against mpc2emu.** Across a spread of twelve CD 1 banks, every sample this backend decodes is one mpc2emu decodes to identical PCM and the same rate — 548 of 548 — matched on content so mpc2emu's own naming of unreferenced samples cannot cause a spurious miss. An env-gated test reproduces it against a checkout; a self-contained check that every rate is a plausible, mostly-standard value runs without it.

## Rejected

- **Read the pool as a flat audio file.** It is one 600 MB blob of concatenated samples at mixed rates; without the object directory there is no sample, no rate, no loop and no boundary. This is the whole reason D28 stopped at the bank.
- **Trust the header's stored end as the audio end.** It is the loop end, so every looped sample would be cut at its loop, losing the decay tail it plays past it. The next-start recovery is exact because the pool is gapless.
- **Read the rate as a frequency at the period's offset.** It is a nanosecond period; read as a 16-bit frequency it is garbage (1130, 45351), which is exactly the wrong turn taken before the format was pinned. `1e9 / period`, snapped, is the rate.
- **Give every WAV the neutral root key of 60, as E-mu does.** E-mu's record genuinely has no root; Kurzweil's does, and discarding it would throw away a real, useful value the disc hands us.
- **Ship on internal consistency alone.** The plan was oracle-first, and an independent reader of the same format existed. A byte-for-byte agreement with mpc2emu is far stronger evidence than "the extents tile the pool", and it was available, so it is what the decode rests on.
- **Defer stereo, as the unverified EBL interleave was ([#57](https://github.com/bmxcode/samplerdisc/issues/57)).** There the interleave was a guess with no render to check; here the planar layout is documented and the oracle confirms it channel for channel, so there is nothing to defer.
- **Convert the programs and keymaps to a playable instrument.** That is ConvertWithMoss's job, and it reads `.KRZ`; keeping the bank whole feeds it better than any lossy re-encoding of ours ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)).

## Consequences

**Good.** The two Gigapack discs now convert: 3 846 samples from CD 1 and 6 637 from CD 2, each a WAV with its rate, root key and loop, stereo joined both ways it is stored. The decode is pinned to an independent reader, not just to itself. `--keep-originals` hands ConvertWithMoss the `.KRZ` for the instruments this tool deliberately does not build.

**Bad, accepted.** The evidence is two discs of one publisher plus one external reader; a K2000 authored by different hardware or software could exercise object shapes these do not (a compacted keymap, an 8-bit sample). The reader skips what it cannot confirm rather than guessing, so the failure mode is a listed-but-not-converted sample, not a wrong one.

**Watch for.** A multi-header *mono* group (one object, several samples at different root keys) exists in the wild but not on these two discs; the reader handles it by emitting one WAV per loaded header, but that path is exercised only synthetically. A bank whose directory somehow exceeds the half-megabyte enumeration prefix is re-read in full; no bank here comes close.
