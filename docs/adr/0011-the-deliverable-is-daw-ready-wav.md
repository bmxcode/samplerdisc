# ADR-0011 · The deliverable is DAW-ready WAV, not a sampler format

**Status:** accepted · 2026-08-18 · supersedes [ADR-0010](0010-build-the-instrument-layer-ourselves.md)

## Context

[ADR-0010](0010-build-the-instrument-layer-ourselves.md) chose to build the instrument layer — programs and keygroups out to SFZ, DecentSampler, MPC — rather than hand that off to [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss). It framed the goal as *one tool takes a disc all the way to a playable instrument*.

That framed the goal wrongly. The point of this project is to free these sounds from the hardware they were trapped in, so they can be used **independently of any sampler at all** — dragged into a DAW, dropped on a track, loaded by whatever the user already owns. SFZ and MPC keygroups are sampler formats. Converting into one trades an obsolete cage for a current one, and lands us competing on a destination-format list where ConvertWithMoss is far ahead and the race is unwinnable.

The sounds themselves are already the universal format. AKAI sample payloads are signed 16-bit little-endian PCM — exactly what a WAV data chunk holds.

## Decision

The deliverable is **uncompressed WAV that works everywhere**. No sampler-specific destination format ships.

Where a disc carries information that makes a WAV more useful on its own — loop points, root key, fine tuning — it goes into the WAV itself, using standard RIFF chunks (`smpl`, `cue `, `LIST`/`INFO`) that any DAW or sampler may read and any may ignore. That is the opposite of a sampler format: it makes the file self-describing without binding it to a vendor.

Programs and keygroups are read far enough to inform naming and to be listed. They are not converted.

## Alternatives rejected

**Build the instrument layer ourselves ([ADR-0010](0010-build-the-instrument-layer-ourselves.md)).** Gives a user one tool from disc to playable instrument. Rejected: it re-cages the samples, duplicates a mature project, and the multisample destination list is a treadmill. Superseded rather than reversed on new information — the information was the same, the goal was stated more precisely.

**Plain WAV with no metadata chunks at all.** The purest reading of "works everywhere", and provably safe. Rejected because the loop points and root key are on the disc, are lost forever if dropped, and cost nothing to carry: a DAW that does not read `smpl` sees an ordinary WAV. Throwing that away is not neutrality, it is data loss.

## Consequences

**Good.** The scope is small, finishable, and hard to argue with. Output is bit-identical PCM plus standard metadata. No competing with ConvertWithMoss, which stays the recommendation for anyone who does want an SFZ — and `export-iso` still feeds it.

**Bad.** A user who wants a playable multisample instrument needs a second tool. Accepted: that tool exists, is good, and we point at it.

**Consequence for the code.** The stdlib `wave` module cannot write a `smpl` chunk, so WAV output becomes a small RIFF writer of our own. That stays well inside stdlib-only ([ADR-0001](0001-pure-python-stdlib-only.md)) and keeps the data chunk a byte-for-byte copy.

**Watch for.** Any pull toward "just a little" instrument support — an SFZ exporter because the key ranges are right there. That is this decision being reversed by accident.
