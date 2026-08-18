"""Synthetic container fixtures, built in code.

No disc image or fragment of one is ever committed (ADR-0008), so every fixture
here is constructed from scratch and carries no audio.
"""

from __future__ import annotations

import struct
import zlib

from samplerdisc.container.mdx import BLOCK_SIZE, MAGIC, PAYLOAD_OFFSET
from samplerdisc.container.rawcd import RAW_SECTOR_SIZE, SYNC, USER_DATA_OFFSET


def compressible_block(seed: int = 0) -> bytes:
    """32 KB that deflates well below its own size."""
    return bytes([(seed + i // 512) & 0xFF for i in range(BLOCK_SIZE)])


def incompressible_block(seed: int = 1) -> bytes:
    """32 KB of high-entropy data, so a real encoder would store it literally."""
    out = bytearray()
    state = seed | 1
    while len(out) < BLOCK_SIZE:
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        out += struct.pack("<I", state)
    return bytes(out[:BLOCK_SIZE])


def make_mdx(blocks: list[bytes], stored: set[int] | None = None) -> tuple[bytes, bytes]:
    """Build a compressed MDX. Returns (file bytes, expected decoded payload)."""
    stored = stored or set()
    payload = bytearray()
    expected = bytearray()
    for index, block in enumerate(blocks):
        expected += block
        if index in stored:
            payload += block
        else:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload += compressor.compress(block) + compressor.flush()

    header = bytearray(PAYLOAD_OFFSET)
    header[0 : len(MAGIC)] = MAGIC
    header[0x10:0x12] = b"\x02\x00"
    header[0x12:0x2C] = b"(C) 2000-2011 DT Soft Ltd."
    struct.pack_into("<Q", header, 0x30, PAYLOAD_OFFSET + len(payload))
    struct.pack_into("<Q", header, 0x38, 192)
    descriptor = b"\x00" * 640
    return bytes(header) + bytes(payload) + descriptor, bytes(expected)


def make_rawcd(sectors: list[bytes]) -> bytes:
    """Wrap cooked 2048-byte sectors in 2352-byte raw CD sectors."""
    out = bytearray()
    for index, data in enumerate(sectors):
        sector = bytearray(RAW_SECTOR_SIZE)
        sector[0 : len(SYNC)] = SYNC
        sector[12:15] = bytes((index // 4500, (index // 75) % 60, index % 75))
        sector[15] = 1
        sector[USER_DATA_OFFSET : USER_DATA_OFFSET + len(data)] = data
        out += sector
    return bytes(out)


def make_nrg(
    cooked: bytes,
    pregap_sectors: int = 150,
    sector_size: int = 2048,
    version: int = 2,
) -> bytes:
    """Build an NRG whose data track begins after ``pregap_sectors`` of zeros."""
    pregap = b"\x00" * (pregap_sectors * sector_size)
    data = pregap + cooked
    track_start = len(pregap)
    track_end = len(data)

    dao_body = bytearray(22)
    struct.pack_into(">I", dao_body, 0, 22 + 42)
    dao_body[19] = 1  # toc type
    dao_body[20] = 1  # first track
    dao_body[21] = 1  # last track
    track = bytearray(42)
    struct.pack_into(">HH", track, 12, sector_size, 0)  # sector size, mode
    struct.pack_into(">Q", track, 18, 0)  # index0
    struct.pack_into(">Q", track, 26, track_start)  # index1
    struct.pack_into(">Q", track, 34, track_end)  # end
    dao_body += track

    footer = bytearray()
    footer += b"DAOX" + struct.pack(">I", len(dao_body)) + bytes(dao_body)
    footer += b"SINF" + struct.pack(">I", 4) + struct.pack(">I", 1)
    footer += b"END!" + struct.pack(">I", 0)

    first_chunk = len(data)
    if version == 2:
        trailer = b"NER5" + struct.pack(">Q", first_chunk)
    else:
        trailer = b"\x00" * 4 + b"NERO" + struct.pack(">I", first_chunk)
    return data + bytes(footer) + trailer


def cooked_sectors(count: int, fill: int = 0xA5) -> bytes:
    """``count`` recognisable 2048-byte sectors."""
    out = bytearray()
    for index in range(count):
        sector = bytearray(2048)
        struct.pack_into("<I", sector, 0, index)
        for i in range(4, 2048):
            sector[i] = (fill + index + i) & 0xFF
        out += sector
    return bytes(out)
