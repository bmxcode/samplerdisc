# ADR-0040 · Sound Designer II is decoded from the data fork, with parameters from the resource fork

**Status:** accepted · 2026-09-03

## Context

D32 read the SampleCell discs as HFS and converted their AIFF, but left the 24 `Sd2f` (Digidesign Sound Designer II) files on `sonic-images-v2` listed and unread ([ADR-0039](0039-samplecell-is-read-as-hfs-behind-an-apple-partition-map.md), [issue #72](https://github.com/bmxcode/samplerdisc/issues/72)). ADR-0039 deferred them on a stated premise: that SDII "keeps its audio in the HFS *resource* fork," a separate reverse-engineering effort, and that shipping an unverified resource-fork PCM reader would be the silent-noise failure this project refuses.

That premise is wrong, and establishing so is most of this deliverable. Read against the disc with `machfs` and cross-checked against libsndfile's `src/sd2.c` (the canonical open-source SD2 decoder): each of the 24 `Sd2f` files has a **large data fork** (847 KB – 1.29 MB) of plain **big-endian, interleaved PCM** — which the backend already read as every file's data fork — and a **tiny 1184-byte resource fork** that holds only metadata, in three `STR ` resources (id 1000 = sample size in bytes, 1001 = rate as a float string, 1002 = channels). All 24 are uniformly 16-bit, 44 100 Hz, stereo. So the audio was reachable all along; what was missing was three parameters in a fork nothing read.

This also corrects a smaller premise from the issue: the resource-fork logical length is `filRLgLen` at file-record datum offset **36**, not 40 (offset 40 is `filRPyLen`, the block-rounded physical length). `filRExtRec` at 86 was right.

## Decision

Decode SDII, and hold it to the same oracle bar as every other format here. The audio is the **data fork**, carried to WAV by reversing the bytes within each 16-bit sample (big-endian to little-endian) — the same and only change AIFF gets, byte order and never sample values ([ADR-0011](0011-the-deliverable-is-daw-ready-wav.md), [ADR-0024](0024-the-aiff-twin-is-converted-and-deduplicated.md)). The rate, width and channel count come from the resource fork's `STR ` resources. SD2 stereo is already interleaved, so unlike the E-mu backends no de-planing is needed.

The work sits where the three-layer design puts it ([ADR-0003](0003-brand-neutral-pluggable-backends.md)):

- `fs/hfs.py` gains the ability to resolve a file's **resource fork** (`filRLgLen`/`filRExtRec`, fork type `0xFF` in the extents-overflow key) and hand its bytes over through an optional `read_resource_fork`, reached by `getattr` the way `parse_sample` is — one backend needs it, so it does not widen the shared `Backend` protocol. `read_file` still returns the data fork, so the D32 AIFF path and its `machfs` oracle are untouched.
- A new `sample/sd2.py` reads the resource map, pulls the three parameters, and byte-swaps the data fork to little-endian PCM, refusing anything but 16-bit with a reason and degrading to a reasoned skip on a malformed fork rather than crashing ([ADR-0012](0012-a-probe-must-confirm-a-file.md)).
- `extract.py` routes the `sd2` kind through a `_convert_sd2` that reads both forks, mirroring `_convert_ebl`.

**Loop points and a root key are not read.** The resource fork carries Digidesign region/loop resources (`sdLL`, `sdDD`), and `sdLL` on the first file even looks like a loop (two in-range frame values) — but there is no open decoder or a render to verify one against, so it is left out rather than guessed ([ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md)). That is the follow-up a disc with a confirmable loop would reopen.

The oracle is total and needs no Mac fork magic. `machfs` returns the data fork byte-for-byte (the D32 oracle, now extended to the resource fork as well), and because our audio is a verbatim byte-swap of the data fork, our little-endian PCM swapped back to big-endian must equal `machfs`'s `obj.data` exactly — the "payload is the disc's own bytes" check AKAI uses. So the reader is not shipped on faith, which is the condition ADR-0039 set for building this at all.

## Alternatives rejected

**Keep the resource-fork-audio theory and read audio from the resource fork** — what ADR-0039 and issue #72 assumed. Rejected: it is contradicted by the disc (the data forks are the audio, the resource forks are 1184 bytes) and by libsndfile. Inverting `read_file` to return the resource fork, as issue #72 proposed, would have thrown the audio away.

**Shell out to `soundfile`/libsndfile as the decoder.** libsndfile reads SD2, so it is tempting as both decoder and oracle. Rejected: it reads the resource fork only through a real Macintosh named fork, which is macOS-only and fragile, and it adds a runtime dependency for one corner of one disc — against the one-module-per-format principle. It remains available as a bonus cross-check, not the gate.

**Decode the SDII loop from `sdLL` now.** Rejected: no verification oracle, and an off-by-a-frame loop opens, plays, and reports nothing wrong — the exact failure [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) guards against. Deferred against a specimen whose loop can be confirmed.

## Consequences

**Good.** The 24 `Sd2f` files on `sonic-images-v2` now convert to stereo 44.1 kHz WAV; the disc goes from 288 sounds to 312. The correction is recorded where the wrong premise lived — `docs/formats/hfs.md` and ADR-0039 — so the next session inherits the fact, not the mistake. The resource-fork reader is general (it is the same map every Mac file uses), so a later format that needs it starts from here.

**Bad.** The decoder's `parse` takes two forks, not one, breaking the single-payload shape every other `sample/` module has. That is inherent — the audio and its parameters genuinely live in different forks — and it is documented at the top of the module rather than hidden.

**Watch for.** A SampleCell disc whose SDII files are not 16-bit, or are mono, or carry a loop worth reading. The first two are handled (mono via the channel count, non-16-bit refused with a reason); the loop is the deferred follow-up.
