"""E-mu Emulator X ``.EBL`` sample banks. See docs/formats/emu-ebl.md.

An ``.EBL`` is an ordinary file inside an ordinary ISO 9660 filesystem, written
by Emulator X-3 (E-mu's Windows software sampler). It is *not* the ``EMU3``
on-disc filesystem -- that is a hardware sampler's own layout, read by
``fs/emu3.py``. This is the third layer of the design: a sample format inside a
file, so it lands here and the ISO 9660 backend that already finds the file
hands it over (ADR-0003).

An ``.EBL`` is an IFF ``FORM`` wrapper -- big-endian outer headers, little-endian
data headers -- around uncompressed 16-bit little-endian PCM. That is already
exactly what a WAV data chunk holds, so a mono payload is copied verbatim; no
value is altered and no byte is reordered (ADR-0011). The header carries the
sample rate (which varies wildly across a bank -- 282 distinct rates on Vintage
Pro, only 27 of them 44 100) and, on most files, a loop.

Stereo is stored non-interleaved -- a whole left block then a whole right block
(``LLLL...RRRR``) -- and would need interleaving to become a WAV. No disc in
hand carries a stereo ``.EBL`` (Vintage Pro is 1 061 mono files), and no stereo
``.EBL`` is available paired with a known-good render to check an interleave
against, so a stereo record is refused with a reason rather than converted by a
rule nothing has verified (ADR-0026, #57). The channel
count is read from the record; the mono path is what ships.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.wav import LOOP_FORWARD

MAGIC = b"FORM"
#: The metadata section that follows ``FORM`` and marks this as an EBL rather
#: than any other IFF file. The bytes after it are the table of contents.
TOC2 = b"E5B0TOC2"
#: The section id that recurs through the header. There are two: the first
#: carries the 64-byte name, the second precedes the data-description block.
SECTION = b"E5S1"

#: EBL is little-endian 16-bit PCM -- a WAV data chunk unchanged, unlike AIFF.
SAMPLE_WIDTH = 2

#: The header up to the data description is not a fixed size -- a bank writes a
#: few bytes more or fewer of padding -- so the offset of the data-description
#: block is read from the file rather than assumed. ``FORM`` (8) and the TOC2
#: marker (12) are fixed; the first ``E5S1`` section starts here, and its third
#: field gives the absolute offset of the second ``E5S1`` section.
FIRST_SECTION = 0x14
#: Within the first section: id (4), a big-endian size (4), then the big-endian
#: absolute offset of the second section (the value is 0x62 on Vintage Pro).
SECOND_SECTION_OFFSET_FIELD = FIRST_SECTION + 8
#: The second ``E5S1`` section is 14 bytes -- id (4), a size (4), six more --
#: and the fixed-layout data-description block follows it.
SECOND_SECTION_LEN = 14

#: The data-description block: a 64-byte UTF-16LE name, twelve 32-bit
#: little-endian fields, then a 64-byte comment. The audio follows, after eight
#: bytes of padding.
NAME_LEN = 64
#: Offsets of the little-endian fields, from the start of the block: the twelve
#: numbered fields begin right after the 64-byte name, so field N is at
#: ``NAME_LEN + (N - 1) * 4``. V2..V5 give the two channel spans, the tenth is
#: the sample rate.
V2_SPAN_1_START = NAME_LEN + 4
V3_SPAN_1_END = NAME_LEN + 8
V4_SPAN_2_START = NAME_LEN + 12
V5_SPAN_2_END = NAME_LEN + 16
RATE_OFFSET = NAME_LEN + 36
#: HeaderData is 176 bytes (name 64 + twelve fields 48 + comment 64) and the
#: audio begins eight bytes further on, past a run of padding that is eight
#: bytes wide on every file measured.
AUDIO_AFTER_BLOCK = 176 + 8

#: The optional loop trailer, at the very end of a file that carries a loop.
#: ``EXLZ`` opens it; ``MARK`` is followed by the loop's start and end frames,
#: little-endian. 849 of Vintage Pro's 1 061 files carry one.
LOOP_MARKER = b"EXLZ"
MARK = b"MARK"


class NotASample(_NotASample):
    """The payload is not an uncompressed mono EBL we can carry to WAV."""


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive, as elsewhere in this project;
    the WAV writer makes it inclusive as the RIFF spec requires.

    The EBL stores an explicit start and end frame. Whether its end is the last
    frame played or one past it is not something any render we can check settles
    -- but every loop measured ends several frames short of the audio, so the
    one-frame question is inaudible and the project's exclusive convention is
    used for consistency with the other formats (see docs/formats/emu-ebl.md).
    """

    start: int
    end: int
    loop_type: int = LOOP_FORWARD


@dataclass(frozen=True)
class EmuEblSample:
    name: str
    rate: int
    frames: int
    channels: int
    width: int
    pcm: bytes
    loops: tuple[SampleLoop, ...] = ()

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def _u32le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise NotASample("header field runs past the end of the file")
    return struct.unpack_from("<I", data, offset)[0]


def _u32be(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise NotASample("header field runs past the end of the file")
    return struct.unpack_from(">I", data, offset)[0]


def _name(raw: bytes) -> str:
    """A 64-byte UTF-16LE name, trimmed of its NUL and space padding.

    This is the name the bank gave the sample -- ``EP4MKIIL A0``, ``909 Tom
    Low`` -- and it is what the output is named after, because the ISO 9660
    names are a meaningless sequence (``Vintage ProSL001.ebl``).
    """
    return raw.decode("utf-16-le", "replace").split("\x00", 1)[0].strip()


def _loop(payload: bytes, frames: int) -> tuple[SampleLoop, ...]:
    """The loop from the EXLZ trailer, or none.

    The trailer is optional and sits at the end of the file. A loop that does
    not run forwards, or runs past the audio, is dropped rather than written --
    a loop a DAW would refuse is worse than none.
    """
    marker = payload.rfind(LOOP_MARKER)
    if marker < 0:
        return ()
    mark = payload.find(MARK, marker)
    if mark < 0 or mark + 16 > len(payload):
        return ()
    # The MARK chunk is its id (4), a size (4, always 8), then the loop's start
    # and end frames, little-endian.
    start = _u32le(payload, mark + 8)
    end = _u32le(payload, mark + 12)
    if not 0 <= start < end <= frames:
        return ()
    return (SampleLoop(start=start, end=end),)


def parse(payload: bytes, fallback_name: str = "") -> EmuEblSample:
    """One EBL payload, as little-endian PCM ready for a WAV data chunk."""
    if len(payload) < FIRST_SECTION + 12 or payload[:4] != MAGIC:
        raise NotASample("not a FORM")
    if payload[8:16] != TOC2:
        raise NotASample("not an EBL (no E5B0TOC2 table of contents)")
    if payload[FIRST_SECTION : FIRST_SECTION + 4] != SECTION:
        raise NotASample("EBL first section is not E5S1")

    # The header up to the data description is variable-width; its end is the
    # second E5S1 section, whose absolute offset the first section declares.
    second = _u32be(payload, SECOND_SECTION_OFFSET_FIELD)
    if payload[second : second + 4] != SECTION:
        raise NotASample("EBL second section is not where the header says")
    block = second + SECOND_SECTION_LEN
    if block + AUDIO_AFTER_BLOCK > len(payload):
        raise NotASample("EBL data-description block runs past the end of the file")

    name = _name(payload[block : block + NAME_LEN])
    v2 = _u32le(payload, block + V2_SPAN_1_START)
    v3 = _u32le(payload, block + V3_SPAN_1_END)
    v4 = _u32le(payload, block + V4_SPAN_2_START)
    v5 = _u32le(payload, block + V5_SPAN_2_END)
    rate = _u32le(payload, block + RATE_OFFSET)

    # The two channel spans. Equal spans -- the common case, and every file on
    # the one disc in hand -- mean mono, and the mono block's length is stated
    # apart, as V4 - V3 + 2. Unequal spans mean a left block then a right block.
    if v3 - v2 != v5 - v4:
        raise NotASample(
            "stereo EBL (non-interleaved L/R) is not yet supported: no stereo "
            "specimen exists to verify the interleave against"
        )

    audio_start = block + AUDIO_AFTER_BLOCK
    length = v4 - v3 + 2
    # Damage degrades, never crashes: a truncated rip declares a length it does
    # not carry, so the audio is clamped to what is actually on the disc and to
    # a whole number of samples (ADR: damaged input degrades).
    length = max(0, min(length, len(payload) - audio_start))
    length -= length % SAMPLE_WIDTH
    pcm = payload[audio_start : audio_start + length]
    frames = length // SAMPLE_WIDTH

    return EmuEblSample(
        name=name or fallback_name,
        rate=rate,
        frames=frames,
        channels=1,
        width=SAMPLE_WIDTH,
        pcm=pcm,
        loops=_loop(payload, frames),
    )
