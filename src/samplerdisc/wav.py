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

#: smpl loop types (RIFF spec). 0 is a plain forward loop.
LOOP_FORWARD = 0


@dataclass(frozen=True)
class Loop:
    start: int  # in frames
    end: int  # in frames, inclusive per the RIFF spec
    loop_type: int = LOOP_FORWARD


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
    if midi_note is not None:
        body += _smpl_chunk(rate, midi_note, cents, loops or [])
    body += _chunk(b"data", pcm)

    with open(path, "wb") as out:
        out.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return 8 + len(body)
