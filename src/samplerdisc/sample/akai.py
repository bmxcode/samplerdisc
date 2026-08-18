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
OFF_TUNE_CENTS = 20
OFF_TUNE_SEMI = 21

#: Rates observed across the reference discs run 22050 to 48000, including the
#: fractional 33075 (3/4) and 29400 (2/3) these samplers used to trade
#: bandwidth for memory. The ceiling is deliberately below 65535.
MIN_RATE = 4000
MAX_RATE = 50000


class NotASample(ValueError):
    """The payload does not begin with a sample header."""


@dataclass(frozen=True)
class AkaiSample:
    name: str
    rate: int
    pitch: int
    frames: int
    header_len: int
    pcm: bytes

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
    )
