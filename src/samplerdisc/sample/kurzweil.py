"""Kurzweil ``.KRZ`` sample audio. See docs/formats/kurzweil-krz.md.

A ``.KRZ`` is not a bare sample but a big-endian bundle of Kurzweil objects --
programs, keymaps and samples sharing one PCM pool. The filesystem layer
(``fs/kurzweil.py``) walks that bundle, locates each sample's channel or
channels in the pool, and hands the raw pool bytes here with the rate, root key
and loop the object declared. What is left for this module is the one thing that
is genuinely a *sample format* concern: the pool is **16-bit signed big-endian
PCM**, and a WAV data chunk is little-endian, so each sample value's two bytes
are reversed on the way out -- the carry an AIFF payload gets, and the reason it
is reordered rather than copied verbatim like an AKAI or E-mu sample (ADR-0011,
ADR-0024). No sample value is otherwise altered.

A stereo sample is stored **planar** -- the whole left channel, then the whole
right -- so it is interleaved here for the WAV. Root key the Kurzweil sample
object *does* carry (unlike E-mu, ADR-0025), so it and the loop go into the
``smpl`` chunk.
"""

from __future__ import annotations

from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.wav import LOOP_FORWARD

#: 16-bit PCM: two bytes to a mono frame.
SAMPLE_WIDTH = 2

#: A loop shorter than this is a boundary artefact, not a sustain loop, and is
#: dropped rather than written. Matches the E-mu floor (ADR-0025); a DAW asked
#: to loop a handful of frames clicks rather than sustains.
MIN_LOOP_FRAMES = 64


class NotASample(_NotASample):
    """The pool slice is not usable 16-bit PCM."""


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive, as elsewhere in this project;
    the WAV writer makes it inclusive as the RIFF spec requires.

    The Kurzweil object stores the loop as absolute frame addresses into the
    bank's PCM pool; the filesystem layer has already subtracted the sample's
    start so these are sample-relative. Whether the object's end frame is the
    last frame played or one past it is mixed in the wild (see
    docs/formats/kurzweil-krz.md), so the end is clamped to the audio and the
    project's exclusive convention is used for consistency with the other
    formats -- the one-frame question is inaudible.
    """

    start: int
    end: int
    loop_type: int = LOOP_FORWARD


@dataclass(frozen=True)
class KurzweilSample:
    name: str
    rate: int
    frames: int
    pcm: bytes
    channels: int = 1
    #: The MIDI note the sample plays at, from the object's ``rootkey``. Written
    #: into the ``smpl`` chunk (ADR-0011); ``None`` only if the object carried
    #: none, which the Kurzweil format never does.
    pitch: int | None = None
    loops: tuple[SampleLoop, ...] = ()

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def _swap16(pcm: bytes) -> bytes:
    """Reverse the two bytes of each 16-bit sample. Big-endian in, LE out.

    Whole samples only: a slice whose length is odd has a stray byte at the end
    -- tail damage on the rip -- and reversing across it would move real audio
    into the wrong frame rather than dropping the fragment. Host-independent by
    construction; it reorders bytes and never reads them as integers.
    """
    usable = len(pcm) - len(pcm) % SAMPLE_WIDTH
    out = bytearray(usable)
    out[0::SAMPLE_WIDTH] = pcm[1:usable:SAMPLE_WIDTH]
    out[1::SAMPLE_WIDTH] = pcm[0:usable:SAMPLE_WIDTH]
    return bytes(out)


def _interleave(left: bytes, right: bytes) -> bytes:
    """Weave two equal-length little-endian mono channels into stereo frames.

    Byte-strided, so no per-frame loop and no host-order dependence. The two
    channels are the same length by construction (the planar split is even).
    """
    frames = min(len(left), len(right))
    frames -= frames % SAMPLE_WIDTH
    out = bytearray(frames * 2)
    out[0::4] = left[0:frames:SAMPLE_WIDTH]
    out[1::4] = left[1:frames:SAMPLE_WIDTH]
    out[2::4] = right[0:frames:SAMPLE_WIDTH]
    out[3::4] = right[1:frames:SAMPLE_WIDTH]
    return bytes(out)


def _loops(loop: tuple[int, int] | None, frames: int) -> tuple[SampleLoop, ...]:
    """The sample-relative loop, guarded, or none.

    ``loop`` is ``(start, end)`` in sample-relative frames, present only when the
    object is flagged looped. The end is clamped to the audio -- never allowed to
    run into a neighbouring sample's PCM -- and a loop that does not run forwards
    or is too short to sustain is dropped: a loop a DAW would refuse is worse
    than none.
    """
    if loop is None:
        return ()
    start, end = loop
    end = min(end, frames)
    if not 0 <= start < end <= frames:
        return ()
    if end - start < MIN_LOOP_FRAMES:
        return ()
    return (SampleLoop(start=start, end=end),)


def parse(
    payload: bytes,
    *,
    rate: int,
    name: str = "",
    loop: tuple[int, int] | None = None,
    root: int | None = None,
    channels: int = 1,
    channel_bytes: int = 0,
) -> KurzweilSample:
    """One sample's pool bytes, carried to little-endian PCM for a WAV.

    ``payload`` is the big-endian pool audio -- one channel for a mono sample,
    two planar channels of ``channel_bytes`` each for a stereo one. ``rate``,
    ``root`` and ``loop`` were read from the bank directory by the filesystem
    layer rather than from these bytes.
    """
    if len(payload) < SAMPLE_WIDTH:
        raise NotASample("sample holds no audio")
    if channels == 2:
        left = _swap16(payload[:channel_bytes])
        right = _swap16(payload[channel_bytes : 2 * channel_bytes])
        pcm = _interleave(left, right)
        frames = len(pcm) // (SAMPLE_WIDTH * 2)
    else:
        pcm = _swap16(payload)
        frames = len(pcm) // SAMPLE_WIDTH
    return KurzweilSample(
        name=name,
        rate=rate,
        frames=frames,
        pcm=pcm,
        channels=channels,
        pitch=root,
        loops=_loops(loop, frames),
    )
