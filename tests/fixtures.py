"""Synthetic container fixtures, built in code.

No disc image or fragment of one is ever committed (ADR-0008), so every fixture
here is constructed from scratch and carries no audio.
"""

from __future__ import annotations

import struct
import zlib

from samplerdisc.container.mdx import DEFAULT_BLOCK_SIZE, MAGIC, PAYLOAD_OFFSET
from samplerdisc.container.rawcd import RAW_SECTOR_SIZE, SYNC, USER_DATA_OFFSET


def compressible_block(seed: int = 0, size: int = DEFAULT_BLOCK_SIZE) -> bytes:
    """A block that deflates well below its own size."""
    return bytes([(seed + i // 512) & 0xFF for i in range(size)])


def incompressible_block(seed: int = 1, size: int = DEFAULT_BLOCK_SIZE) -> bytes:
    """High-entropy data, so a real encoder would store it literally."""
    out = bytearray()
    state = seed | 1
    while len(out) < size:
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        out += struct.pack("<I", state)
    return bytes(out[:size])


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


def akai_name(text: str) -> bytes:
    """Encode a name in the AKAI charset, padded to 12 with the space index."""
    from samplerdisc.fs.akai import CHARSET, NAME_LEN

    text = text.upper()[:NAME_LEN].ljust(NAME_LEN)
    return bytes(CHARSET.index(c) if c in CHARSET else CHARSET.index(" ") for c in text)


def akai_partition(volumes, blocks_total: int = 512) -> bytes:
    """Build an AKAI partition image.

    ``volumes`` is a list of ``(name, [(file_name, type_byte, size, payload)])``.
    Returns a byte image whose block 0 is the partition header.
    """
    from samplerdisc.fs.akai import (
        BLOCK_SIZE,
        FILE_ENTRY_LEN,
        NAME_LEN,
        VOLUME_DIR_OFFSET,
        VOLUME_ENTRY_LEN,
    )

    image = bytearray(blocks_total * BLOCK_SIZE)
    next_block = 1
    header = bytearray(BLOCK_SIZE)

    for index, (volume_name, files) in enumerate(volumes):
        volume_block = next_block
        next_block += 1
        entry = bytearray(VOLUME_ENTRY_LEN)
        entry[:NAME_LEN] = akai_name(volume_name)
        struct.pack_into("<HH", entry, NAME_LEN, 1, volume_block)
        base = VOLUME_DIR_OFFSET + index * VOLUME_ENTRY_LEN
        header[base : base + VOLUME_ENTRY_LEN] = entry

        directory = bytearray(BLOCK_SIZE)
        for slot, (file_name, type_byte, size, payload) in enumerate(files):
            file_block = next_block
            next_block += (len(payload) + BLOCK_SIZE - 1) // BLOCK_SIZE or 1
            image[file_block * BLOCK_SIZE : file_block * BLOCK_SIZE + len(payload)] = payload
            record = bytearray(FILE_ENTRY_LEN)
            record[:NAME_LEN] = akai_name(file_name)
            record[NAME_LEN : NAME_LEN + 4] = b"\x20\x20\x20\x20"
            record[16] = type_byte
            record[17] = size & 0xFF
            record[18] = (size >> 8) & 0xFF
            record[19] = (size >> 16) & 0xFF
            struct.pack_into("<H", record, 20, file_block)
            directory[slot * FILE_ENTRY_LEN : (slot + 1) * FILE_ENTRY_LEN] = record
        image[volume_block * BLOCK_SIZE : (volume_block + 1) * BLOCK_SIZE] = directory

    image[0:BLOCK_SIZE] = header
    return bytes(image)


def akai_sample(
    name: str,
    rate: int = 44100,
    words: int = 64,
    pitch: int = 60,
    loop: tuple[int, int] | None = None,
    dwell: int = 9999,
    cents: int = 0,
) -> bytes:
    """A 150-byte S1000 sample header followed by signed 16-bit LE PCM.

    ``loop`` is (start, end) in frames; the header stores the end and the
    length, not the start.
    """
    from samplerdisc.fs.akai import NAME_LEN, SAMPLE_HEADER_LEN, SAMPLE_VALID
    from samplerdisc.sample.akai import OFF_LOOP_RECORDS, OFF_LOOPS, OFF_TUNE_CENTS

    header = bytearray(SAMPLE_HEADER_LEN)
    header[0] = 3
    header[1] = 1
    header[2] = pitch
    header[3 : 3 + NAME_LEN] = akai_name(name)
    header[15] = SAMPLE_VALID
    struct.pack_into("<I", header, 26, words)
    struct.pack_into("<H", header, 138, rate)
    header[OFF_TUNE_CENTS] = cents & 0xFF
    if loop is not None:
        start, end = loop
        header[OFF_LOOPS] = 1
        struct.pack_into("<I", header, OFF_LOOP_RECORDS, end)
        struct.pack_into("<H", header, OFF_LOOP_RECORDS + 4, 0)  # fraction
        struct.pack_into("<H", header, OFF_LOOP_RECORDS + 6, end - start)
        struct.pack_into("<H", header, OFF_LOOP_RECORDS + 10, dwell)
    pcm = b"".join(struct.pack("<h", (i * 137) % 20000 - 10000) for i in range(words))
    return bytes(header) + pcm


def make_iso9660(files: dict[str, bytes], label: str = "SAMPLE CD") -> bytes:
    """A minimal single-level ISO 9660 image.

    Enough of the standard to exercise the backend: a 16-sector system area, a
    primary volume descriptor, a terminator, a root directory and the file
    extents. No Joliet, no Rock Ridge, no subdirectories.
    """
    sector = 2048

    def both32(value: int) -> bytes:
        return struct.pack("<I", value) + struct.pack(">I", value)

    def both16(value: int) -> bytes:
        return struct.pack("<H", value) + struct.pack(">H", value)

    def record(name: bytes, extent: int, length: int, flags: int) -> bytes:
        base = 33 + len(name)
        padded = base + (base % 2)
        rec = bytearray(padded)
        rec[0] = padded
        rec[2:10] = both32(extent)
        rec[10:18] = both32(length)
        rec[25] = flags
        rec[28:32] = both16(1)
        rec[32] = len(name)
        rec[33 : 33 + len(name)] = name
        return bytes(rec)

    root_extent = 19
    entries = bytearray()
    entries += record(b"\x00", root_extent, sector, 0x02)
    entries += record(b"\x01", root_extent, sector, 0x02)

    data_extent = root_extent + 1
    payloads = bytearray()
    for name, blob in files.items():
        encoded = name.upper().encode("ascii") + b";1"
        entries += record(encoded, data_extent, len(blob), 0)
        blocks = (len(blob) + sector - 1) // sector
        payloads += blob + b"\x00" * (blocks * sector - len(blob))
        data_extent += blocks

    root_dir = bytes(entries).ljust(sector, b"\x00")

    pvd = bytearray(sector)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[40:72] = label.ljust(32).encode("ascii")[:32]
    pvd[80:88] = both32(data_extent)
    pvd[128:132] = both16(sector)
    pvd[156:190] = record(b"\x00", root_extent, sector, 0x02)[:34]

    terminator = bytearray(sector)
    terminator[0] = 255
    terminator[1:6] = b"CD001"
    terminator[6] = 1

    system_area = b"\x00" * (16 * sector)
    spare = b"\x00" * sector
    return system_area + bytes(pvd) + bytes(terminator) + spare + root_dir + bytes(payloads)


def tiny_wav(tmp_path, frames: int = 32, rate: int = 44100) -> bytes:
    """A real WAV, built by our own writer, for use as ISO 9660 payload."""
    from samplerdisc.wav import write_wav

    pcm = b"".join(struct.pack("<h", (i * 211) % 8000 - 4000) for i in range(frames))
    path = tmp_path / "t.wav"
    write_wav(path, pcm, rate)
    return path.read_bytes()
