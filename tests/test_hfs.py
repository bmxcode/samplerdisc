"""HFS behind an Apple Partition Map -- the SampleCell backend (ADR-0039).

Synthetic fixtures only; no disc byte is committed (ADR-0008). The disc-backed
counterparts, including the ``machfs`` byte oracle, live in ``test_discs.py``.
"""

from __future__ import annotations

import struct

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, Skipped, extract_disc
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.fs.base import File
from samplerdisc.fs.hfs import APPLE_BLOCK, HfsBackend
from samplerdisc.fs.iso9660 import Iso9660Backend
from samplerdisc.fs.probe import find_origin
from samplerdisc.sample.aiff import _swap
from samplerdisc.wav import read_header
from tests import fixtures


def _be_pcm(frames: int, channels: int = 2) -> bytes:
    """A run of distinct big-endian 16-bit samples, so a byte-order slip shows."""
    values = [((i * 37) % 60000) - 30000 for i in range(frames * channels)]
    return struct.pack(f">{len(values)}h", *values)


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
            "OLD": (b"Sd2f", b"e"),  # Sound Designer II -> sd2 (decoded, ADR-0040)
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


def test_read_resource_fork_returns_the_exact_bytes(tmp_path):
    """A Sound Designer II file's resource fork is read whole (ADR-0040).

    The audio stays the data fork; the resource fork carries the parameters, and
    the backend must hand back its exact bytes for the decoder to read.
    """
    rsrc = fixtures.make_sd2_rsrc(sample_size=2, rate=44100, channels=2)
    image = hfs_image(tmp_path, {"Samples/Brass": (b"Sd2f", _be_pcm(64), rsrc)})
    entry = next(e for e in next(iter(BACKEND.volumes(image, 0))).files if e.kind == "sd2")
    assert BACKEND.read_resource_fork(image, 0, entry) == rsrc
    # The data fork is still the audio, unchanged.
    assert BACKEND.read_file(image, 0, entry) == _be_pcm(64)


def test_read_resource_fork_spans_several_extents(tmp_path):
    """A fragmented resource fork is stitched from its own extent list.

    Real forks are contiguous, but the ``r``-keyed extents must be walked the
    same way the data fork's are -- degrade-never-crash if they could not be.
    """
    al = 2048
    raw = bytearray(al * 5)
    first = b"R" * al
    second = b"S" * al
    raw[0:al] = first  # allocation block 0
    raw[2 * al : 3 * al] = second  # allocation block 2
    path = tmp_path / "forks.bin"
    path.write_bytes(bytes(raw))
    entry = File(
        name="frag",
        kind="sd2",
        size=0,
        start_block=0,
        meta=(
            ("forkbase", 0),
            ("albksz", al),
            ("r0s", 0),
            ("r0c", 1),
            ("r1s", 2),
            ("r1c", 1),
            ("rlen", al + 10),
        ),
    )
    assert BACKEND.read_resource_fork(FlatImage(path), 0, entry) == first + second[:10]


def test_a_file_without_a_resource_fork_reads_as_empty(tmp_path):
    """No resource fork means no ``rlen`` in meta, and an empty read -- not a
    stray tail of another fork."""
    image = hfs_image(tmp_path, {"CLAP": (b"AIFF", b"data")})
    entry = next(iter(BACKEND.volumes(image, 0))).files[0]
    assert BACKEND.read_resource_fork(image, 0, entry) == b""


def test_a_sound_designer_ii_file_converts_to_stereo_wav(tmp_path):
    """An Sd2f entry decodes: data-fork BE PCM to a little-endian stereo WAV.

    The parameters come from the resource fork; the audio is the data fork with
    its byte order reversed and its values untouched (ADR-0011/0040).
    """
    data = _be_pcm(frames=128, channels=2)
    rsrc = fixtures.make_sd2_rsrc(sample_size=2, rate=44100, channels=2)
    image = hfs_image(tmp_path, {"SI Samples/Brass Tutti/Brass C5": (b"Sd2f", data, rsrc)})
    origin = find_origin(image)
    out = tmp_path / "out"
    results = list(extract_disc(image, origin.backend, origin.offset, str(out)))
    extracted = [r for r in results if isinstance(r, Extracted)]
    assert len(extracted) == 1
    assert extracted[0].channels == 2
    assert extracted[0].rate == 44100
    assert extracted[0].frames == 128
    with open(extracted[0].path, "rb") as handle:
        written = handle.read()
    header = read_header(written)
    assert header is not None
    assert (header.channels, header.rate, header.width) == (2, 44100, 2)
    # The data chunk is the data fork with byte order reversed, nothing more.
    body = written[header.offset : header.offset + header.length]
    assert _swap(body, 2) == data


def test_a_malformed_sound_designer_ii_file_is_skipped_not_crashed(tmp_path):
    """A resource fork with no usable STR parameters degrades to a reasoned
    skip, never a traceback (ADR-0012)."""
    image = hfs_image(tmp_path, {"BROKEN": (b"Sd2f", _be_pcm(16), b"not a resource map")})
    origin = find_origin(image)
    out = tmp_path / "out"
    results = list(extract_disc(image, origin.backend, origin.offset, str(out)))
    assert [r for r in results if isinstance(r, Skipped)]
    assert not [r for r in results if isinstance(r, Extracted)]


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
