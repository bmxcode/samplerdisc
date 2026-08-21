"""Sample parsing and extraction, against synthetic discs (ADR-0008)."""

from __future__ import annotations

import struct
import wave

import pytest

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, Skipped, extract_disc, safe_name, unique_path
from samplerdisc.fs.akai import SAMPLE_HEADER_LEN, AkaiBackend
from samplerdisc.fs.iso9660 import Iso9660Backend
from samplerdisc.sample.akai import NotASample, parse
from samplerdisc.wav import Loop, write_wav
from tests import fixtures

BACKEND = AkaiBackend()


def disc(tmp_path, volumes, name="d.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(fixtures.akai_partition(volumes))
    return FlatImage(path)


# --- parsing ------------------------------------------------------------


def test_parse_reads_the_header_fields():
    payload = fixtures.akai_sample("KICK 1", rate=22050, words=128, pitch=48)
    sample = parse(payload)
    assert (sample.name, sample.rate, sample.pitch, sample.frames) == ("KICK 1", 22050, 48, 128)
    assert sample.pcm == payload[SAMPLE_HEADER_LEN:]


def test_parse_rejects_a_payload_that_is_not_a_sample():
    with pytest.raises(NotASample):
        parse(b"\x00" * 400)


def test_parse_rejects_an_implausible_rate():
    payload = bytearray(fixtures.akai_sample("X"))
    struct.pack_into("<H", payload, 138, 65535)
    with pytest.raises(NotASample, match="implausible sample rate"):
        parse(bytes(payload))


def test_parse_clamps_a_truncated_tail():
    """Declared length beyond what is present yields a short sample, not a crash."""
    payload = bytearray(fixtures.akai_sample("X", words=1000))
    truncated = bytes(payload[: SAMPLE_HEADER_LEN + 100])  # 50 frames present
    sample = parse(truncated)
    assert sample.frames == 50
    assert len(sample.pcm) == 100


# --- naming -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MOVIN 105 -L", "MOVIN 105 -L"),
        ("A/B:C", "A_B_C"),
        ("  padded  ", "padded"),
        ("...", "unnamed"),
        ("", "unnamed"),
        ("KICK#1+2", "KICK#1+2"),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_unique_path_avoids_collisions(tmp_path):
    """Sanitising can map two distinct AKAI names onto one filename."""
    first = unique_path(str(tmp_path), "KICK")
    open(first, "w").close()
    second = unique_path(str(tmp_path), "KICK")
    assert first != second
    assert second.endswith("KICK_2.wav")


# --- extraction ---------------------------------------------------------


def test_extracts_samples_to_playable_wavs(tmp_path):
    payload = fixtures.akai_sample("KICK 1", rate=44100, words=200)
    image = disc(tmp_path, [("VOL 1", [("KICK 1", 0x73, len(payload), payload)])])
    out = tmp_path / "out"
    results = list(extract_disc(image, BACKEND, 0, str(out)))
    assert len(results) == 1
    written = out / "partition-1" / "VOL 1" / "KICK 1.wav"
    assert written.exists()
    with wave.open(str(written)) as w:
        assert w.getframerate() == 44100
        assert w.getnframes() == 200
        assert w.readframes(200) == payload[SAMPLE_HEADER_LEN:]


def test_programs_are_not_written(tmp_path):
    payload = fixtures.akai_sample("KICK 1")
    image = disc(
        tmp_path,
        [("VOL 1", [("A PROG", 0x70, 64, b"\x01" * 64), ("KICK 1", 0x73, len(payload), payload)])],
    )
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    assert sorted(p.name for p in (out / "partition-1" / "VOL 1").iterdir()) == ["KICK 1.wav"]


def test_a_damaged_entry_is_skipped_and_the_rest_still_extract(tmp_path):
    """One bad sample must not cost the disc. This is the loopsoup case."""
    good = fixtures.akai_sample("GOOD")
    image = disc(
        tmp_path,
        [
            (
                "VOL 1",
                [
                    ("BROKEN", 0x73, 4096, b"\xc3\x01\x00" + b"\x9a" * 4093),
                    ("GOOD", 0x73, len(good), good),
                ],
            )
        ],
    )
    out = tmp_path / "out"
    results = list(extract_disc(image, BACKEND, 0, str(out)))
    skipped = [r for r in results if isinstance(r, Skipped)]
    assert len(skipped) == 1
    assert skipped[0].name == "BROKEN"
    assert (out / "partition-1" / "VOL 1" / "GOOD.wav").exists()


def test_each_volume_gets_its_own_directory(tmp_path):
    a = fixtures.akai_sample("A")
    b = fixtures.akai_sample("B")
    image = disc(
        tmp_path,
        [("VOL 1", [("A", 0x73, len(a), a)]), ("VOL 2", [("B", 0x73, len(b), b)])],
    )
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    assert (out / "partition-1" / "VOL 1" / "A.wav").exists()
    assert (out / "partition-1" / "VOL 2" / "B.wav").exists()


def test_volumes_of_one_name_in_two_partitions_do_not_share_a_directory(tmp_path):
    """Nearly every partition of an AKAI disc has a 'VOLUME 001' (ADR-0023).

    Written flat, the second one's audio lands beside the first's under
    ``unique_path`` suffixes -- two libraries in one directory with nothing
    saying which sample came from where. That is not a lost file, it is an
    unusable one, which is why the partition is part of the path.
    """
    first = fixtures.akai_sample("PIANO C3", words=64)
    second = fixtures.akai_sample("PIANO C3", words=128)
    data = fixtures.akai_disc(
        [
            fixtures.akai_partition([("VOLUME 001", [("PIANO C3", 0x73, len(first), first)])]),
            fixtures.akai_partition([("VOLUME 001", [("PIANO C3", 0x73, len(second), second)])]),
        ]
    )
    path = tmp_path / "two.iso"
    path.write_bytes(data)
    image = FlatImage(path)
    out = tmp_path / "out"
    written = [r.path for r in extract_disc(image, BACKEND, 0, str(out))]
    assert written == [
        str(out / "partition-1" / "VOLUME 001" / "PIANO C3.wav"),
        str(out / "partition-2" / "VOLUME 001" / "PIANO C3.wav"),
    ]
    # And they are the two different samples, not one written twice.
    with wave.open(written[0]) as one, wave.open(written[1]) as two:
        assert (one.getnframes(), two.getnframes()) == (64, 128)


def _iso_results(tmp_path, files, **kwargs):
    """Extract one synthetic ISO 9660 disc and return what came back."""
    path = tmp_path / "d.iso"
    path.write_bytes(fixtures.make_iso9660(files, **kwargs))
    image = FlatImage(path)
    backend = Iso9660Backend()
    return list(extract_disc(image, backend, 0, str(tmp_path / "out")))


def test_an_aiff_whose_audio_is_already_written_is_skipped_not_written(tmp_path):
    """Best Service shipped these discs with an AIFF tree beside a WAV tree of
    the same sounds. Writing both gives every sample twice for no extra
    audio (ADR-0024)."""
    pcm = fixtures.aiff_pcm(64)
    wav = _wav_bytes(tmp_path, _swapped(pcm), rate=44100)
    results = _iso_results(tmp_path, {"A.AIF": fixtures.make_aiff(frames=64), "A.WAV": wav})

    written = [r for r in results if isinstance(r, Extracted)]
    duplicates = [r for r in results if isinstance(r, Skipped) and r.duplicate]
    assert [r.name for r in written] == ["A.WAV"]
    assert [r.name for r in duplicates] == ["A.AIF"]
    assert "A.WAV" in duplicates[0].reason


def test_an_aiff_with_different_audio_is_written_however_it_is_named(tmp_path):
    """The twin is recognised by its audio and not by its name. ProSamples
    vol.43 carries pairs that share a name and differ by eleven frames, and
    those are two different sounds."""
    wav = _wav_bytes(tmp_path, _swapped(fixtures.aiff_pcm(64)), rate=44100)
    results = _iso_results(tmp_path, {"A.AIF": fixtures.make_aiff(frames=48), "A.WAV": wav})

    assert sorted(r.name for r in results if isinstance(r, Extracted)) == ["A.AIF", "A.WAV"]
    assert not [r for r in results if isinstance(r, Skipped) and r.duplicate]


def test_the_twin_is_kept_when_it_carries_a_loop_the_wav_has_nowhere(tmp_path):
    """Same audio is not the same file. On 314 of these pairs the AIFF holds a
    root key and a loop and the plain WAV holds neither, so deduplicating on
    the audio alone would drop the metadata with it."""
    pcm = fixtures.aiff_pcm(200)
    plain = _wav_bytes(tmp_path, _swapped(pcm), rate=44100)
    aiff_with_loop = fixtures.make_aiff(frames=200, loop=(64, 192), base_note=48)
    results = _iso_results(tmp_path, {"A.AIF": aiff_with_loop, "A.WAV": plain})

    written = sorted(r.name for r in results if isinstance(r, Extracted))
    assert written == ["A.AIF", "A.WAV"]


def test_the_twin_is_dropped_when_the_wav_already_carries_the_metadata(tmp_path):
    """And where both carry it they agree: checked on 173 ProSamples pairs
    against the publisher's own smpl chunk."""
    pcm = fixtures.aiff_pcm(200)
    path = tmp_path / "rich.wav"
    write_wav(path, _swapped(pcm), rate=44100, midi_note=48, loops=[Loop(start=64, end=191)])
    aiff_with_loop = fixtures.make_aiff(frames=200, loop=(64, 192), base_note=48)
    results = _iso_results(tmp_path, {"A.AIF": aiff_with_loop, "A.WAV": path.read_bytes()})

    assert [r.name for r in results if isinstance(r, Extracted)] == ["A.WAV"]
    assert [r.name for r in results if isinstance(r, Skipped) and r.duplicate] == ["A.AIF"]


def test_a_copied_wav_reports_the_rate_and_length_it_declares(tmp_path):
    """A run that cannot say what it wrote reported nothing. Every ISO 9660
    payload used to come back as 0 Hz and 0 frames."""
    wav = _wav_bytes(tmp_path, _swapped(fixtures.aiff_pcm(64)), rate=22050)
    results = _iso_results(tmp_path, {"A.WAV": wav})
    extracted = next(r for r in results if isinstance(r, Extracted))
    assert (extracted.rate, extracted.frames) == (22050, 64)


def test_a_converted_aiff_reports_the_rate_and_length_it_declares(tmp_path):
    results = _iso_results(tmp_path, {"A.AIF": fixtures.make_aiff(frames=64, rate=22050)})
    extracted = next(r for r in results if isinstance(r, Extracted))
    assert (extracted.rate, extracted.frames) == (22050, 64)


def _swapped(pcm: bytes) -> bytes:
    """The same 16-bit samples, little-endian."""
    return bytes(b for pair in zip(pcm[1::2], pcm[0::2], strict=True) for b in pair)


def _wav_bytes(tmp_path, pcm: bytes, rate: int) -> bytes:
    path = tmp_path / "w.wav"
    write_wav(path, pcm, rate=rate)
    return path.read_bytes()


# --- a sample that is stereo on the disc (D18, ADR-0026) ------------------


def test_a_stereo_emu_record_is_written_as_one_stereo_wav(tmp_path):
    """Not two files, and not in ``stereo/``.

    ``<volume>/stereo/`` means "joined from two mono files whose names looked
    like a pair" (ADR-0007, ADR-0017). This record is not a join: the disc
    declared two channels in the sample record itself, so the file belongs in
    the volume directory under its own name, and there is no mono half to keep
    alongside it (ADR-0026).
    """
    from samplerdisc.fs.emu3 import Emu3Backend

    path = tmp_path / "emu.iso"
    path.write_bytes(
        fixtures.emu3_disc(
            [("Default Folder", [("Bank One        ", [("Wide", 22050, 4000)])])],
            stereo=("Wide",),
        )
    )
    image = FlatImage(path)
    out = tmp_path / "out"
    results = [
        r for r in extract_disc(image, Emu3Backend(), 0, str(out)) if isinstance(r, Extracted)
    ]
    assert len(results) == 1
    assert results[0].channels == 2
    written = out / "Bank One" / "Wide.wav"
    assert written.exists()
    assert not (out / "Bank One" / "stereo").exists()
    with wave.open(str(written)) as w:
        assert w.getnchannels() == 2
        assert w.getnframes() == results[0].frames
        # Frames, not samples: the duration the CLI prints is the sound's.
        assert w.getnframes() * 4 == len(w.readframes(w.getnframes()))
