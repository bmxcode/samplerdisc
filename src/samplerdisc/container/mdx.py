"""DAEMON Tools MDX, including the compressed variant.

Nothing else open-source reads compressed ``.mdx``. The format is documented
byte by byte in docs/formats/mdx.md; the classification rule and the reason it
is safe rather than lucky are in ADR-0006.
"""

from __future__ import annotations

import struct
import zlib
from collections import OrderedDict
from typing import NamedTuple

from samplerdisc.container.base import SECTOR_SIZE, _FileBacked

MAGIC = b"MEDIA DESCRIPTOR"

#: The magic is NOT unique to the merged form: a split .mds descriptor opens
#: with the same 16 bytes. The major version at 0x10 is what separates them --
#: 2 on every merged .mdx seen, 1 on the split .mds. Miss this and a .mds is
#: handed to this parser, which reads a zero descriptor offset out of a header
#: that is not one and rejects the file. See docs/formats/mdx.md.
VERSION_OFFSET = 0x10
MERGED_VERSION_MAJOR = 2
SPLIT_VERSION_MAJOR = 1

#: The block size most images use. It is NOT universal -- see _derive_block_size
#: -- so this is only the fallback when the first block cannot be decoded.
DEFAULT_BLOCK_SIZE = 32768

#: The payload starts here -- NOT at the value in the field at 0x38, which
#: looks exactly like a data offset and is not one. See docs/formats/mdx.md.
PAYLOAD_OFFSET = 0x40

#: u64 LE: offset of the trailing MDS descriptor, which is where the payload ends.
DESCRIPTOR_OFFSET_FIELD = 0x30

#: No block can need more than this compressed; used to bound a read.
_MAX_BLOCK_READ = 1 << 18

#: Blocks kept decoded. Reads are usually sequential, so a few is plenty.
_CACHE_BLOCKS = 8

#: An MDX may store plain 2048-byte sectors, or 2048 followed by 96 bytes of
#: subchannel data. Nothing in the header says which; the block size does,
#: because it is a whole number of whichever stride is in use.
SUBCHANNEL_LEN = 96
STRIDES = (SECTOR_SIZE, SECTOR_SIZE + SUBCHANNEL_LEN)


class Block(NamedTuple):
    """One entry of the block chain."""

    offset: int  # where the block starts in the file
    clen: int  # compressed (or stored) length
    stored: bool  # True when held literally rather than deflated
    out_len: int  # decoded length; BLOCK_SIZE except possibly for the last


def looks_mdx(head: bytes) -> bool:
    """Merged MDX -- the magic plus a major version that is not the split form.

    Phrased as "not 1" rather than "is 2" on purpose. An unrecognised version
    is better sent here than left to the flat reader: this parser validates its
    own header and says so when the file is not one, whereas ``flat`` would take
    the descriptor for sectors and report an unreadable disc rather than an
    error. ``head`` must reach past ``VERSION_OFFSET``.
    """
    return (
        head.startswith(MAGIC)
        and len(head) > VERSION_OFFSET
        and head[VERSION_OFFSET] != SPLIT_VERSION_MAJOR
    )


def _inflate(raw: bytes) -> tuple[bytes, int] | None:
    """Inflate one self-terminating raw-DEFLATE stream. (data, consumed) or None."""
    decompressor = zlib.decompressobj(-15)
    try:
        out = decompressor.decompress(raw)
    except zlib.error:
        return None
    if not decompressor.eof:
        return None
    return out, len(raw) - len(decompressor.unused_data)


def _decode_block(raw: bytes, block_size: int) -> tuple[bytes, int] | None:
    """Try to read one compressed block. Returns (data, consumed) or None.

    A block counts as compressed only when the stream terminates, emits exactly
    ``block_size`` bytes, *and* consumed fewer than that. The third check is
    what makes this safe: a stored block exists precisely because compressing it
    saved nothing, so a genuine compressed block always consumes less than it
    emits. Without it, PCM that happens to parse as valid DEFLATE is silently
    misread, and the corruption shows up only as noise in an extracted WAV.
    """
    decoded = _inflate(raw)
    if decoded is None:
        return None
    out, consumed = decoded
    if len(out) != block_size or consumed >= block_size:
        return None
    return out, consumed


class MdxImage(_FileBacked):
    """Compressed or plain MDX, presented as a flat cooked-sector stream.

    The chain carries no index, so one pass on open builds one. That pass has to
    inflate anyway to find each block's end, but it discards the output -- the
    index is a few hundred KB where the decoded image is half a gigabyte, and
    random reads then re-inflate a single 32 KB block.
    """

    kind = "mdx"

    def __init__(self, path):
        super().__init__(path)
        header = self._raw(0, 0x40)
        if not looks_mdx(header):
            raise ValueError(f"{self.path}: not an MDX image")
        (descriptor_offset,) = struct.unpack_from("<Q", header, DESCRIPTOR_OFFSET_FIELD)
        if not 0 < descriptor_offset <= self._end:
            raise ValueError(f"{self.path}: implausible descriptor offset {descriptor_offset}")
        self._payload_end = descriptor_offset
        #: False when the first block was stored, so the size could not be read
        #: off the image and DEFAULT_BLOCK_SIZE was assumed. See stored_only.
        self.block_size_measured = True
        self.block_size = self._derive_block_size()
        self.stride = self._derive_stride()
        self.blocks: list[Block] = self._build_index()
        self._cache: OrderedDict[int, bytes] = OrderedDict()

        raw_total = sum(block.out_len for block in self.blocks)
        total = (raw_total // self.stride) * SECTOR_SIZE
        # The final chunk is often a short stored remainder that leaves the total
        # off a sector boundary. Those bytes fall outside any in-use filesystem
        # block, so trim rather than refuse the disc. See docs/formats/mdx.md.
        self._size = (total // SECTOR_SIZE) * SECTOR_SIZE
        self.trimmed = raw_total - (self._size // SECTOR_SIZE) * self.stride

    def _derive_block_size(self) -> int:
        """Read the block size off the image rather than assuming it.

        Most images use 32768, but not all: one AKAI disc in the wild uses
        32160 throughout, and hard-coding the common value made every block
        fail to inflate and fall through to the stored path -- which reads as
        an unrecognisable filesystem rather than as an error.

        The first block is decoded with no size expectation and its length
        becomes the size for the rest. When that block is stored there is
        nothing to measure, and ``block_size_measured`` records the fact --
        see the note on ``stored_only`` for why that is reported rather than
        searched around.
        """
        decoded = _inflate(self._raw(PAYLOAD_OFFSET, _MAX_BLOCK_READ))
        if decoded is None:
            self.block_size_measured = False
            return DEFAULT_BLOCK_SIZE
        out, consumed = decoded
        if not out or consumed >= len(out):
            self.block_size_measured = False
            return DEFAULT_BLOCK_SIZE
        self.block_size_measured = True
        return len(out)

    def _derive_stride(self) -> int:
        """Bytes per sector inside the payload: 2048, or 2144 with subchannel.

        The block size is a whole number of sectors, so divisibility settles
        it: 32768 is 16 x 2048, while 32160 is 15 x 2144. Miss this and every
        sector is 96 bytes further out than the last, which walks the
        filesystem off its block boundaries and reads as an empty disc.
        """
        for stride in STRIDES:
            if self.block_size % stride == 0:
                return stride
        return SECTOR_SIZE

    def _build_index(self) -> list[Block]:
        blocks: list[Block] = []
        offset = PAYLOAD_OFFSET
        while offset < self._payload_end:
            remaining = self._payload_end - offset
            raw = self._raw(offset, min(_MAX_BLOCK_READ, remaining))
            decoded = _decode_block(raw, self.block_size)
            if decoded is not None:
                _data, consumed = decoded
                blocks.append(Block(offset, consumed, False, self.block_size))
                offset += consumed
            else:
                clen = min(self.block_size, remaining)
                blocks.append(Block(offset, clen, True, clen))
                offset += clen
        # The walk lands on _payload_end by construction: a stored block absorbs
        # min(BLOCK_SIZE, remaining), so the final one always consumes exactly
        # what is left. That makes exact termination a loop invariant, NOT a
        # verification -- do not add a check here and believe it proves anything.
        # A wrong payload offset shows up instead as a stored-block count that
        # dwarfs the compressed one; `samplerdisc info` prints both.
        return blocks

    @property
    def size(self) -> int:
        return self._size

    @property
    def granularity(self) -> int:
        """One block of the chain, in cooked bytes -- 32 768 on most images.

        The chain carries no index, so nothing in the file says which block is
        which: a rip that lost one produces a file that decodes perfectly and
        is short of the disc by exactly this much, with everything after the
        gap moved forward. That is what makes the number worth publishing
        rather than keeping to this module.

        Measured, never assumed. It is ``block_size`` scaled from the stored
        stride to the cooked one, so an image holding 2144-byte sectors with
        subchannel reports the 30 720 cooked bytes its 32 160-byte block
        carries, not 32 160. See docs/formats/mdx.md.
        """
        return self.block_size // self.stride * SECTOR_SIZE

    @property
    def compressed_blocks(self) -> int:
        return sum(1 for block in self.blocks if not block.stored)

    @property
    def stored_only(self) -> bool:
        """Did every block fall through to the stored path?

        This is the one state the container cannot interpret on its own, and it
        has exactly two causes:

        * the payload genuinely does not compress -- an image of a Red Book
          audio CD is entirely stored, because PCM does not deflate;
        * the block size is wrong, so every compressed block failed the size
          check and was taken literally.

        The second cause cannot arise while ``block_size_measured`` is true: a
        size read off a block that inflated is a size that works. It can arise
        when the first block is stored, because then there is nothing to
        measure and DEFAULT_BLOCK_SIZE is assumed.

        Searching the payload for the first real DEFLATE stream looks like the
        fix and is not one. Scanning a 2 MB window of ordinary CD audio at
        byte alignment turns up 167 byte runs that inflate cleanly, so a
        forward scan would pick a plausible wrong size on a disc that decodes
        perfectly today -- trading a silent failure we have never seen for one
        we would cause. Reporting the state and letting a second view of the
        disc settle it is both cheaper and honest; ``samplerdisc info`` says so
        in as many words. See docs/formats/mdx.md.
        """
        return bool(self.blocks) and self.compressed_blocks == 0

    @property
    def stored_blocks(self) -> int:
        return sum(1 for block in self.blocks if block.stored)

    def block_data(self, index: int) -> bytes:
        cached = self._cache.get(index)
        if cached is not None:
            self._cache.move_to_end(index)
            return cached
        block = self.blocks[index]
        if block.stored:
            data = self._raw(block.offset, block.clen)
        else:
            data = zlib.decompressobj(-15).decompress(self._raw(block.offset, block.clen))
        self._cache[index] = data
        if len(self._cache) > _CACHE_BLOCKS:
            self._cache.popitem(last=False)
        return data

    def _read_payload(self, offset: int, length: int) -> bytes:
        """Read from the decoded payload, subchannel included."""
        out = bytearray()
        index, skip = divmod(offset, self.block_size)
        while len(out) < length and index < len(self.blocks):
            chunk = self.block_data(index)[skip:]
            out += chunk[: length - len(out)]
            index += 1
            skip = 0
        return bytes(out)

    def read(self, offset: int, length: int) -> bytes:
        if length <= 0 or offset >= self._size:
            return b""
        length = min(length, self._size - offset)
        if self.stride == SECTOR_SIZE:
            return self._read_payload(offset, length)

        first = offset // SECTOR_SIZE
        last = (offset + length - 1) // SECTOR_SIZE
        count = last - first + 1
        raw = self._read_payload(first * self.stride, count * self.stride)
        out = b"".join(raw[i * self.stride : i * self.stride + SECTOR_SIZE] for i in range(count))
        skip = offset - first * SECTOR_SIZE
        return out[skip : skip + length]

    def iter_sectors(self, chunk_sectors: int = 512):
        """Yield the cooked stream in order, for streaming to an ISO."""
        emitted = 0
        step = chunk_sectors * SECTOR_SIZE
        while emitted < self._size:
            chunk = self.read(emitted, min(step, self._size - emitted))
            if not chunk:
                return
            emitted += len(chunk)
            yield chunk
