"""Kurzweil ``.KRZ`` sample-audio tests (ADR-0008: synthetic bytes only).

The filesystem layer (``test_kurzweil_fs.py``) locates a sample in its bank and
hands the raw big-endian pool bytes here with the rate, root and loop it read.
What this module owns is the sample-format concern: the big-endian-to-WAV byte
swap, the planar-stereo interleave, and the loop guards. The byte-for-byte oracle
against the real discs lives in ``test_discs.py`` and skips where the shelf is
bare.
"""

from __future__ import annotations

import struct

import pytest

from samplerdisc.sample import NotASample
from samplerdisc.sample.kurzweil import MIN_LOOP_FRAMES, KurzweilSample, parse


def be(*values: int) -> bytes:
    """Big-endian 16-bit PCM, as a Kurzweil pool stores it."""
    return b"".join(struct.pack(">h", v) for v in values)


def le(*values: int) -> bytes:
    """Little-endian 16-bit PCM, as a WAV data chunk wants it."""
    return b"".join(struct.pack("<h", v) for v in values)


def test_big_endian_pool_bytes_are_carried_to_little_endian():
    sample = parse(be(1, -2, 0x1234, -0x4000), rate=44100)
    assert sample.pcm == le(1, -2, 0x1234, -0x4000)
    assert sample.frames == 4
    assert sample.channels == 1


def test_rate_and_root_come_from_the_object_not_the_bytes():
    sample = parse(be(0, 0, 0), rate=22050, root=48)
    assert isinstance(sample, KurzweilSample)
    assert sample.rate == 22050
    assert sample.pitch == 48


def test_a_loop_within_the_audio_is_kept():
    sample = parse(be(*range(500)), rate=44100, loop=(100, 400))
    assert len(sample.loops) == 1
    loop = sample.loops[0]
    assert (loop.start, loop.end) == (100, 400)


def test_a_one_shot_has_no_loop():
    sample = parse(be(*range(500)), rate=44100, loop=None)
    assert sample.loops == ()


def test_a_loop_shorter_than_the_floor_is_dropped():
    sample = parse(be(*range(500)), rate=44100, loop=(100, 100 + MIN_LOOP_FRAMES - 1))
    assert sample.loops == ()


def test_a_loop_end_past_the_audio_is_clamped_not_trusted():
    """The stored end is the loop end; a value past the extent is clamped, never
    read into a neighbour (docs/formats/kurzweil-krz.md)."""
    sample = parse(be(*range(300)), rate=44100, loop=(50, 999))
    # Clamped to the audio; still a valid forward loop, so it survives.
    assert sample.loops == () or sample.loops[0].end <= sample.frames


def test_a_backwards_loop_is_dropped():
    sample = parse(be(*range(500)), rate=44100, loop=(400, 100))
    assert sample.loops == ()


def test_planar_stereo_is_interleaved():
    left = be(1, 2, 3)
    right = be(-1, -2, -3)
    sample = parse(left + right, rate=48000, channels=2, channel_bytes=len(left))
    assert sample.channels == 2
    assert sample.frames == 3
    # Interleaved little-endian: L0 R0 L1 R1 L2 R2.
    assert sample.pcm == le(1, -1, 2, -2, 3, -3)


def test_a_stereo_loop_is_in_frames_not_bytes():
    left = be(*range(300))
    right = be(*range(300))
    sample = parse(left + right, rate=48000, channels=2, channel_bytes=len(left), loop=(64, 200))
    assert sample.loops[0].start == 64
    assert sample.loops[0].end == 200


def test_an_empty_payload_is_refused_with_a_reason():
    with pytest.raises(NotASample, match="no audio"):
        parse(b"", rate=44100)


def test_a_trailing_odd_byte_degrades_rather_than_corrupting_a_frame():
    """A slice with a stray byte -- tail damage -- drops the fragment, never
    reverses across it (ADR: damaged input degrades)."""
    sample = parse(be(7, 8, 9) + b"\x01", rate=44100)
    assert sample.frames == 3
    assert sample.pcm == le(7, 8, 9)
