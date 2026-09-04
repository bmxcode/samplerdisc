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
(``LLLL...RRRR``), the two blocks equal and contiguous, so the audio span the
mono path already bounds splits at its midpoint into the two channels. They are
interleaved with the shared ``stereo.interleave`` -- the same call the EMU3
backend uses for its block-split stereo -- and the result is verified
byte-for-byte against the publisher's render (ADR-0026, ADR-0041, #57).

The channel count and the audio geometry are read from the record, and both are
computed the same way on every bank. The three constants D33 fitted to Vintage
Pro alone -- the channel count from the two spans' equality, the audio at a
fixed ``block + 184``, the mono length as ``V4 - V3 + 2`` -- each misfire on
other banks (a second bank, Dance 2000, inverts the span test, pads the audio
by 4 not 8, and yields a length of 0). What generalises, verified byte-for-byte
against two banks' publisher renders (Vintage Pro all-mono, Dance 2000 mono +
stereo), is read here instead: the channel byte of the ``V12`` field, the audio
anchored at ``V2``, and the length taken to the trailer or the end of the file.
See docs/formats/emu-ebl.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.stereo import interleave
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
#: little-endian fields, then a 64-byte comment. The audio follows the block.
NAME_LEN = 64
#: Offsets of the little-endian fields, from the start of the block: the twelve
#: numbered fields begin right after the 64-byte name, so field N is at
#: ``NAME_LEN + (N - 1) * 4``.
#:
#: ``V2`` (block + 68) anchors the audio: it is ``180`` plus the pad the bank
#: writes before the PCM, so the audio starts at ``block + V2 - 4`` -- 184 on
#: Vintage Pro (pad 8), 180 on Dance 2000 (pad 4). D33's fixed ``block + 184``
#: was that one bank's pad. ``V12`` (block + 108) carries the channel byte; the
#: tenth field is the sample rate.
V2_AUDIO_ANCHOR = NAME_LEN + 4
#: ``V3`` (block + 72). ``V3 - V2`` is the **per-channel** byte length on every
#: bank measured -- mono and stereo alike -- so a stereo record's two blocks are
#: each ``V3 - V2`` bytes and its audio is ``2 * (V3 - V2)`` bytes total. This is
#: what anchors a stereo split from the end (see ``parse``): the front anchor
#: ``block + V2 - 4`` is exact on Dance 2000 but two bytes late on the grand
#: banks, whereas ``audio_end - 2 * (V3 - V2)`` is exact on both.
V3_LENGTH_FIELD = NAME_LEN + 8
RATE_OFFSET = NAME_LEN + 36
CHANNEL_FIELD = NAME_LEN + 44
#: The pad ``V2`` counts past: ``V2 - AUDIO_PAD_BASE`` is the byte pad, so the
#: audio starts ``AUDIO_PAD_BASE - 4`` past the block plus that pad.
AUDIO_PAD_BASE = 180
#: The fixed size of the data-description block (64-byte name, twelve 32-bit
#: fields, 64-byte comment). The audio can never start before it, so it is the
#: floor a from-the-end stereo anchor is clamped to on a truncated file.
BLOCK_LEN = NAME_LEN + 12 * 4 + NAME_LEN

#: The channel byte of ``V12`` -- ``(V12 >> 16) & 0xFF``. ``0x03`` is the only
#: value that means stereo; ``0x01`` is the common mono value and ``0x02`` is a
#: second mono sub-type (38 files on Vintage Pro, all verified mono against the
#: render). So the test is equality to STEREO, not inequality to MONO: reading
#: it the other way would misclassify those 38 as stereo. The sibling byte
#: ``(V12 >> 8) & 0xFF`` is ``0x02``, the 16-bit sample width.
CHANNEL_MONO = 0x01
CHANNEL_STEREO = 0x03

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


def _trailer_offset(payload: bytes) -> int:
    """Where the optional EXLZ trailer begins, or -1.

    The trailer sits at the very end of a file that carries a loop, so it is
    found from the end. A trailer counts only if its ``MARK`` sub-chunk is
    present and complete; a bare or truncated marker is ignored, which leaves
    the bytes it sits in counted as audio (damage degrades, never crashes).
    This offset is where the audio ends -- verified byte-for-byte on two banks
    -- so the same call locates the loop and bounds the PCM.
    """
    marker = payload.rfind(LOOP_MARKER)
    if marker < 0:
        return -1
    mark = payload.find(MARK, marker)
    if mark < 0 or mark + 16 > len(payload):
        return -1
    return marker


def _loop(payload: bytes, frames: int, trailer: int) -> tuple[SampleLoop, ...]:
    """The loop from the EXLZ trailer, or none.

    A loop that does not run forwards, or runs past the audio, is dropped rather
    than written -- a loop a DAW would refuse is worse than none.
    """
    if trailer < 0:
        return ()
    mark = payload.find(MARK, trailer)
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
    # The block must at least reach V12 to be read; a file shorter than that is
    # too damaged to convert (damage degrades, never crashes).
    if block + CHANNEL_FIELD + 4 > len(payload):
        raise NotASample("EBL data-description block runs past the end of the file")

    name = _name(payload[block : block + NAME_LEN])
    rate = _u32le(payload, block + RATE_OFFSET)

    # The channel count is the channel byte of V12, not the spans D33 read: the
    # spans invert between banks, while V12 agrees with both banks' renders.
    channel_byte = (_u32le(payload, block + CHANNEL_FIELD) >> 16) & 0xFF
    channels = 2 if channel_byte == CHANNEL_STEREO else 1

    # The audio is anchored at V2 (the pad varies by bank) and runs to the EXLZ
    # trailer or, with no loop, the end of the file. That end is the length the
    # renders agree with -- reading a fixed span or to EOF regardless is wrong
    # by a frame on every looped file. The same span bounds both channels of a
    # stereo record, since stereo stores one block after the other.
    audio_start = block + _u32le(payload, block + V2_AUDIO_ANCHOR) - 4
    trailer = _trailer_offset(payload)
    audio_end = trailer if trailer >= 0 else len(payload)
    # Damage degrades, never crashes: a truncated rip loses its tail, so the
    # audio is clamped to what is on the disc and to a whole number of samples.
    length = max(0, min(audio_end, len(payload)) - audio_start)
    length -= length % SAMPLE_WIDTH
    span = payload[audio_start : audio_start + length]

    if channels == 2:
        # Stereo is a whole left block then a whole right block, equal and
        # contiguous (LLLL...RRRR). Each block is V3 - V2 bytes, so the audio is
        # 2 * (V3 - V2) and its true start is audio_end - that: the front anchor
        # block + V2 - 4 is exact on Dance 2000 but two bytes late on the grand
        # banks, while the from-the-end anchor is exact on both (verified
        # byte-for-byte against the render -- docs/formats/emu-ebl.md, ADR-0041).
        per_channel = _u32le(payload, block + V3_LENGTH_FIELD) - _u32le(
            payload, block + V2_AUDIO_ANCHOR
        )
        stereo_start = audio_end - 2 * per_channel
        if per_channel > 0 and stereo_start >= block + BLOCK_LEN:
            left = payload[stereo_start : stereo_start + per_channel]
            right = payload[stereo_start + per_channel : audio_end]
            frames = per_channel // SAMPLE_WIDTH
        else:
            # A truncated rip lost its tail, so the from-the-end anchor would run
            # off the front into the header. Degrade instead: split what is on
            # the disc at the front anchor's midpoint, losing the tail not the
            # head. ``interleave`` trims each side to whole samples and pads a
            # short one, so the odd-byte case does not crash.
            half = length // 2
            left, right = span[:half], span[half:]
            frames = half // SAMPLE_WIDTH
        # ``frames`` is the per-channel count -- the unit the loop and the WAV
        # smpl chunk use, not the interleaved total.
        pcm = interleave(left, right)
    else:
        pcm = span
        frames = length // SAMPLE_WIDTH

    return EmuEblSample(
        name=name or fallback_name,
        rate=rate,
        frames=frames,
        channels=channels,
        width=SAMPLE_WIDTH,
        pcm=pcm,
        loops=_loop(payload, frames, trailer),
    )
