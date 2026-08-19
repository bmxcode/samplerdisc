"""E-mu EIII/ESI sample payloads. See docs/formats/emu3.md.

There is nothing to decode. The filesystem layer already located the record and
read its rate, and the payload that follows the 92-byte header is signed 16-bit
little-endian PCM -- the same thing a WAV data chunk holds. So this module
carries the rate and the bytes and converts nothing (ADR-0011).

The endianness is worth a note, because it was got wrong first. Sampling this
data at 2048-byte sector boundaries makes it read as big-endian, convincingly
and repeatably. It is not: the sample payload starts at an odd byte offset, so
a sector-aligned probe reads every 16-bit word one byte out, which swaps the
apparent byte order. Read from the record's own start and it is little-endian.
"""

from __future__ import annotations

from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample


class NotASample(_NotASample):
    """The payload is not usable as audio."""


@dataclass(frozen=True)
class Emu3Sample:
    name: str
    rate: int
    frames: int
    pcm: bytes

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def parse(payload: bytes, rate: int, fallback_name: str = "") -> Emu3Sample:
    """Wrap an already-located payload. Raises NotASample if it is unusable."""
    if not payload:
        raise NotASample("no data on disc")
    frames = len(payload) // 2
    if frames == 0:
        raise NotASample("zero-length sample")
    return Emu3Sample(
        name=fallback_name,
        rate=rate,
        frames=frames,
        pcm=payload[: frames * 2],
    )
