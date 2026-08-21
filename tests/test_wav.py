"""WAV writer tests. The stdlib reader is a strict-enough structural validator."""

from __future__ import annotations

import struct
import wave

import pytest

from samplerdisc.wav import DEFAULT_ROOT_KEY, Loop, write_wav


def pcm(frames: int, channels: int = 1) -> bytes:
    return b"".join(struct.pack("<h", (i * 137) % 20000 - 10000) for i in range(frames * channels))


def test_stdlib_wave_can_read_what_we_write(tmp_path):
    path = tmp_path / "a.wav"
    write_wav(path, pcm(500), 44100)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100)
        assert w.getnframes() == 500


def test_data_chunk_is_a_verbatim_copy(tmp_path):
    """No resampling, no dithering, no conversion. ADR-0011."""
    path = tmp_path / "a.wav"
    payload = pcm(1000)
    write_wav(path, payload, 22050)
    with wave.open(str(path)) as w:
        assert w.readframes(w.getnframes()) == payload


def test_stereo_frames_are_counted_per_frame_not_per_sample(tmp_path):
    path = tmp_path / "s.wav"
    write_wav(path, pcm(300, channels=2), 44100, channels=2)
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 2
        assert w.getnframes() == 300


def test_smpl_chunk_carries_the_root_key(tmp_path):
    path = tmp_path / "a.wav"
    write_wav(path, pcm(100), 44100, midi_note=60)
    raw = path.read_bytes()
    index = raw.find(b"smpl")
    assert index != -1
    assert struct.unpack_from("<I", raw, index + 8 + 12)[0] == 60


def test_smpl_chunk_carries_loop_points(tmp_path):
    path = tmp_path / "a.wav"
    write_wav(path, pcm(1000), 44100, midi_note=48, loops=[Loop(100, 899)])
    raw = path.read_bytes()
    index = raw.find(b"smpl") + 8
    assert struct.unpack_from("<I", raw, index + 28)[0] == 1  # loop count
    start, end = struct.unpack_from("<II", raw, index + 36 + 8)
    assert (start, end) == (100, 899)


def test_no_smpl_chunk_when_there_is_no_root_key(tmp_path):
    """A plain WAV stays plain."""
    path = tmp_path / "a.wav"
    write_wav(path, pcm(100), 44100)
    assert b"smpl" not in path.read_bytes()


def test_odd_length_data_is_padded_but_frames_are_right(tmp_path):
    """RIFF chunks must be even-aligned; the frame count must not shift."""
    path = tmp_path / "a.wav"
    write_wav(path, b"\x01\x02\x03", 8000)
    raw = path.read_bytes()
    assert len(raw) % 2 == 0
    index = raw.find(b"data")
    assert struct.unpack_from("<I", raw, index + 4)[0] == 3


@pytest.mark.parametrize("rate", [8000, 22050, 29400, 33075, 44100, 48000])
def test_odd_sampler_rates_survive(tmp_path, rate):
    """29400 and 33075 are real AKAI rates, not corruption."""
    path = tmp_path / f"{rate}.wav"
    write_wav(path, pcm(50), rate, midi_note=60)
    with wave.open(str(path)) as w:
        assert w.getframerate() == rate


def test_a_loop_is_carried_even_where_the_disc_states_no_root_key(tmp_path):
    """The smpl chunk's root key is mandatory, so carrying a loop means
    writing one. 60 is the neutral value, not a claim (ADR-0025)."""
    path = tmp_path / "loop.wav"
    write_wav(
        path, b"\x01\x00" * 1000, rate=22050, midi_note=None, loops=[Loop(start=100, end=899)]
    )
    raw = path.read_bytes()
    at = raw.find(b"smpl")
    assert at != -1
    body = at + 8
    assert struct.unpack_from("<I", raw, body + 12)[0] == DEFAULT_ROOT_KEY
    assert struct.unpack_from("<I", raw, body + 28)[0] == 1
    assert struct.unpack_from("<II", raw, body + 36 + 8) == (100, 899)


def test_no_root_key_and_no_loop_writes_no_smpl_chunk(tmp_path):
    """A format that knows neither writes a plain WAV, not an invented one."""
    path = tmp_path / "plain.wav"
    write_wav(path, b"\x01\x00" * 1000, rate=22050, midi_note=None, loops=[])
    assert b"smpl" not in path.read_bytes()
