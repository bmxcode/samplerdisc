"""Stereo rejoining. The pairing is a name heuristic, so it must be conservative."""

from __future__ import annotations

import struct
import wave

import pytest

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Joined, Skipped, extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.stereo import find_pairs, interleave, split_side
from tests import fixtures

BACKEND = AkaiBackend()


def _named(names):
    """Pair each name with itself as payload.

    ``find_pairs`` carries a payload beside every name; these name-only tests
    pass the name as its own payload, so a matched pair reads back as the names
    it joined.
    """
    return [(name, name) for name in names]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("MOVIN 105 -L", ("MOVIN 105", "L")),
        ("MOVIN 105 -R", ("MOVIN 105", "R")),
        ("SWG-T2-100-L", ("SWG-T2-100", "L")),
        ("FUNK 106  -L", ("FUNK 106", "L")),
        ("KICKIN JAMZ1", None),
        ("-L", None),
        ("LEFTOVER", None),
    ],
)
def test_split_side(name, expected):
    assert split_side(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Roland S-7xx separates the side letter with 0x7F, not a hyphen.
        ("STR:Vn1 Pizz55\x7fL", ("STR:Vn1 Pizz55", "L")),
        ("STR:Vn1 Pizz55\x7fR", ("STR:Vn1 Pizz55", "R")),
        # Names are fixed width and space-padded, so the marker is not last.
        ("STR:Vn1 Pizz\x7fL  ", ("STR:Vn1 Pizz", "L")),
        ("STR:Vn1 Pizz \x7f L", ("STR:Vn1 Pizz", "L")),
        # 0x7F is legal in these names generally; only a side letter pairs.
        ("STR:Vn1 Pizz\x7fX", None),
        ("STR:Vn1 Pizz\x7f", None),
        ("STR:Vn1\x7fLoop", None),
        # Real, from amg-now, and the case that most rewards anchoring the
        # side letter at the end: the base itself ends in "-R", so a pattern
        # that let anything follow would read this as the right half of
        # "FX :Headache" and weld it to an unrelated sound.
        ("FX :Headache-R\x7fN", None),
        # A marker with no base is not half of anything.
        ("\x7fL", None),
        ("\x7fR", None),
        ("  \x7fL ", None),
    ],
)
def test_split_side_roland(name, expected):
    assert split_side(name) == expected


@pytest.mark.parametrize("name", ["KICKL", "KICKR", "PIANO L", "PIANO R"])
def test_the_separator_is_not_optional(name):
    """``KICKL``/``KICKR`` are not a pair, and guessing they are is unrecoverable."""
    assert split_side(name) is None


def test_roland_pairs_are_matched_by_base_name():
    result = find_pairs(
        _named(
            [
                "STR:Vn1 Pizz55\x7fL",
                "STR:Solo Vla",
                "STR:Vn1 Pizz55\x7fR",
                "MOVIN 105 -L",
                "MOVIN 105 -R",
            ]
        )
    )
    assert [(p.base, p.left, p.right) for p in result.pairs] == [
        ("STR:Vn1 Pizz55", "STR:Vn1 Pizz55\x7fL", "STR:Vn1 Pizz55\x7fR"),
        ("MOVIN 105", "MOVIN 105 -L", "MOVIN 105 -R"),
    ]


def test_an_unmatched_roland_half_is_not_a_pair():
    assert find_pairs(_named(["STR:Lone\x7fL"])).pairs == []
    assert find_pairs(_named(["STR:Lone\x7fR"])).pairs == []


def test_ambiguous_roland_names_are_reported_not_paired():
    result = find_pairs(_named(["A\x7fL", "A\x7fL", "A\x7fR"]))
    assert result.pairs == []
    assert [a.base for a in result.ambiguous] == ["A"]


def test_pairs_are_matched_by_base_name():
    result = find_pairs(
        _named(["MOVIN 105 -L", "KICK", "MOVIN 105 -R", "SWG-T2-100-L", "SWG-T2-100-R"])
    )
    assert [(p.base, p.left, p.right) for p in result.pairs] == [
        ("MOVIN 105", "MOVIN 105 -L", "MOVIN 105 -R"),
        ("SWG-T2-100", "SWG-T2-100-L", "SWG-T2-100-R"),
    ]


def test_an_unmatched_half_is_not_a_pair():
    """A lone half with no opposite stays mono -- neither a pair nor ambiguous."""
    assert find_pairs(_named(["LONE -L"])) == find_pairs([])
    assert find_pairs(_named(["LONE -R"])) == find_pairs([])


def test_ambiguous_names_are_reported_not_paired():
    """Two lefts for one base is not a pair; now it is reported, not dropped.

    Being conservative costs a manual join; being loose welds two unrelated
    sounds together and, without the mono originals, unrecoverably. Reporting
    the refusal is what keeps a duplicate name upstream from defeating it
    silently (issue #11).
    """
    result = find_pairs(_named(["A -L", "A -L", "A -R"]))
    assert result.pairs == []
    assert [a.base for a in result.ambiguous] == ["A"]
    assert "2 files marked -L and 1 marked -R" in result.ambiguous[0].reason


# --- interleaving -------------------------------------------------------


def mono(values) -> bytes:
    return b"".join(struct.pack("<h", v) for v in values)


def test_interleave_alternates_channels():
    out = interleave(mono([1, 2, 3]), mono([-1, -2, -3]))
    assert struct.unpack("<6h", out) == (1, -1, 2, -2, 3, -3)


def test_shorter_side_is_padded_not_truncated():
    """Losing a tail is worse than silence in one channel, and irreversible."""
    out = interleave(mono([1, 2, 3, 4]), mono([-1]))
    assert struct.unpack("<8h", out) == (1, -1, 2, 0, 3, 0, 4, 0)


def test_interleave_handles_empty_input():
    assert interleave(b"", b"") == b""


# --- end to end ---------------------------------------------------------


def stereo_disc(tmp_path, rate_left=44100, rate_right=44100):
    left = fixtures.akai_sample("PAD -L", rate=rate_left, words=100)
    right = fixtures.akai_sample("PAD -R", rate=rate_right, words=100)
    path = tmp_path / "d.iso"
    path.write_bytes(
        fixtures.akai_partition(
            [("VOL 1", [("PAD -L", 0x73, len(left), left), ("PAD -R", 0x73, len(right), right)])]
        )
    )
    return FlatImage(path)


def test_stereo_is_written_and_the_mono_originals_are_kept(tmp_path):
    """ADR-0007: the joined file is additional, never a replacement."""
    out = tmp_path / "out"
    results = list(extract_disc(stereo_disc(tmp_path), BACKEND, 0, str(out)))
    assert sum(isinstance(r, Joined) for r in results) == 1

    volume = out / "partition-1" / "VOL 1"
    assert (volume / "PAD -L.wav").exists()
    assert (volume / "PAD -R.wav").exists()
    joined = volume / "stereo" / "PAD.wav"
    assert joined.exists()
    with wave.open(str(joined)) as w:
        assert w.getnchannels() == 2
        assert w.getnframes() == 100


def test_halves_at_different_rates_are_not_joined(tmp_path):
    out = tmp_path / "out"
    results = list(extract_disc(stereo_disc(tmp_path, 44100, 22050), BACKEND, 0, str(out)))
    assert not any(isinstance(r, Joined) for r in results)
    reasons = [r.reason for r in results if isinstance(r, Skipped)]
    assert any("rate mismatch" in r for r in reasons)
    assert (out / "partition-1" / "VOL 1" / "PAD -L.wav").exists()  # mono still written


def test_no_stereo_flag_disables_joining(tmp_path):
    out = tmp_path / "out"
    results = list(extract_disc(stereo_disc(tmp_path), BACKEND, 0, str(out), join_stereo=False))
    assert not any(isinstance(r, Joined) for r in results)
    assert not (out / "partition-1" / "VOL 1" / "stereo").exists()


def test_stereo_channels_match_their_mono_sources(tmp_path):
    out = tmp_path / "out"
    list(extract_disc(stereo_disc(tmp_path), BACKEND, 0, str(out)))
    volume = out / "partition-1" / "VOL 1"
    with wave.open(str(volume / "PAD -L.wav")) as w:
        left = w.readframes(w.getnframes())
    with wave.open(str(volume / "PAD -R.wav")) as w:
        right = w.readframes(w.getnframes())
    with wave.open(str(volume / "stereo" / "PAD.wav")) as w:
        both = w.readframes(w.getnframes())
    assert both[0::4] == left[0::2] and both[1::4] == left[1::2]
    assert both[2::4] == right[0::2] and both[3::4] == right[1::2]


def test_two_lefts_under_one_name_are_reported_not_welded(tmp_path):
    """Two distinct files named ``KICK -L`` and one ``KICK -R`` must not weld.

    A name is not unique on these filesystems, and a name-keyed accumulator
    would drop one left before the pairing ever saw the collision -- then join
    whichever survived to the right and report an ordinary stereo file, the
    silent wrong join ADR-0007 keeps the mono originals against (issue #11).
    Nothing is lost by refusing: both lefts and the right are already on disk.
    """
    first = fixtures.akai_sample("KICK -L", words=64)
    second = fixtures.akai_sample("KICK -L", words=128)
    right = fixtures.akai_sample("KICK -R", words=100)
    path = tmp_path / "dup.iso"
    path.write_bytes(
        fixtures.akai_partition(
            [
                (
                    "VOL 1",
                    [
                        ("KICK -L", 0x73, len(first), first),
                        ("KICK -L", 0x73, len(second), second),
                        ("KICK -R", 0x73, len(right), right),
                    ],
                )
            ]
        )
    )
    out = tmp_path / "out"
    results = list(extract_disc(FlatImage(path), BACKEND, 0, str(out)))

    assert not any(isinstance(r, Joined) for r in results)
    ambiguous = [r for r in results if isinstance(r, Skipped) and r.name == "KICK"]
    assert len(ambiguous) == 1
    assert "-L" in ambiguous[0].reason and "-R" in ambiguous[0].reason

    volume = out / "partition-1" / "VOL 1"
    assert (volume / "KICK -L.wav").exists()
    assert (volume / "KICK -L_2.wav").exists()  # unique_path kept the second
    assert (volume / "KICK -R.wav").exists()
    assert not (volume / "stereo").exists()
