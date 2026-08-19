"""Roland S-7xx sample payloads. See docs/formats/roland-s7xx.md.

There is nothing to decode. The filesystem layer located the payload through
the allocation table and read the 48-byte parameter record that goes with it,
and what that record describes -- root key, loop points -- arrives here on the
``File`` rather than in front of the audio, because on this format it lives in
a different region of the disc (block 4780, nowhere near the sample data).

So this module carries the parameters and the bytes and converts nothing. The
payload is signed 16-bit little-endian PCM, which is what a WAV data chunk
holds, so the WAV is a copy with a header in front of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample


class NotASample(_NotASample):
    """The payload is not usable as audio."""


#: The lowest and highest MIDI note a root key may claim. Every key measured
#: across five discs sits in 24..108; this is the format's own range, and a
#: value outside it means the record is damaged rather than exotic.
MIN_KEY = 0
MAX_KEY = 127


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive here, as it is for AKAI; the
    WAV writer makes it inclusive as the RIFF spec requires.

    Whether the disc means it inclusively or exclusively is below the
    resolution of the measurement that established the loop at all -- the two
    readings differ by a single frame at 44.1 kHz, and the splice test cannot
    separate them. The AKAI convention is followed for consistency.
    """

    start: int
    end: int


@dataclass(frozen=True)
class RolandS7xxSample:
    name: str
    rate: int
    frames: int
    pcm: bytes
    pitch: int | None = None
    loops: tuple[SampleLoop, ...] = ()

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def parse(
    payload: bytes,
    *,
    rate: int,
    key: int = 0,
    loop_mode: int = 0,
    loop_start: int = 0,
    loop_end: int = 0,
    fallback_name: str = "",
) -> RolandS7xxSample:
    """Wrap an already-located payload. Raises NotASample if it is unusable."""
    if not payload:
        raise NotASample("no data on disc")
    frames = len(payload) // 2
    if frames == 0:
        raise NotASample("zero-length sample")
    pitch = key if MIN_KEY <= key <= MAX_KEY else None
    return RolandS7xxSample(
        name=fallback_name,
        rate=rate,
        frames=frames,
        pcm=payload[: frames * 2],
        pitch=pitch,
        loops=_loops(loop_mode, loop_start, loop_end, frames),
    )


def _loops(mode: int, start: int, end: int, frames: int) -> tuple[SampleLoop, ...]:
    """The sustain loop, when the mode byte says the sampler uses it.

    Two rules, both established by measurement rather than assumed:

    A zero mode means no loop. It does *not* mean the addresses are junk --
    mode-0 samples carry loop points that splice as cleanly as mode-1 ones
    (80.6% against 86.5%), because the points are crafted whether or not the
    sampler is told to play them. So nothing is inferred from a zero beyond
    "do not loop this".

    Any non-zero mode loops. Which of 1, 2, 4 and 16 means forward, alternating
    or reverse is not established -- all four show seamless splices and nothing
    distinguishes them -- so every one becomes a plain forward loop, which is
    what a DAW does with an unmarked loop anyway. Mode 1 covers 3 962 of the
    6 392 samples measured; the other three together cover 263.

    Points are clamped to the audio actually present, for the same reason
    AKAI's are: a rip can be a little shorter than its directory claims.
    """
    if not mode:
        return ()
    end = min(end, frames)
    if not 0 <= start < end:
        return ()
    return (SampleLoop(start=start, end=end),)
