# ADR-0037 · A fragmented E-mu `FORM/E4B0` bank is read along the block-2 FAT chain

**Status:** accepted · 2026-09-02

## Context

[Issue #67](https://github.com/bmxcode/samplerdisc/issues/67) asked whether the real FAT at block 2 of every EMU3 master is the actual allocation mechanism that the reader's per-disc `address == unit × start + bias` fit approximates — and, if so, whether addresses should be resolved from it instead of from the regression. The fit is the least principled part of the EMU3 reader: it is measured from the very headers it then places, needs two or three agreeing banks, and rejects a negative-address solution by hand ([ADR-0015](0015-locate-banks-by-signature.md), [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md)).

The FAT is real, and it was measured against all ten reference discs. It occupies blocks `2 .. OFF_FOLDER_BLOCK-1` (a variable extent — the folder table's block moves per disc), is a flat array of little-endian u16 cluster-chain entries with `fat[0] = 0x8000` reserved and `0x7FFF` as the end-of-chain marker, and a directory entry's `start` field is a cluster index. Its cluster size **equals the `unit` the fit measures** on every disc, and `block(cluster) = unit × cluster + bias` — so the fit's own formula *is* the block address of a cluster. The fit and the FAT agree to the byte on every located bank of every disc.

Two findings decide the shape of this record.

**The cluster size is not derivable.** `protozoa` uses 1 MiB clusters where its FAT ceiling would fit 256 KiB comfortably (502 clusters against a ceiling of 1 023), so mpc2emu's "smallest size that fits" rule is wrong here. The cluster→byte map has two unknowns — the cluster size and the data-region start — which is exactly the two-anchor solve the fit already does. The FAT re-expresses the fit; it cannot eliminate the measured constant.

**The FAT recovers real audio the linear model cannot.** Nine of the ten discs are wholly contiguous, and so is every `FORM/E4B0` bank but one. The exception is `eiv-vitous`'s `CES 1`, whose chain is three runs — clusters 640–658, 620–634, 579–583. The current reader reads a `FORM` bank contiguously from the image, so it stops at the first break and lists **12** samples; the bank actually holds **20**, the eight in the tail (`CES E_2 2` … `STR:VcsD_5 2`, a velocity layer's upper half) stranded past the fragment boundary. A linear address can name only the first cluster; a fragmented file's later bytes are unreachable without the chain.

## Decision

**Read a `FORM/E4B0` bank whose FAT chain is fragmented by gathering it along that chain; read every other bank exactly as before.** The reader fits the cluster geometry as it always has, then consults the block-2 FAT:

- **A contiguous bank keeps the current image-based read, byte for byte.** `_fat_contiguous` gates it, and a contiguous bank's bytes are identical whether gathered along the chain or read straight from the image — so the FAT changes nothing it does not have to. Nine discs, and every `FORM` bank but `CES 1`, take this path.
- **A fragmented bank is gathered from the clusters the FAT names**, and its samples are `embedded` slices of that gathered buffer — the same route [ADR-0036](0036-the-krz-bank-is-read-as-objects-and-verified-against-mpc2emu.md) uses for a Kurzweil sample that is a window into a bank rather than a file the disc placed. `read_file` re-gathers the chain (cached) and slices, so a sample whose PCM straddles a fragment boundary is read from the right bytes.
- **The block-2 FAT is asserted as the independent corroboration of addressing.** A disc-backed test walks the FAT and requires every located bank/base to begin a real chain whose first cluster's byte address equals the located address, and pins the per-disc cluster size. The fit is measured from the headers it places; the FAT is a different structure that agrees, which is the external check [CLAUDE.md](../../CLAUDE.md)'s "verify a constant against a real disc" rule wants.

`CES 1` goes from 12 samples to 20; the eight recovered are mono one-shots, so `eiv-vitous`'s loop and stereo counts do not move, only its sample count (852 → 860) and its payload digest. This is the [ADR-0032](0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md) / D25 shape again: a bank that read empty now reads, and nothing else changes.

## Alternatives rejected

**Replace the fit end to end with FAT resolution.** The issue's headline proposal. Rejected on the evidence: the FAT reproduces the fit exactly on every disc for *first-cluster location*, because the fit's formula is the cluster→block map, so a wholesale replacement changes no address — and it cannot remove the per-disc unit, because `protozoa` proves the cluster size is not derivable. It would rewrite the shared record parser's addressing for no output on nine discs and one fragmented bank's recovery on the tenth, trading real regression risk for nothing the narrow change does not already deliver.

**Derive the cluster size from the FAT ceiling** (mpc2emu's `_choose_cse`). Rejected: `protozoa` uses 1 MiB where 256 KiB fits, so the smallest-that-fits rule is wrong on our corpus. The size is a property of the mastering generation, measured per disc, not computed.

**Gather every bank along its chain, not only the fragmented one.** Uniform, and it would make the reader correct against a fragmented EIII bank too. Rejected: every EIII bank and every flat E-IV bank on all ten discs is contiguous, so this rewrites the shared read path — the highest-risk code — for zero output, and the contiguous read has to be preserved anyway to keep the `FORM` overrun-past-declared-size behaviour ([ADR-0032](0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)) byte-identical. The chain path is confined to the one place a real disc needs it.

**Read `CES 1` contiguously and note the eight lost samples.** The conservative reading, in the spirit of the deferred displaced-partition cases ([ADR-0028](0028-a-displaced-partition-is-anchored-quantised-and-floored.md)). Rejected because, unlike those, the recovery is *exact*: the FAT names the clusters, the samples parse under the same gates as the twelve already read, and they carry sensible names and rates. Leaving them noted would withhold audio the disc plainly offers and the FAT plainly locates.

**Reduce the fit to a single anchor by trying each candidate cluster size against the FAT.** More principled — it would drop the two-agreements requirement. Rejected as unnecessary and riskier: the fit is exact on every current disc, the cluster geometry it produces is what the FAT is then read with, and a disc with only one bank (where one anchor would help) is not in hand. Deferred against a specimen that does not yet exist.

## Consequences

**Good.** Eight real samples on `eiv-vitous` are recovered, and the mechanism is exact rather than heuristic: the FAT names the clusters and the samples parse like any other.

**Good.** Addressing now has an *independent* witness. The fit was self-referential; the block-2 FAT is a different structure that reproduces every located address on every disc, asserted by a disc-backed test, and it is the authority when a file is fragmented, which the linear model cannot represent.

**Good.** The blast radius is one bank. Every contiguous bank on every disc takes the unchanged image-based path, so nine discs and every `FORM` bank but one are byte-for-byte what they were — the payload digests prove it.

**Bad.** The per-disc cluster size is still a measured constant, not derived — `protozoa` closes that door. The FAT explains *why* `unit × start + bias` works and corroborates it, but does not remove it.

**Watch for.** A fragmented EIII or flat E-IV bank. None exists on any current disc, so those paths stay contiguous; one would be read short exactly as `CES 1` was before this record, and the fix would be to extend the chain gather to them — visible as a bank that lists fewer samples than its run declares, not as wrong audio.
