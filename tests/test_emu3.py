"""E-mu EMU3 filesystem tests against synthetic images (ADR-0008)."""

from __future__ import annotations

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.emu3 import Emu3Backend, is_plausible_name
from samplerdisc.fs.probe import find_origin
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


def test_a_bank_with_no_header_lists_but_yields_no_samples(tmp_path):
    """The E-IV case.

    Those banks are real and their names are right, but their interior is a
    format this project has one specimen of, so they are listed and not
    guessed at. See ADR-0015.
    """
    image = image_of(tmp_path, fixtures.emu3_disc(THREE_FOLDERS, bank_header=False), "noheader.iso")
    volumes = list(BACKEND.volumes(image, 0))
    assert len(volumes) == 3
    assert all(v.files == [] for v in volumes)
