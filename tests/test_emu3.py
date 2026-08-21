"""E-mu EMU3 filesystem tests against synthetic images (ADR-0008)."""

from __future__ import annotations

import re
import struct

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.emu3 import (
    BANK_MAGICS,
    OFF_SAMPLE_START_L,
    Emu3Backend,
    is_plausible_name,
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


def test_probe_accepts_a_real_emu3_header(tmp_path):
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    assert BACKEND.probe(image, 0)


def test_probe_rejects_the_magic_alone(tmp_path):
    """Four bytes is not a filesystem (ADR-0012).

    The header's own arithmetic must close and the directory it names must
    actually yield a bank.
    """
    data = bytearray(fixtures.emu3_disc(ONE_FOLDER))
    data[0x08:0x0C] = (99).to_bytes(4, "little")  # folder + reserved no longer == banks
    assert not BACKEND.probe(image_of(tmp_path, bytes(data), "broken.iso"), 0)


def test_probe_rejects_zeros_and_noise(tmp_path):
    assert not BACKEND.probe(image_of(tmp_path, b"\x00" * 65536, "z.iso"), 0)
    assert not BACKEND.probe(image_of(tmp_path, fixtures.incompressible_block(3) * 2, "n.iso"), 0)


def test_origin_probe_resolves_to_emu3(tmp_path):
    image = image_of(tmp_path, fixtures.emu3_disc(ONE_FOLDER))
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "emu3"
    assert origin.offset == 0


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


# --- loop points (D17, ADR-0025) ----------------------------------------


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
