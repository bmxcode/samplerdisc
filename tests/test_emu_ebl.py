"""E-mu Emulator X ``.EBL`` sample banks. See docs/formats/emu-ebl.md.

The parser's real oracle is mattetti's publisher-grade renders of the Vintage
Pro bank: every one of the disc's 1 057 mono samples decodes byte-for-byte to
the same PCM at the same rate. That check needs the disc and the oracle, so it
lives in test_discs.py. What is here is the shape of the format and the edges
that oracle does not reach -- the loop trailer, a refused stereo record, a
truncated tail.
"""

from __future__ import annotations

import os

import pytest

from samplerdisc.extract import extract_volume
from samplerdisc.sample import NotASample
from samplerdisc.sample.emu_ebl import parse
from tests import fixtures


def test_the_header_name_is_read_not_the_iso_name():
    """The output is named from the 64-byte UTF-16LE header, trimmed.

    The ISO 9660 names are a meaningless sequence; the header carries the real
    name, space-padded, and the padding is trimmed.
    """
    sample = parse(fixtures.make_ebl(name="EP4MKIIL A0"))
    assert sample.name == "EP4MKIIL A0"


def test_mono_audio_is_carried_verbatim():
    """An EBL is already little-endian PCM -- copied, not re-ordered."""
    pcm = bytes(range(256)) * 4
    sample = parse(fixtures.make_ebl(pcm=pcm, rate=32010))
    assert sample.pcm == pcm
    assert sample.channels == 1
    assert sample.rate == 32010
    assert sample.frames == len(pcm) // 2


def test_the_rate_is_read_from_the_record_not_assumed():
    """Rates vary wildly across a bank; the record is the authority."""
    assert parse(fixtures.make_ebl(rate=48139)).rate == 48139
    assert parse(fixtures.make_ebl(rate=22050)).rate == 22050


def test_a_loop_is_read_from_the_exlz_trailer():
    """The EXLZ/MARK trailer carries a start and end frame, little-endian."""
    sample = parse(fixtures.make_ebl(pcm=b"\x00\x00" * 512, loop=(100, 400)))
    assert len(sample.loops) == 1
    assert (sample.loops[0].start, sample.loops[0].end) == (100, 400)


def test_a_file_with_no_trailer_carries_no_loop():
    assert parse(fixtures.make_ebl(pcm=b"\x00\x00" * 64)).loops == ()


def test_a_loop_past_the_audio_is_dropped_not_written():
    """A loop a DAW would refuse is worse than none, so it is dropped."""
    sample = parse(fixtures.make_ebl(pcm=b"\x00\x00" * 64, loop=(10, 5000)))
    assert sample.loops == ()


def test_a_stereo_record_is_refused_with_a_reason():
    """Stereo is detected from the record's channel field (V12), and the
    interleave is deferred to #57, so a stereo EBL is refused rather than
    converted by an unverified rule (ADR-0026)."""
    with pytest.raises(NotASample, match="stereo"):
        parse(fixtures.make_ebl(stereo=True))


def test_the_channel_count_is_read_from_v12_not_the_spans():
    """The channel byte of V12 is the authority. 0x03 is stereo and refused;
    0x01 is mono and converted -- the spans D33 read invert between banks."""
    assert parse(fixtures.make_ebl(channel_byte=0x01)).channels == 1
    with pytest.raises(NotASample, match="stereo"):
        parse(fixtures.make_ebl(channel_byte=0x03))


def test_the_0x02_channel_byte_is_a_mono_subtype_not_stereo():
    """Vintage Pro has 38 mono files whose V12 channel byte is 0x02, verified
    mono against the render. The test is equality to 0x03, so 0x02 stays mono --
    reading it as 'not 0x01, therefore stereo' would misclassify all 38."""
    pcm = bytes(range(256)) * 2
    sample = parse(fixtures.make_ebl(pcm=pcm, channel_byte=0x02))
    assert sample.channels == 1
    assert sample.pcm == pcm


def test_the_audio_is_located_from_v2_whatever_the_pad():
    """The pad before the audio varies by bank (8 on Vintage Pro, 4 on Dance
    2000); V2 records it, so the audio is found at block + V2 - 4 rather than a
    fixed offset. The same PCM is recovered whichever pad the bank wrote."""
    pcm = bytes(range(256)) * 3
    for pad in (4, 8, 12):
        sample = parse(fixtures.make_ebl(pcm=pcm, pad=pad))
        assert sample.pcm == pcm, pad


def test_the_length_runs_to_the_trailer_or_the_end_of_the_file():
    """The audio ends at the EXLZ trailer when there is one and at the end of
    the file when there is not -- both give exactly the PCM, no trailing frame
    from the loop trailer and none short."""
    pcm = b"\x01\x02" * 500
    assert parse(fixtures.make_ebl(pcm=pcm)).pcm == pcm
    looped = parse(fixtures.make_ebl(pcm=pcm, loop=(10, 400)))
    assert looped.pcm == pcm
    assert looped.frames == len(pcm) // 2


def test_a_form_that_is_not_an_ebl_is_refused():
    """AIFF is a FORM too; only E5B0TOC2 makes it an EBL."""
    with pytest.raises(NotASample):
        parse(fixtures.make_ebl(toc=b"AIFFxxxx"))


def test_not_a_form_is_refused():
    with pytest.raises(NotASample):
        parse(b"RIFF" + b"\x00" * 200)


def test_a_truncated_tail_degrades_and_does_not_crash():
    """These are rips; a file that loses its tail still yields the audio ahead
    of it rather than raising."""
    whole = fixtures.make_ebl(pcm=bytes(range(256)) * 4)
    sample = parse(whole[:-50])
    assert sample.frames > 0
    assert sample.frames < 512


def test_extract_names_from_the_header_under_the_bank_folder(tmp_path):
    """End to end: the WAV keeps the disc's bank folder and takes the header
    name, and a colliding header name is disambiguated rather than overwritten.
    """
    from samplerdisc.fs.base import File, Volume

    backend = _StubBackend(
        {
            "Bank.exb/SamplePool/S001.ebl": fixtures.make_ebl(name="EP4 A0", rate=40000),
            "Bank.exb/SamplePool/S002.ebl": fixtures.make_ebl(name="EP4 A0", rate=40000),
        }
    )
    volume = Volume(
        name="TestBank",
        start_block=0,
        files=[
            File(name=n, kind="ebl", size=len(p), start_block=0)
            for n, p in backend.payloads.items()
        ],
    )
    out = tmp_path / "out"
    results = list(extract_volume(None, backend, 0, volume, str(out)))
    written = {os.path.relpath(r.path, out) for r in results if hasattr(r, "path")}
    sub = os.path.join("Bank.exb", "SamplePool")
    assert os.path.join(sub, "EP4 A0.wav") in written
    assert os.path.join(sub, "EP4 A0_2.wav") in written


class _StubBackend:
    """The barest backend: it hands back payloads by name, so the extract path
    can be exercised without building a whole ISO 9660 image."""

    name = "stub"

    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads

    def read_file(self, image, origin, entry):
        return self.payloads[entry.name]
