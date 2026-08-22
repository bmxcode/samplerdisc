"""AKAI S1000/S3000 sample payloads. See docs/formats/akai-fs.md.

The payload is signed 16-bit little-endian mono PCM, which is exactly what a
WAV data chunk holds -- so nothing here converts audio. It parses a header and
hands the bytes on untouched.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from samplerdisc.fs.akai import NAME_LEN, decode_name, is_plausible_name
from samplerdisc.sample import NotASample as _NotASample
from samplerdisc.sample import PayloadMismatch as _PayloadMismatch

#: Two header lengths, and **which one applies is declared, not sniffed**: the
#: S3000 family writes 192 bytes and the S1000 family 150. The directory's type
#: byte carries the generation in its high bit -- the same bit that already
#: names a kept original `.s3s` rather than `.s1s` -- and it splits the 56 490
#: samples of the 44 discs perfectly, 13 451 at 192 and 42 989 at 150, with no
#: disc mixing the two rules.
#:
#: The payload confirms it from the other side: the directory's declared size
#: is ``words * 2 + header_len`` on **56 430 of 56 430** readable payloads, and
#: the 60 that fail that identity are the damaged ones. Placed by one
#: structure, confirmed by another, the shape ADR-0020, ADR-0021 and ADR-0023
#: already use. See docs/formats/akai-fs.md and ADR-0027.
HEADER_LEN_S1000 = 150
HEADER_LEN_S3000 = 192

SAMPLE_ID = 3

#: The valid **flag**, tested as a bit and not as a whole byte. 29 samples on
#: `AKAI.S3000.Sound.Library.2` carry 0x81 and two on `Library.1` carry 0x9c,
#: with a correct id, a correct name, a plausible rate and a word count the
#: directory's size agrees with. Requiring the byte to equal 0x80 threw all 31
#: away as damage (ADR-0027).
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


class NotASample(_NotASample):
    """The payload does not begin with a sample header."""


class PayloadMismatch(_PayloadMismatch, NotASample):
    """The payload is not the file the directory entry placed here."""


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


def _check_identity(payload: bytes, declared_name: str | None) -> str:
    """Is this payload the file the directory placed here? Returns its name.

    Every AKAI sample payload repeats what the directory already said -- an id,
    a valid flag and the name -- and until D19 nothing compared the two. The
    tests run in the order a failure is most informative in, and each names the
    field and both values, because "does not start with an AKAI sample header"
    is true of a mid-PCM payload and of a wrong-but-valid one alike and they
    are not the same news.

    **What the name test is for.** Across the 44 AKAI discs it fires 60 times
    and never once on its own: every payload whose name disagrees also has a
    wrong id and a cleared valid flag, because on these images the displacement
    lands mid-audio rather than on another header. It is kept regardless. The
    other three ask whether the payload is *a* sample; only this one asks
    whether it is *this* sample, which is the failure issue #23 named and the
    one a short image's recovered partitions would raise (#25). It is also what
    makes the valid flag safe to read as a bit rather than as a byte.
    See ADR-0027.
    """
    if len(payload) <= OFF_RATE + 2:
        raise NotASample(f"payload is {len(payload)} bytes, too short for a sample header")

    # Every disagreement is collected rather than the first one raised. On the
    # 61 real mismatches the id is wrong on all of them, so stopping at the
    # first would report "id is 179" every time and never once mention the name
    # -- which is the test that says the payload belongs to a different file
    # rather than to none. What the fields disagree about *together* is also
    # the diagnosis: id, valid and name all wrong is a payload that is
    # mid-audio, while a name alone is one sample's header under another's
    # entry, and those want different answers from whoever reads the log.
    wrong: list[str] = []
    if payload[OFF_ID] != SAMPLE_ID:
        wrong.append(f"id {payload[OFF_ID]} not {SAMPLE_ID}")
    if not payload[OFF_VALID] & VALID_FLAG:
        wrong.append(f"valid byte 0x{payload[OFF_VALID]:02x} without the 0x80 flag")
    raw = payload[OFF_NAME : OFF_NAME + NAME_LEN]
    name = decode_name(raw) if is_plausible_name(raw) else ""
    if not is_plausible_name(raw):
        wrong.append("a name that does not decode in the AKAI charset")
    elif declared_name is not None and name != declared_name:
        wrong.append(f"the name {name!r}")
    if wrong:
        placed = f", placed by an entry named {declared_name!r}" if declared_name else ""
        raise PayloadMismatch(f"payload header carries {', '.join(wrong)}{placed}")
    return name


def parse(
    payload: bytes,
    fallback_name: str = "",
    *,
    declared_name: str | None = None,
    s3000: bool = False,
) -> AkaiSample:
    """Parse a sample file. Raises NotASample if the payload is not one.

    ``declared_name`` is the name the directory entry gave this file, and where
    one is supplied the payload's own name must match it. ``s3000`` says the
    entry's type byte carries the S3000 generation bit, which is what chooses
    between the two header lengths.

    Both come from the directory rather than from these bytes, so they arrive
    through ``AkaiBackend.parse_sample``; called bare, this parses a payload on
    its own terms as it always did.

    Lengths are clamped to what is actually present: a truncated tail is common
    in these rips and yields a short sample rather than an exception.
    """
    name = _check_identity(payload, declared_name) or fallback_name
    pitch = payload[OFF_PITCH]
    (words,) = struct.unpack_from("<I", payload, OFF_WORDS)
    (rate,) = struct.unpack_from("<H", payload, OFF_RATE)
    if not MIN_RATE <= rate <= MAX_RATE:
        # Not a PayloadMismatch: on all four occurrences the id, the valid flag
        # and the name agree with the directory, so this *is* the file the
        # entry placed -- with one field of it unusable. 65535 is the giveaway
        # for the damaged case: an unwritten field reads as all ones, and it
        # sits inside any range generous enough to be "safe".
        raise NotASample(f"implausible sample rate {rate}")

    header_len = HEADER_LEN_S3000 if s3000 else HEADER_LEN_S1000
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
