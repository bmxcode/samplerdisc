"""Loop points and tuning in the WAV smpl chunk (ADR-0011).

These are what make an extracted WAV usable in a DAW without a second tool,
and they are lost forever if dropped -- the disc is the only source.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.sample.akai import parse
from tests import fixtures

BACKEND = AkaiBackend()


def read_smpl(path) -> dict | None:
    raw = path.read_bytes()
    index = raw.find(b"smpl")
    if index == -1:
        return None
    body = index + 8
    note, fraction = struct.unpack_from("<II", raw, body + 12)
    count = struct.unpack_from("<I", raw, body + 28)[0]
    loops = [struct.unpack_from("<II", raw, body + 36 + i * 24 + 8) for i in range(count)]
    return {"note": note, "fraction": fraction, "loops": loops}


# --- parsing ------------------------------------------------------------


def test_loop_start_is_derived_from_end_minus_length():
    """The header stores the end and the length; there is no start field."""
    sample = parse(fixtures.akai_sample("PAD", words=1000, loop=(600, 950)))
    assert [(loop.start, loop.end) for loop in sample.loops] == [(600, 950)]


def test_a_sample_without_loops_has_none():
    assert parse(fixtures.akai_sample("KICK", words=100)).loops == ()


def test_a_timed_dwell_is_not_a_sustain_loop():
    """Only dwell 9999 -- hold -- maps onto what a WAV smpl loop means."""
    sample = parse(fixtures.akai_sample("PAD", words=1000, loop=(600, 950), dwell=500))
    assert sample.loops == ()


def test_loop_end_past_the_audio_is_clamped():
    """Declared length can exceed the payload; common on these rips."""
    payload = bytearray(fixtures.akai_sample("PAD", words=1000, loop=(600, 998)))
    truncated = bytes(payload[: 150 + 900 * 2])  # only 900 frames present
    sample = parse(truncated)
    assert sample.frames == 900
    assert sample.loops[0].end == 900
    assert sample.loops[0].start == 600


def test_negative_tuning_is_signed():
    assert parse(fixtures.akai_sample("PAD", cents=-25)).cents == -25.0


# --- written into the WAV -----------------------------------------------


def disc_with(tmp_path, sample_bytes, name="PAD"):
    path = tmp_path / "d.iso"
    path.write_bytes(
        fixtures.akai_partition([("VOL 1", [(name, 0x73, len(sample_bytes), sample_bytes)])])
    )
    return FlatImage(path)


def test_loop_is_written_to_the_smpl_chunk(tmp_path):
    image = disc_with(tmp_path, fixtures.akai_sample("PAD", words=1000, loop=(600, 950)))
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    smpl = read_smpl(out / "partition-1" / "VOL 1" / "PAD.wav")
    assert smpl is not None
    # RIFF loop ends are inclusive, AKAI's are exclusive.
    assert smpl["loops"] == [(600, 949)]


def test_loop_end_stays_inside_the_audio(tmp_path):
    """An inclusive end equal to the frame count would point past the data."""
    image = disc_with(tmp_path, fixtures.akai_sample("PAD", words=500, loop=(100, 500)))
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    path = out / "partition-1" / "VOL 1" / "PAD.wav"
    with wave.open(str(path)) as w:
        frames = w.getnframes()
    start, end = read_smpl(path)["loops"][0]
    assert start < end < frames


def test_stereo_files_keep_the_loop(tmp_path):
    """Loop points are frame offsets, so interleaving does not move them."""
    left = fixtures.akai_sample("PAD -L", words=1000, loop=(600, 950))
    right = fixtures.akai_sample("PAD -R", words=1000, loop=(600, 950))
    path = tmp_path / "d.iso"
    path.write_bytes(
        fixtures.akai_partition(
            [("VOL 1", [("PAD -L", 0x73, len(left), left), ("PAD -R", 0x73, len(right), right)])]
        )
    )
    out = tmp_path / "out"
    list(extract_disc(FlatImage(path), BACKEND, 0, str(out)))
    assert read_smpl(out / "partition-1" / "VOL 1" / "stereo" / "PAD.wav")["loops"] == [(600, 949)]


def test_an_unlooped_sample_gets_a_root_key_but_no_loop(tmp_path):
    image = disc_with(tmp_path, fixtures.akai_sample("KICK", words=100, pitch=36), name="KICK")
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    smpl = read_smpl(out / "partition-1" / "VOL 1" / "KICK.wav")
    assert smpl["note"] == 36
    assert smpl["loops"] == []


# --- E-mu: loop points with no root key (D17, ADR-0025) -----------------


def test_an_emu3_sample_carries_its_loop_and_a_neutral_root_key(tmp_path):
    """The E-mu record declares loop points and no root key anywhere in its 92
    bytes, so the WAV says what the disc says and no more (ADR-0025)."""
    from samplerdisc.container.flat import FlatImage
    from samplerdisc.fs.emu3 import Emu3Backend
    from samplerdisc.wav import DEFAULT_ROOT_KEY

    data = fixtures.emu3_disc(
        [
            (
                "Default Folder",
                [
                    (
                        "Bank One        ",
                        [
                            ("Looped", 22050, 5000),
                            ("Plain", 22050, 5000),
                        ],
                    )
                ],
            )
        ],
        loops={"Looped": (1200, 4800)},
    )
    path = tmp_path / "emu.iso"
    path.write_bytes(data)
    out = tmp_path / "out"
    results = list(extract_disc(FlatImage(path), Emu3Backend(), 0, str(out)))
    written = {r.name: r.path for r in results if getattr(r, "path", None)}

    looped = read_smpl(Path(written["Looped"]))
    assert looped is not None
    assert looped["note"] == DEFAULT_ROOT_KEY
    assert looped["loops"] == [(1200, 4799)]  # exclusive in, inclusive out

    # A record declaring no loop gets a plain WAV rather than an invented one.
    assert read_smpl(Path(written["Plain"])) is None
