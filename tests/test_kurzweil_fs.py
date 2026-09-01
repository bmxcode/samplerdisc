"""Kurzweil ``KMSI`` (FAT16) filesystem tests against synthetic images (ADR-0008).

Every fixture below is built in code from the backend's own constants. Nothing
here came off a disc, and nothing here may: the reference libraries are
commercial and this repository is public. The disc-backed pins for the two real
``Gigapack I & II (Kurzweil)`` discs live in ``tests/test_discs.py`` and skip
where the shelf is bare.
"""

from __future__ import annotations

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.kurzweil import KRZ_SIGNATURE, KurzweilBackend
from samplerdisc.fs.probe import find_origin
from tests import fixtures

BACKEND = KurzweilBackend()


def image_of(tmp_path, data: bytes, name: str = "kmsi.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


def krz(name: str, chain, *, size=None, body=None, **kw):
    return fixtures.kurzweil_file(name, chain, size=size, body=body, **kw)


#: A small disc in the shape of a real one: a few .KRZ banks, one of them
#: fragmented (its FAT chain out of order), each cluster carrying different
#: bytes so a contiguity-assuming walk returns visibly wrong data.
THREE_BANKS = [
    krz("CH GRG 1.KRZ", (2, 3)),
    krz("SYN 01.KRZ", (7, 4, 6)),  # fragmented: 7 -> 4 -> 6
    krz("PIA AC.KRZ", (5,)),
]


def test_probe_resolves_a_kmsi_disc_at_offset_zero(tmp_path):
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS))
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "kurzweil"
    assert origin.offset == 0


def test_probe_finds_a_filesystem_behind_a_zeroed_pregap(tmp_path):
    """A .bin with 150 zeroed sectors of pregap in front still resolves (ADR-0005)."""
    pregap = b"\x00" * (150 * 2048)
    image = image_of(tmp_path, pregap + fixtures.kurzweil_disc(THREE_BANKS))
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "kurzweil"
    assert origin.offset == 150 * 2048


def test_volumes_lists_every_bank_as_one_flat_volume(tmp_path):
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS, volume_label="GIGA 1"))
    volumes = list(BACKEND.volumes(image, 0))
    assert len(volumes) == 1
    volume = volumes[0]
    assert volume.name == "GIGA 1"
    assert [f.name for f in volume.files] == ["CH GRG 1.KRZ", "SYN 01.KRZ", "PIA AC.KRZ"]
    assert all(f.kind == "bank" for f in volume.files)
    assert not volume.note


def test_an_unlabelled_volume_is_named_kmsi(tmp_path):
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS))
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert volume.name == "KMSI"


def test_read_file_follows_the_fat_chain_including_a_fragmented_bank(tmp_path):
    bodies = {
        "CH GRG 1.KRZ": KRZ_SIGNATURE + b"first-bank-payload" * 40,
        "SYN 01.KRZ": KRZ_SIGNATURE + b"fragmented-across-7-4-6" * 30,
        "PIA AC.KRZ": KRZ_SIGNATURE + b"single-cluster" * 10,
    }
    files = [
        krz("CH GRG 1.KRZ", (2, 3), body=bodies["CH GRG 1.KRZ"]),
        krz("SYN 01.KRZ", (7, 4, 6), body=bodies["SYN 01.KRZ"]),
        krz("PIA AC.KRZ", (5,), body=bodies["PIA AC.KRZ"]),
    ]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    volume = next(iter(BACKEND.volumes(image, 0)))
    for entry in volume.files:
        got = BACKEND.read_file(image, 0, entry)
        assert got == bodies[entry.name], entry.name


def test_read_file_truncates_to_the_declared_size(tmp_path):
    body = KRZ_SIGNATURE + b"x" * 2000
    files = [krz("SHORT.KRZ", (2, 3, 4), body=body, size=1234)]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    volume = next(iter(BACKEND.volumes(image, 0)))
    got = BACKEND.read_file(image, 0, volume.files[0])
    assert len(got) == 1234
    assert got == body[:1234]


def test_a_subdirectory_is_walked_and_its_files_carry_the_path(tmp_path):
    child = krz("DEEP.KRZ", (9,), body=KRZ_SIGNATURE + b"nested" * 20)
    files = [
        krz("TOP.KRZ", (2,), body=KRZ_SIGNATURE + b"top" * 20),
        fixtures.kurzweil_file("PIANOS", (3,), children=[child]),
    ]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    origin = find_origin(image)
    assert origin is not None
    volume = next(iter(origin.backend.volumes(image, origin.offset)))
    names = [f.name for f in volume.files]
    assert names == ["TOP.KRZ", "PIANOS/DEEP.KRZ"]


def test_layout_and_suffix(tmp_path):
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS))
    layout = BACKEND.layout(image, 0)
    assert layout.startswith("FAT16 (KMSI/Kurzweil)")
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert all(BACKEND.original_suffix(f) == ".krz" for f in volume.files)


def test_probe_declines_a_run_of_zeros(tmp_path):
    image = image_of(tmp_path, b"\x00" * (4200 * 512))
    assert not BACKEND.probe(image, 0)
    assert find_origin(image) is None


def test_probe_declines_a_generic_non_kmsi_fat(tmp_path):
    """A DOS FAT with a different OEM name is not claimed (ADR-0004)."""
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS, oem=b"MSDOS5.0"))
    assert not BACKEND.probe(image, 0)


def test_probe_declines_a_fat12_sized_volume(tmp_path):
    """The reader is FAT16 only; a FAT12-sized volume is declined, not misread."""
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS, min_clusters=100))
    assert not BACKEND.probe(image, 0)


def test_probe_declines_kmsi_with_no_confirmable_file(tmp_path):
    """A valid KMSI boot sector over a zeroed root is structure, not a disc (ADR-0012)."""
    image = image_of(tmp_path, fixtures.kurzweil_disc(THREE_BANKS, zero_root=True))
    assert not BACKEND.probe(image, 0)


def test_probe_declines_when_the_first_file_is_not_a_krz_bank(tmp_path):
    """The confirming step is the PRAM tag, not just a plausible directory entry."""
    files = [krz("NOTKRZ.KRZ", (2, 3), signature=b"junk")]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    assert not BACKEND.probe(image, 0)


def test_a_volume_with_only_an_empty_subdirectory_says_why_it_is_empty(tmp_path):
    """No file, but a note rather than a silent empty volume (ADR-0012).

    Reached by calling ``volumes`` directly: the probe would decline this disc
    (it confirms a real top-level file), so it never resolves through
    ``find_origin`` -- but a backend must still never yield an unexplained empty
    volume if asked to walk one.
    """
    files = [fixtures.kurzweil_file("EMPTY", (2,), children=[])]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert not volume.files
    assert volume.note
