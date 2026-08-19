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


def make_mdx(
    blocks: list[bytes],
    stored: set[int] | None = None,
    disc_soft: bool = False,
) -> tuple[bytes, bytes]:
    """Build a compressed MDX. Returns (file bytes, expected decoded payload).

    ``disc_soft`` writes the later header seen on 2015-era images -- version
    ``02 01``, "Disc Soft Ltd.", and 2560 rather than 192 in the field at 0x38.
    The payload still starts at 0x40 in both, which is the point of testing it.
    """
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
    # Fixed-width fields: a slice assignment of the wrong length grows the
    # bytearray and shifts every offset after it, which produces a header that
    # parses to nonsense rather than an error.
    version, notice = (
        (b"\x02\x01", b"(C) 2000-2015 DiscSoft Ltd")
        if disc_soft
        else (b"\x02\x00", b"(C) 2000-2011 DT Soft Ltd.")
    )
    assert len(notice) == 0x2C - 0x12, f"copyright notice must be {0x2C - 0x12} bytes"
    header[0x10:0x12] = version
    header[0x12:0x2C] = notice
    struct.pack_into("<Q", header, 0x30, PAYLOAD_OFFSET + len(payload))
    struct.pack_into("<Q", header, 0x38, 2560 if disc_soft else 192)
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


def subchannel_block(seed: int = 0, sectors: int = 15) -> tuple[bytes, bytes]:
    """One MDX block of 2144-byte sectors: 2048 of data plus 96 of subchannel.

    Returns (block as stored, the cooked 2048-byte data it should yield).
    """
    from samplerdisc.container.mdx import SUBCHANNEL_LEN

    stored = bytearray()
    cooked = bytearray()
    for index in range(sectors):
        data = bytes(((seed + index + i // 256) & 0xFF) for i in range(2048))
        stored += data + b"\x40\x00" * (SUBCHANNEL_LEN // 2)
        cooked += data
    return bytes(stored), bytes(cooked)


def stereo_audio_block(frames: int = 16384, seed: int = 7) -> bytes:
    """A smooth 16-bit LE stereo waveform whose channels differ.

    Not a sine: a slow random walk per channel, which is closer to what real
    programme material looks like to the statistics in ``audiocd`` and avoids a
    periodicity the gate could pick up on for the wrong reason.
    """
    out = bytearray()
    left = right = 0
    state = seed | 1
    for _ in range(frames):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        left = max(-20000, min(20000, left + ((state >> 16) % 401) - 200))
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        right = max(-20000, min(20000, right + ((state >> 16) % 401) - 200))
        out += struct.pack("<hh", left, right)
    return bytes(out)


def mono_sample_block(frames: int = 32768, seed: int = 11) -> bytes:
    """A smooth 16-bit LE *mono* waveform -- what a sampler payload looks like.

    The audio gate must not accept this: it is exactly the shape that fools a
    plain smoothness test, and real Roland discs are full of it.
    """
    out = bytearray()
    value = 0
    state = seed | 1
    for _ in range(frames):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        value = max(-20000, min(20000, value + ((state >> 16) % 401) - 200))
        out += struct.pack("<h", value)
    return bytes(out)


def emu3_disc(
    folders,
    *,
    folder_block: int = 6,
    reserved: int = 2,
    nul_padded: bool = False,
    bank_header: bool = True,
    total_blocks: int = 4096,
) -> bytes:
    """Build a synthetic EMU3 image.

    ``folders`` is ``[(folder_name, [(bank_name, [(sample_name, rate, frames)])])]``.
    Each folder gets its own 512-byte bank directory, which is the layout that
    matters: reading only the directory the header points at loses every bank
    past the first folder.

    ``bank_header`` False omits the ``EMULATOR`` header, which is the E-IV
    case: the banks are listed from the directory and cannot be located, so no
    samples come out.
    """
    from samplerdisc.fs.emu3 import (
        BANK_MAGIC,
        BLOCK,
        ENTRY_LEN,
        MAGIC,
        OFF_SAMPLE_HEADER_LEN,
        OFF_SAMPLE_RATE,
        OFF_SAMPLE_RECORD_LEN,
        RECORD_LEN_BIAS,
        SAMPLE_HEADER_LEN,
    )

    pad = b"\x00" if nul_padded else b" "

    def name16(text: str) -> bytes:
        return text.encode("ascii")[:16].ljust(16, pad)

    image = bytearray(total_blocks * BLOCK)
    image[0:4] = MAGIC
    bank_block = folder_block + reserved
    struct.pack_into("<I", image, 0x08, folder_block)
    struct.pack_into("<I", image, 0x0C, reserved)
    struct.pack_into("<I", image, 0x10, bank_block)

    # Bank payloads live after the directories; one 1 MiB slot per bank.
    data_at = 64 * BLOCK
    slot = 1 << 20
    if data_at + slot * sum(len(b) for _, b in folders) > len(image):
        image.extend(b"\x00" * (data_at + slot * sum(len(b) for _, b in folders) - len(image)))

    folder_dir = bytearray()
    index = 0
    for f_index, (folder_name, banks) in enumerate(folders):
        dir_block = bank_block + f_index
        entry = bytearray(ENTRY_LEN)
        entry[:16] = name16(folder_name)
        struct.pack_into("<HH", entry, 18, dir_block, 0xFFFF)
        struct.pack_into("<H", entry, 26, 0xFFFF)
        folder_dir += entry

        bank_dir = bytearray()
        for bank_name, samples in banks:
            record = bytearray(ENTRY_LEN)
            record[:16] = name16(bank_name)
            struct.pack_into("<HH", record, 18, index + 1, 1)
            struct.pack_into("<H", record, 26, 0x0081)
            bank_dir += record

            at = data_at + slot * index
            if bank_header:
                image[at : at + len(BANK_MAGIC)] = BANK_MAGIC
                image[at + 16 : at + 32] = name16(bank_name)
            cursor = at + 256
            for sample_name, rate, frames in samples:
                pcm = stereo_audio_block(frames=frames // 2)[: frames * 2]
                record_len = SAMPLE_HEADER_LEN + len(pcm)
                head = bytearray(SAMPLE_HEADER_LEN)
                head[2:18] = name16(sample_name)
                struct.pack_into("<I", head, OFF_SAMPLE_HEADER_LEN, SAMPLE_HEADER_LEN)
                struct.pack_into("<I", head, OFF_SAMPLE_RECORD_LEN, record_len - RECORD_LEN_BIAS)
                struct.pack_into("<I", head, OFF_SAMPLE_RATE, rate)
                image[cursor : cursor + SAMPLE_HEADER_LEN] = head
                image[cursor + SAMPLE_HEADER_LEN : cursor + record_len] = pcm
                cursor += record_len + 16  # a gap: records are not contiguous
            index += 1
        image[dir_block * BLOCK : dir_block * BLOCK + len(bank_dir)] = bank_dir

    image[folder_block * BLOCK : folder_block * BLOCK + len(folder_dir)] = folder_dir
    return bytes(image)
