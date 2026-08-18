"""Container tests against synthetic images (ADR-0008)."""

from __future__ import annotations

import struct

import pytest

from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.mdx import DEFAULT_BLOCK_SIZE, MdxImage, _decode_block
from samplerdisc.container.nrg import NrgImage, parse_chunks
from samplerdisc.container.rawcd import RawCdImage, parse_cue_sector_size
from samplerdisc.export import export_iso
from tests import fixtures


def write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --- MDX ----------------------------------------------------------------


def test_mdx_decodes_compressed_blocks(tmp_path):
    blocks = [fixtures.compressible_block(i) for i in range(4)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "a.mdx", raw))
    assert len(image.blocks) == 4
    assert image.stored_blocks == 0
    assert image.read(0, len(expected)) == expected


def test_mdx_handles_stored_blocks(tmp_path):
    blocks = [fixtures.compressible_block(0), fixtures.incompressible_block(7)]
    raw, expected = fixtures.make_mdx(blocks, stored={1})
    image = MdxImage(write(tmp_path, "a.mdx", raw))
    assert (image.compressed_blocks, image.stored_blocks) == (1, 1)
    assert image.read(0, len(expected)) == expected


def test_mdx_truncated_payload_degrades_rather_than_crashing(tmp_path):
    """A short final block is taken as stored, not raised on.

    Note what is NOT asserted here: that the walk ends on the descriptor
    offset. It always does -- a stored block absorbs whatever remains, so exact
    termination is a loop invariant rather than a check. See ADR-0006.
    """
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    raw, _ = fixtures.make_mdx(blocks)
    corrupt = bytearray(raw)
    struct.pack_into("<Q", corrupt, 0x30, len(raw) - 640 - 5)
    image = MdxImage(write(tmp_path, "short.mdx", bytes(corrupt)))
    assert image.stored_blocks == 1
    assert image.read(0, DEFAULT_BLOCK_SIZE) == blocks[0]


def test_mdx_rejects_an_implausible_descriptor_offset(tmp_path):
    blocks = [fixtures.compressible_block(0)]
    raw, _ = fixtures.make_mdx(blocks)
    corrupt = bytearray(raw)
    struct.pack_into("<Q", corrupt, 0x30, 1 << 40)
    with pytest.raises(ValueError, match="implausible descriptor offset"):
        MdxImage(write(tmp_path, "bad.mdx", bytes(corrupt)))


def test_mdx_stored_ratio_signals_a_misparse(tmp_path):
    """The only available misparse signal: stored blocks dwarfing compressed.

    Reading a compressed payload from the wrong offset makes nearly everything
    fail to inflate. Nothing raises -- this is what `info` surfaces so a human
    can see it.
    """
    blocks = [fixtures.compressible_block(i) for i in range(4)]
    raw, _ = fixtures.make_mdx(blocks)
    good = MdxImage(write(tmp_path, "good.mdx", raw))
    assert good.stored_blocks == 0

    shifted = bytearray(raw)
    shifted[0x40:0x40] = b"\x00" * 7  # shove the payload out of alignment
    struct.pack_into("<Q", shifted, 0x30, len(raw) - 640 + 7)
    bad = MdxImage(write(tmp_path, "bad.mdx", bytes(shifted)))
    assert bad.stored_blocks > bad.compressed_blocks


def test_mdx_rejects_non_mdx(tmp_path):
    with pytest.raises(ValueError, match="not an MDX"):
        MdxImage(write(tmp_path, "x.mdx", b"NOT A DESCRIPTOR" + b"\x00" * 200))


def test_decode_block_rejects_stream_that_consumed_too_much():
    """The consumed-length guard from ADR-0006 -- the load-bearing check.

    A block whose compressed form is not smaller than its output is by
    definition one an encoder would have stored, so accepting it would mean
    mis-reading literal data as compressed.
    """
    import zlib

    payload = fixtures.incompressible_block(3)
    compressor = zlib.compressobj(0, zlib.DEFLATED, -15)  # level 0: stored, so larger
    stream = compressor.compress(payload) + compressor.flush()
    assert len(stream) >= DEFAULT_BLOCK_SIZE
    assert _decode_block(stream, DEFAULT_BLOCK_SIZE) is None


def test_decode_block_accepts_a_real_compressed_block():
    import zlib

    payload = fixtures.compressible_block(2)
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = compressor.compress(payload) + compressor.flush()
    decoded = _decode_block(stream + b"trailing", DEFAULT_BLOCK_SIZE)
    assert decoded is not None
    data, consumed = decoded
    assert data == payload
    assert consumed == len(stream)


def test_mdx_trims_partial_tail_to_a_sector_boundary(tmp_path):
    blocks = [fixtures.compressible_block(0)]
    raw, _ = fixtures.make_mdx(blocks)
    # Append a short stored remainder that is not sector-aligned.
    remainder = b"\x11" * 953
    corrupt = bytearray(raw[: len(raw) - 640]) + remainder + raw[len(raw) - 640 :]
    struct.pack_into("<Q", corrupt, 0x30, len(raw) - 640 + len(remainder))
    image = MdxImage(write(tmp_path, "tail.mdx", bytes(corrupt)))
    assert image.size % SECTOR_SIZE == 0
    assert image.trimmed == 953


# --- raw CD -------------------------------------------------------------


def test_rawcd_deinterleaves(tmp_path):
    cooked = fixtures.cooked_sectors(6)
    sectors = [cooked[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE] for i in range(6)]
    image = RawCdImage(write(tmp_path, "a.bin", fixtures.make_rawcd(sectors)))
    assert image.sectors == 6
    assert image.read(0, len(cooked)) == cooked


def test_rawcd_reads_across_sector_boundaries(tmp_path):
    cooked = fixtures.cooked_sectors(4)
    sectors = [cooked[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE] for i in range(4)]
    image = RawCdImage(write(tmp_path, "a.bin", fixtures.make_rawcd(sectors)))
    assert image.read(2000, 100) == cooked[2000:2100]


@pytest.mark.parametrize(
    ("cue", "expected"),
    [
        ('FILE "X.BIN" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n', 2352),
        ('FILE "X.ISO" BINARY\n  TRACK 01 MODE1/2048\n', 2048),
        ('FILE "X.BIN" BINARY\n  TRACK 01 AUDIO\n  TRACK 02 MODE1/2352\n', 2352),
        ("nonsense", None),
    ],
)
def test_cue_sector_size(cue, expected):
    assert parse_cue_sector_size(cue) == expected


# --- NRG ----------------------------------------------------------------


def test_nrg_finds_the_track_behind_the_pregap(tmp_path):
    """The bug ADR-0005 exists for: assuming byte 0 reads an empty disc."""
    cooked = fixtures.cooked_sectors(20)
    image = NrgImage(write(tmp_path, "a.nrg", fixtures.make_nrg(cooked)))
    assert image.track.start == 150 * SECTOR_SIZE
    assert image.size == len(cooked)
    assert image.read(0, 64) == cooked[:64]


def test_nrg_v1_trailer(tmp_path):
    cooked = fixtures.cooked_sectors(8)
    image = NrgImage(write(tmp_path, "a.nrg", fixtures.make_nrg(cooked, version=1)))
    assert image.read(0, 32) == cooked[:32]


def test_nrg_raw_sector_track(tmp_path):
    cooked = fixtures.cooked_sectors(5)
    sectors = [cooked[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE] for i in range(5)]
    raw = fixtures.make_rawcd(sectors)
    image = NrgImage(write(tmp_path, "a.nrg", fixtures.make_nrg(raw, 0, sector_size=2352)))
    assert image.read(0, len(cooked)) == cooked


def test_parse_chunks_stops_at_end():
    body = b"SINF" + struct.pack(">I", 4) + b"\x00\x00\x00\x01"
    body += b"END!" + struct.pack(">I", 0) + b"garbage after the terminator"
    ids = [chunk_id for chunk_id, _ in parse_chunks(body)]
    assert ids == [b"SINF", b"END!"]


def test_nrg_rejects_a_file_with_no_trailer(tmp_path):
    with pytest.raises(ValueError, match="NER5 or NERO"):
        NrgImage(write(tmp_path, "a.nrg", b"\x00" * 5000))


# --- detection ----------------------------------------------------------


def test_sniff_ignores_misleading_extensions(tmp_path):
    """A renamed file must still be recognised. ADR-0004."""
    mdx, _ = fixtures.make_mdx([fixtures.compressible_block(0)])
    assert sniff(write(tmp_path, "actually.iso", mdx)) == "mdx"

    cooked = fixtures.cooked_sectors(4)
    nrg = fixtures.make_nrg(cooked)
    assert sniff(write(tmp_path, "mystery.bin", nrg)) == "nrg"

    sectors = [cooked[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE] for i in range(4)]
    assert sniff(write(tmp_path, "raw.img", fixtures.make_rawcd(sectors))) == "rawcd"

    assert sniff(write(tmp_path, "plain.iso", cooked)) == "flat"


def test_sniff_uses_a_cue_when_there_is_no_signature(tmp_path):
    cooked = fixtures.cooked_sectors(2)
    path = write(tmp_path, "disc.bin", cooked)
    (tmp_path / "disc.cue").write_text('FILE "DISC.BIN" BINARY\n  TRACK 01 MODE1/2048\n')
    assert sniff(path) == "flat"


def test_open_image_dispatches(tmp_path):
    cooked = fixtures.cooked_sectors(4)
    assert isinstance(open_image(write(tmp_path, "a.iso", cooked)), FlatImage)
    mdx, _ = fixtures.make_mdx([fixtures.compressible_block(0)])
    assert isinstance(open_image(write(tmp_path, "b.dat", mdx)), MdxImage)


# --- export -------------------------------------------------------------


def test_export_iso_is_a_faithful_unwrap(tmp_path):
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "a.mdx", raw))
    out = tmp_path / "out.iso"
    written = export_iso(image, out)
    assert written == image.size
    assert out.read_bytes() == expected[: image.size]


def test_exported_iso_reopens_identically(tmp_path):
    cooked = fixtures.cooked_sectors(30)
    source = NrgImage(write(tmp_path, "a.nrg", fixtures.make_nrg(cooked)))
    out = tmp_path / "out.iso"
    export_iso(source, out)
    with open_image(out) as reopened:
        assert reopened.size == source.size
        assert reopened.read(0, source.size) == source.read(0, source.size)


def test_reads_past_the_end_return_what_is_available(tmp_path):
    """Damaged input degrades rather than raising."""
    cooked = fixtures.cooked_sectors(2)
    image = FlatImage(write(tmp_path, "a.iso", cooked))
    assert image.read(image.size - 10, 500) == cooked[-10:]
    assert image.read(image.size + 1000, 10) == b""


def test_block_size_is_read_off_the_image_not_assumed(tmp_path):
    """A real AKAI disc uses 32160-byte blocks, not the usual 32768.

    Assuming the common value made every block fail to inflate and fall
    through to the stored path, which surfaces as an unrecognisable
    filesystem rather than as an error.
    """
    odd = 32160
    blocks = [fixtures.compressible_block(i, size=odd) for i in range(3)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "odd.mdx", raw))
    assert image.block_size == odd
    assert image.stored_blocks == 0
    # 32160 is not a whole number of sectors, so the image trims to the last
    # complete one -- the blocks still decode, the tail is just not addressable.
    assert image.size % SECTOR_SIZE == 0
    assert image.read(0, image.size) == expected[: image.size]


def test_usual_block_size_still_works(tmp_path):
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "usual.mdx", raw))
    assert image.block_size == DEFAULT_BLOCK_SIZE
    assert image.read(0, len(expected)) == expected
