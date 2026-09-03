"""Digidesign Sound Designer II (``Sd2f``) files. See docs/formats/hfs.md.

An SD2 file is a Macintosh two-fork file on a SampleCell HFS disc, not a
sampler-native format -- so it lands here for the same reason ``aiff`` does: the
filesystem (``fs/hfs.py``) already finds it, and only the decode is ours.

The audio and its parameters live in *different forks*, which is the whole
reason the file went unread until now. The **data fork** is the audio: plain
big-endian PCM, interleaved when stereo. The **resource fork** carries only
metadata, in three ``STR `` (trailing space) resources whose bodies are ASCII
decimal Pascal strings:

    id 1000  sample size, in *bytes*  ("2" -> 16-bit)
    id 1001  sample rate, in Hz       ("44100.000000")
    id 1002  channel count            ("2" -> stereo)

So ``parse`` takes both forks. The audio is carried to WAV by reversing the
bytes within each sample (big-endian to little-endian), exactly as ``aiff`` does
and for the same reason -- byte order changes, sample values do not (ADR-0011,
ADR-0024). SD2 stereo is already interleaved in the data fork, so unlike the
E-mu backends no channel de-planing is needed.

Loop points and a root key are not read. The resource fork can carry Digidesign
region/loop resources (``sdLL``, ``sdDD``), but there is no open decoder or a
render to verify one against, so the loop is left out rather than guessed
(ADR-0025). The numbers above are verified against ``sonic-images-v2``, whose 24
``Sd2f`` files are uniformly 16-bit, 44 100 Hz, stereo.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.sample.aiff import _swap

#: Resource type carrying the SD2 parameters, and the three ids within it. The
#: trailing space is part of the four-character type.
STR_TYPE = b"STR "
ID_SAMPLE_SIZE = 1000  # bytes per sample, not bits
ID_SAMPLE_RATE = 1001
ID_CHANNELS = 1002

#: Only 16-bit is carried, the same line ``aiff`` draws: reversing byte order is
#: exact, but an 8-bit resample or a width change alters sample values.
SUPPORTED_WIDTH = 2

#: A resource-map reference-list entry is 12 bytes: id (2), name offset (2),
#: attributes (1) + a 3-byte data offset, reserved (4).
_REF_LEN = 12


class NotASample(_NotASample):
    """The forks are not a Sound Designer II sample we can carry to WAV."""


@dataclass(frozen=True)
class Sd2Sample:
    name: str
    rate: int
    frames: int
    channels: int
    width: int
    pcm: bytes
    #: SD2 carries no root key this project reads; ``None`` so the WAV is
    #: written without an invented one (ADR-0025), as ``aiff`` does with no INST.
    pitch: int | None = None
    cents: float = 0.0
    loops: tuple = ()

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def _resources(rsrc: bytes, want_type: bytes) -> dict[int, bytes]:
    """Every resource of one type, as ``{id: body}``.

    Walks the resource-fork header, the type list and the reference list of the
    Macintosh resource map. Any offset that does not fit yields ``{}`` rather
    than raising -- these are rips, and a truncated map degrades to "no
    parameters found", which the caller turns into a reasoned skip.
    """
    if len(rsrc) < 16:
        return {}
    data_off, map_off, _data_len, _map_len = struct.unpack_from(">IIII", rsrc, 0)
    if map_off + 28 > len(rsrc) or data_off > len(rsrc):
        return {}
    type_list_off = struct.unpack_from(">H", rsrc, map_off + 24)[0]
    tl = map_off + type_list_off
    if tl + 2 > len(rsrc):
        return {}
    num_types = struct.unpack_from(">H", rsrc, tl)[0] + 1
    found: dict[int, bytes] = {}
    for i in range(num_types):
        off = tl + 2 + i * 8
        if off + 8 > len(rsrc):
            break
        rtype = rsrc[off : off + 4]
        count = struct.unpack_from(">H", rsrc, off + 4)[0] + 1
        ref_off = struct.unpack_from(">H", rsrc, off + 6)[0]
        if rtype != want_type:
            continue
        base = tl + ref_off
        for j in range(count):
            r = base + j * _REF_LEN
            if r + _REF_LEN > len(rsrc):
                break
            res_id = struct.unpack_from(">h", rsrc, r)[0]
            res_data_off = struct.unpack_from(">I", rsrc, r + 4)[0] & 0xFFFFFF
            pos = data_off + res_data_off
            if pos + 4 > len(rsrc):
                continue
            length = struct.unpack_from(">I", rsrc, pos)[0]
            body = rsrc[pos + 4 : pos + 4 + length]
            found[res_id] = body
    return found


def _pascal_number(body: bytes) -> str:
    """The ASCII text of a Pascal string: one length byte, then the digits."""
    if not body:
        return ""
    return body[1 : 1 + body[0]].decode("ascii", "replace")


def parse(data_fork: bytes, rsrc_fork: bytes, fallback_name: str = "") -> Sd2Sample:
    """One SD2 file, from its data fork (audio) and resource fork (parameters)."""
    params = _resources(rsrc_fork, STR_TYPE)
    if not all(k in params for k in (ID_SAMPLE_SIZE, ID_SAMPLE_RATE, ID_CHANNELS)):
        raise NotASample("no SD2 STR parameters in the resource fork")
    try:
        width = int(_pascal_number(params[ID_SAMPLE_SIZE]))
        # The rate is written as a float ("44100.000000"); take the integer part.
        rate = int(float(_pascal_number(params[ID_SAMPLE_RATE])))
        channels = int(_pascal_number(params[ID_CHANNELS]))
    except ValueError as exc:
        raise NotASample(f"unreadable SD2 parameter: {exc}") from None

    if channels < 1:
        raise NotASample(f"SD2 declares {channels} channels")
    if width != SUPPORTED_WIDTH:
        raise NotASample(
            f"{width * 8}-bit SD2 is not carried to WAV: only byte order is "
            f"changed, and this depth would need the sample values changed too"
        )
    if not data_fork:
        raise NotASample("SD2 data fork is empty")

    pcm = _swap(data_fork, width)
    block = channels * width
    frames = len(pcm) // block if block else 0
    pcm = pcm[: frames * block]
    return Sd2Sample(
        name=fallback_name,
        rate=rate,
        frames=frames,
        channels=channels,
        width=width,
        pcm=pcm,
    )
