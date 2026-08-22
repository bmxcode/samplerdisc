"""An AKAI payload must be the file its directory entry placed (ADR-0027).

Two things are checked here and they arrived together, because ruling out the
false positive for one is what found the other.

**The header length.** S3000-family samples put 192 bytes in front of the
audio and S1000 ones 150, and the directory's type byte says which in its high
bit. Reading a 192 at 150 does not fail -- it writes a WAV holding 42 bytes of
header as PCM, 21 frames short at the end, with every loop point 21 frames out.

**The identity.** The payload repeats the id, the valid flag and the name the
directory already gave, and until D19 nothing compared them.

The name comparison has **no instance anywhere in the 44-disc collection** --
all 60 real disagreements also have a wrong id and a cleared valid flag,
because on those images the displacement lands mid-audio. So the only exercise
it gets is the synthetic one below, and that is stated rather than left for a
reader to discover from a coverage report.
"""

from __future__ import annotations

import pytest

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, Skipped, extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.sample import PayloadMismatch
from samplerdisc.sample.akai import HEADER_LEN_S1000, HEADER_LEN_S3000
from tests import fixtures

BACKEND = AkaiBackend()

#: Directory type bytes: 's' for a sample, with the high bit set on the S3000
#: family. That bit is the whole of what selects the header length.
S1000_SAMPLE = 0x73
S3000_SAMPLE = 0xF3
S1000_PROGRAM = 0x70


def disc(tmp_path, volumes, name="d.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(fixtures.akai_partition(volumes))
    return FlatImage(path)


def results(tmp_path, volumes, **kwargs):
    image = disc(tmp_path, volumes)
    return list(extract_disc(image, BACKEND, 0, str(tmp_path / "out"), **kwargs))


def one_volume(entries):
    return [("SOUP 101-103", entries)]


# --- the header length --------------------------------------------------


def test_an_s3000_entry_reads_its_payload_at_192(tmp_path):
    """The audio starts where the S3000 header ends, not where the S1000 one does.

    The assertion is on the *bytes*, against the payload the fixture built, so
    it fails if the parser takes the audio from anywhere else at all -- not on
    a frame count, which a 42-byte slip leaves very nearly right.
    """
    payload = fixtures.akai_sample("PIANO C3", words=64, header_len=HEADER_LEN_S3000)
    assert len(payload) == HEADER_LEN_S3000 + 128
    out = results(tmp_path, one_volume([("PIANO C3", S3000_SAMPLE, len(payload), payload)]))
    written = [r for r in out if isinstance(r, Extracted)]
    assert len(written) == 1
    sample = _parse(payload, s3000=True)
    assert sample.header_len == HEADER_LEN_S3000
    assert sample.frames == 64
    assert sample.pcm == payload[HEADER_LEN_S3000:]


def test_an_s1000_entry_still_reads_its_payload_at_150(tmp_path):
    payload = fixtures.akai_sample("KICK 1", words=64)
    assert len(payload) == HEADER_LEN_S1000 + 128
    sample = _parse(payload, s3000=False)
    assert (sample.header_len, sample.frames) == (HEADER_LEN_S1000, 64)
    assert sample.pcm == payload[HEADER_LEN_S1000:]
    out = results(tmp_path, one_volume([("KICK 1", S1000_SAMPLE, len(payload), payload)]))
    assert len([r for r in out if isinstance(r, Extracted)]) == 1


def test_reading_a_192_header_at_150_puts_header_bytes_in_the_audio(tmp_path):
    """What the bug sounded like, asserted rather than described.

    The first 42 bytes of the WAV were the tail of the header and the last 21
    frames of the sound were gone. Both halves are checked, because a fix that
    corrected the start and left the length short would pass the first alone.
    """
    payload = bytearray(fixtures.akai_sample("PIANO C3", words=64, header_len=HEADER_LEN_S3000))
    # Something recognisable in the 42 bytes the S1000 length would swallow.
    payload[HEADER_LEN_S1000:HEADER_LEN_S3000] = b"\xff\x7f" * 21
    wrong = _parse(bytes(payload), s3000=False)
    right = _parse(bytes(payload), s3000=True)
    # The head: 21 frames of header where the attack should be.
    assert wrong.pcm[:42] == b"\xff\x7f" * 21
    assert right.pcm == bytes(payload[HEADER_LEN_S3000:])
    # The tail: the same 42-byte slip drops the last 21 frames of the sound.
    assert wrong.pcm[42:] == right.pcm[: len(right.pcm) - 42]
    assert right.pcm[len(right.pcm) - 42 :] not in wrong.pcm


# --- the identity checks ------------------------------------------------


def test_a_payload_naming_another_file_is_refused(tmp_path):
    """The check this deliverable exists for, and the only place it is exercised.

    ``ALPHA``'s directory entry points at a payload that is a complete, valid,
    perfectly extractable sample -- of ``BETA``. Every other test in the suite
    would pass on it: the id is 3, the valid flag is set, the name decodes, the
    rate is 44 100. Only the comparison with the entry catches it, and without
    that this writes BETA's audio into ALPHA.wav and reports success.
    """
    payload = fixtures.akai_sample("BETA", words=64)
    out = results(tmp_path, one_volume([("ALPHA", S1000_SAMPLE, len(payload), payload)]))
    assert not [r for r in out if isinstance(r, Extracted)]
    (skipped,) = [r for r in out if isinstance(r, Skipped)]
    assert skipped.mismatch
    assert "the name 'BETA'" in skipped.reason
    assert "entry named 'ALPHA'" in skipped.reason


def test_a_payload_whose_id_is_not_a_sample_is_refused(tmp_path):
    payload = fixtures.akai_sample("KICK 1", sample_id=179)
    (skipped,) = _skips(tmp_path, [("KICK 1", S1000_SAMPLE, len(payload), payload)])
    assert skipped.mismatch
    assert "id 179 not 3" in skipped.reason


def test_a_payload_without_the_valid_flag_is_refused(tmp_path):
    payload = fixtures.akai_sample("KICK 1", valid=0x03)
    (skipped,) = _skips(tmp_path, [("KICK 1", S1000_SAMPLE, len(payload), payload)])
    assert skipped.mismatch
    assert "valid byte 0x03" in skipped.reason


def test_the_valid_byte_is_a_flag_not_a_value(tmp_path):
    """0x81 is 29 real samples on `AKAI.S3000.Sound.Library.2`, and 0x9c is two
    more on `Library.1`.

    Their id, name, rate and word count are all correct; requiring the byte to
    *equal* 0x80 discarded all 31 as damage. This is what makes the name check
    load-bearing rather than decorative: relaxing the flag is only safe because
    something else still asks whether the payload is this file.
    """
    for flag in (0x80, 0x81, 0x9C):
        payload = fixtures.akai_sample("CHOIR", words=64, valid=flag)
        assert _parse(payload, s3000=False).name == "CHOIR"


def test_an_implausible_rate_is_refused_but_is_not_a_mismatch(tmp_path):
    """Four files on the shelf, and they are a different fact from the other 61.

    `EG 2MUTE` declares 0 Hz, `M.VOICE A1` and `SYN 1` declare 519 and
    `HOUSE BASS` 1280 -- and on all four the id, the valid flag and the name
    agree with the directory. These *are* the files their entries placed, with
    one field unusable, so they are refused without being counted as the
    directory and the data having come apart (ADR-0024's principle, ADR-0027).
    """
    payload = fixtures.akai_sample("HOUSE BASS", rate=1280)
    (skipped,) = _skips(tmp_path, [("HOUSE BASS", S1000_SAMPLE, len(payload), payload)])
    assert not skipped.mismatch
    assert "implausible sample rate 1280" in skipped.reason


def test_a_program_is_never_condemned_by_the_sample_check(tmp_path):
    """A program's payload id is 1, not 3, and it must survive that.

    Programs hold the key ranges and envelopes a WAV cannot carry and the disc
    is the only copy, so `--keep-originals` writes them out verbatim. They
    never reach the sample parser -- if the id test ever started reading them
    it would condemn every program on every disc, and the symptom would be
    files quietly missing from ``original/``.
    """
    program = fixtures.akai_sample("BASS PRG", sample_id=1)
    sample = fixtures.akai_sample("BASS SMP", words=64)
    out = results(
        tmp_path,
        one_volume(
            [
                ("BASS PRG", S1000_PROGRAM, len(program), program),
                ("BASS SMP", S1000_SAMPLE, len(sample), sample),
            ]
        ),
        keep_originals=True,
    )
    kept = [r for r in out if type(r).__name__ == "Kept"]
    assert sorted(k.name for k in kept) == ["BASS PRG", "BASS SMP"]
    assert not [r for r in out if isinstance(r, Skipped)]


def test_parsing_bare_still_works_without_a_directory_entry(tmp_path):
    """``parse`` called with no declared name skips only the name test.

    The backend always supplies one; this is the floor for a caller that has a
    payload and nothing else, and it must not silently become a no-op check.
    """
    from samplerdisc.sample.akai import parse

    assert parse(fixtures.akai_sample("KICK 1")).name == "KICK 1"
    with pytest.raises(PayloadMismatch):
        parse(fixtures.akai_sample("KICK 1", sample_id=179))


# --- helpers ------------------------------------------------------------


def _parse(payload: bytes, *, s3000: bool):
    """Parse through the backend hook, which is where the two declared values
    -- the entry's name and its generation bit -- are handed across."""
    from samplerdisc.fs.akai import NAME_LEN, decode_name
    from samplerdisc.fs.base import File

    entry = File(
        name=decode_name(payload[3 : 3 + NAME_LEN]),
        kind="sample",
        size=len(payload),
        start_block=1,
        raw_type=S3000_SAMPLE if s3000 else S1000_SAMPLE,
    )
    return BACKEND.parse_sample(entry, payload)


def _skips(tmp_path, entries):
    out = results(tmp_path, one_volume(entries))
    assert not [r for r in out if isinstance(r, Extracted)]
    return [r for r in out if isinstance(r, Skipped)]
