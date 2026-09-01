"""Kurzweil ``KMSI`` (FAT16) filesystem tests against synthetic images (ADR-0008).

Every fixture below is built in code from the backend's own constants. Nothing
here came off a disc, and nothing here may: the reference libraries are
commercial and this repository is public. The disc-backed pins for the two real
``Gigapack I & II (Kurzweil)`` discs live in ``tests/test_discs.py`` and skip
where the shelf is bare.

The backend both lists a bank (as a volume) and enumerates the sample objects
inside it (as that volume's files); the sample *audio* -- big-endian PCM carried
to little-endian WAV -- is tested in ``test_kurzweil_sample.py``. What is here is
the filesystem shape: a bank per volume, its samples and the ``.krz`` kept whole.
"""

from __future__ import annotations

import math
import struct

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.kurzweil import KRZ_SIGNATURE, KurzweilBackend
from samplerdisc.fs.probe import find_origin
from tests import fixtures

BACKEND = KurzweilBackend()


def image_of(tmp_path, data: bytes, name: str = "kmsi.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


def tone(frames: int, step: int = 137) -> bytes:
    """Deterministic little-endian mono PCM -- what a round-trip expects back."""
    return b"".join(struct.pack("<h", ((i * step) % 20000) - 10000) for i in range(frames))


#: Real sample objects: a looped mono piano, a one-shot kick, a single stereo
#: object (two planar channels), and an empty ``NewSample`` slot the walk skips.
S_PIANO = fixtures.kurzweil_sample(
    "PIANO C3", rate=44100, root=48, pcm=tone(2000), loop=(500, 1500)
)
S_KICK = fixtures.kurzweil_sample("KICK", rate=22050, root=60, pcm=tone(800, 91))
S_STEREO = fixtures.kurzweil_sample(
    "STR:Vn\x7fL", rate=48000, root=57, pcm=tone(1000, 50), right=tone(1000, 70), loop=(100, 900)
)
S_EMPTY = fixtures.kurzweil_sample("NewSample", pcm=b"", has_data=False)


def disc_of(banks, *, first_cluster: int = 2, **kwargs) -> bytes:
    """A KMSI disc from ``(name, [sample, ...])`` banks, chains sized to fit."""
    files = []
    cluster = first_cluster
    for name, samples in banks:
        body = fixtures.kurzweil_bank(samples)
        count = max(1, math.ceil(len(body) / 512))
        files.append(
            fixtures.kurzweil_file(name, tuple(range(cluster, cluster + count)), body=body)
        )
        cluster += count
    return fixtures.kurzweil_disc(files, **kwargs)


THREE_BANKS = [
    ("CH GRG 1.KRZ", [S_PIANO, S_KICK]),
    ("SYN 01.KRZ", [S_STEREO]),
    ("PIA AC.KRZ", [S_PIANO]),
]


# --- the probe -----------------------------------------------------------------


def test_probe_resolves_a_kmsi_disc_at_offset_zero(tmp_path):
    image = image_of(tmp_path, disc_of(THREE_BANKS))
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "kurzweil"
    assert origin.offset == 0


def test_probe_finds_a_filesystem_behind_a_zeroed_pregap(tmp_path):
    """A .bin with 150 zeroed sectors of pregap in front still resolves (ADR-0005)."""
    pregap = b"\x00" * (150 * 2048)
    image = image_of(tmp_path, pregap + disc_of(THREE_BANKS))
    origin = find_origin(image)
    assert origin is not None
    assert origin.offset == 150 * 2048


def test_probe_declines_a_run_of_zeros(tmp_path):
    image = image_of(tmp_path, b"\x00" * (4200 * 512))
    assert not BACKEND.probe(image, 0)
    assert find_origin(image) is None


def test_probe_declines_a_generic_non_kmsi_fat(tmp_path):
    """A DOS FAT with a different OEM name is not claimed (ADR-0004)."""
    assert not BACKEND.probe(image_of(tmp_path, disc_of(THREE_BANKS, oem=b"MSDOS5.0")), 0)


def test_probe_declines_a_fat12_sized_volume(tmp_path):
    """The reader is FAT16 only; a FAT12-sized volume is declined, not misread."""
    assert not BACKEND.probe(image_of(tmp_path, disc_of(THREE_BANKS, min_clusters=100)), 0)


def test_probe_declines_kmsi_with_no_confirmable_file(tmp_path):
    """A valid KMSI boot sector over a zeroed root is structure, not a disc (ADR-0012)."""
    assert not BACKEND.probe(image_of(tmp_path, disc_of(THREE_BANKS, zero_root=True)), 0)


def test_probe_declines_when_the_first_file_is_not_a_krz_bank(tmp_path):
    """The confirming step is the PRAM tag, not just a plausible directory entry."""
    files = [fixtures.kurzweil_file("NOTKRZ.KRZ", (2, 3), signature=b"junk")]
    assert not BACKEND.probe(image_of(tmp_path, fixtures.kurzweil_disc(files)), 0)


# --- a bank is a volume, its samples the files ---------------------------------


def test_each_bank_is_its_own_volume(tmp_path):
    image = image_of(tmp_path, disc_of(THREE_BANKS))
    volumes = list(BACKEND.volumes(image, 0))
    assert [v.name for v in volumes] == ["CH GRG 1.KRZ", "SYN 01.KRZ", "PIA AC.KRZ"]


def test_a_volumes_files_are_its_samples_then_the_whole_bank_to_keep(tmp_path):
    image = image_of(tmp_path, disc_of([("SOUNDS.KRZ", [S_PIANO, S_KICK, S_STEREO, S_EMPTY])]))
    volume = next(iter(BACKEND.volumes(image, 0)))
    samples = [f for f in volume.files if f.kind == "sample"]
    programs = [f for f in volume.files if f.kind == "program"]
    # The empty NewSample slot is skipped; the stereo object is one file.
    assert [f.name for f in samples] == ["PIANO C3", "KICK", "STR:Vn\x7fL"]
    # The whole bank is listed once as a program so --keep-originals writes it.
    assert [f.name for f in programs] == ["SOUNDS.KRZ"]
    assert BACKEND.original_suffix(programs[0]) == ".krz"


def test_a_sample_file_carries_its_rate_root_and_loop(tmp_path):
    image = image_of(tmp_path, disc_of([("SOUNDS.KRZ", [S_PIANO, S_KICK, S_STEREO])]))
    volume = next(iter(BACKEND.volumes(image, 0)))
    by_name = {f.name: f for f in volume.files if f.kind == "sample"}
    piano = by_name["PIANO C3"]
    assert piano.raw_type == 44100
    assert piano.get("root") == 48
    assert piano.get("has_loop") == 1
    assert piano.get("channels") == 1
    # A one-shot carries no loop; the stereo object declares two channels.
    assert by_name["KICK"].get("has_loop") == 0
    assert by_name["STR:Vn\x7fL"].get("channels") == 2


def test_a_bank_with_no_samples_is_listed_with_a_note(tmp_path):
    """A programs/keymaps-only bank (like DRUM KIT) is real but sample-free."""
    image = image_of(tmp_path, disc_of([("DRUM KIT.KRZ", [S_EMPTY])]))
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert not [f for f in volume.files if f.kind == "sample"]
    assert volume.note


# --- reading bytes: a sample slice, and the whole bank -------------------------


def test_read_file_returns_a_samples_pool_slice_that_round_trips(tmp_path):
    image = image_of(tmp_path, disc_of([("SOUNDS.KRZ", [S_PIANO, S_KICK])]))
    volume = next(iter(BACKEND.volumes(image, 0)))
    piano = next(f for f in volume.files if f.name == "PIANO C3")
    sample = BACKEND.parse_sample(piano, BACKEND.read_file(image, 0, piano))
    assert sample.pcm == S_PIANO["pcm"]
    assert sample.rate == 44100
    assert sample.pitch == 48


def test_read_file_returns_the_whole_krz_for_the_program_entry(tmp_path):
    body = fixtures.kurzweil_bank([S_PIANO])
    count = math.ceil(len(body) / 512)
    disc = fixtures.kurzweil_disc(
        [fixtures.kurzweil_file("SOUNDS.KRZ", tuple(range(2, 2 + count)), body=body)]
    )
    image = image_of(tmp_path, disc)
    volume = next(iter(BACKEND.volumes(image, 0)))
    program = next(f for f in volume.files if f.kind == "program")
    assert BACKEND.read_file(image, 0, program).startswith(KRZ_SIGNATURE)
    assert BACKEND.read_file(image, 0, program) == body


def test_a_fragmented_bank_is_reassembled_before_its_samples_are_cut(tmp_path):
    """The FAT chain is followed, never assumed contiguous, when slicing a sample."""
    body = fixtures.kurzweil_bank([S_PIANO, S_KICK])
    count = math.ceil(len(body) / 512)
    # A deliberately out-of-order chain: a contiguity-assuming read would splice
    # the wrong clusters and the sample PCM would not round-trip.
    chain = tuple(reversed(range(2, 2 + count + 2)))
    disc = fixtures.kurzweil_disc([fixtures.kurzweil_file("FRAG.KRZ", chain, body=body)])
    image = image_of(tmp_path, disc)
    volume = next(iter(BACKEND.volumes(image, 0)))
    kick = next(f for f in volume.files if f.name == "KICK")
    assert BACKEND.parse_sample(kick, BACKEND.read_file(image, 0, kick)).pcm == S_KICK["pcm"]


# --- subdirectories, layout, and the empty-volume note -------------------------


def test_a_subdirectory_bank_becomes_its_own_volume(tmp_path):
    body = fixtures.kurzweil_bank([S_KICK])
    count = math.ceil(len(body) / 512)
    child = fixtures.kurzweil_file("DEEP.KRZ", tuple(range(9, 9 + count)), body=body)
    top = fixtures.kurzweil_bank([S_PIANO])
    top_count = math.ceil(len(top) / 512)
    files = [
        fixtures.kurzweil_file("TOP.KRZ", tuple(range(2, 2 + top_count)), body=top),
        fixtures.kurzweil_file("PIANOS", (30,), children=[child]),
    ]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    origin = find_origin(image)
    assert origin is not None
    volumes = list(origin.backend.volumes(image, origin.offset))
    assert [v.name for v in volumes] == ["TOP.KRZ", "PIANOS/DEEP.KRZ"]


def test_layout_reports_fat16(tmp_path):
    image = image_of(tmp_path, disc_of(THREE_BANKS))
    assert BACKEND.layout(image, 0).startswith("FAT16 (KMSI/Kurzweil)")


def test_a_volume_with_only_an_empty_subdirectory_says_why_it_is_empty(tmp_path):
    """No bank at all, but a note rather than a silent empty disc (ADR-0012)."""
    files = [fixtures.kurzweil_file("EMPTY", (2,), children=[])]
    image = image_of(tmp_path, fixtures.kurzweil_disc(files))
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert not volume.files
    assert volume.note
