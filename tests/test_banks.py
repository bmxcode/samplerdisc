"""Loose ``.ebl`` sample banks converted from an ordinary directory (ADR-0042).

The decode itself is the on-disc EBL path's, oracle-verified in test_discs.py;
what is exercised here is the loose-file *source* -- discovery, grouping, the
output tree, and that a bad file degrades rather than crashes. Synthetic ``.ebl``
built by ``fixtures.make_ebl`` so no disc is needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from samplerdisc import banks
from samplerdisc.batch import convert_tree
from samplerdisc.extract import Extracted, Skipped
from samplerdisc.wav import read_header
from tests import fixtures


def _bank(tmp_path, samples, bank="Proteus 1"):
    """A bank dir laid out as E-mu ships it: ``<bank>/SamplePool/*.ebl``."""
    pool = tmp_path / bank / "SamplePool"
    pool.mkdir(parents=True)
    for i, payload in enumerate(samples, start=1):
        (pool / f"{bank}SL{i:03d}.ebl").write_bytes(payload)
    return pool


def test_a_bank_of_loose_ebl_converts_to_wav(tmp_path):
    _bank(tmp_path, [fixtures.make_ebl(name="EP4MKIIL A0"), fixtures.make_ebl(name="909 Tom Low")])
    out = tmp_path / "out"
    results = list(banks.extract_banks(str(tmp_path / "Proteus 1"), str(out)))
    written = [r for r in results if isinstance(r, Extracted)]
    assert len(written) == 2
    # Named from the header, not the meaningless ProteusSLNNN.ebl filename, and
    # grouped under the bank name (the parent of SamplePool), not the pool.
    names = {os.path.basename(r.path) for r in written}
    assert names == {"EP4MKIIL A0.wav", "909 Tom Low.wav"}
    for r in written:
        assert r.volume == "Proteus 1"
        assert os.path.exists(r.path)
        assert os.path.dirname(r.path) == str(out / "Proteus 1")


def test_the_exb_definition_is_ignored(tmp_path):
    """Only the sample ``.ebl`` convert; the ``.exb`` preset is left alone."""
    pool = _bank(tmp_path, [fixtures.make_ebl(name="Kick")])
    (pool.parent / "Proteus 1.exb").write_bytes(b"not a sample bank we read")
    results = list(banks.extract_banks(str(tmp_path / "Proteus 1"), str(tmp_path / "out")))
    written = [r for r in results if isinstance(r, Extracted)]
    assert [os.path.basename(r.path) for r in written] == ["Kick.wav"]


def test_a_loop_rides_into_the_smpl_chunk(tmp_path):
    _bank(tmp_path, [fixtures.make_ebl(name="Pad", pcm=b"\x00\x00" * 512, loop=(100, 400))])
    out = tmp_path / "out"
    results = banks.extract_banks(str(tmp_path / "Proteus 1"), str(out))
    written = [r for r in results if isinstance(r, Extracted)]
    assert len(written) == 1
    header = read_header(Path(written[0].path).read_bytes())
    assert header is not None and header.has_smpl


def test_a_corrupt_ebl_is_skipped_not_raised(tmp_path):
    _bank(tmp_path, [fixtures.make_ebl(name="Good"), b"FORM\x00\x00\x00\x04junk"])
    results = list(banks.extract_banks(str(tmp_path / "Proteus 1"), str(tmp_path / "out")))
    written = [r for r in results if isinstance(r, Extracted)]
    skipped = [r for r in results if isinstance(r, Skipped)]
    assert len(written) == 1
    assert len(skipped) == 1


def test_find_bank_dirs_groups_the_pool_under_its_bank(tmp_path):
    _bank(tmp_path, [fixtures.make_ebl()], bank="Proteus 1")
    _bank(tmp_path, [fixtures.make_ebl()], bank="Proteus 2")
    found = banks.find_bank_dirs(str(tmp_path))
    assert [banks.bank_name(d) for d in found] == ["Proteus 1", "Proteus 2"]


def test_a_folder_with_no_ebl_is_not_a_bank(tmp_path):
    # A render/oracle tree of FLAC, or a bare .exb folder, is not a bank.
    (tmp_path / "renders").mkdir()
    (tmp_path / "renders" / "a.flac").write_bytes(b"flac")
    assert banks.find_bank_dirs(str(tmp_path)) == []


def test_batch_picks_up_a_loose_bank_tree(tmp_path):
    _bank(tmp_path, [fixtures.make_ebl(), fixtures.make_ebl()], bank="Proteus 1")
    _bank(tmp_path, [fixtures.make_ebl()], bank="Proteus 2")
    reports = list(convert_tree(str(tmp_path), str(tmp_path / "out")))
    banks_reports = [r for r in reports if r.container == "loose-ebl"]
    assert {os.path.basename(r.source.rstrip("/")) for r in banks_reports} == {"SamplePool"}
    assert sorted(r.samples for r in banks_reports) == [1, 2]
    assert all(r.filesystem == "none" and r.ok for r in banks_reports)
