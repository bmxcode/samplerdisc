from samplerdisc import __version__
from samplerdisc.cli import build_parser


def test_version_matches_package():
    assert __version__ == "0.3.0"


def test_parser_exposes_version_flag():
    parser = build_parser()
    assert any(a.dest == "version" for a in parser._actions)


def test_assume_audio_cd_refuses_a_stream_that_is_not_audio(tmp_path, capsys):
    """The flag is an assertion by the user, not an instruction to obey blindly.

    Writing a whole disc out on request is fine; doing it when the bytes say
    otherwise hands back hundreds of megabytes of noise with nothing reporting
    a problem, which is the silent failure this project keeps meeting.
    """
    from samplerdisc.cli import main
    from tests import fixtures

    disc = tmp_path / "notaudio.iso"
    disc.write_bytes(b"".join(fixtures.incompressible_block(i) for i in range(24)))
    assert main(["extract", "--assume-audio-cd", str(disc), str(tmp_path / "out")]) == 1
    assert "does not look like 16-bit stereo PCM" in capsys.readouterr().err


def test_assume_audio_cd_writes_one_wav_for_a_cueless_audio_disc(tmp_path):
    import wave

    from samplerdisc.cli import main
    from tests import fixtures

    disc = tmp_path / "audio.iso"
    disc.write_bytes(fixtures.stereo_audio_block(frames=1 << 19))
    out = tmp_path / "out"
    assert main(["extract", "--assume-audio-cd", str(disc), str(out)]) == 0
    written = list(out.glob("*.wav"))
    assert len(written) == 1
    with wave.open(str(written[0]), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 44100
