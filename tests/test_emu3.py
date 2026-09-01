"""E-mu EMU3 filesystem tests against synthetic images (ADR-0008)."""

from __future__ import annotations

import re
import struct

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.emu3 import (
    BANK_MAGICS,
    OFF_CHECKSUM,
    OFF_SAMPLE_END_L,
    OFF_SAMPLE_END_R,
    OFF_SAMPLE_RATE,
    OFF_SAMPLE_START_L,
    OFF_SAMPLE_START_R,
    SAMPLE_HEADER_LEN,
    SUPERBLOCK_LEN,
    Emu3Backend,
    _form_e3s1_chunks,
    _superblock_checksum_ok,
    is_plausible_name,
    record_extent,
)
from samplerdisc.fs.probe import find_origin
from samplerdisc.sample.emu3 import DATA_START, MIN_LOOP_FRAMES
from samplerdisc.sample.emu3 import parse as parse_sample
from tests import fixtures

BACKEND = Emu3Backend()

ONE_FOLDER = [
    (
        "Default Folder",
        [
            ("Proteus1Presets", [("Piano E0", 20000, 2048), ("Piano A0", 15625, 1024)]),
            ("Proteus1Instrmt", [("Snare Verb", 32000, 512)]),
        ],
    )
]

THREE_FOLDERS = [
    ("Boom da Drumz", [("Scroggins Secret", [("Kick", 24000, 512)])]),
    ("Symphoniks", [("Orchestralcolorz", [("Strings", 22000, 512)])]),
    ("Strung Out", [("Strummer of Love", [("Guitar", 18000, 512)])]),
]


def image_of(tmp_path, data: bytes, name: str = "emu.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


# --- probe --------------------------------------------------------------


def _rechecksum(data: bytearray) -> bytearray:
    """Restore the superblock checksum after mutating a header field.

    A fixture writes a valid checksum, so mutating a byte breaks it -- which is
    the point of ``test_probe_rejects_a_corrupted_superblock_checksum`` but noise
    in a test isolating a *different* gate, since the checksum would reject the
    header before that gate runs.
    """
    words = struct.unpack_from(f"<{SUPERBLOCK_LEN // 2}H", data, 0)
    struct.pack_into("<H", data, OFF_CHECKSUM, sum(words[: OFF_CHECKSUM // 2]) % 0x10000)
    return data


def test_probe_accepts_a_real_emu3_header(tmp_path):
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    assert BACKEND.probe(image, 0)


def test_probe_rejects_the_magic_alone(tmp_path):
    """Four bytes is not a filesystem (ADR-0012).

    The header's own arithmetic must close and the directory it names must
    actually yield a bank. The checksum is repaired after the mutation so this
    exercises the arithmetic gate and not the checksum gate, which would
    otherwise reject the header first.
    """
    data = bytearray(fixtures.emu3_disc(ONE_FOLDER))
    data[0x08:0x0C] = (99).to_bytes(4, "little")  # folder + reserved no longer == banks
    assert not BACKEND.probe(image_of(tmp_path, bytes(_rechecksum(data)), "broken.iso"), 0)


def test_probe_rejects_a_corrupted_superblock_checksum(tmp_path):
    """A header whose 0x1FE checksum does not verify is not this filesystem (#66).

    This is the gate that catches a truncated rip or a wrong container track
    start (ADR-0005): flip one header byte and leave the stored checksum, and the
    sum no longer matches -- exactly what a mis-offset or damaged header looks
    like. A whole valid disc otherwise, so only the checksum decides.
    """
    data = bytearray(fixtures.emu3_disc(ONE_FOLDER))
    assert _superblock_checksum_ok(bytes(data[:SUPERBLOCK_LEN]))
    data[0x40] ^= 0x01  # a byte inside the summed range, checksum left stale
    assert not _superblock_checksum_ok(bytes(data[:SUPERBLOCK_LEN]))
    assert not BACKEND.probe(image_of(tmp_path, bytes(data), "corrupt.iso"), 0)


def test_probe_rejects_a_truncated_header(tmp_path):
    """A header short of a whole 512-byte block cannot carry the checksum (#66)."""
    data = fixtures.emu3_disc(ONE_FOLDER)[: SUPERBLOCK_LEN - 2]
    assert not BACKEND.probe(image_of(tmp_path, data, "short.iso"), 0)


def test_probe_rejects_zeros_and_noise(tmp_path):
    assert not BACKEND.probe(image_of(tmp_path, b"\x00" * 65536, "z.iso"), 0)
    assert not BACKEND.probe(image_of(tmp_path, fixtures.incompressible_block(3) * 2, "n.iso"), 0)


def test_origin_probe_resolves_to_emu3(tmp_path):
    """One half of ADR-0005: the header sits at byte 0 of the cooked stream.

    This is the common case and it resolves at offset 0, so on its own it never
    exercises a non-zero origin -- the test below does that.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "emu3"
    assert origin.offset == 0


def test_origin_resolves_when_the_pregap_is_inside_the_cooked_stream(tmp_path):
    """The other half of ADR-0005: the pregap genuinely in the stream.

    ``test_origin_probe_resolves_to_emu3`` resolves at 0 and so never exercises
    a non-zero origin. Here the 150 zeroed sectors really are in the reported
    stream -- a hybrid disc or a raw rip -- and the resolved origin must be the
    byte the header sits on, not zero. Getting it wrong reads as an empty disc.
    """
    pregap = b"\x00" * (150 * 2048)
    image = image_of(tmp_path, pregap + fixtures.emu3_disc(ONE_FOLDER), "gap.iso")
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "emu3"
    assert origin.offset == 150 * 2048
    # And the samples resolve from the resolved origin exactly as at offset 0.
    # The bug this guards: the bank-header and E-IV scans returned addresses
    # relative to the file rather than the origin, so at a non-zero origin the
    # banks listed and every one came back empty -- the silent empty-disc
    # failure ADR-0005 exists to prevent, reached this time from inside the fs.
    banks = {v.name: v for v in origin.backend.volumes(image, origin.offset)}
    assert [f.name for f in banks["Proteus1Presets"].files] == ["Piano E0", "Piano A0"]


# --- the folder table ---------------------------------------------------


def test_every_folder_is_walked_not_just_the_first(tmp_path):
    """The header points at the FIRST folder's directory, not at all of them.

    Walking only that one stops at its zero entry and loses every later
    folder -- 6 banks of 12 on the E-IV reference disc, with no error and a
    listing that looks complete.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(THREE_FOLDERS), "folders.iso")
    names = [v.name for v in BACKEND.volumes(image, 0)]
    assert names == ["Scroggins Secret", "Orchestralcolorz", "Strummer of Love"]


def test_folder_block_plus_reserved_equals_bank_block(tmp_path):
    """Verified on all five reference discs; the fixture must honour it too."""
    import struct

    data = fixtures.emu3_disc(ONE_FOLDER)
    folder, reserved, banks = (struct.unpack_from("<I", data, o)[0] for o in (0x08, 0x0C, 0x10))
    assert folder + reserved == banks


# --- names --------------------------------------------------------------


def test_names_may_be_padded_with_spaces_or_nuls(tmp_path):
    """Requiring one padding style silently truncates a directory.

    The E-IV disc NUL-pads. Rejecting that dropped 4 of its 12 banks, and
    because a hex dump prints NUL exactly like a full stop the cause is easy
    to look straight past.
    """
    assert is_plausible_name(b"Scroggins Secret")
    assert is_plausible_name(b"619 Grooved\x00\x00\x00\x00\x00")
    assert not is_plausible_name(b"\x00" * 16)
    assert not is_plausible_name(b"bad\x01name\x00\x00\x00\x00\x00\x00\x00\x00")

    image = image_of(tmp_path, fixtures.emu3_disc(THREE_FOLDERS, nul_padded=True), "nul.iso")
    volumes = list(BACKEND.volumes(image, 0))
    assert [v.name for v in volumes] == [
        "Scroggins Secret",
        "Orchestralcolorz",
        "Strummer of Love",
    ]


# --- samples ------------------------------------------------------------


def test_samples_are_found_with_their_rates(tmp_path):
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    first = volumes["Proteus1Presets"]
    assert [f.name for f in first.files] == ["Piano E0", "Piano A0"]
    assert [f.raw_type for f in first.files] == [20000, 15625]
    assert [f.size for f in first.files] == [4096, 2048]


def test_a_sample_walk_stops_at_its_own_bank(tmp_path):
    """A bank ends where the next one begins.

    Without that bound the walk runs into the neighbouring bank and reports
    its samples as this one's -- which reads as a plausible listing, not as an
    error.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert [f.name for f in volumes["Proteus1Instrmt"].files] == ["Snare Verb"]


def test_payload_is_returned_verbatim(tmp_path):
    """No conversion anywhere: the record's payload is already 16-bit LE PCM."""
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    volume = next(v for v in BACKEND.volumes(image, 0) if v.files)
    entry = volume.files[0]
    payload = BACKEND.read_file(image, 0, entry)
    assert len(payload) == entry.size
    assert payload == image.read(entry.start_block, entry.size)


INDEX_BANK = [
    (
        "Designed by S&M.",
        [
            ("E-mu Banks 1-44", []),
            ("Full Arco String", [("Arco C1", 22000, 512)]),
        ],
    )
]


def test_a_bank_that_declares_no_sample_area_says_so(tmp_path):
    """An index bank is empty because the disc made it empty.

    Three EIII/ESI reference discs carry exactly one bank each that holds the
    library's index and no audio -- `esi32-gm`'s ``General Midi   X``,
    ``E-mu Banks 1-44``, ``Emu Banks 45-88``. Each is located by its own
    header and bounded to exactly the one allocation unit its directory entry
    claims, so the walk is right and the bank really is empty. Without the
    note that reads identically to a bank whose bound is wrong (ADR-0012).
    """
    image = image_of(tmp_path, fixtures.emu3_disc(INDEX_BANK), "index.iso")
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    index = volumes["E-mu Banks 1-44"]
    assert index.files == []
    assert index.note
    # The bank beside it is untouched: the note is not a blanket excuse.
    assert [f.name for f in volumes["Full Arco String"].files] == ["Arco C1"]
    assert not volumes["Full Arco String"].note


def test_an_unexplained_empty_bank_gets_no_note(tmp_path):
    """The note states a fact, so it must not appear where the fact is absent.

    A bank that declares sample data and yields none is the ADR-0012 signature
    and has to stay visible as such. Noting it unconditionally -- "no samples
    found" -- would silence the one check that catches a mis-bounded walk.
    """
    data = bytearray(fixtures.emu3_disc(INDEX_BANK))
    record = data.index(b"Arco C1") - 2  # a record begins two bytes before its name
    struct.pack_into("<I", data, record + OFF_SAMPLE_START_L, 0)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "u.iso"), 0)}
    assert volumes["Full Arco String"].files == []
    assert not volumes["Full Arco String"].note


# --- the record extent (ADR-0029) ---------------------------------------


def _extent_header(start_l: int = 0, end_l: int = 0, start_r: int = 0, end_r: int = 0) -> bytes:
    """A 92-byte record header carrying just the four extent pointers."""
    head = bytearray(SAMPLE_HEADER_LEN)
    for offset, value in (
        (OFF_SAMPLE_START_L, start_l),
        (OFF_SAMPLE_END_L, end_l),
        (OFF_SAMPLE_START_R, start_r),
        (OFF_SAMPLE_END_R, end_r),
    ):
        struct.pack_into("<I", head, offset, value)
    return bytes(head)


def test_the_extent_comes_from_the_set_that_opens_the_audio():
    """``+34`` is the right channel's end, not the record's length.

    Four shapes the right-hand set takes on the reference discs when it is not
    describing the record it sits in, and all four broke a reader that took
    ``+34`` for a length: 7 005 records where it is the left set counted from
    the payload rather than the record, 872 with the side zeroed, 95 naming a
    fixed memory frame, and 1 371 that declare their one channel on the right.
    Together they are why `ditto-drums` read 74 samples where it holds 948.
    """
    payload = 4096
    end = SAMPLE_HEADER_LEN + payload - 2

    # mirror-92: the right set is the left set counted from the payload start.
    assert record_extent(_extent_header(start_l=92, end_l=end, end_r=end - 92)) == end + 2
    # zeroed: the unused side is all zeros, and +34 would give an extent of 2.
    assert record_extent(_extent_header(start_l=92, end_l=end)) == end + 2
    # a fixed allocation frame, which +34 would put past the whole bank.
    frame = 1 << 20
    assert (
        record_extent(
            _extent_header(start_l=92, end_l=end, start_r=92 + frame, end_r=92 + 2 * frame - 2)
        )
        == end + 2
    )
    # the one channel declared on the right, which the left-hand signature
    # never sees at all.
    assert record_extent(_extent_header(start_r=92, end_r=end)) == end + 2


def test_a_two_channel_record_runs_to_the_end_of_its_second_block():
    """The one case where ``+34`` is the record's far end.

    The right block opens exactly where the left one closes and the two are
    the same length -- ADR-0026's gate, stated from the pointers alone so that
    it does not need the payload size it is being used to compute.
    """
    half = 2048
    split = SAMPLE_HEADER_LEN + half
    assert (
        record_extent(
            _extent_header(start_l=92, end_l=split - 2, start_r=split, end_r=split + half - 2)
        )
        == split + half
    )


def test_a_record_where_neither_set_opens_the_audio_is_refused():
    """Refused, not guessed at. A header too short for the block likewise:
    a record that was not read must not present as one that declared nothing.
    """
    assert record_extent(_extent_header(end_l=4096)) is None
    assert record_extent(b"\x00" * 30) is None


def test_a_bank_of_right_declared_records_is_not_an_empty_bank(tmp_path):
    """`vintage`'s ``Juno Synths``, in miniature.

    Every record in that bank puts 0 in ``start_L`` and 92 in ``start_R``, so
    a walk whose signature is 92 at ``+22`` finds nothing and the bank claims
    a volume and returns no files -- the ADR-0012 signature, and issue #39.
    """
    data = bytearray(fixtures.emu3_disc(ONE_FOLDER))
    at = data.index(b"Piano E0") - 2
    struct.pack_into("<I", data, at + OFF_SAMPLE_START_L, 0)
    struct.pack_into("<I", data, at + OFF_SAMPLE_START_R, SAMPLE_HEADER_LEN)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "right.iso"), 0)}
    found = {f.name: f.size for f in volumes["Proteus1Presets"].files}
    assert found == {"Piano E0": 4096, "Piano A0": 2048}


def test_a_record_with_its_unused_side_zeroed_keeps_its_length(tmp_path):
    """872 records on `ditto-drums` zero the side they do not use, and ``+34``
    then gives an extent of 2 -- shorter than the header, so the record is
    dropped and nine of that disc's banks read as empty.
    """
    data = bytearray(fixtures.emu3_disc(ONE_FOLDER))
    at = data.index(b"Piano E0") - 2
    struct.pack_into("<I", data, at + OFF_SAMPLE_END_R, 0)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "zero.iso"), 0)}
    found = {f.name: f.size for f in volumes["Proteus1Presets"].files}
    assert found == {"Piano E0": 4096, "Piano A0": 2048}


#: Four banks, because the placement fit below needs three names it can trust
#: before it will arbitrate a fourth that is written twice.
FOUR_BANKS = [
    (
        "Default Folder",
        [
            ("Orbit Presets  X", [("Ahh2 SW", 15000, 512), ("Attack Rim", 30000, 256)]),
            ("Orbit Presets 4k", [("Ahh2 SW", 15000, 512), ("Attack Rim", 30000, 256)]),
            ("Orbit Instrmt  X", [("ARP3Cx4", 27996, 128)]),
            ("Phatt Presets  X", [("Full Kik", 26000, 512)]),
        ],
    )
]


def test_a_formula_4000_bank_header_locates_its_bank(tmp_path):
    """``EMU SI-32`` is a bank header too, and a bank nobody locates is worse
    than a bank nobody reads.

    `protozoa` writes it on ``Orbit Presets 4k`` and ``Phatt Presets 4K``.
    Both are ordinary banks -- same header layout, same records -- and
    recognising only ``EMULATOR`` left them with no header at all, which
    handed each one's region to the bank in front of it: ``Orbit Presets  X``
    reported 1 077 records where its own 8 MiB holds 539.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(FOUR_BANKS, formula_4000=("Orbit Presets 4k",)))
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert [f.name for f in volumes["Orbit Presets 4k"].files] == ["Ahh2 SW", "Attack Rim"]
    assert not volumes["Orbit Presets 4k"].note
    # And the bank in front of it keeps to its own records rather than
    # counting its neighbour's a second time.
    assert [f.name for f in volumes["Orbit Presets  X"].files] == ["Ahh2 SW", "Attack Rim"]


def test_a_bank_reports_only_the_records_its_own_header_declares(tmp_path):
    """A bank's region holds more than the bank (ADR-0021).

    Mastering writes a bank image into a fixed region and whatever was there
    before survives past its end. On `protozoa` that leftover is 264 records
    in ``Vintage+InstrmtX`` alone, every one of them another bank's record at
    a constant offset -- and inside the region, so no bound drawn between
    banks can exclude it. The bank's own ``0x34`` can.
    """
    image = image_of(
        tmp_path,
        fixtures.emu3_disc(FOUR_BANKS, stale_tail=(("Left Behind", 22000, 256),)),
        "stale.iso",
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    for volume in volumes.values():
        assert "Left Behind" not in [f.name for f in volume.files], volume.name
    assert [f.name for f in volumes["Orbit Instrmt  X"].files] == ["ARP3Cx4"]


def test_the_bank_a_directory_entry_means_is_the_one_it_placed(tmp_path):
    """Two headers, one name: the directory's placement decides.

    `esi32-gm` keeps an older revision of two banks in a region it allocates
    to nobody, *below* the banks its directory points at, and `protozoa`
    keeps a second ``Phatt Presets  X`` above them. Taking the first header
    of each name reads the wrong copy on one disc, and taking the last reads
    the wrong copy on the other. Neither is a rule; where the directory put
    the bank is.
    """
    image = image_of(
        tmp_path,
        fixtures.emu3_disc(FOUR_BANKS, second_header="Phatt Presets  X"),
        "twice.iso",
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert [f.name for f in volumes["Phatt Presets  X"].files] == ["Full Kik"]


def test_a_bank_with_no_header_on_an_eiii_disc_says_which_structure_is_missing(tmp_path):
    """The note names what was looked for, and the two discs look for
    different things.

    ``E3 Main Code`` on the three EIII/ESI reference discs is a bank slot
    holding the sampler's operating system: it has no bank header, and it has
    no E-IV sample directory either, because the disc has none anywhere. It
    was being told it had no *sample directory*, which named a structure that
    format does not use.
    """
    banks = [
        ("Default Folder", [("E3 Main Code", []), ("Orbit Presets  X", [("Ahh2 SW", 15000, 512)])])
    ]
    data = bytearray(fixtures.emu3_disc(banks))
    # Strip the code bank's header, which is what the real discs do -- the
    # bank beside it keeps its own and so the disc is still an EIII one.
    at = next(
        m.start()
        for m in re.finditer(re.escape(BANK_MAGICS[0]), data)
        if data[m.start() + 16 : m.start() + 27] == b"E3 Main Cod"
    )
    data[at : at + 64] = b"\x00" * 64
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "code.iso"), 0)}
    assert volumes["E3 Main Code"].files == []
    assert volumes["E3 Main Code"].note == "no bank header found for this bank; listed only"
    assert [f.name for f in volumes["Orbit Presets  X"].files] == ["Ahh2 SW"]


def test_a_bank_with_neither_header_nor_directory_is_listed_with_a_note(tmp_path):
    """A bank whose interior yields nothing must say so.

    E-IV banks are read now (ADR-0020), but a bank with no ``EMULATOR`` header
    *and* no ``E3S1`` sample directory still cannot be opened. It is listed
    with its real name and an explanation. The note is load-bearing: a volume
    with no files and no note is indistinguishable from a probe that matched
    garbage (ADR-0012), and the disc-backed suite asserts exactly that.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(THREE_FOLDERS, bank_header=False), "noheader.iso")
    volumes = list(BACKEND.volumes(image, 0))
    assert len(volumes) == 3
    assert all(v.files == [] for v in volumes)
    assert all(v.note for v in volumes)


# --- a mistyped header name (ADR-0031) ----------------------------------


def test_near_name_matches_the_mistyped_headers_and_nothing_else():
    """The five real corruptions match; the two OS-slot collisions do not.

    Every recovery on the real discs is a shifted space, a case change or one
    doubled/dropped character -- normalised away, an edit of at most one. The
    ``E3 Main Code``/``E3X Main Code`` slots whose arithmetic lands on another
    bank's header are a dozen edits off, which is the margin the gate lives in.
    """
    from samplerdisc.fs.emu3 import _near_name

    for directory, header in (
        ("Electric Grand X", "Eelectric GrandX"),
        ("PERCUSSION#1   X", "PERCUSSION #1  X"),
        ("HvyGtr FX5     X", "HvyGtr FX5    XX"),
        ("Misc Gtr FX 2MbX", "Misc Gtr FX 2mbX"),
        ("HvGtrFdBkTxtr2Mb", "HvGtrFdBkTxtr2M"),
    ):
        assert _near_name(directory, header), (directory, header)
    assert not _near_name("E3 Main Code", "Ditto Drums    X")
    assert not _near_name("E3X Main Code", "DAVE W  KIT1   X")


def test_bank_offsets_recovers_a_mistyped_header_only_when_unclaimed():
    """The recovery binds a near-named header the placement predicts, and only
    then (ADR-0031).

    Three exactly-named banks pin the fit at ``unit == 100``. ``Delta``'s
    header is mistyped ``Deltaa`` at the address it predicts and is recovered;
    ``Echo``'s predicted address holds an unrelated name and is not; and
    ``Alphaa`` -- near ``Alpha`` but predicting an address ``Alpha`` already
    owns -- is refused, because a bank may never take a header another entry
    already claims.
    """
    from samplerdisc.fs.emu3 import _Bank

    backend = Emu3Backend()
    headers = [
        (100, "Alpha"),
        (200, "Beta"),
        (300, "Gamma"),
        (400, "Deltaa"),
        (500, "Zulu Foxtrot"),
    ]
    banks = [
        _Bank("Alpha", "", 1, 1),
        _Bank("Beta", "", 2, 1),
        _Bank("Gamma", "", 3, 1),
        _Bank("Delta", "", 4, 1),
        _Bank("Echo", "", 5, 1),
        _Bank("Alphaa", "", 1, 1),
    ]
    # Keyed by directory-entry index, not by name (ADR-0034): banks[3] is
    # ``Delta``, banks[4] ``Echo``, banks[5] ``Alphaa``, banks[0] ``Alpha``.
    found = backend._bank_offsets(banks, headers)
    assert found[3] == 400  # mistyped header, recovered by its address
    assert 4 not in found  # predicted address holds a far name
    assert 5 not in found  # would steal Alpha's header, refused
    assert found[0] == 100  # the claim it would have stolen is intact


def test_bank_offsets_splits_a_name_written_twice_across_its_own_headers():
    """A directory name written twice binds each entry to its own header, and
    never both to one (ADR-0034, #47).

    Two shapes occur on real discs and both are here. ``Piano`` is written
    twice with a real header apiece -- `elements1mb`'s ``Harpsichord    X`` --
    and the placement fit gives each entry the header at its own predicted
    address, so the two do not collapse onto one and double-list its records.
    ``Organ`` is written twice with only *one* header wearing the name --
    `heavy`'s ``HvyGtr Maj.Open`` -- and its second entry's predicted address
    holds a blank-named header whose name confirms nothing; that entry binds
    nothing rather than being handed a header by address alone (ADR-0031).
    """
    from samplerdisc.fs.emu3 import _Bank

    backend = Emu3Backend()
    headers = [
        (100, "Aaa"),
        (200, "Bbb"),
        (300, "Ccc"),
        (400, "Piano"),
        (500, "Organ"),
        (600, "        X"),  # a blank-named header, as `heavy` writes
        (700, "Piano"),
    ]
    banks = [
        _Bank("Aaa", "", 1, 1),
        _Bank("Bbb", "", 2, 1),
        _Bank("Ccc", "", 3, 1),
        _Bank("Piano", "", 4, 1),  # index 3: predicts 400
        _Bank("Piano", "", 7, 1),  # index 4: predicts 700 -- its own header
        _Bank("Organ", "", 5, 1),  # index 5: predicts 500, the one real header
        _Bank("Organ", "", 6, 1),  # index 6: predicts 600, a blank name -> note
    ]
    found = backend._bank_offsets(banks, headers)
    assert found[3] == 400
    assert found[4] == 700
    assert found[3] != found[4]  # the two Piano entries do not collapse
    assert found[5] == 500
    assert 6 not in found  # the blank-named header confirms nothing


def test_a_mistyped_bank_header_is_recovered_end_to_end(tmp_path):
    """A bank whose header name the mastering mistyped reads its records.

    ``Gutar Leads  X`` carries a real ``EMULATOR`` header at the address its
    directory placement predicts, but the header's own name is one edit off, so
    keying ``located`` on exact-name equality listed it empty with a note. The
    address plus the near-name gate binds it. ``OS Reserved  X`` sits at an
    address whose header carries an unrelated name -- the OS-slot shape -- and
    stays noted, which is what proves the gate is not merely accepting whatever
    header the arithmetic reaches.
    """
    banks = [
        (
            "Default Folder",
            [
                ("Piano Grand  X", [("Grand C1", 20000, 512)]),
                ("Strings Warm X", [("Str A2", 22000, 512)]),
                ("Brass Bright X", [("Brs D3", 24000, 512)]),
                ("Gutar Leads  X", [("Lead E1", 26000, 512)]),
                ("OS Reserved  X", [("Unread", 28000, 256)]),
            ],
        )
    ]
    image = image_of(
        tmp_path,
        fixtures.emu3_disc(
            banks,
            header_names={
                "Gutar Leads  X": "Gutarr Leads X",  # one edit: recovered
                "OS Reserved  X": "Zebra Marimba X",  # unrelated: not recovered
            },
        ),
        "mistyped.iso",
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert [f.name for f in volumes["Gutar Leads  X"].files] == ["Lead E1"]
    assert not volumes["Gutar Leads  X"].note
    assert volumes["OS Reserved  X"].files == []
    assert volumes["OS Reserved  X"].note == "no bank header found for this bank; listed only"
    # The banks that pinned the fit are untouched.
    assert [f.name for f in volumes["Piano Grand  X"].files] == ["Grand C1"]


# --- E-IV ---------------------------------------------------------------


#: Two banks carry more than one sample, which is the minimum that pins the
#: allocation unit down -- a single corroborated chain fits any unit at some
#: bias. The third has one sample, and must still bind off the others' fit.
EIV_FOLDERS = [
    (
        "Boom da Drumz",
        [
            ("Scroggins Secret", [("Stage Door", 44100, 512), ("All Nines", 44100, 256)]),
            ("TribebunillDrumd", [("Tribebunill J.75", 24000, 300), ("Rattle Traps", 44100, 128)]),
        ],
    ),
    ("Symphoniks", [("Orchestralcolorz", [("Strings", 22000, 512)])]),
]


def test_eiv_banks_extract_their_samples(tmp_path):
    """E-IV banks carry no ``EMULATOR`` header and are still read.

    They are reached through a chained ``E3S1`` sample directory instead --
    the finding that made ADR-0015's conditional position expire.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(EIV_FOLDERS, eiv=True), "eiv.iso")
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert set(volumes) == {"Scroggins Secret", "TribebunillDrumd", "Orchestralcolorz"}
    assert [f.name for f in volumes["Scroggins Secret"].files] == ["Stage Door", "All Nines"]
    assert [f.raw_type for f in volumes["Scroggins Secret"].files] == [44100, 44100]
    assert not any(v.note for v in volumes.values())


def test_an_eiv_bank_reports_only_its_own_samples(tmp_path):
    """The chain bounds a bank; a neighbour's samples are not adopted.

    Without a bound this reads as a longer, entirely believable listing rather
    than as an error -- the failure ADR-0015 was written against.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(EIV_FOLDERS, eiv=True), "eiv.iso")
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert [f.name for f in volumes["TribebunillDrumd"].files] == [
        "Tribebunill J.75",
        "Rattle Traps",
    ]
    assert [f.name for f in volumes["Orchestralcolorz"].files] == ["Strings"]


def test_eiv_samples_resolve_when_the_pregap_is_inside_the_cooked_stream(tmp_path):
    """ADR-0005 for the E-IV path, which locates records by a whole-image scan.

    That scan and the ``E3S1`` directory bind records at addresses the reader
    later reads at ``offset + address``. Keyed from the file rather than the
    origin, a 150-sector pregap left in the stream shifts every record so the
    bind lands past it and each bank comes back empty -- a folder that lists and
    yields nothing. Here the origin is non-zero and the samples must still come
    out.
    """
    pregap = b"\x00" * (150 * 2048)
    image = image_of(tmp_path, pregap + fixtures.emu3_disc(EIV_FOLDERS, eiv=True), "gap.iso")
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "emu3"
    assert origin.offset == 150 * 2048
    volumes = {v.name: v for v in origin.backend.volumes(image, origin.offset)}
    scroggins = volumes["Scroggins Secret"].files
    assert [f.name for f in scroggins] == ["Stage Door", "All Nines"]
    # The listing alone is not enough here: E-IV records are read from an
    # in-memory scan window, so a bank still *lists* under the file-relative
    # scan. The PCM is what exposes the bug -- ``read_file`` adds the origin to
    # the record address, so a scan keyed from the file read 1 024 zero bytes
    # out of the pregap: a silent empty sample of the right length, not an error.
    expected = fixtures.stereo_audio_block(frames=512 // 2)[: 512 * 2]
    assert origin.backend.read_file(image, origin.offset, scroggins[0]) == expected
    assert not any(v.note for v in volumes.values())


def test_a_single_sample_eiv_bank_still_binds(tmp_path):
    """A lone directory entry has no chain invariant, and is not lost for it.

    It cannot vote on the allocation unit -- only corroborated chains do that
    -- but once that fit is settled it must land exactly where the fit says.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(EIV_FOLDERS, eiv=True), "eiv.iso")
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    assert len(volumes["Orchestralcolorz"].files) == 1


def test_the_eiv_directory_is_big_endian(tmp_path):
    """The sample directory is the one big-endian structure in the format.

    Everything else -- every EIII header field and the payload itself -- is
    little-endian, and docs/formats/emu3.md records how convincingly that got
    read the wrong way round once. Byte-swapping a length must break the
    chain, not quietly resize a sample.
    """
    data = bytearray(fixtures.emu3_disc(EIV_FOLDERS, eiv=True))
    at = data.find(b"E3S1", 32 * 512)
    length = struct.unpack_from(">I", data, at + 4)[0]
    struct.pack_into("<I", data, at + 4, length)  # same bytes, wrong way round
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "swap.iso"), 0)}
    assert volumes["Scroggins Secret"].files == []
    assert volumes["Scroggins Secret"].note


def test_the_directory_sizes_the_sample_not_the_record(tmp_path):
    """The record's own length field is not usable on E-IV.

    ``+34`` plus the EIII bias of two matches the distance to the next record
    on 0 of 522, 0 of 3893 and 0 of 934 consecutive pairs across the three
    reference discs. The directory's big-endian length matches on every one.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(EIV_FOLDERS, eiv=True), "eiv.iso")
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    first = volumes["Scroggins Secret"].files[0]
    assert first.size == 1024
    assert len(BACKEND.read_file(image, 0, first)) == first.size


def test_an_eiv_record_declaring_no_header_length_still_reads(tmp_path):
    """``OFF_SAMPLE_START_L`` reads 0 on 547 of `studio`'s records.

    Requiring it to equal 92, as the EIII walk does, drops a fifth of that
    disc. The directory already says where the record is and what it is
    called, so the field is not needed to confirm one.
    """
    data = bytearray(fixtures.emu3_disc(EIV_FOLDERS, eiv=True))
    at = data.find(b"Stage Door", 64 * 512)
    struct.pack_into("<I", data, at - 2 + OFF_SAMPLE_START_L, 0)
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, bytes(data), "hdr0.iso"), 0)}
    assert [f.name for f in volumes["Scroggins Secret"].files] == ["Stage Door", "All Nines"]


def test_a_directory_written_twice_yields_each_sample_once(tmp_path):
    """Two chains can resolve to one base, and must not list the record twice.

    On `analogia` concatenating them gave 509 samples at 449 distinct
    addresses -- 60 byte-identical WAVs, under names that looked like a
    genuine stereo pair rather than like a bug.
    """
    image = image_of(
        tmp_path,
        fixtures.emu3_disc(EIV_FOLDERS, eiv=True, duplicate_sample_dir=True),
        "twice.iso",
    )
    files = [f for v in BACKEND.volumes(image, 0) for f in v.files]
    assert len(files) == 5
    assert len({f.start_block for f in files}) == 5


def test_folder_entries_need_not_carry_the_0xffff_flags(tmp_path):
    """`studio` writes 0x0013 and 0x0018 on its first two folders.

    Requiring 0xFFFF aborts the folder walk on entry 0, finds no folders at
    all, and silently falls back to the single directory the header points at
    -- 77 banks of the 230 that disc has.
    """
    image = image_of(
        tmp_path,
        fixtures.emu3_disc(EIV_FOLDERS, eiv=True, folder_flags=0x0013),
        "flags.iso",
    )
    assert len(list(BACKEND.volumes(image, 0))) == 3


# --- FORM/E4B0 banks (D25, ADR-0032) ------------------------------------


#: Flat banks alone fix the allocation fit; the FORM banks carry no flat
#: directory and bind only through the FORM at the address that fit predicts --
#: exactly as on the real discs, where the fit rests on the flat sample banks.
#: Two multi-sample banks corroborate the unit and a single-sample bank pins it
#: (a lone pair fits several units at some bias). ``Studio Snare`` embeds two
#: samples as ``E3S1`` chunks; ``Credits`` is a FORM with a preset chunk and no
#: sample -- the residual case.
EIV_FORM_FOLDERS = [
    (
        "Studio Kits",
        [
            ("Live Room", [("Kick Axis", 44100, 512), ("Snare Top", 44100, 256)]),
            ("Room Verb", [("Tom Floor", 24000, 300), ("Hat Tight", 44100, 128)]),
            ("Studio Snare", [("Snare 01", 44100, 400), ("Snare 02", 22000, 220)]),
            # The single-sample flat bank sits a slot past the FORM so its base
            # is one the true unit alone explains -- a half-unit fit would need a
            # bank start this disc does not have, which is what pins the fit.
            ("Perc Kit", [("Shaker", 32000, 200)]),
            ("Credits", []),
        ],
    ),
]
FORM_BANKS = ("Studio Snare", "Credits")


def test_a_form_e4b0_bank_extracts_its_e3s1_chunk_samples(tmp_path):
    """The D25 recovery: a native FORM/E4B0 bank is not empty.

    Its samples are ``E3S1`` chunks inside the IFF container rather than a flat
    record run, so the chained-directory reader bound nothing and listed it
    empty. The same per-disc allocation fit the flat banks establish predicts
    the FORM's address, and the chunk body is the record the rest of the path
    already reads (ADR-0032).
    """
    image = image_of(
        tmp_path, fixtures.emu3_disc(EIV_FORM_FOLDERS, eiv=True, form_banks=FORM_BANKS), "form.iso"
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    snare = volumes["Studio Snare"]
    assert [f.name for f in snare.files] == ["Snare 01", "Snare 02"]
    assert [f.raw_type for f in snare.files] == [44100, 22000]
    assert not snare.note
    # The flat banks that corroborate the fit are untouched by the new path.
    assert [f.name for f in volumes["Live Room"].files] == ["Kick Axis", "Snare Top"]
    # And the payload comes back verbatim, so it is really read, not just listed.
    expected = fixtures.stereo_audio_block(frames=400 // 2)[: 400 * 2]
    assert BACKEND.read_file(image, 0, snare.files[0]) == expected


def test_a_form_bank_sample_is_sized_by_its_chunk(tmp_path):
    """The IFF chunk size is the record length, as the directory's BE length is
    for a flat bank -- the record's own ``+34`` is unusable on E-IV either way.
    """
    image = image_of(
        tmp_path, fixtures.emu3_disc(EIV_FORM_FOLDERS, eiv=True, form_banks=FORM_BANKS), "form.iso"
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    first = volumes["Studio Snare"].files[0]
    assert first.size == 400 * 2
    assert len(BACKEND.read_file(image, 0, first)) == first.size


def test_a_sample_free_form_bank_is_noted_not_silent(tmp_path):
    """A FORM the disc placed here that holds no sample chunk -- the ``Credits``
    text banks and a few preset banks -- is correctly located and genuinely
    empty, and must say so with a note of its own rather than the generic one,
    now that a bank without a flat directory may still carry audio (ADR-0012).
    """
    image = image_of(
        tmp_path, fixtures.emu3_disc(EIV_FORM_FOLDERS, eiv=True, form_banks=FORM_BANKS), "form.iso"
    )
    volumes = {v.name: v for v in BACKEND.volumes(image, 0)}
    credits = volumes["Credits"]
    assert credits.files == []
    assert credits.note == "the bank holds presets or text and no samples; listed only"
    assert "no sample directory" not in credits.note


#: The FORM bank last, so truncating it leaves the three flat banks that pin
#: the allocation fit intact -- the cut is meant to damage the FORM, not the fit.
EIV_TRUNC_FOLDERS = [
    (
        "Studio Kits",
        [
            ("Live Room", [("Kick Axis", 44100, 512), ("Snare Top", 44100, 256)]),
            ("Room Verb", [("Tom Floor", 24000, 300), ("Hat Tight", 44100, 128)]),
            ("Perc Kit", [("Shaker", 32000, 200)]),
            ("Studio Snare", [("Snare 01", 44100, 400), ("Snare 02", 22000, 220)]),
        ],
    ),
]


def test_a_truncated_form_bank_degrades_to_its_whole_samples(tmp_path):
    """Damaged input degrades, it does not crash (ADR-0012).

    Cutting the image partway through the FORM's second sample chunk drops that
    sample -- its body is not wholly present -- and keeps the first, without
    raising and without reading past the end of the image.
    """
    data = fixtures.emu3_disc(EIV_TRUNC_FOLDERS, eiv=True, form_banks=("Studio Snare",))
    # The FORM is the last bank; find its second sample and cut into it, so the
    # flat banks that pin the fit are untouched and only the FORM is damaged.
    second = data.find(b"Snare 02")
    assert second != -1
    truncated = data[: second + 32]  # inside the record, before its PCM ends
    volumes = {v.name: v for v in BACKEND.volumes(image_of(tmp_path, truncated, "cut.iso"), 0)}
    assert [f.name for f in volumes["Studio Snare"].files] == ["Snare 01"]


def _form_bytes(chunks: list[bytes], declared_size: int | None = None) -> bytes:
    body = b"E4B0" + b"".join(chunks)
    size = len(body) if declared_size is None else declared_size
    return b"FORM" + struct.pack(">I", size) + body


def _e3s1_chunk(name: str, pcm: bytes, rate: int = 44100) -> bytes:
    head = bytearray(SAMPLE_HEADER_LEN)
    head[2 : 2 + len(name)] = name.encode("ascii")
    struct.pack_into("<I", head, OFF_SAMPLE_START_L, SAMPLE_HEADER_LEN)
    struct.pack_into("<I", head, OFF_SAMPLE_RATE, rate)
    record = bytes(head) + pcm
    return b"E3S1" + struct.pack(">I", len(record)) + record


def test_the_form_walk_recovers_the_last_chunk_past_an_understated_size(tmp_path):
    """The declared FORM size understates the container by a few bytes on every
    reference disc: the last ``E3S1`` chunk's body ends just past it and only
    garbage follows. So the size bounds where a chunk may *begin*, not where its
    body may end -- the last chunk is recovered, and the garbage that follows is
    not walked into.
    """
    two = [_e3s1_chunk("First", b"\x11\x22" * 40), _e3s1_chunk("Second", b"\x33\x44" * 60)]
    # Understate by four, as the discs do, then append a chunk that decodes as
    # an enormous size -- the next region's bytes, seen as a chunk header.
    body_len = len(b"E4B0") + sum(len(c) for c in two)
    blob = _form_bytes(two, declared_size=body_len - 4)
    blob += b"\xff\xff\xff\xff" + struct.pack(">I", 1 << 30) + b"\x00" * 64
    image = image_of(tmp_path, blob + b"\x00" * 4096, "understated.iso")
    chunks = list(_form_e3s1_chunks(image, 0))
    assert len(chunks) == 2  # both recovered, garbage not walked
    records = [image.read(off, length) for off, length in chunks]
    assert records[0][2:7] == b"First"
    assert records[1][2:8] == b"Second"


def _pointers(frames, loop=None, *, channel="l", other_zero=True):
    """One record's pointer block, as it reaches the sample layer."""
    end = DATA_START + frames * 2 - 2
    out = dict.fromkeys(
        (
            "start_l",
            "end_l",
            "loop_start_l",
            "loop_end_l",
            "start_r",
            "end_r",
            "loop_start_r",
            "loop_end_r",
        ),
        0,
    )
    out[f"start_{channel}"] = DATA_START
    out[f"end_{channel}"] = end
    if loop is not None:
        start, stop = loop
        out[f"loop_start_{channel}"] = DATA_START + start * 2
        out[f"loop_end_{channel}"] = DATA_START + stop * 2
    if not other_zero:
        out["start_r"] = out["end_r"] = end
    return out


def _sample(frames, loop=None, **kwargs):
    return parse_sample(
        b"\x01\x00" * frames,
        rate=22050,
        fallback_name="X",
        pointers=_pointers(frames, loop, **kwargs),
    )


def test_the_left_pointer_set_gives_the_loop_in_frames():
    sample = _sample(5000, (1200, 4800))
    assert [(loop.start, loop.end) for loop in sample.loops] == [(1200, 4800)]


def test_the_right_set_is_read_where_the_record_declares_no_left_channel():
    """542 of `studio`'s records zero the left start and put 92 at +26."""
    sample = _sample(5000, (1200, 4800), channel="r")
    assert [(loop.start, loop.end) for loop in sample.loops] == [(1200, 4800)]


def test_a_loop_end_past_the_audio_is_refused_rather_than_clamped():
    """The one place this format parts company with AKAI and Roland.

    Both of those clamp a declared end back to the audio present. Here the
    same move destroys the loop: `protozoa`'s mono records whose end already
    fits correlate at their splice at +0.86, and the 525 whose end overshoots
    score -0.10 once clamped -- same disc, same shape (ADR-0025).

    Modelled as `esi32-gm` writes it: the record declares an extent longer than
    the payload it carries, and a loop ending inside that declared extent but
    past the audio. The pointers nest perfectly; only the audio is short.
    """
    frames = 5000
    pointers = _pointers(frames + 50)  # an extent 50 frames past the payload
    pointers["loop_start_l"] = DATA_START + 1200 * 2
    pointers["loop_end_l"] = DATA_START + (frames + 20) * 2
    sample = parse_sample(b"\x01\x00" * frames, rate=22050, pointers=pointers)
    assert sample.loops == ()
    assert sample.frames == frames  # still a sample, just not a looped one


def test_a_loop_spanning_the_whole_extent_is_not_a_loop():
    """The sampler fills the pointers with the sample's own bounds when
    nothing set them; looping the entire file is not what that means."""
    assert _sample(5000, (0, 5000)).loops == ()


def test_a_whole_extent_loop_inset_a_few_frames_is_still_not_a_loop():
    """The format writes its "no loop" bounds inset by a fixed few bytes at
    *both* ends, not at exactly frame 0 (ADR-0030).

    `ditto-drums` writes ``(12, 12)`` bytes -- frame 6 to six frames from the
    end -- on 898 of its records, the EIIIX discs ``(4, 4)``, `esi32-gm` and
    `protozoa` ``(12, 10)``. Refusing only the frame-0 form shipped a loop over
    the entire file on 934 of `ditto-drums`'s 948 records. Measured across all
    ten reference discs the inset whole-extent population is a filled-in "no
    loop" -- it ends in silence and carries no uniquely-splicing loop point --
    so the guard carries the same slack at the start as at the end.
    """
    frames = 5000
    # extent is frames - 1 here (the end pointer names the last word), so the
    # far end must clear extent - FULL_EXTENT_SLACK.
    assert _sample(frames, (2, frames - 8)).loops == ()  # EIIIX-style (4, 4)
    assert _sample(frames, (6, frames - 7)).loops == ()  # ditto-style (12, 12)


def test_a_near_whole_loop_inset_past_the_slack_is_kept():
    """The guard is targeted: a loop whose start clears the slack, or whose end
    stops short of it, is a real loop and survives.

    Only a span within FULL_EXTENT_SLACK of *both* bounds is the "no loop"; a
    genuine sustain loop that begins well inside the sample, or ends well short
    of it, is the `narrow` population the measurement calibrated against and is
    emitted unchanged.
    """
    frames = 5000

    def bounds(loop):
        return [(s.start, s.end) for s in _sample(frames, loop).loops]

    # start past the slack, end at the extent: a real loop.
    assert bounds((200, frames - 7)) == [(200, frames - 7)]
    # start inside the slack but end well short of the extent: also a real loop.
    assert bounds((6, 3000)) == [(6, 3000)]


def test_a_loop_shorter_than_the_floor_is_dropped():
    assert _sample(5000, (1200, 1200 + MIN_LOOP_FRAMES - 1)).loops == ()
    assert _sample(5000, (1200, 1200 + MIN_LOOP_FRAMES)).loops != ()


def test_pointers_that_do_not_nest_are_dropped():
    assert _sample(5000, (4800, 1200)).loops == ()


def test_an_unaligned_pointer_is_dropped():
    pointers = _pointers(5000, (1200, 4800))
    pointers["loop_start_l"] += 1
    assert parse_sample(b"\x01\x00" * 5000, rate=22050, pointers=pointers).loops == ()


def test_a_record_with_no_pointers_still_yields_a_sample():
    """Tail damage: the header was too short to hold the block."""
    sample = parse_sample(b"\x01\x00" * 100, rate=22050, pointers={})
    assert sample.frames == 100 and sample.loops == ()


def test_the_root_key_is_always_none():
    """No byte of the 92 tracks the note in the sample's own name -- 8% on
    1 741 named records of `esi32-gm`, which is chance (ADR-0025)."""
    assert _sample(5000, (1200, 4800)).pitch is None


def test_the_walk_carries_the_pointers_onto_the_file(tmp_path):
    data = fixtures.emu3_disc(
        [("Default Folder", [("Bank One        ", [("Looped", 22050, 5000)])])],
        loops={"Looped": (1200, 4800)},
    )
    backend = Emu3Backend()
    image = image_of(tmp_path, data)
    volume = next(v for v in backend.volumes(image, 0) if v.files)
    entry = volume.files[0]
    assert entry.get("start_l") == DATA_START
    sample = backend.parse_sample(entry, backend.read_file(image, 0, entry))
    assert [(loop.start, loop.end) for loop in sample.loops] == [(1200, 4800)]


# --- the channel count (D18, ADR-0026) -----------------------------------


def _stereo_pointers(channel_frames, loop=None, *, end_l=None):
    """A record declaring two channels over ``channel_frames`` per channel.

    The payload is twice that: all of the left channel, then all of the right.
    ``end_l`` overrides where the left block says it ends, which is the third
    condition of the gate and the one 65 records on the shelf fail.
    """
    split = DATA_START + channel_frames * 2
    out = {
        "start_l": DATA_START,
        "end_l": split - 2 if end_l is None else end_l,
        "loop_start_l": 0,
        "loop_end_l": 0,
        "start_r": split,
        "end_r": split + channel_frames * 2 - 2,
        "loop_start_r": 0,
        "loop_end_r": 0,
    }
    if loop is not None:
        start, stop = loop
        out["loop_start_l"] = DATA_START + start * 2
        out["loop_end_l"] = DATA_START + stop * 2
        out["loop_start_r"] = split + start * 2
        out["loop_end_r"] = split + stop * 2
    return out


def _deinterleave(pcm: bytes) -> tuple[bytes, bytes]:
    """Pull the two channels back out of an interleaved buffer, as 16-bit
    frames rather than as bytes -- ``pcm[0::4]`` would take the low byte of
    every left sample and leave its high byte behind."""
    return (
        b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4)),
        b"".join(pcm[i : i + 2] for i in range(2, len(pcm), 4)),
    )


def _blocks(left: bytes, right: bytes, pointers=None, **kwargs):
    payload = left + right
    return parse_sample(
        payload,
        rate=22050,
        fallback_name="X",
        pointers=pointers or _stereo_pointers(len(left) // 2, **kwargs),
    )


def test_a_two_channel_record_is_interleaved_not_concatenated():
    """The defect this deliverable exists for: 2 843 of the 19 371 E-mu
    samples came out as a mono file twice as long as the sound."""
    sample = _blocks(b"\x01\x00" * 500, b"\x02\x00" * 500)
    assert sample.channels == 2
    assert sample.frames == 500
    assert len(sample.pcm) == 2000
    assert sample.duration == 500 / 22050


def test_the_first_block_is_the_left_channel():
    """Asserted rather than assumed, because a swap is inaudible in isolation
    and wrong forever.

    The record's pointer block is ordered ``(start_L, start_R)`` and
    ``start_L`` addresses the first block, which is the whole of the
    structural argument. The only content evidence is weak and agrees: of the
    twelve name-paired records on `eiv-analogia`, all six `-L` names populate
    the left-hand set and none of them the right (ADR-0026).
    """
    sample = _blocks(b"\x11\x11" * 4, b"\x22\x22" * 4)
    assert sample.pcm == b"\x11\x11\x22\x22" * 4


def test_the_loop_frames_are_the_same_read_as_stereo_or_as_mono():
    """The neatest check that D17 and D18 agree.

    ``(pointer - start) / 2`` is a per-channel frame index either way: it
    lands in the left block of the double-length mono file this used to write,
    and on the frame number of the interleaved one it writes now. All seven
    per-disc loop counts survive the change untouched.
    """
    stereo = _blocks(b"\x01\x00" * 5000, b"\x02\x00" * 5000, loop=(1200, 4800))
    mono = _sample(5000, (1200, 4800))
    assert [(loop.start, loop.end) for loop in stereo.loops] == [(1200, 4800)]
    assert stereo.loops == mono.loops


def test_a_left_block_that_does_not_end_at_the_split_stays_mono():
    """The third condition of the gate, and the one that took measuring.

    2 721 records declare ``start_R == start_L + P/2`` and 65 of them declare
    a left channel that overlaps the right block or stops short of it -- 19 on
    `protozoa`, 40 on `eiiix-1`, 6 on `eiiix-2`. Those 65 are not stereo:
    their halves score 0.01 on fine structure and 0.01 on best-lag
    correlation, which is two unrelated records, against 0.40 and 0.53 for the
    stereo pairs ADR-0017 joins by name. `protozoa`'s trombones are the case
    to keep in mind -- the second half of one of those payloads is another
    bank's record (ADR-0026).
    """
    split = DATA_START + 500 * 2
    overlaps = _blocks(b"\x01\x00" * 500, b"\x02\x00" * 500, end_l=split + 8)
    short = _blocks(b"\x01\x00" * 500, b"\x02\x00" * 500, end_l=split - 200)
    assert overlaps.channels == 1 and overlaps.frames == 1000
    assert short.channels == 1 and short.frames == 1000


def test_a_payload_that_does_not_divide_by_four_stays_mono():
    """Half a frame out on one channel is not stereo, it is noise. No record
    on the seven reference discs is like this; the gate is here so that one
    arriving is refused rather than mangled."""
    pointers = _stereo_pointers(501)
    sample = parse_sample(b"\x01\x00" * 1001, rate=22050, pointers=pointers)
    assert sample.channels == 1


def test_a_one_channel_record_is_untouched():
    sample = _sample(5000, (1200, 4800))
    assert sample.channels == 1
    assert sample.frames == 5000
    assert sample.pcm == b"\x01\x00" * 5000


def test_the_walk_carries_a_two_channel_record_through_to_the_sample(tmp_path):
    """End to end: the pointers are read by the filesystem layer and the
    channel count is decided in the sample layer, the same split the loop
    decode uses."""
    data = fixtures.emu3_disc(
        [("Default Folder", [("Bank One        ", [("Wide", 22050, 4000)])])],
        stereo=("Wide",),
    )
    image = image_of(tmp_path, data)
    volume = next(v for v in BACKEND.volumes(image, 0) if v.files)
    entry = volume.files[0]
    payload = BACKEND.read_file(image, 0, entry)
    sample = BACKEND.parse_sample(entry, payload)
    assert sample.channels == 2
    assert sample.frames == len(payload) // 4
    # The audio is the disc's own bytes, permuted -- nothing resampled and
    # nothing dropped.
    half = len(payload) // 2
    assert _deinterleave(sample.pcm) == (payload[:half], payload[half:])
