"""Container tests against synthetic images (ADR-0008)."""

from __future__ import annotations

import struct

import pytest

from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.mdsmdf import looks_mds, open_mds
from samplerdisc.container.mdx import (
    DEFAULT_BLOCK_SIZE,
    MERGED_VERSION_MAJOR,
    SPLIT_VERSION_MAJOR,
    VERSION_OFFSET,
    MdxImage,
    _decode_block,
    looks_mdx,
)
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


def test_a_split_mds_is_not_taken_for_a_merged_mdx(tmp_path):
    """The two share a 16-byte magic; the version byte at 0x10 separates them.

    Testing the magic alone routed every real .mds to the MDX parser, which
    read 0 out of a field that is not a descriptor offset and rejected the
    file -- so the .mds branch of ``sniff`` was dead for the input it exists
    for. Asserting the predicates as well as the routing, because the bug was
    that one predicate answered for both formats.
    """
    mds = fixtures.make_mds()
    mdx, _ = fixtures.make_mdx([fixtures.compressible_block(0)])

    # The magic really is shared -- that is the whole problem.
    assert mds[:16] == mdx[:16]
    # The bytes docs/formats/mdx.md records for the specimens of each form.
    assert mds[VERSION_OFFSET] == SPLIT_VERSION_MAJOR
    assert mdx[VERSION_OFFSET] == MERGED_VERSION_MAJOR

    assert (looks_mds(mds), looks_mdx(mds)) == (True, False)
    assert (looks_mds(mdx), looks_mdx(mdx)) == (False, True)

    (tmp_path / "disc.mdf").write_bytes(fixtures.cooked_sectors(4))
    assert sniff(write(tmp_path, "disc.mds", mds)) == "mdsmdf"

    # And the parser it used to be handed to now says what is wrong with it,
    # rather than "implausible descriptor offset 0" out of a field that is not
    # a descriptor offset.
    with pytest.raises(ValueError, match="not an MDX image"):
        MdxImage(write(tmp_path, "wrong.mdx", mds))


def test_a_split_mds_is_detected_by_signature_not_by_extension(tmp_path):
    """Both directions, since the extension is the thing that must not decide.

    ADR-0004: these files arrive named whatever someone typed. A .mds under
    another name is still the split form, and an .mdx under a .mds name is
    still merged.
    """
    (tmp_path / "renamed.mdf").write_bytes(fixtures.cooked_sectors(4))
    assert sniff(write(tmp_path, "renamed.mds", fixtures.make_mds())) == "mdsmdf"

    mdx, _ = fixtures.make_mdx([fixtures.compressible_block(0)])
    assert sniff(write(tmp_path, "merged.mds", mdx)) == "mdx"


def test_an_unsigned_mds_still_falls_back_to_its_extension(tmp_path):
    """The tiebreak survives: a descriptor with no magic we know is still a .mds."""
    (tmp_path / "odd.mdf").write_bytes(fixtures.cooked_sectors(4))
    assert sniff(write(tmp_path, "odd.mds", b"\x00" * 486)) == "mdsmdf"


def test_open_mds_reads_the_geometry_of_the_mdf_beside_it(tmp_path):
    """Cooked or raw, chosen by looking at the .mdf -- the descriptor is not parsed."""
    cooked = fixtures.cooked_sectors(4)
    (tmp_path / "cooked.mdf").write_bytes(cooked)
    (tmp_path / "cooked.mds").write_bytes(fixtures.make_mds())
    image = open_image(tmp_path / "cooked.mds")
    assert image.kind == "mdsmdf"
    assert image.read(0, len(cooked)) == cooked

    sectors = [cooked[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE] for i in range(4)]
    (tmp_path / "raw.mdf").write_bytes(fixtures.make_rawcd(sectors))
    (tmp_path / "raw.mds").write_bytes(fixtures.make_mds())
    raw_image = open_image(tmp_path / "raw.mds")
    assert raw_image.kind == "mdsmdf"
    assert raw_image.read(0, len(cooked)) == cooked


def test_open_mds_without_its_mdf_says_so(tmp_path):
    (tmp_path / "lonely.mds").write_bytes(fixtures.make_mds())
    with pytest.raises(ValueError, match=r"no matching \.mdf"):
        open_mds(tmp_path / "lonely.mds")


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


def test_block_size_and_stride_are_read_off_the_image(tmp_path):
    """A real AKAI disc uses 32160-byte blocks of 2144-byte sectors.

    32160 is 15 x 2144: 2048 of data plus 96 of subchannel. Assuming the usual
    32768 made every block fail to inflate and fall through to the stored path;
    getting the block size right but not the stride put every sector 96 bytes
    further out than the last. Both surface as an unreadable filesystem rather
    than as an error.
    """
    pairs = [fixtures.subchannel_block(i) for i in range(3)]
    stored = [block for block, _ in pairs]
    cooked = [data for _, data in pairs]
    raw, _ = fixtures.make_mdx(stored)
    image = MdxImage(write(tmp_path, "subch.mdx", raw))
    assert image.block_size == 32160
    assert image.stride == 2144
    assert image.stored_blocks == 0
    expected = b"".join(cooked)
    assert image.size == len(expected)
    assert image.read(0, image.size) == expected


def test_plain_images_have_no_subchannel_stride(tmp_path):
    blocks = [fixtures.compressible_block(i) for i in range(2)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "plain.mdx", raw))
    assert image.stride == SECTOR_SIZE
    assert image.read(0, image.size) == expected[: image.size]


def test_usual_block_size_still_works(tmp_path):
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    raw, expected = fixtures.make_mdx(blocks)
    image = MdxImage(write(tmp_path, "usual.mdx", raw))
    assert image.block_size == DEFAULT_BLOCK_SIZE
    assert image.read(0, len(expected)) == expected


# --- MDX generations and the all-stored case (D11) -----------------------


def test_payload_starts_at_0x40_in_the_2015_header_too(tmp_path):
    """The field at 0x38 reads 192 on a 2011 image and 2560 on a 2015 one.

    Neither is the payload offset. One wrong value could be coincidence; two
    different wrong values in the same field settle it. See docs/formats/mdx.md.
    """
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    data, expected = fixtures.make_mdx(blocks, disc_soft=True)
    path = tmp_path / "discsoft.mdx"
    path.write_bytes(data)
    with MdxImage(path) as image:
        assert image.read(0, len(expected)) == expected
        assert image.block_size == DEFAULT_BLOCK_SIZE


def test_an_all_stored_image_is_reported_not_guessed_at(tmp_path):
    """PCM does not deflate, so an audio CD image is legitimately all stored.

    The container cannot tell that from a block size it failed to measure, so
    it reports both facts and leaves the reading to the caller rather than
    searching the payload for a DEFLATE stream that may not be there.
    """
    blocks = [fixtures.incompressible_block(i) for i in range(4)]
    data, expected = fixtures.make_mdx(blocks, stored={0, 1, 2, 3})
    path = tmp_path / "stored.mdx"
    path.write_bytes(data)
    with MdxImage(path) as image:
        assert image.stored_only
        assert not image.block_size_measured
        # Block size is arithmetically irrelevant when every block is stored:
        # the blocks partition the payload contiguously whatever it is.
        assert image.read(0, len(expected)) == expected


def test_a_measured_block_size_is_not_reported_as_assumed(tmp_path):
    """A size read off a block that inflated is a size that works."""
    blocks = [fixtures.compressible_block(i) for i in range(3)]
    data, _ = fixtures.make_mdx(blocks)
    path = tmp_path / "measured.mdx"
    path.write_bytes(data)
    with MdxImage(path) as image:
        assert image.block_size_measured
        assert not image.stored_only
