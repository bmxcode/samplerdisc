"""HFS behind an Apple Partition Map -- the SampleCell backend (ADR-0039).

Synthetic fixtures only; no disc byte is committed (ADR-0008). The disc-backed
counterparts, including the ``machfs`` byte oracle, live in ``test_discs.py``.
"""

from __future__ import annotations

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.fs.base import File
from samplerdisc.fs.hfs import APPLE_BLOCK, HfsBackend
from samplerdisc.fs.iso9660 import Iso9660Backend
from samplerdisc.fs.probe import find_origin
from tests import fixtures

BACKEND = HfsBackend()


def hfs_image(tmp_path, files, name="d.iso", **kwargs) -> FlatImage:
    path = tmp_path / name
    path.write_bytes(fixtures.make_hfs(files, **kwargs))
    return FlatImage(path)


def test_probe_finds_the_driver_descriptor_and_partition_map(tmp_path):
    image = hfs_image(tmp_path, {"KICK": (b"AIFF", b"FORM....data")})
    assert BACKEND.probe(image, 0)


def test_probe_rejects_a_non_apple_image(tmp_path):
    path = tmp_path / "zeros.iso"
    path.write_bytes(b"\x00" * (64 * APPLE_BLOCK))
    assert not BACKEND.probe(FlatImage(path), 0)


def test_the_backends_do_not_shadow_each_other(tmp_path):
    """An HFS disc is not ISO 9660 or AKAI, and neither is HFS.

    The converse matters most: a Mac/PC hybrid disc carries an Apple Partition
    Map (which HFS matches) over an ISO 9660 filesystem that is its intended
    reading, so HFS is registered last and must not probe-match a plain ISO 9660
    or AKAI image.
    """
    hfs = hfs_image(tmp_path, {"KICK": (b"AIFF", b"FORM....data")})
    assert not Iso9660Backend().probe(hfs, 0)
    assert not AkaiBackend().probe(hfs, 0)

    iso = tmp_path / "d.iso"
    iso.write_bytes(fixtures.make_iso9660({"A.WAV": fixtures.tiny_wav(tmp_path)}))
    assert not BACKEND.probe(FlatImage(iso), 0)

    akai = tmp_path / "a.iso"
    sample = fixtures.akai_sample("KICK")
    akai.write_bytes(fixtures.akai_partition([("VOL 1", [("KICK", 0x73, len(sample), sample)])]))
    assert not BACKEND.probe(FlatImage(akai), 0)


def test_volume_name_comes_from_the_master_directory_block(tmp_path):
    image = hfs_image(tmp_path, {"K": (b"AIFF", b"x")}, volume_name="My Library")
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert volume.name == "My Library"


def test_files_are_listed_with_their_folder_path(tmp_path):
    image = hfs_image(
        tmp_path,
        {
            "KICK": (b"AIFF", b"a"),
            "Perc/SNARE": (b"AIFF", b"b"),
            "Perc/Deep/TOM": (b"AIFF", b"c"),
        },
    )
    names = {f.name for f in next(iter(BACKEND.volumes(image, 0))).files}
    assert names == {"KICK", "Perc/SNARE", "Perc/Deep/TOM"}


def test_finder_type_and_name_classify_the_payload(tmp_path):
    image = hfs_image(
        tmp_path,
        {
            "SOUND": (b"AIFF", b"a"),  # by Finder type, no extension
            "TAKE.AIF": (b"\x00\x00\x00\x00", b"b"),  # by name, no Finder type
            "INSTR": (b"SCin", b"c"),  # SampleCell instrument -> program
            "MIX": (b"MixD", b"d"),  # SampleCell mix document -> program
            "OLD": (b"Sd2f", b"e"),  # Sound Designer II -> listed, not read
            "NOTES": (b"TEXT", b"f"),  # anything else -> file
        },
    )
    kinds = {f.name: f.kind for f in next(iter(BACKEND.volumes(image, 0))).files}
    assert kinds == {
        "SOUND": "aiff",
        "TAKE.AIF": "aiff",
        "INSTR": "program",
        "MIX": "program",
        "OLD": "sd2",
        "NOTES": "file",
    }


def test_read_file_returns_the_exact_data_fork(tmp_path):
    payload = bytes(range(256)) * 20  # spills past one 2048-byte allocation block
    image = hfs_image(tmp_path, {"KICK": (b"AIFF", payload)})
    entry = next(iter(BACKEND.volumes(image, 0))).files[0]
    assert entry.size == len(payload)
    assert BACKEND.read_file(image, 0, entry) == payload


def test_read_file_spans_several_extents(tmp_path):
    """A fragmented fork is stitched back together from its extent list.

    Real SampleCell files are contiguous, but the reader must walk the extent
    list rather than assume one run -- a fork of two non-adjacent allocation
    blocks is reassembled in order (degrade-never-crash if it could not).
    """
    al_blk_size = 2048
    # Two allocation blocks with a gap between them, so the extents are not
    # adjacent and a single-run read would splice in the wrong bytes.
    raw = bytearray(al_blk_size * 5)
    first = b"A" * al_blk_size
    second = b"B" * al_blk_size
    raw[0:al_blk_size] = first  # allocation block 0
    raw[2 * al_blk_size : 3 * al_blk_size] = second  # allocation block 2
    path = tmp_path / "forks.bin"
    path.write_bytes(bytes(raw))
    entry = File(
        name="frag",
        kind="aiff",
        size=al_blk_size + 10,  # all of block 0, part of block 2
        start_block=0,
        meta=(
            ("forkbase", 0),
            ("albksz", al_blk_size),
            ("x0s", 0),
            ("x0c", 1),
            ("x1s", 2),
            ("x1c", 1),
        ),
    )
    assert BACKEND.read_file(FlatImage(path), 0, entry) == first + second[:10]


def test_origin_probe_resolves_to_the_hfs_backend(tmp_path):
    image = hfs_image(tmp_path, {"KICK": (b"AIFF", b"data")})
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "hfs"
    assert origin.offset == 0


def test_an_aiff_payload_converts_through_the_existing_path(tmp_path):
    """The sample layer is untouched: an AIFF entry rides ``_convert_aiff``.

    This is the whole point of the deliverable -- HFS yields named AIFF files
    and the ISO 9660 conversion path (ADR-0024) turns them into WAV unchanged.
    """
    aiff_bytes = fixtures.make_aiff(frames=64, name="Clap")
    image = hfs_image(tmp_path, {"Samples/CLAP": (b"AIFF", aiff_bytes)})
    origin = find_origin(image)
    out = tmp_path / "out"
    results = list(extract_disc(image, origin.backend, origin.offset, str(out)))
    extracted = [r for r in results if isinstance(r, Extracted)]
    assert len(extracted) == 1
    assert extracted[0].frames == 64
    assert extracted[0].path.endswith(".wav")


def test_an_empty_catalog_yields_a_volume_with_a_note(tmp_path):
    """A blank catalog degrades to an empty, annotated volume -- never a crash.

    A volume with no files and no note is the ADR-0012 signature of a probe that
    matched something it should not have, so the empty case must say why.
    """
    path = tmp_path / "blank.iso"
    # A valid DDR + APM + MDB, then a zeroed catalog region.
    good = fixtures.make_hfs({"K": (b"AIFF", b"x")})
    blanked = bytearray(good)
    # Wipe the allocation-block region (catalog + forks) to zeros.
    volume_start = 4 * APPLE_BLOCK
    alloc_start = volume_start + 8 * APPLE_BLOCK
    for i in range(alloc_start, len(blanked)):
        blanked[i] = 0
    path.write_bytes(bytes(blanked))
    image = FlatImage(path)
    assert BACKEND.probe(image, 0)
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert volume.files == []
    assert volume.note
