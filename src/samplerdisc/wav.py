"""Minimal RIFF/WAVE writer.

The stdlib ``wave`` module cannot write a ``smpl`` chunk, and ADR-0011 wants
root key and loop points carried in the file so the WAV is self-describing in
a DAW. So the RIFF is assembled here -- still stdlib-only, and the data chunk
stays a byte-for-byte copy of what the sampler stored.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

WAVE_FORMAT_PCM = 1

#: smpl loop types (RIFF spec). 0 is a plain forward loop, 1 alternates.
LOOP_FORWARD = 0
LOOP_ALTERNATING = 1

#: The root key written when the disc carries loop points and no root key.
#: The smpl chunk has no way to say "this sample has no root key" -- the field
#: is mandatory -- so carrying a loop at all means writing something here, and
#: 60 is the neutral value: middle C, no transposition, what a sampler assumes
#: when nothing tells it otherwise.
#:
#: It is a placeholder and not a finding. The E-mu sample record states no root
#: key anywhere in its 92 bytes, and a WAV written this way is saying "here are
#: the loop points" rather than "this sample is middle C" (ADR-0025).
DEFAULT_ROOT_KEY = 60


@dataclass(frozen=True)
class Loop:
    start: int  # in frames
    end: int  # in frames, inclusive per the RIFF spec
    loop_type: int = LOOP_FORWARD


@dataclass(frozen=True)
class Header:
    """What a WAV declares about its audio, and where the audio sits."""

    channels: int
    rate: int
    width: int  # bytes per sample
    offset: int  # of the data chunk body, within the payload
    length: int  # of the data chunk body, in bytes
    #: Whether the file carries a smpl chunk -- root key and loop points. Used
    #: to tell a WAV that already knows what the disc knows from one that does
    #: not, when an AIFF of the same audio turns up (ADR-0024).
    has_smpl: bool = False

    @property
    def frames(self) -> int:
        block = self.channels * self.width
        return self.length // block if block else 0


def read_header(payload: bytes) -> Header | None:
    """Read a WAV's fmt, data and smpl chunks, or None if it is not a WAV.

    Needed because a WAV copied off an ISO 9660 disc is passed through
    untouched, and a run that cannot say what rate it wrote is a run that
    reported nothing. The chunks are walked rather than assumed at fixed
    offsets: ten of the ProSamples WAVs put LIST or PAD ahead of data.

    The walk runs to the end rather than stopping at ``data``, because smpl is
    written after the audio as often as before it and stopping early would
    report half the collection as carrying no root key.
    """
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return None
    channels = rate = width = 0
    data: tuple[int, int] | None = None
    has_smpl = False
    pos = 12
    while pos + 8 <= len(payload):
        tag = payload[pos : pos + 4]
        size = struct.unpack_from("<I", payload, pos + 4)[0]
        body_at = pos + 8
        if tag == b"fmt " and size >= 16:
            _, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", payload, body_at)
            width = (bits + 7) // 8
        elif tag == b"smpl":
            has_smpl = True
        elif tag == b"data" and data is None:
            # Trust the disc over the header: a truncated rip declares the
            # length it was mastered with and carries less.
            data = (body_at, min(size, len(payload) - body_at))
        pos = body_at + size + (size & 1)
    if data is None or not channels or not width:
        return None
    return Header(channels, rate, width, data[0], data[1], has_smpl)


def _chunk(tag: bytes, body: bytes) -> bytes:
    """A RIFF chunk, padded to an even length as the spec requires."""
    padding = b"\x00" if len(body) % 2 else b""
    return tag + struct.pack("<I", len(body)) + body + padding


def _fmt_chunk(channels: int, rate: int, sample_width: int) -> bytes:
    block_align = channels * sample_width
    return _chunk(
        b"fmt ",
        struct.pack(
            "<HHIIHH",
            WAVE_FORMAT_PCM,
            channels,
            rate,
            rate * block_align,  # byte rate
            block_align,
            sample_width * 8,
        ),
    )


def _smpl_chunk(rate: int, midi_note: int, cents: float, loops: list[Loop]) -> bytes:
    """The sampler chunk: root key, fine tuning and loop points.

    A DAW that reads it gets the sample mapped and looping correctly; one that
    does not sees an ordinary WAV. That is the whole point -- self-describing
    without being a sampler format (ADR-0011).
    """
    # Fine tune is expressed as a fraction of a semitone in 1/0x80000000 units.
    fraction = int(max(min(cents, 50.0), -50.0) / 100.0 * 0xFFFFFFFF) & 0xFFFFFFFF
    body = struct.pack(
        "<IIIIIIIII",
        0,  # manufacturer
        0,  # product
        int(1_000_000_000 / rate) if rate else 0,  # sample period, nanoseconds
        midi_note,
        fraction,
        0,  # SMPTE format
        0,  # SMPTE offset
        len(loops),
        0,  # sampler-specific data length
    )
    for index, loop in enumerate(loops):
        body += struct.pack("<IIIIII", index, loop.loop_type, loop.start, loop.end, 0, 0)
    return _chunk(b"smpl", body)


def _info_chunk(name: str) -> bytes:
    encoded = name.encode("ascii", "replace") + b"\x00"
    if len(encoded) % 2:
        encoded += b"\x00"
    return _chunk(b"LIST", b"INFO" + _chunk(b"INAM", encoded))


def write_wav_streaming(
    path: str | os.PathLike[str],
    chunks: Iterable[bytes],
    total_bytes: int,
    rate: int,
    channels: int = 1,
    sample_width: int = 2,
) -> int:
    """Write a WAV whose data chunk is streamed rather than held in memory.

    ``total_bytes`` must be exact -- RIFF puts both lengths in the header, so
    they are written before any audio arrives. A whole-disc audio rip is
    hundreds of megabytes, and buffering it twice (once to read, once to build
    the body) is the difference between working and not on a modest machine.

    The bytes are copied verbatim, exactly as ``write_wav`` copies them.
    """
    header = b"WAVE" + _fmt_chunk(channels, rate, sample_width)
    padding = 1 if total_bytes % 2 else 0
    riff_size = len(header) + 8 + total_bytes + padding

    written = 0
    with open(path, "wb") as out:
        out.write(b"RIFF" + struct.pack("<I", riff_size) + header)
        out.write(b"data" + struct.pack("<I", total_bytes))
        for chunk in chunks:
            out.write(chunk)
            written += len(chunk)
        if padding:
            out.write(b"\x00")
    if written != total_bytes:
        raise ValueError(f"{path}: declared {total_bytes} audio bytes, wrote {written}")
    return 8 + riff_size


def write_wav(
    path: str | os.PathLike[str],
    pcm: bytes,
    rate: int,
    channels: int = 1,
    sample_width: int = 2,
    midi_note: int | None = None,
    cents: float = 0.0,
    loops: list[Loop] | None = None,
    name: str = "",
) -> int:
    """Write ``pcm`` as a WAV. Returns bytes written.

    ``pcm`` must already be signed little-endian PCM of ``sample_width`` bytes,
    interleaved if ``channels`` > 1 -- it is copied verbatim.
    """
    body = b"WAVE" + _fmt_chunk(channels, rate, sample_width)
    if name:
        body += _info_chunk(name)
    # A loop is worth carrying even where the disc states no root key, so the
    # chunk is written for either. E-mu is the format that needs this: it
    # declares loop points in every sample record and a root key in none.
    if midi_note is not None or loops:
        body += _smpl_chunk(
            rate,
            midi_note if midi_note is not None else DEFAULT_ROOT_KEY,
            cents,
            loops or [],
        )
    body += _chunk(b"data", pcm)

    with open(path, "wb") as out:
        out.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return 8 + len(body)
