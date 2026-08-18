"""AKAI S1000/S3000 sample payloads. See docs/formats/akai-fs.md.

The payload is signed 16-bit little-endian mono PCM, which is exactly what a
WAV data chunk holds -- so nothing here converts audio. It parses a header and
hands the bytes on untouched.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.fs.akai import NAME_LEN, decode_name, is_plausible_name

#: S1000 header. S3000 discs may use a 192-byte variant.
HEADER_LEN_S1000 = 150
HEADER_LEN_S3000 = 192

SAMPLE_ID = 3
VALID_FLAG = 0x80

#: Field offsets, all verified in docs/formats/akai-fs.md.
OFF_ID = 0
OFF_PITCH = 2
OFF_NAME = 3
OFF_VALID = 15
OFF_WORDS = 26
OFF_RATE = 138

#: Loop and tuning fields, used to populate the WAV smpl chunk (ADR-0011).
OFF_LOOPS = 16
OFF_TUNE_CENTS = 21
OFF_TUNE_SEMI = 22

#: Eight 12-byte loop records follow the play markers. Each holds the loop
#: *end* in words, then the loop length as 16.16 fixed point (fraction first),
#: then a dwell time. Loop start is end - length; there is no start field.
OFF_LOOP_RECORDS = 38
LOOP_RECORD_LEN = 12
MAX_LOOP_RECORDS = 8

#: Dwell 9999 means "hold" -- loop for as long as the note sounds. Anything
#: else is a timed dwell the WAV smpl chunk cannot express.
DWELL_HOLD = 9999

#: Rates observed across the reference discs run 22050 to 48000, including the
#: fractional 33075 (3/4) and 29400 (2/3) these samplers used to trade
#: bandwidth for memory. The ceiling is deliberately below 65535.
MIN_RATE = 4000
MAX_RATE = 50000


class NotASample(ValueError):
    """The payload does not begin with a sample header."""


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive here; the WAV writer makes it
    inclusive as the RIFF spec requires."""

    start: int
    end: int


@dataclass(frozen=True)
class AkaiSample:
    name: str
    rate: int
    pitch: int
    frames: int
    header_len: int
    pcm: bytes
    loops: tuple[SampleLoop, ...] = ()
    cents: float = 0.0

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def _looks_like_header(payload: bytes) -> bool:
    return (
        len(payload) > OFF_RATE + 2
        and payload[OFF_ID] == SAMPLE_ID
        and payload[OFF_VALID] == VALID_FLAG
        and is_plausible_name(payload[OFF_NAME : OFF_NAME + NAME_LEN])
    )


def parse(payload: bytes, fallback_name: str = "") -> AkaiSample:
    """Parse a sample file. Raises NotASample if the payload is not one.

    Lengths are clamped to what is actually present: a truncated tail is common
    in these rips and yields a short sample rather than an exception.
    """
    if not _looks_like_header(payload):
        raise NotASample("payload does not start with an AKAI sample header")

    name = decode_name(payload[OFF_NAME : OFF_NAME + NAME_LEN]) or fallback_name
    pitch = payload[OFF_PITCH]
    (words,) = struct.unpack_from("<I", payload, OFF_WORDS)
    (rate,) = struct.unpack_from("<H", payload, OFF_RATE)
    if not MIN_RATE <= rate <= MAX_RATE:
        # 65535 is the giveaway: an unwritten or damaged field reads as all
        # ones, and it sits inside any range generous enough to be "safe".
        raise NotASample(f"implausible sample rate {rate}")

    header_len = HEADER_LEN_S1000
    available = (len(payload) - header_len) // 2
    frames = min(words, max(available, 0))
    pcm = payload[header_len : header_len + frames * 2]
    return AkaiSample(
        name=name,
        rate=rate,
        pitch=pitch,
        frames=frames,
        header_len=header_len,
        pcm=pcm,
        loops=_loops(payload, frames),
        cents=_cents(payload),
    )


def _cents(payload: bytes) -> float:
    """Pitch offset in cents, signed."""
    raw = payload[OFF_TUNE_CENTS]
    return float(raw - 256 if raw > 127 else raw)


def _loops(payload: bytes, frames: int) -> tuple[SampleLoop, ...]:
    """Read the active loop records.

    Points are clamped to the audio actually present: a declared loop end can
    sit a few words past a payload that is marginally shorter than its header
    claims, which is common enough on these rips to be normal rather than an
    error.
    """
    count = min(payload[OFF_LOOPS], MAX_LOOP_RECORDS)
    found: list[SampleLoop] = []
    for index in range(count):
        base = OFF_LOOP_RECORDS + index * LOOP_RECORD_LEN
        if base + LOOP_RECORD_LEN > len(payload):
            break
        (end,) = struct.unpack_from("<I", payload, base)
        # 16.16 fixed point: the fraction comes first and is below WAV's
        # resolution, so only the whole part is used.
        (length,) = struct.unpack_from("<H", payload, base + 6)
        (dwell,) = struct.unpack_from("<H", payload, base + 10)
        if length == 0 or dwell != DWELL_HOLD:
            continue
        # Derive the start from the *declared* end, then clamp. Clamping first
        # would drag the start earlier by however far the end overshot, which
        # silently retunes the loop instead of shortening it.
        start = end - length
        end = min(end, frames)
        if 0 <= start < end:
            found.append(SampleLoop(start=start, end=end))
    return tuple(found)
