"""AIFF payloads on ISO 9660 discs. See docs/formats/aiff.md.

The one place in this project where the audio bytes are not handed on exactly
as the disc stored them: AIFF is big-endian and WAV is little-endian, so each
sample's bytes are reversed. That is a re-ordering of the bytes *within* a
sample value, not a re-sampling -- no rate change, no bit-depth change, no
dithering, and it is exactly reversible (ADR-0024).

The line is drawn at byte order. 8-bit AIFF is signed and 8-bit WAV is
unsigned, so carrying one to the other means adding 128 to every sample, which
changes the values; that is a conversion and this module refuses it rather than
doing it quietly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.wav import LOOP_ALTERNATING, LOOP_FORWARD

MAGIC = b"FORM"
FORM_AIFF = b"AIFF"
#: AIFF-C. Its payload may be compressed -- ``sowt``, ``ima4``, ``ulaw`` -- and
#: a compressed payload emitted as PCM opens, plays as noise, and reports
#: nothing wrong. Rejected rather than guessed; no disc in the collection has
#: one. See docs/formats/aiff.md.
FORM_AIFC = b"AIFC"

#: Byte orders we can carry to WAV by reversing bytes within a sample.
SUPPORTED_WIDTHS = (2, 3)

#: An AIFF chunk header is a four-character id and a big-endian length.
CHUNK_HEADER_LEN = 8

#: INST playMode values (AIFF 1.3).
PLAY_NONE = 0
PLAY_FORWARD = 1
PLAY_FORWARD_BACKWARD = 2

_PLAY_MODES = {PLAY_FORWARD: LOOP_FORWARD, PLAY_FORWARD_BACKWARD: LOOP_ALTERNATING}

#: The 80-bit IEEE 754 extended sample rate in COMM: sign and 15-bit exponent,
#: then a 64-bit mantissa with an explicit leading bit.
EXTENDED_BIAS = 16383
MANTISSA_BITS = 63


class NotASample(_NotASample):
    """The payload is not an uncompressed AIFF we can carry to WAV."""


@dataclass(frozen=True)
class SampleLoop:
    """One loop, in frames. ``end`` is exclusive, as elsewhere in this project;
    the WAV writer makes it inclusive as the RIFF spec requires."""

    start: int
    end: int
    loop_type: int = LOOP_FORWARD


@dataclass(frozen=True)
class AiffSample:
    name: str
    rate: int
    frames: int
    channels: int
    width: int
    pcm: bytes
    #: None where the file carries no INST chunk, so the WAV is written without
    #: an invented root key rather than with one.
    pitch: int | None = None
    cents: float = 0.0
    loops: tuple[SampleLoop, ...] = ()

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0


def _extended(raw: bytes) -> int:
    """The 80-bit extended float in COMM, as an integer sample rate.

    Done in integer arithmetic rather than through a float: the mantissa is 64
    bits and a double has 53, so the obvious ``mantissa * 2.0 ** shift`` is
    lossy for exactly the large mantissas this field uses.
    """
    if len(raw) < 10:
        raise NotASample("COMM sample rate is truncated")
    exponent = struct.unpack_from(">H", raw, 0)[0]
    mantissa = struct.unpack_from(">Q", raw, 2)[0]
    negative = bool(exponent & 0x8000)
    exponent &= 0x7FFF
    if exponent == 0x7FFF:
        raise NotASample("COMM sample rate is infinity or NaN")
    if mantissa == 0:
        return 0
    shift = exponent - EXTENDED_BIAS - MANTISSA_BITS
    value = mantissa << shift if shift >= 0 else mantissa >> -shift
    return -value if negative else value


def _chunks(payload: bytes):
    """Walk the chunks of a FORM, yielding ``(id, body)``.

    Stops at the first header that does not fit rather than raising: these are
    rips and a truncated tail is normal, so a file that loses its last chunk
    still yields the audio ahead of it.
    """
    pos = 12
    while pos + CHUNK_HEADER_LEN <= len(payload):
        chunk_id = payload[pos : pos + 4]
        size = struct.unpack_from(">I", payload, pos + 4)[0]
        body = payload[pos + CHUNK_HEADER_LEN : pos + CHUNK_HEADER_LEN + size]
        yield chunk_id, body
        # Chunks are padded to an even length; the pad byte is not counted in
        # the declared size.
        pos += CHUNK_HEADER_LEN + size + (size & 1)


def _markers(body: bytes) -> dict[int, int]:
    """MARK, as ``{marker id: frame position}``.

    Marker names are Pascal strings padded to an even total, and a malformed
    one would shift every marker after it -- so the walk stops at the first
    marker that does not fit rather than reading past it.
    """
    if len(body) < 2:
        return {}
    count = struct.unpack_from(">H", body, 0)[0]
    found: dict[int, int] = {}
    pos = 2
    for _ in range(count):
        if pos + 7 > len(body):
            break
        marker_id, position, name_len = struct.unpack_from(">hIB", body, pos)
        found[marker_id] = position
        pos += 7 + name_len + (1 - (name_len & 1))
    return found


def _swap(pcm: bytes, width: int) -> bytes:
    """Reverse the bytes within each sample. Big-endian in, little-endian out.

    Whole samples only: a payload whose length is not a multiple of the sample
    width has a partial sample at the end, and reversing that would move real
    audio bytes into the wrong sample rather than dropping a fragment.
    """
    usable = len(pcm) - len(pcm) % width
    out = bytearray(usable)
    for offset in range(width):
        out[offset::width] = pcm[width - 1 - offset : usable : width]
    return bytes(out)


def parse(payload: bytes, fallback_name: str = "") -> AiffSample:
    """One AIFF payload, with its audio carried to little-endian PCM."""
    if len(payload) < 12 or payload[:4] != MAGIC:
        raise NotASample("not a FORM")
    form = payload[8:12]
    if form == FORM_AIFC:
        raise NotASample("AIFF-C, which may be compressed and is not read")
    if form != FORM_AIFF:
        raise NotASample(f"FORM type {form!r} is not AIFF")

    channels = width = frames = rate = 0
    audio: bytes | None = None
    name = ""
    inst: bytes | None = None
    marks: dict[int, int] = {}

    for chunk_id, body in _chunks(payload):
        if chunk_id == b"COMM":
            if len(body) < 18:
                raise NotASample("COMM chunk is truncated")
            channels, frames, bits = struct.unpack_from(">HIH", body, 0)
            rate = _extended(body[8:18])
            width = (bits + 7) // 8
        elif chunk_id == b"SSND":
            if len(body) < 8:
                raise NotASample("SSND chunk is truncated")
            # The offset field is a gap before the audio, for block alignment.
            audio = body[8 + struct.unpack_from(">I", body, 0)[0] :]
        elif chunk_id == b"NAME":
            name = body.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
        elif chunk_id == b"INST":
            inst = body
        elif chunk_id == b"MARK":
            marks = _markers(body)

    if channels == 0 or width == 0:
        raise NotASample("no COMM chunk")
    if audio is None:
        raise NotASample("no SSND chunk")
    if width not in SUPPORTED_WIDTHS:
        raise NotASample(
            f"{width * 8}-bit AIFF is not carried to WAV: only byte order is "
            f"changed, and this depth would need the sample values changed too"
        )
    if channels < 1:
        raise NotASample(f"COMM declares {channels} channels")

    pcm = _swap(audio, width)
    block = channels * width
    # The disc is the authority on how much audio there is, not the header: a
    # truncated rip declares the frames it was mastered with and carries fewer.
    frames = min(frames, len(pcm) // block) if block else 0
    pcm = pcm[: frames * block]

    pitch, cents, loops = _instrument(inst, marks)
    return AiffSample(
        name=name or fallback_name,
        rate=rate,
        frames=frames,
        channels=channels,
        width=width,
        pcm=pcm,
        pitch=pitch,
        cents=cents,
        loops=loops,
    )


def _instrument(
    inst: bytes | None, marks: dict[int, int]
) -> tuple[int | None, float, tuple[SampleLoop, ...]]:
    """Root key, tuning and the sustain loop, from INST and the markers it names.

    A file with no INST gets ``None`` for the root key rather than a plausible
    60, so ``write_wav`` leaves the smpl chunk out entirely (ADR-0011).
    """
    if inst is None or len(inst) < 14:
        return None, 0.0, ()
    base_note, detune = struct.unpack_from(">bb", inst, 0)
    play_mode, begin_id, end_id = struct.unpack_from(">hhh", inst, 8)
    loop_type = _PLAY_MODES.get(play_mode)
    loops: tuple[SampleLoop, ...] = ()
    if loop_type is not None and begin_id in marks and end_id in marks:
        start, end = marks[begin_id], marks[end_id]
        # A loop that does not run forwards is not a loop, whatever the
        # markers say. Dropping it beats writing one a DAW would refuse.
        if end > start:
            loops = (SampleLoop(start=start, end=end, loop_type=loop_type),)
    if not 0 <= base_note <= 127:
        return None, 0.0, loops
    return base_note, float(detune), loops
