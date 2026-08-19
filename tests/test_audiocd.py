"""Red Book audio CDs: no filesystem, the sectors are the audio."""

from __future__ import annotations

import struct
import wave

from samplerdisc import cue
from samplerdisc.audiocd import AUDIO_SECTOR_SIZE, detect, extract_tracks
from tests import fixtures

CUE = """FILE "DISC.BIN" BINARY
  TRACK 01 AUDIO
    TITLE "01 Cyril Beats 100"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "02 User 135"
    INDEX 01 00:02:00
  TRACK 03 AUDIO
    INDEX 01 00:04:00
"""


def make_disc(tmp_path, sectors=450, name="disc"):
    """A synthetic audio CD: 6 seconds of tone across three tracks."""
    pcm = bytearray()
    for i in range(sectors * AUDIO_SECTOR_SIZE // 4):
        value = int(12000 * ((i % 200) / 200 - 0.5))
        pcm += struct.pack("<hh", value, -value)
    (tmp_path / f"{name}.bin").write_bytes(bytes(pcm))
    (tmp_path / f"{name}.cue").write_text(CUE.replace("DISC.BIN", f"{name}.bin"))
    return tmp_path / f"{name}.bin"


# --- cue parsing --------------------------------------------------------


def test_parses_tracks_titles_and_positions():
    sheet = cue.parse(CUE)
    assert sheet.data_file == "DISC.BIN"
    assert [t.number for t in sheet.tracks] == [1, 2, 3]
    assert sheet.tracks[0].title == "01 Cyril Beats 100"
    assert sheet.all_audio
    # 00:02:00 is two seconds in, at 75 frames per second.
    assert sheet.tracks[1].start_lba == 150


def test_msf_conversion():
    assert cue.msf_to_lba(0, 0, 0) == 0
    assert cue.msf_to_lba(1, 0, 8) == 4508


def test_a_data_cue_is_not_all_audio():
    sheet = cue.parse('FILE "X.BIN" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n')
    assert not sheet.all_audio
    assert sheet.data_sector_size() == 2352


# --- detection ----------------------------------------------------------


def test_detects_an_audio_cd(tmp_path):
    assert detect(make_disc(tmp_path)) is not None


def test_a_disc_without_a_cue_is_not_detected(tmp_path):
    """Nothing in the bytes distinguishes CD audio from any other PCM."""
    path = make_disc(tmp_path)
    (tmp_path / "disc.cue").unlink()
    assert detect(path) is None


def test_a_data_disc_is_not_an_audio_cd(tmp_path):
    (tmp_path / "d.bin").write_bytes(b"\x00" * (AUDIO_SECTOR_SIZE * 4))
    (tmp_path / "d.cue").write_text('FILE "D.BIN" BINARY\n  TRACK 01 MODE1/2352\n')
    assert detect(tmp_path / "d.bin") is None


def test_a_ragged_file_is_rejected(tmp_path):
    path = make_disc(tmp_path)
    path.write_bytes(path.read_bytes() + b"\x00" * 7)
    assert detect(path) is None


# --- extraction ---------------------------------------------------------


def test_tracks_are_written_as_stereo_wavs(tmp_path):
    path = make_disc(tmp_path)
    out = tmp_path / "out"
    tracks = list(extract_tracks(path, detect(path), str(out)))
    assert len(tracks) == 3
    written = out / "01 Cyril Beats 100.wav"
    assert written.exists()
    with wave.open(str(written)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 44100)


def test_audio_is_a_verbatim_copy_of_the_sectors(tmp_path):
    """CD audio is already 16-bit 44.1k stereo LE -- there is nothing to convert."""
    path = make_disc(tmp_path)
    raw = path.read_bytes()
    out = tmp_path / "out"
    list(extract_tracks(path, detect(path), str(out)))
    with wave.open(str(out / "01 Cyril Beats 100.wav")) as w:
        audio = w.readframes(w.getnframes())
    assert audio == raw[: 150 * AUDIO_SECTOR_SIZE]


def test_boundaries_come_from_the_cue(tmp_path):
    path = make_disc(tmp_path)
    out = tmp_path / "out"
    tracks = list(extract_tracks(path, detect(path), str(out)))
    # Tracks 1 and 2 are two seconds each; track 3 runs to the end.
    assert tracks[0].frames == 150 * 588
    assert tracks[1].frames == 150 * 588
    assert tracks[2].frames == 150 * 588


def test_an_untitled_track_gets_a_numbered_name(tmp_path):
    path = make_disc(tmp_path)
    out = tmp_path / "out"
    list(extract_tracks(path, detect(path), str(out)))
    assert (out / "Track 03.wav").exists()


# --- recognising CD audio without a cue (D11) ----------------------------


def _image(tmp_path, data: bytes, name: str):
    from samplerdisc.container.flat import FlatImage

    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


def test_gate_accepts_interleaved_stereo_audio(tmp_path):
    from samplerdisc.audiocd import looks_like_cd_audio

    data = fixtures.stereo_audio_block(frames=1 << 19)
    with _image(tmp_path, data, "audio.bin") as image:
        assert looks_like_cd_audio(image)


def test_gate_rejects_a_mono_sampler_payload(tmp_path):
    """The case a plain smoothness test gets wrong.

    Roland sample data is a smooth waveform, so "does this look like audio"
    says yes. It is mono, though, and read as stereo its lag-1 differences
    collapse -- which is what separates it from a Red Book disc. Measured on
    real discs: audio CDs 5.1-14.0, every sampler disc at or below 1.01.
    """
    from samplerdisc.audiocd import looks_like_cd_audio

    data = fixtures.mono_sample_block(frames=1 << 20)
    with _image(tmp_path, data, "mono.bin") as image:
        assert not looks_like_cd_audio(image)


def test_gate_rejects_noise(tmp_path):
    from samplerdisc.audiocd import looks_like_cd_audio

    data = b"".join(fixtures.incompressible_block(i) for i in range(24))
    with _image(tmp_path, data, "noise.bin") as image:
        assert not looks_like_cd_audio(image)


def test_gate_rejects_silence_rather_than_guessing(tmp_path):
    """No evidence is not the same as evidence of audio."""
    from samplerdisc.audiocd import looks_like_cd_audio

    with _image(tmp_path, b"\x00" * (1 << 20), "quiet.bin") as image:
        assert not looks_like_cd_audio(image)


def test_whole_disc_wav_is_a_verbatim_copy(tmp_path):
    """A raw audio sector is already what a WAV data chunk holds (ADR-0011)."""
    import wave

    from samplerdisc.audiocd import write_whole_disc

    data = fixtures.stereo_audio_block(frames=1 << 16)
    out = tmp_path / "whole.wav"
    with _image(tmp_path, data, "src.bin") as image:
        frames = write_whole_disc(image, out)

    assert frames == len(data) // 4
    with wave.open(str(out), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 44100
        assert handle.getsampwidth() == 2
        assert handle.readframes(handle.getnframes()) == data
