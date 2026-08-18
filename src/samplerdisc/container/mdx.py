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

#: Every block expands to exactly this much.
BLOCK_SIZE = 32768

#: The payload starts here -- NOT at the value in the field at 0x38, which
#: looks exactly like a data offset and is not one. See docs/formats/mdx.md.
PAYLOAD_OFFSET = 0x40

#: u64 LE: offset of the trailing MDS descriptor, which is where the payload ends.
DESCRIPTOR_OFFSET_FIELD = 0x30

#: No block can need more than this compressed; used to bound a read.
_MAX_BLOCK_READ = 1 << 18

#: Blocks kept decoded. Reads are usually sequential, so a few is plenty.
_CACHE_BLOCKS = 8


class Block(NamedTuple):
    """One entry of the block chain."""

    offset: int  # where the block starts in the file
    clen: int  # compressed (or stored) length
    stored: bool  # True when held literally rather than deflated
    out_len: int  # decoded length; BLOCK_SIZE except possibly for the last


def looks_mdx(head: bytes) -> bool:
    return head.startswith(MAGIC)


def _decode_block(raw: bytes) -> tuple[bytes, int] | None:
    """Try to read one compressed block. Returns (data, consumed) or None.

    A block counts as compressed only when the stream terminates, emits exactly
    BLOCK_SIZE bytes, *and* consumed fewer than BLOCK_SIZE. That third check is
    what makes this safe: a stored block exists precisely because compressing it
    saved nothing, so a genuine compressed block always consumes less than it
    emits. Without it, PCM that happens to parse as valid DEFLATE is silently
    misread, and the corruption shows up only as noise in an extracted WAV.
    """
    decompressor = zlib.decompressobj(-15)
    try:
        out = decompressor.decompress(raw)
    except zlib.error:
        return None
    if not decompressor.eof or len(out) != BLOCK_SIZE:
        return None
    consumed = len(raw) - len(decompressor.unused_data)
    if consumed >= BLOCK_SIZE:
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
        self.blocks: list[Block] = self._build_index()
        self._cache: OrderedDict[int, bytes] = OrderedDict()

        total = sum(block.out_len for block in self.blocks)
        # The final chunk is often a short stored remainder that leaves the total
        # off a sector boundary. Those bytes fall outside any in-use filesystem
        # block, so trim rather than refuse the disc. See docs/formats/mdx.md.
        self._size = (total // SECTOR_SIZE) * SECTOR_SIZE
        self.trimmed = total - self._size

    def _build_index(self) -> list[Block]:
        blocks: list[Block] = []
        offset = PAYLOAD_OFFSET
        while offset < self._payload_end:
            remaining = self._payload_end - offset
            raw = self._raw(offset, min(_MAX_BLOCK_READ, remaining))
            decoded = _decode_block(raw)
            if decoded is not None:
                _data, consumed = decoded
                blocks.append(Block(offset, consumed, False, BLOCK_SIZE))
                offset += consumed
            else:
                clen = min(BLOCK_SIZE, remaining)
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
    def compressed_blocks(self) -> int:
        return sum(1 for block in self.blocks if not block.stored)

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

    def read(self, offset: int, length: int) -> bytes:
        if length <= 0 or offset >= self._size:
            return b""
        length = min(length, self._size - offset)
        out = bytearray()
        index, skip = divmod(offset, BLOCK_SIZE)
        while len(out) < length and index < len(self.blocks):
            chunk = self.block_data(index)[skip:]
            out += chunk[: length - len(out)]
            index += 1
            skip = 0
        return bytes(out)

    def iter_sectors(self, chunk_blocks: int = 32):
        """Yield the cooked stream in order, for streaming to an ISO."""
        emitted = 0
        buffer = bytearray()
        for index in range(len(self.blocks)):
            buffer += self.block_data(index)
            if len(buffer) >= chunk_blocks * BLOCK_SIZE:
                take = min(len(buffer), self._size - emitted)
                yield bytes(buffer[:take])
                emitted += take
                buffer = buffer[take:]
                if emitted >= self._size:
                    return
        if buffer and emitted < self._size:
            yield bytes(buffer[: self._size - emitted])
