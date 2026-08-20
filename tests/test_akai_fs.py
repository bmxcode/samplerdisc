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


def test_probe_accepts_a_single_volume_disc(tmp_path):
    """Unusual but real. Requiring two volumes would report "no filesystem"
    for a perfectly good disc -- a silent failure, which is what ADR-0005 is
    about. A lone volume is confirmed via its own file directory instead.
    """
    payload = fixtures.akai_sample("KICK")
    data = fixtures.akai_partition([("VOL 1", [("KICK", 0x73, len(payload), payload)])])
    assert BACKEND.probe(image_of(tmp_path, data, "one.iso"), 0)


def test_a_lone_volume_pointing_at_an_empty_directory_is_rejected(tmp_path):
    """The single-volume path must not become a way in for false positives."""
    from samplerdisc.fs.akai import BLOCK_SIZE

    data = bytearray(fixtures.akai_partition([("VOL 1", [("KICK", 0x73, 200, b"\x00" * 200)])]))
    # Wipe the volume's file directory.
    data[BLOCK_SIZE : 2 * BLOCK_SIZE] = b"\x00" * BLOCK_SIZE
    assert not BACKEND.probe(image_of(tmp_path, bytes(data), "empty.iso"), 0)


def test_probe_rejects_a_multi_volume_header_whose_volumes_hold_no_files(tmp_path):
    """Ordering and clean names are not evidence of a filesystem (ADR-0012).

    Two non-AKAI discs got this far on arbitrary mid-disc data -- an E-mu EMU3
    disc and a Digidesign SampleCell one -- and were reported as AKAI at a
    confident, wrong offset. Each yielded volumes with names like
    "010000000000" and zero files in every one, because a directory that merely
    looks plausible is one the walk then rejects entry by entry.

    Before the fix this returned True on sight of two ordered volumes, without
    ever opening one.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE

    data = bytearray(simple_partition())
    # Volume directories live at blocks 1 and 3; leave the header intact so the
    # ordering test still passes, and empty the directories it points at.
    for block in (1, 3):
        data[block * BLOCK_SIZE : (block + 1) * BLOCK_SIZE] = b"\x00" * BLOCK_SIZE
    assert not BACKEND.probe(image_of(tmp_path, bytes(data), "hollow.iso"), 0)


def test_probe_rejects_entries_whose_type_byte_is_not_a_file_type(tmp_path):
    """The probe applies the same type test the walk does.

    An unallocated volume can point at a block of 0x01 filler, and every 24
    bytes of that decodes to a plausible name with a non-zero size and start
    block. Only the type byte gives it away -- 0x01 is not one of "psdxmqt" --
    which is why the probe and ``_files`` must agree on what a valid entry is.
    When they disagree the disc comes back as volumes containing nothing, which
    reads as empty rather than as wrong.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE

    payload = fixtures.akai_sample("KICK")
    data = bytearray(fixtures.akai_partition([("VOL 1", [("KICK", 0x73, len(payload), payload)])]))
    data[BLOCK_SIZE : 2 * BLOCK_SIZE] = b"\x01" * BLOCK_SIZE
    assert not BACKEND.probe(image_of(tmp_path, bytes(data), "filler.iso"), 0)


def test_directory_stops_at_one_block(tmp_path):
    """A volume's file directory is one 8192-byte block.

    Reading further walks into the next block -- which is file data -- and
    yields "files" assembled from audio.
    """
    from samplerdisc.fs.akai import _MAX_FILES, BLOCK_SIZE, FILE_ENTRY_LEN

    assert _MAX_FILES == BLOCK_SIZE // FILE_ENTRY_LEN == 341


def test_a_volume_pointing_at_filler_yields_nothing(tmp_path):
    """An unallocated volume can point at a block of 0x01 filler.

    Every 24 bytes of it decodes to a plausible AKAI name, so without a type
    check the whole block reads as hundreds of files.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE

    payload = fixtures.akai_sample("KICK")
    data = bytearray(
        fixtures.akai_partition(
            [
                ("VOL 1", [("KICK", 0x73, len(payload), payload)]),
                ("VOLUME 016", [("X", 0x73, 32, b"\x00" * 32)]),
            ]
        )
    )
    # Point the second volume's directory at a block of filler.
    bogus = 40
    data[bogus * BLOCK_SIZE : (bogus + 1) * BLOCK_SIZE] = b"\x01" * BLOCK_SIZE
    import struct

    from samplerdisc.fs.akai import VOLUME_DIR_OFFSET, VOLUME_ENTRY_LEN

    struct.pack_into("<H", data, VOLUME_DIR_OFFSET + VOLUME_ENTRY_LEN + 14, bogus)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "f.iso"), 0)}
    assert [f.name for f in volumes["VOL 1"].files] == ["KICK"]
    assert volumes["VOLUME 016"].files == []


def test_deleted_entries_are_skipped_not_emitted(tmp_path):
    """A deleted file keeps its name but loses its type; its blocks are freed."""
    from samplerdisc.fs.akai import BLOCK_SIZE, FILE_ENTRY_LEN

    good = fixtures.akai_sample("KEEPER")
    data = bytearray(
        fixtures.akai_partition(
            [("VOL 1", [("GONE", 0x73, 100, b"\xff" * 100), ("KEEPER", 0x73, len(good), good)])]
        )
    )
    data[BLOCK_SIZE + 16] = 0x00  # clear the first entry's type byte
    volumes = list(BACKEND.volumes(image_of(tmp_path, bytes(data), "d.iso"), 0))
    assert [f.name for f in volumes[0].files] == ["KEEPER"]
    assert FILE_ENTRY_LEN == 24


# --- the allocation map, and why a volume is empty ----------------------


def test_the_volume_entry_type_is_a_byte_and_13_is_a_separate_field(tmp_path):
    """Reading the pair as one u16 inflates the type by 256 per volume.

    Harmless while nothing read the field, which is exactly how it survived:
    ``start`` sits at 14 and was never disturbed, so the walk found every
    volume on every disc regardless. The one disc that sets the byte at 13
    reported types of 513, 769 and 1025 in a triage sweep, which is what made
    it visible. See docs/formats/akai-fs.md.
    """
    import struct

    from samplerdisc.fs.akai import (
        VOLUME_DIR_OFFSET,
        VOLUME_INDEX_OFFSET,
        VOLUME_START_OFFSET,
        VOLUME_TYPE_OFFSET,
        VOLUME_TYPES,
    )

    data = bytearray(simple_partition())
    entry = VOLUME_DIR_OFFSET
    assert data[entry + VOLUME_TYPE_OFFSET] == 1
    # The readings docs/formats/akai-fs.md records, pinned here so the two
    # cannot drift apart quietly.
    assert VOLUME_TYPES[data[entry + VOLUME_TYPE_OFFSET]] == "S1000"
    assert VOLUME_TYPES == {0: "inactive", 1: "S1000", 3: "S3000", 7: "CD3000"}
    # Set the byte at 13 the way the one disc that uses it does. A u16 read
    # would call this type 0x0201; the walk must not care at all.
    data[entry + VOLUME_INDEX_OFFSET] = 2
    (start,) = struct.unpack_from("<H", data, entry + VOLUME_START_OFFSET)
    volumes = list(BACKEND.volumes(image_of(tmp_path, bytes(data), "i.iso"), 0))
    assert [v.name for v in volumes] == ["SOUP 101-103", "SOUP 104-105"]
    assert volumes[0].start_block == start
    assert [len(v.files) for v in volumes] == [1, 1]


def test_the_allocation_map_agrees_with_every_file_size(tmp_path):
    """The check that makes the map evidence rather than a hopeful reading."""
    from samplerdisc.fs.akai import (
        BLOCK_SIZE,
        FAT_CHAIN_END,
        FAT_VOLUME_DIR,
        allocation_map,
    )

    image = image_of(tmp_path, simple_partition(), "map.iso")
    allocation = allocation_map(image, 0)
    assert allocation
    for volume in BACKEND.volumes(image, 0):
        assert allocation[volume.start_block] == FAT_VOLUME_DIR
        for entry in volume.files:
            want = -(-entry.size // BLOCK_SIZE)
            block, length = entry.start_block, 0
            while length <= want:
                length += 1
                if allocation[block] >= FAT_VOLUME_DIR:
                    break
                block = allocation[block]
            assert length == want
            assert allocation[block] == FAT_CHAIN_END


def test_a_stale_slot_pointing_into_file_data_says_so(tmp_path):
    """Issue #16: a slot AKAI formatted, whose start block was never cleared.

    The four on `Advance Orchestra` and the one on the OMI disc present as a
    default name, a type byte of 0 and a start block that lands inside a
    file's extent -- so the block holds PCM, and the walk stops on the first
    entry. What says it is not a volume is the map, which has that block
    chained to a file.
    """
    payload = fixtures.akai_sample("KICK", words=8192)
    data = fixtures.akai_partition(
        [("VOL 1", [("KICK", 0x73, len(payload), payload)])],
        # Block 2 is the first file's; block 3 is the second block of its
        # extent, which is where a stale pointer lands mid-sample.
        stale_slots=[("VOLUME 016", 3)],
    )
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, data, "s.iso"), 0)}
    assert [f.name for f in volumes["VOL 1"].files] == ["KICK"]
    stale = volumes["VOLUME 016"]
    assert stale.files == []
    assert "file data" in stale.note and "block 3" in stale.note


def test_a_stale_slot_pointing_at_a_free_block_says_so(tmp_path):
    """The other shape of an unused slot: a start block belonging to nothing."""
    payload = fixtures.akai_sample("KICK")
    data = fixtures.akai_partition(
        [("VOL 1", [("KICK", 0x73, len(payload), payload)])],
        stale_slots=[("VOLUME 018", 200)],
    )
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, data, "fr.iso"), 0)}
    empty = volumes["VOLUME 018"]
    assert empty.files == []
    assert empty.note == "block 200 is free in the partition's allocation map"


def test_a_declared_directory_that_is_not_there_says_so(tmp_path):
    """Issue #17: the map says volume directory, the image has none.

    This is what an image short of the disc it was made from looks like from
    inside the filesystem, and it is the case that must not be confused with
    an unused slot: here the disc is asserting that a directory belongs at
    that block, so the volume is real and the *image* is what is wrong.
    """
    import struct

    from samplerdisc.fs.akai import VOLUME_DIR_OFFSET, VOLUME_ENTRY_LEN, VOLUME_START_OFFSET

    payload = fixtures.akai_sample("KICK")
    data = bytearray(
        fixtures.akai_partition(
            [
                ("VOL 1", [("KICK", 0x73, len(payload), payload)]),
                ("14-TRK06 MF1", [("X", 0x73, 32, b"\x00" * 32)]),
            ],
            phantom_directories=[300],
        )
    )
    # Point the second volume at the block the map calls a directory and the
    # image leaves empty, exactly as the four on `Kickin' Lunatic Beats 2 CD1`
    # point past the four 32 KB blocks their image is missing.
    struct.pack_into("<H", data, VOLUME_DIR_OFFSET + VOLUME_ENTRY_LEN + VOLUME_START_OFFSET, 300)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "p.iso"), 0)}
    lost = volumes["14-TRK06 MF1"]
    assert lost.files == []
    assert "marks block 300 a volume directory" in lost.note
    assert "no file entry could be read there" in lost.note


def test_a_volume_with_files_never_carries_a_note(tmp_path):
    """A note explains an emptiness. A volume that lists files has none to explain."""
    payload = fixtures.akai_sample("KICK")
    data = fixtures.akai_partition(
        [("VOL 1", [("KICK", 0x73, len(payload), payload)])],
        stale_slots=[("VOLUME 016", 400)],
    )
    volumes = list(BACKEND.volumes(image_of(tmp_path, data, "n.iso"), 0))
    assert [(v.name, bool(v.note)) for v in volumes] == [("VOL 1", False), ("VOLUME 016", True)]


def test_no_allocation_map_means_no_note_rather_than_an_invented_one(tmp_path):
    """Silence beats a guess: an unexplained empty volume has to stay visible.

    A note is the one thing that distinguishes an emptiness the disc accounts
    for from the ADR-0012 signature. A backend that emitted one whenever it
    could not read the map would explain away exactly the case the invariant
    exists to catch, so a partition that declares nothing usable gets nothing.
    """
    from samplerdisc.fs.akai import allocation_map

    payload = fixtures.akai_sample("KICK")
    data = fixtures.akai_partition(
        [("VOL 1", [("KICK", 0x73, len(payload), payload)])],
        stale_slots=[("VOLUME 016", 400)],
        allocation_map=False,
    )
    image = image_of(tmp_path, data, "u.iso")
    assert allocation_map(image, 0) == []
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert volumes["VOLUME 016"].files == []
    assert volumes["VOLUME 016"].note == ""


def test_an_absurd_partition_size_yields_no_map(tmp_path):
    """The declared block count bounds the map, so it has to be sane first."""
    import struct

    from samplerdisc.fs.akai import PARTITION_BLOCKS_OFFSET, allocation_map

    data = bytearray(simple_partition())
    struct.pack_into("<H", data, PARTITION_BLOCKS_OFFSET, 0xFFFF)
    assert allocation_map(image_of(tmp_path, bytes(data), "a.iso"), 0) == []
    struct.pack_into("<H", data, PARTITION_BLOCKS_OFFSET, 0)
    assert allocation_map(image_of(tmp_path, bytes(data), "b.iso"), 0) == []
