"""AKAI filesystem tests against synthetic partitions (ADR-0008)."""

from __future__ import annotations

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.akai import AkaiBackend, decode_name
from samplerdisc.fs.probe import find_origin
from tests import fixtures

BACKEND = AkaiBackend()


def image_of(tmp_path, data: bytes, name: str = "disc.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


def simple_partition() -> bytes:
    return fixtures.akai_partition(
        [
            ("SOUP 101-103", [("KICK 1", 0x73, 278, fixtures.akai_sample("KICK 1"))]),
            ("SOUP 104-105", [("SNARE 2", 0xF3, 278, fixtures.akai_sample("SNARE 2"))]),
        ]
    )


# --- charset ------------------------------------------------------------


def test_index_10_is_a_space_not_a_digit():
    """The classic trap: 'KICKIN B1-F2' vs 'KICKIN9B1-F2'.

    See docs/formats/akai-fs.md for how the table was confirmed.
    """
    assert decode_name(fixtures.akai_name("KICKIN B1-F2")) == "KICKIN B1-F2"
    assert decode_name(bytes([21, 19, 13, 21, 19, 24, 10, 12, 1, 39, 16, 2])) == "KICKIN B1-F2"


def test_names_are_stripped_of_padding():
    assert decode_name(fixtures.akai_name("KICK")) == "KICK"


# --- walking ------------------------------------------------------------


def test_lists_volumes_and_files(tmp_path):
    image = image_of(tmp_path, simple_partition())
    volumes = list(BACKEND.volumes(image, 0))
    assert [v.name for v in volumes] == ["SOUP 101-103", "SOUP 104-105"]
    assert [f.name for f in volumes[0].files] == ["KICK 1"]
    assert volumes[0].files[0].kind == "sample"


def test_type_high_nibble_is_masked(tmp_path):
    """0x73 and 0xF3 are both samples -- S1000 and S3000 differ in the nibble."""
    image = image_of(tmp_path, simple_partition())
    volumes = list(BACKEND.volumes(image, 0))
    assert volumes[0].files[0].kind == "sample"
    assert volumes[1].files[0].kind == "sample"


def test_programs_are_listed_not_treated_as_samples(tmp_path):
    data = fixtures.akai_partition(
        [
            (
                "VOL 1",
                [
                    ("A PROGRAM", 0x70, 4608, b"\x01" * 64),
                    ("A SAMPLE", 0x73, 278, fixtures.akai_sample("A SAMPLE")),
                ],
            )
        ]
    )
    volumes = list(BACKEND.volumes(image_of(tmp_path, data), 0))
    kinds = {f.name: f.kind for f in volumes[0].files}
    assert kinds == {"A PROGRAM": "program", "A SAMPLE": "sample"}
    assert [f.name for f in volumes[0].samples()] == ["A SAMPLE"]


def test_entries_pointing_outside_the_image_are_skipped(tmp_path):
    """Damaged rips are common: skip the entry, keep the disc."""
    from samplerdisc.fs.akai import BLOCK_SIZE, FILE_ENTRY_LEN

    data = bytearray(simple_partition())
    directory = 1 * BLOCK_SIZE
    # Point the first file's start block far past the end of the image.
    data[directory + 20 : directory + 22] = (60000).to_bytes(2, "little")
    volumes = list(BACKEND.volumes(image_of(tmp_path, bytes(data)), 0))
    assert volumes[0].files == []
    assert len(volumes) == 2  # the rest of the disc still reads
    assert FILE_ENTRY_LEN == 24


def test_read_file_returns_the_payload(tmp_path):
    payload = fixtures.akai_sample("KICK 1")
    data = fixtures.akai_partition([("VOL 1", [("KICK 1", 0x73, len(payload), payload)])])
    image = image_of(tmp_path, data)
    entry = next(iter(BACKEND.volumes(image, 0))).files[0]
    assert BACKEND.read_file(image, 0, entry) == payload


# --- probing ------------------------------------------------------------


def test_probe_accepts_a_real_partition(tmp_path):
    assert BACKEND.probe(image_of(tmp_path, simple_partition()), 0)


def test_probe_rejects_zeros_and_noise(tmp_path):
    """A loose probe would resolve an origin confidently and wrongly (ADR-0005)."""
    assert not BACKEND.probe(image_of(tmp_path, b"\x00" * 65536, "z.iso"), 0)
    assert not BACKEND.probe(image_of(tmp_path, fixtures.incompressible_block(5) * 2, "n.iso"), 0)


def test_origin_probe_finds_a_partition_behind_a_pregap(tmp_path):
    """The whole point of ADR-0005, end to end."""
    from samplerdisc.container.nrg import NrgImage

    path = tmp_path / "disc.nrg"
    path.write_bytes(fixtures.make_nrg(simple_partition()))
    image = NrgImage(path)
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "akai"
    first = next(iter(origin.backend.volumes(image, origin.offset)))
    assert first.name == "SOUP 101-103"


def test_origin_probe_finds_a_partition_offset_into_the_image(tmp_path):
    """A hybrid disc: something else occupies the first sectors."""
    padding = b"\x00" * (8 * 2048)
    image = image_of(tmp_path, padding + simple_partition())
    origin = find_origin(image)
    assert origin is not None
    assert origin.offset == len(padding)


def test_origin_probe_returns_none_when_nothing_matches(tmp_path):
    image = image_of(tmp_path, fixtures.incompressible_block(9) * 4, "junk.iso")
    assert find_origin(image) is None


def test_probe_tolerates_preformatted_unallocated_slots(tmp_path):
    """AKAI writes a default name into every slot; unused ones point at block 0.

    A rule that treats a named entry with start 0 as corruption rejects a
    perfectly good disc -- which is exactly what happened to the loopsoup
    reference image.
    """
    from samplerdisc.fs.akai import NAME_LEN, VOLUME_DIR_OFFSET, VOLUME_ENTRY_LEN

    data = bytearray(simple_partition())
    slot = VOLUME_DIR_OFFSET + 2 * VOLUME_ENTRY_LEN
    entry = bytearray(VOLUME_ENTRY_LEN)
    entry[:NAME_LEN] = fixtures.akai_name("VOLUME 008")
    # type 0, start 0: formatted but never allocated.
    data[slot : slot + VOLUME_ENTRY_LEN] = entry
    image = image_of(tmp_path, bytes(data), "unalloc.iso")
    assert BACKEND.probe(image, 0)
    assert [v.name for v in BACKEND.volumes(image, 0)] == ["SOUP 101-103", "SOUP 104-105"]


def test_probe_still_rejects_an_all_zero_header(tmp_path):
    """The unallocated rule must not weaken the zeros case (ADR-0005)."""
    assert not BACKEND.probe(image_of(tmp_path, b"\x00" * (64 * 2048), "z2.iso"), 0)
