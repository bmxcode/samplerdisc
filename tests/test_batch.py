"""Batch conversion. One unreadable disc must never end the run."""

from __future__ import annotations

import json

from samplerdisc.batch import convert_disc, convert_tree, find_images, write_manifest
from tests import fixtures


def sample_disc_bytes() -> bytes:
    payload = fixtures.akai_sample("KICK 1", words=64)
    other = fixtures.akai_sample("SNARE", words=64)
    return fixtures.akai_partition(
        [
            ("VOL 1", [("KICK 1", 0x73, len(payload), payload)]),
            ("VOL 2", [("SNARE", 0x73, len(other), other)]),
        ]
    )


def test_find_images_ignores_companions_and_other_files(tmp_path):
    (tmp_path / "disc.bin").write_bytes(b"x")
    (tmp_path / "disc.cue").write_text('FILE "DISC.BIN" BINARY\n')
    (tmp_path / "other.mds").write_bytes(b"x")
    (tmp_path / "other.mdf").write_bytes(b"x")
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    found = [p.rsplit("/", 1)[-1] for p in find_images(str(tmp_path))]
    assert found == ["disc.bin", "other.mds"]


def test_find_images_recurses(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "deep.iso").write_bytes(b"x")
    assert len(find_images(str(tmp_path))) == 1


def test_converts_a_disc_and_reports_what_it_did(tmp_path):
    source = tmp_path / "disc.iso"
    source.write_bytes(sample_disc_bytes())
    report = convert_disc(str(source), str(tmp_path / "out"))
    assert report.ok
    assert report.container == "flat"
    assert report.filesystem == "akai"
    assert report.samples == 2
    assert {v["name"] for v in report.volumes} == {"VOL 1", "VOL 2"}
    assert (tmp_path / "out" / "disc" / "partition-1" / "VOL 1" / "KICK 1.wav").exists()


def test_metadata_flag_writes_a_credits_sidecar_and_counts_its_lines(tmp_path):
    """The ``--metadata`` sidecar rides the batch path too: a FORM-bank disc's
    text-bank provenance is written and its line count lands in the report and
    the manifest totals (ADR-0043)."""
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
    source = tmp_path / "eiv.iso"
    source.write_bytes(
        fixtures.emu3_disc(
            folders,
            eiv=True,
            form_banks=("Studio Snare", "Credits"),
            credits={"Credits": ["Q Up Arts 97", "Denny Jaeger"]},
        )
    )
    report = convert_disc(str(source), str(tmp_path / "out"), metadata=True)
    assert report.credit_lines == 2
    assert (tmp_path / "out" / "eiv" / "Credits.txt").exists()

    # Without the flag: no sidecar, and the count stays zero.
    plain = convert_disc(str(source), str(tmp_path / "plain"), metadata=False)
    assert plain.credit_lines == 0
    assert not (tmp_path / "plain" / "eiv" / "Credits.txt").exists()

    manifest = tmp_path / "m.json"
    write_manifest(str(manifest), [report, plain])
    assert json.loads(manifest.read_text())["totals"]["credit_lines"] == 2


def test_an_unreadable_disc_becomes_a_report_not_an_exception(tmp_path):
    source = tmp_path / "junk.iso"
    source.write_bytes(fixtures.incompressible_block(11))
    report = convert_disc(str(source), str(tmp_path / "out"))
    assert not report.ok
    assert report.error == "no recognised filesystem"


def test_one_bad_disc_does_not_stop_the_run(tmp_path):
    """The whole point of batch: a collection has duds in it."""
    (tmp_path / "good.iso").write_bytes(sample_disc_bytes())
    (tmp_path / "bad.iso").write_bytes(fixtures.incompressible_block(12))
    reports = list(convert_tree(str(tmp_path), str(tmp_path / "out")))
    assert len(reports) == 2
    assert sum(r.ok for r in reports) == 1
    assert sum(bool(r.error) for r in reports) == 1


def test_discs_land_in_separate_directories(tmp_path):
    (tmp_path / "one.iso").write_bytes(sample_disc_bytes())
    (tmp_path / "two.iso").write_bytes(sample_disc_bytes())
    list(convert_tree(str(tmp_path), str(tmp_path / "out")))
    out = tmp_path / "out"
    assert (out / "one" / "partition-1" / "VOL 1" / "KICK 1.wav").exists()
    assert (out / "two" / "partition-1" / "VOL 1" / "KICK 1.wav").exists()


def test_manifest_records_totals_and_failures(tmp_path):
    (tmp_path / "good.iso").write_bytes(sample_disc_bytes())
    (tmp_path / "bad.iso").write_bytes(fixtures.incompressible_block(13))
    reports = list(convert_tree(str(tmp_path), str(tmp_path / "out")))
    path = tmp_path / "out" / "manifest.json"
    write_manifest(str(path), reports)

    payload = json.loads(path.read_text())
    assert payload["totals"] == {
        "discs": 2,
        "converted": 1,
        "failed": 1,
        "samples": 2,
        "stereo_samples": 0,
        "stereo_pairs": 0,
        "originals": 0,
        "credit_lines": 0,
        "audio_tracks": 0,
        "skipped": 0,
        "duplicates": 0,
        "mismatches": 0,
        "recovered": 0,
    }
    failed = [d for d in payload["discs"] if d["error"]]
    assert len(failed) == 1
    assert "no recognised filesystem" in failed[0]["error"]


def test_batch_can_keep_originals(tmp_path):
    (tmp_path / "d.iso").write_bytes(sample_disc_bytes())
    reports = list(convert_tree(str(tmp_path), str(tmp_path / "out"), keep_originals=True))
    assert reports[0].originals == 2
    assert (tmp_path / "out" / "d" / "partition-1" / "VOL 1" / "original" / "KICK 1.s1s").exists()


def test_the_manifest_counts_a_stereo_sample_apart_from_a_joined_pair(tmp_path):
    """Two different things, and a manifest that added them together would say
    a disc had rebuilt pairings it never guessed at.

    ``stereo_samples`` is a channel count the record declared (ADR-0026);
    ``stereo_pairs`` is a join this tool inferred from two filenames
    (ADR-0007). The E-mu disc here has one of the first and none of the second.
    """
    (tmp_path / "emu.iso").write_bytes(
        fixtures.emu3_disc(
            [("Default Folder", [("Bank One        ", [("Wide", 22050, 4000)])])],
            stereo=("Wide",),
        )
    )
    reports = list(convert_tree(str(tmp_path), str(tmp_path / "out")))
    assert (reports[0].samples, reports[0].stereo_samples, reports[0].stereo_pairs) == (1, 1, 0)

    path = tmp_path / "out" / "manifest.json"
    write_manifest(str(path), reports)
    totals = json.loads(path.read_text())["totals"]
    assert (totals["samples"], totals["stereo_samples"], totals["stereo_pairs"]) == (1, 1, 0)
