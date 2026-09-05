from samplerdisc import __version__
from samplerdisc.cli import build_parser


def test_version_matches_package():
    """The reported version is the installed metadata, not a hardcoded literal.

    A literal here mirroring a literal in the source is what let 0.5.1 ship
    reporting 0.5.0: both sat still while pyproject moved. Assert the real
    invariant instead — the runtime string is the packaged version.
    """
    from importlib.metadata import version

    assert __version__ == version("samplerdisc")


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


def test_extract_metadata_flag_writes_the_credits_sidecar(tmp_path, capsys):
    """``extract --metadata`` reads the E-IV text banks' provenance and reports
    the sidecar it wrote; without the flag no ``Credits.txt`` appears (ADR-0043).
    """
    from samplerdisc.cli import main
    from tests import fixtures

    folders = [
        (
            "Studio Kits",
            [
                ("Live Room", [("Kick Axis", 44100, 512), ("Snare Top", 44100, 256)]),
                ("Room Verb", [("Tom Floor", 24000, 300), ("Hat Tight", 44100, 128)]),
                ("Studio Snare", [("Snare 01", 44100, 400), ("Snare 02", 22000, 220)]),
                ("Perc Kit", [("Shaker", 32000, 200)]),
                ("Credits", []),
            ],
        ),
    ]
    disc = tmp_path / "eiv.iso"
    disc.write_bytes(
        fixtures.emu3_disc(
            folders,
            eiv=True,
            form_banks=("Studio Snare", "Credits"),
            credits={"Credits": ["Q Up Arts 97", "Denny Jaeger"]},
        )
    )
    out = tmp_path / "out"
    assert main(["extract", "--metadata", str(disc), str(out)]) == 0
    assert "credit lines" in capsys.readouterr().out
    assert (out / "Credits.txt").read_text(encoding="utf-8").splitlines() == [
        "Credits",
        "Q Up Arts 97",
        "Denny Jaeger",
    ]

    plain = tmp_path / "plain"
    assert main(["extract", str(disc), str(plain)]) == 0
    assert not (plain / "Credits.txt").exists()
