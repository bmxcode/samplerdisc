"""AIFF payloads, and the one place this project re-orders audio bytes.

The parser's real oracle is a disc: Best Service mastered the ProSamples discs
with an AIFF tree beside a WAV tree of the same sounds, so the publisher's own
WAV says what our conversion should produce. That check lives in test_discs.py
because it needs the discs. What is here is the shape of the format and the
edges no disc in hand exercises.
"""

from __future__ import annotations

import struct

import pytest

from samplerdisc.sample import NotASample
from samplerdisc.sample.aiff import parse
from samplerdisc.wav import LOOP_ALTERNATING, LOOP_FORWARD
from tests import fixtures


def test_the_audio_is_the_same_values_with_their_bytes_reversed():
    """The conversion is a byte order change and nothing else.

    Asserted as an identity on the sample values rather than on the bytes, so
    it stays true if the fixture's audio changes: reading the payload
    big-endian and the result little-endian must give the same numbers.
    """
    sample = parse(fixtures.make_aiff(frames=64))
    source = fixtures.aiff_pcm(64)
    assert struct.unpack(">64h", source) == struct.unpack("<64h", sample.pcm)
    assert sample.pcm != source  # and it did have to be reversed


def test_the_swap_is_exactly_reversible():
    payload = fixtures.make_aiff(frames=48)
    once = parse(payload).pcm
    twice = bytes(b for pair in zip(once[1::2], once[0::2], strict=True) for b in pair)
    assert twice == fixtures.aiff_pcm(48)


def test_the_header_is_read():
    sample = parse(fixtures.make_aiff(frames=100, rate=22050, channels=2), fallback_name="x")
    assert (sample.rate, sample.channels, sample.width, sample.frames) == (22050, 2, 2, 100)
    assert len(sample.pcm) == 100 * 2 * 2


@pytest.mark.parametrize("rate", [8000, 22050, 44100, 48000, 96000, 33075, 44033])
def test_the_80_bit_extended_sample_rate_round_trips(rate):
    """Including the odd rates these libraries really use.

    Done in integer arithmetic in the parser because the mantissa is 64 bits
    and a double holds 53; 44 033 is a rate one of these discs actually
    carries, so this is not a hypothetical.
    """
    assert parse(fixtures.make_aiff(rate=rate)).rate == rate


def test_a_name_chunk_is_preferred_over_the_filename():
    named = parse(fixtures.make_aiff(name="Conga Mute"), fallback_name="42x.aif")
    assert named.name == "Conga Mute"
    assert parse(fixtures.make_aiff(), fallback_name="42x.aif").name == "42x.aif"


def test_the_ssnd_offset_is_a_gap_before_the_audio():
    """Skipping it is what keeps the audio aligned; reading from the wrong
    place produces a file that plays as noise and reports nothing wrong."""
    sample = parse(fixtures.make_aiff(frames=32, ssnd_offset=8))
    assert struct.unpack("<32h", sample.pcm) == struct.unpack(">32h", fixtures.aiff_pcm(32))


def test_a_loop_and_a_root_key_come_from_inst_and_the_markers_it_names():
    sample = parse(fixtures.make_aiff(frames=200, loop=(64, 192), base_note=48, detune=-7))
    assert sample.pitch == 48
    assert sample.cents == -7.0
    assert [(loop.start, loop.end, loop.loop_type) for loop in sample.loops] == [
        (64, 192, LOOP_FORWARD)
    ]


def test_an_alternating_loop_keeps_its_type():
    sample = parse(fixtures.make_aiff(frames=200, loop=(10, 100), play_mode=2))
    assert sample.loops[0].loop_type == LOOP_ALTERNATING


def test_play_mode_none_means_no_loop_however_the_markers_read():
    sample = parse(fixtures.make_aiff(frames=200, loop=(10, 100), play_mode=0))
    assert sample.loops == ()
    assert sample.pitch == 60  # the root key is still good


def test_a_file_with_no_inst_offers_no_root_key():
    """None rather than a plausible 60, so write_wav leaves the smpl chunk out
    entirely rather than mapping every sample to middle C (ADR-0011)."""
    sample = parse(fixtures.make_aiff())
    assert sample.pitch is None
    assert sample.loops == ()


def test_aifc_is_refused_rather_than_read_as_pcm():
    """Its payload may be compressed, and compressed data emitted as PCM opens,
    plays as noise, and reports nothing wrong."""
    with pytest.raises(NotASample, match="AIFF-C"):
        parse(fixtures.make_aiff(form=b"AIFC"))


def test_eight_bit_is_refused_because_carrying_it_would_change_the_values():
    """AIFF 8-bit is signed and WAV 8-bit is unsigned. Converting means adding
    128 to every sample, which is a conversion, not a byte order change."""
    with pytest.raises(NotASample, match="8-bit"):
        parse(fixtures.make_aiff(bits=8, pcm=b"\x01\x02\x03\x04"))


def test_twenty_four_bit_is_carried_because_only_the_order_changes():
    payload = fixtures.make_aiff(bits=24, frames=4, pcm=bytes(range(12)))
    sample = parse(payload)
    assert sample.width == 3
    assert sample.pcm == bytes([2, 1, 0, 5, 4, 3, 8, 7, 6, 11, 10, 9])


def test_a_truncated_payload_yields_the_audio_it_has():
    """These are rips and a lost tail is normal: the file declares 400 frames
    and carries 40, and the 40 are worth having."""
    sample = parse(fixtures.make_aiff(frames=40, declared_frames=400))
    assert sample.frames == 40
    assert len(sample.pcm) == 80


def test_a_partial_sample_at_the_end_is_dropped_not_reversed():
    """Reversing a fragment would move real audio bytes into the wrong sample.
    Losing an odd byte is right; shifting the tail is not."""
    sample = parse(fixtures.make_aiff(frames=4, pcm=fixtures.aiff_pcm(4) + b"\x7f"))
    assert len(sample.pcm) % 2 == 0
    assert struct.unpack("<4h", sample.pcm) == struct.unpack(">4h", fixtures.aiff_pcm(4))


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (b"", "not a FORM"),
        (b"RIFF" + b"\x00" * 20, "not a FORM"),
        (b"FORM" + struct.pack(">I", 4) + b"8SVX", "not AIFF"),
    ],
)
def test_something_that_is_not_an_aiff_is_refused(payload, match):
    with pytest.raises(NotASample, match=match):
        parse(payload)


def test_a_form_with_no_ssnd_is_refused():
    payload = fixtures.make_aiff()
    payload = payload[: payload.index(b"SSND")]
    with pytest.raises(NotASample, match="no SSND"):
        parse(payload)
