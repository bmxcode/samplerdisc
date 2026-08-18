"""--keep-originals: the on-disc bytes, kept verbatim beside the WAVs."""

from __future__ import annotations

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import ORIGINALS_DIR, Kept, extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.fs.base import File, original_suffix
from samplerdisc.sample.akai import parse
from tests import fixtures

BACKEND = AkaiBackend()


def disc(tmp_path, files, volume="VOL 1"):
    path = tmp_path / "d.iso"
    path.write_bytes(fixtures.akai_partition([(volume, files)]))
    return FlatImage(path)


def mixed(sample_type=0x73, program_type=0x70):
    sample = fixtures.akai_sample("KICK 1", words=64)
    program = b"\x01" + b"\x7f" * 199
    return (
        [
            ("KICK 1", sample_type, len(sample), sample),
            ("A PROGRAM", program_type, len(program), program),
        ],
        sample,
        program,
    )


# --- naming -------------------------------------------------------------


def test_suffix_reads_the_generation_off_the_type_byte():
    """The high bit distinguishes an S3000 disc from an S1000 one."""
    assert original_suffix(BACKEND, File("x", "sample", 1, 1, raw_type=0x73)) == ".s1s"
    assert original_suffix(BACKEND, File("x", "sample", 1, 1, raw_type=0xF3)) == ".s3s"
    assert original_suffix(BACKEND, File("x", "program", 1, 1, raw_type=0x70)) == ".s1p"
    assert original_suffix(BACKEND, File("x", "program", 1, 1, raw_type=0xF0)) == ".s3p"


def test_a_backend_without_the_hook_gets_a_default():
    class Plain:
        name = "plain"

    assert original_suffix(Plain(), File("x", "file", 1, 1)) == ".bin"


# --- writing ------------------------------------------------------------


def test_originals_are_off_by_default(tmp_path):
    files, _, _ = mixed()
    out = tmp_path / "out"
    results = list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out)))
    assert not any(isinstance(r, Kept) for r in results)
    assert not (out / "VOL 1" / ORIGINALS_DIR).exists()


def test_samples_and_programs_are_both_kept(tmp_path):
    """Programs hold the key ranges; dropping them loses the only copy."""
    files, sample, program = mixed()
    out = tmp_path / "out"
    results = list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out), keep_originals=True))
    kept = {r.name: r.kind for r in results if isinstance(r, Kept)}
    assert kept == {"KICK 1": "sample", "A PROGRAM": "program"}

    originals = out / "VOL 1" / ORIGINALS_DIR
    assert (originals / "KICK 1.s1s").read_bytes() == sample
    assert (originals / "A PROGRAM.s1p").read_bytes() == program


def test_originals_sit_beside_the_wavs_not_among_them(tmp_path):
    files, _, _ = mixed()
    out = tmp_path / "out"
    list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out), keep_originals=True))
    volume = out / "VOL 1"
    assert sorted(p.name for p in volume.iterdir()) == ["KICK 1.wav", ORIGINALS_DIR]


def test_settings_and_effects_are_not_kept(tmp_path):
    """Unusable without the hardware, so not worth the bytes."""
    sample = fixtures.akai_sample("KICK", words=32)
    files = [
        ("KICK", 0x73, len(sample), sample),
        ("DRUM INPUTS", 0x64, 162, b"\x02" * 162),
        ("EFFECTS FILE", 0x78, 200, b"\x03" * 200),
    ]
    out = tmp_path / "out"
    results = list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out), keep_originals=True))
    assert [r.name for r in results if isinstance(r, Kept)] == ["KICK"]


def test_a_kept_sample_still_parses(tmp_path):
    """The bytes are unaltered, so they round-trip through our own reader."""
    files, sample, _ = mixed()
    out = tmp_path / "out"
    list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out), keep_originals=True))
    raw = (out / "VOL 1" / ORIGINALS_DIR / "KICK 1.s1s").read_bytes()
    assert parse(raw).pcm == parse(sample).pcm


def test_s3000_type_bytes_produce_s3_suffixes(tmp_path):
    files, _, _ = mixed(sample_type=0xF3, program_type=0xF0)
    out = tmp_path / "out"
    list(extract_disc(disc(tmp_path, files), BACKEND, 0, str(out), keep_originals=True))
    originals = out / "VOL 1" / ORIGINALS_DIR
    assert sorted(p.name for p in originals.iterdir()) == ["A PROGRAM.s3p", "KICK 1.s3s"]
