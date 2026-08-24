"""E-mu EIII/ESI/E-IV sample payloads. See docs/formats/emu3.md.

The audio needs nothing done to it. The filesystem layer already located the
record and read its rate, and the payload that follows the 92-byte header is
signed 16-bit little-endian PCM -- the same thing a WAV data chunk holds. So
this module converts nothing (ADR-0011).

What it does decode is the record's **eight-pointer block**: a start, an end, a
loop start and a loop end, per channel, as byte offsets from the record's own
start. Those become the WAV's smpl chunk. There is no root key anywhere in the
92 bytes -- see ``pitch`` below and ADR-0025.

The same block declares a **channel count**, and where it declares two the
payload is a *block* split -- all of the left channel, then all of the right,
not interleaved. Read as one mono stream that is a file twice as long as the
sound, which is what this project shipped for 2 656 of the E-mu samples until
D18 (2 843 of 19 371 under D21's record extent). The two halves are
interleaved here, in the sample layer, so what ``pcm`` holds is what a WAV data
chunk holds either way (ADR-0026).

The endianness is worth a note, because it was got wrong first. Sampling this
data at 2048-byte sector boundaries makes it read as big-endian, convincingly
and repeatably. It is not: the sample payload starts at an odd byte offset, so
a sector-aligned probe reads every 16-bit word one byte out, which swaps the
apparent byte order. Read from the record's own start and it is little-endian.
"""

from __future__ import annotations

from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.stereo import interleave


class NotASample(_NotASample):
    """The payload is not usable as audio."""


#: A record's audio begins immediately after its 92-byte header, so the pointer
#: set that describes it opens with exactly this. The other set is its mirror,
#: or zeroed on a record declaring a single channel.
DATA_START = 92

#: An end pointer names the first byte of the *last* word rather than one past
#: it, so the extent it closes runs two bytes further. ``END_POINTER_BIAS`` in
#: fs/emu3.py is the same constant, used there to close the record itself.
END_POINTER_BIAS = 2

#: A stereo payload splits into two equal blocks, so it holds a whole number of
#: frames on both channels only when it divides by four. Every one of the 2 843
#: records the gate below selects does; the check is here because a payload
#: that did not would be split half a sample out and sound like tape hiss.
STEREO_ALIGNMENT = 4

#: Shorter than this and it is not a loop worth writing. The guard is the one
#: docs/formats/roland-s7xx.md records the need for: without a floor on length
#: a loop metric finds pairs a few frames apart in a fade-out and calls them
#: seamless, because the signal there is silent rather than matching.
MIN_LOOP_FRAMES = 64

#: A loop that spans the whole declared extent is the format's "no loop": the
#: sampler fills the pointers with the sample's own bounds when nothing set
#: them. Emitting it would tell a DAW to loop the entire file, which is not
#: what the disc means and is worse than saying nothing.
#:
#: The bounds are written **inset by a small fixed amount at both ends**, not at
#: exactly the record's start and end -- ``loop_start = start + C1``,
#: ``loop_end = end - C2`` for a per-disc constant of a handful of bytes:
#: ``ditto-drums`` writes ``(12, 12)`` on 898 of its records (frame 6 to six
#: frames from the end), the EIIIX discs ``(4, 4)``, `esi32-gm` and `protozoa`
#: ``(12, 10)``. So the guard allows the same slack at the **start** as at the
#: end. Measured against all ten reference discs, the whole-extent population is
#: a filled-in "no loop" and not a real loop that happens to span the sample:
#: 70-100 % of it ends in silence (the loop end sits below 15 % of the sample's
#: peak) where a real loop does so only 13-33 % of the time, its bounds are the
#: record's own extent inset by that fixed constant where a real loop's start is
#: at an arbitrary musical position, and it carries a uniquely-splicing loop
#: point on 0.2-11 % of records where a real loop does on 33-56 %. The join and
#: uniqueness are the shape/join oracle of docs/formats/emu3.md; the end-energy
#: is what carries the discs the oracle has no power on -- a whole-extent loop
#: has almost no audio before its start, so the windowed correlation cannot
#: score it (ADR-0030).
FULL_EXTENT_SLACK = 16

#: The channel pointer sets, in the order they are tried.
_SETS = (
    ("start_l", "end_l", "loop_start_l", "loop_end_l"),
    ("start_r", "end_r", "loop_start_r", "loop_end_r"),
)


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive here, as it is for AKAI and
    Roland; the WAV writer makes it inclusive as the RIFF spec requires."""

    start: int
    end: int


@dataclass(frozen=True)
class Emu3Sample:
    name: str
    rate: int
    frames: int
    pcm: bytes
    #: Always None. The 92-byte record states no root key: no byte in it tracks
    #: the note written in the sample's own name on 1 741 named records of
    #: `esi32-gm` or 917 of `eiiix-1` -- the best constant-offset match is 8%
    #: and 6%, which is chance. The E3 keeps root key in its preset, and
    #: presets are not read. Kept as a field, and None, so that ``extract``
    #: treats this format exactly as it treats an AIFF with no INST rather
    #: than through a special case (ADR-0025).
    pitch: int | None = None
    loops: tuple[SampleLoop, ...] = ()
    #: 2 where the record's pointer block declares two channels and its own
    #: extents agree with the split, 1 otherwise. ``pcm`` is interleaved to
    #: match, and ``frames`` counts frames rather than samples, so duration is
    #: ``frames / rate`` on either (ADR-0026).
    channels: int = 1

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def parse(
    payload: bytes,
    rate: int,
    fallback_name: str = "",
    pointers: dict[str, int] | None = None,
) -> Emu3Sample:
    """Wrap an already-located payload. Raises NotASample if it is unusable."""
    if not payload:
        raise NotASample("no data on disc")
    pointers = pointers or {}
    if _is_block_split(pointers, len(payload)):
        half = len(payload) // 2
        # The first block is the left channel -- see _is_block_split.
        pcm = interleave(payload[:half], payload[half:])
        channels, frames = 2, len(payload) // 4
    else:
        channels, frames = 1, len(payload) // 2
        pcm = payload[: frames * 2]
    if frames == 0:
        raise NotASample("zero-length sample")
    return Emu3Sample(
        name=fallback_name,
        rate=rate,
        frames=frames,
        pcm=pcm,
        channels=channels,
        loops=_loops(pointers, frames),
    )


def _is_block_split(pointers: dict[str, int], size: int) -> bool:
    """Whether this record declares two channels for a payload of ``size``.

    Three conditions, all read off the record rather than measured off the
    audio, and the third is the one that took measuring to arrive at.

    ``start_l`` opens the audio, ``start_r`` opens it again half a payload
    later -- that pair is the channel count, and reading a payload it declares
    as one mono stream is what concatenated the two channels into a
    double-length file (ADR-0025 found this; ADR-0026 acts on it).

    **``end_l`` must close the left block exactly where the right one opens.**
    2 721 records across the seven reference discs satisfy the first two
    conditions and 65 of them fail this one -- 19 on `protozoa`, 40 on
    `eiiix-1`, 6 on `eiiix-2` -- declaring a left channel that overlaps the
    right block or stops short of it. They are not stereo: their halves score
    0.01 on fine structure and 0.01 on best-lag correlation, which is the
    negative control of two unrelated records, while the 2 843 that pass score
    with the known-true stereo pairs ADR-0017 joins by name. Six of
    `protozoa`'s are identified exactly: the first half of each is, byte for
    byte, the whole of a one-channel record of the same name in another bank,
    so the payload is twice the sound and ``start_r`` lands on the halfway
    point by arithmetic rather than by declaration. Without this condition
    those come out with an unaccounted-for second sound in the right channel,
    and two `eiiix-1` records declare a loop that then ends past their own
    left channel.

    This test and ``fs/emu3.py``'s ``record_extent`` are one statement seen
    from two sides. That one, from the pointer block alone, decides how long
    the record is; this one, given the payload that produced, decides how to
    read it. They have to agree, or a record sized as two channels comes out
    written as one. Nothing in the code forces that -- the per-disc **stereo
    counts** in tests/test_discs.py are what hold them together, which is why
    they are pinned separately from the sample counts (ADR-0029).
    """
    if size % STEREO_ALIGNMENT:
        return False
    start = pointers.get("start_l", 0)
    if start != DATA_START:
        return False
    split = start + size // 2
    if pointers.get("start_r", 0) != split:
        return False
    return pointers.get("end_l", 0) + END_POINTER_BIAS == split


def _loops(pointers: dict[str, int], frames: int) -> tuple[SampleLoop, ...]:
    """The sustain loop, where the record declares one this audio can carry.

    ``frames`` is a count of *frames*, so on a two-channel record it is half
    the payload's words. That is the right measure and needs no special case:
    ``(pointer - start) / 2`` is a per-channel frame index either way, landing
    in the left block of a double-length mono file and on the frame number of
    an interleaved one, which is why D18 moved this audio without moving a
    single loop point (ADR-0026).

    Which channel's pointers to read is decided by the record, not guessed: the
    set that describes the audio opens at ``DATA_START``. Both sets do on a
    two-channel record and they name the same loop in each half; exactly one
    does where a record declares a single channel, and on 542 of `studio`'s
    records that is the right-hand set, with the left zeroed.

    **The loop end is gated, not clamped, and that is the one place this format
    parts company with AKAI and Roland.** Both of those clamp a declared end
    back to the audio actually present, because a rip is often marginally short
    of its directory. Here the same move destroys the loop, and `protozoa`
    proves it on a single disc: of its mono-shaped records, the 689 whose end
    already lies inside the payload correlate at their splice at **+0.86**, and
    the 525 whose end lies past it -- clamped back to the last frame -- score
    **-0.10**, against a control of -0.01 either way. Same disc, same shape,
    separated only by whether the end fits. A clamped end is a loop point the
    disc did not state, so it is refused (ADR-0025).
    """
    for start_key, end_key, loop_start_key, loop_end_key in _SETS:
        start = pointers.get(start_key, 0)
        if start != DATA_START:
            continue
        end = pointers.get(end_key, 0)
        loop_start = pointers.get(loop_start_key, 0)
        loop_end = pointers.get(loop_end_key, 0)
        if not start <= loop_start < loop_end <= end:
            continue
        if (loop_start - start) % 2 or (loop_end - start) % 2:
            continue
        # The end must be audio this file actually holds -- this channel's,
        # on a two-channel record. See the docstring: clamping is what the
        # other two formats do and what this one cannot.
        if loop_end > start + frames * 2:
            continue
        a, b = (loop_start - start) // 2, (loop_end - start) // 2
        extent = min((end - start) // 2, frames)
        if b - a < MIN_LOOP_FRAMES:
            continue
        # The whole-extent "no loop", refused at both ends. Several discs write
        # those bounds inset by a fixed few bytes rather than at exactly frame 0,
        # so the start carries the same slack as the end -- see FULL_EXTENT_SLACK
        # and ADR-0030. Refusing the start-0 case alone shipped a loop over the
        # entire file on 934 of `ditto-drums`'s 948 records.
        if a <= FULL_EXTENT_SLACK and b >= extent - FULL_EXTENT_SLACK:
            continue
        return (SampleLoop(start=a, end=b),)
    return ()
