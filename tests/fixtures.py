"""Synthetic container fixtures, built in code.

No disc image or fragment of one is ever committed (ADR-0008), so every fixture
here is constructed from scratch and carries no audio.
"""

from __future__ import annotations

import itertools
import struct
import zlib

from samplerdisc.container.mdx import (
    DEFAULT_BLOCK_SIZE,
    MAGIC,
    PAYLOAD_OFFSET,
    SPLIT_VERSION_MAJOR,
    VERSION_OFFSET,
)
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


def make_mds(sector_count: int = 260287, minor: int = 4) -> bytes:
    """A split .mds descriptor: the MDX magic with the split major version.

    Sized and shaped after the one specimen in hand -- 486 bytes, version
    ``01 04``, the sector count as a u32 at 0x5C, and a ``*.mdf`` filename at
    the tail. Only the first 17 bytes are load-bearing for detection; the rest
    is here so a fixture that gets handed to the MDX parser by mistake fails
    the way a real one did rather than trivially.
    """
    out = bytearray(0x1E6)
    out[0 : len(MAGIC)] = MAGIC
    out[VERSION_OFFSET] = SPLIT_VERSION_MAJOR
    out[VERSION_OFFSET + 1] = minor
    struct.pack_into("<i", out, 0x58, -150)  # session start, before the pregap
    struct.pack_into("<I", out, 0x5C, sector_count)
    struct.pack_into("<I", out, 0x1D0, 0x1E0)  # offset of the filename below
    out[0x1E0:0x1E6] = b"*.mdf\x00"
    return bytes(out)


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


def akai_partition(
    volumes,
    blocks_total: int = 512,
    *,
    stale_slots=(),
    phantom_directories=(),
    allocation_map: bool = True,
    volume_type: int = 1,
) -> bytes:
    """Build an AKAI partition image.

    ``volumes`` is a list of ``(name, [(file_name, type_byte, size, payload)])``.
    Returns a byte image whose block 0 is the partition header.

    The header carries the partition's block count and a **block allocation
    map**, both of which a real one has and neither of which this fixture had
    while the volume walk ignored them. The map is built to match what is
    written: a live volume's directory block reads ``FAT_VOLUME_DIR``, a file's
    blocks chain to ``FAT_CHAIN_END``, everything else stays free.

    The three keyword arguments model the three ways a real disc departs from
    that, one per situation measured on the shelf:

    ``stale_slots``
        ``(name, start_block)`` pairs written into the volume directory with a
        type byte of 0 -- a slot AKAI pre-formatted, whose start block was left
        pointing wherever formatting left it. Point one at a file's block to
        reproduce `Advance Orchestra`, or at an unused one to reproduce
        `Kickin' Lunatic Beats 2 CD1`'s `VOLUME 018`.
    ``phantom_directories``
        blocks marked ``FAT_VOLUME_DIR`` in the map with no directory written
        at them -- what an image short of the disc it came from looks like from
        inside the filesystem.
    ``allocation_map``
        False leaves the map area zeroed and the block count unwritten, for the
        case where the disc declares nothing usable and no note may be drawn.
    """
    from samplerdisc.fs.akai import (
        BLOCK_SIZE,
        FAT_CHAIN_END,
        FAT_OFFSET,
        FAT_VOLUME_DIR,
        FILE_ENTRY_LEN,
        HEADER_PATTERN,
        HEADER_PATTERN_OFFSET,
        HEADER_TAIL,
        HEADER_TAIL_OFFSET,
        NAME_LEN,
        PARTITION_BLOCKS_OFFSET,
        SIZE_ECHO_BIAS,
        SIZE_ECHO_OFFSET,
        VOLUME_DIR_OFFSET,
        VOLUME_ENTRY_LEN,
        VOLUME_START_OFFSET,
        VOLUME_TYPE_INACTIVE,
        VOLUME_TYPE_OFFSET,
    )

    image = bytearray(blocks_total * BLOCK_SIZE)
    next_block = 1
    header = bytearray(BLOCK_SIZE)
    allocation = [0] * blocks_total

    def slot(index: int, name: str, type_byte: int, start: int) -> None:
        entry = bytearray(VOLUME_ENTRY_LEN)
        entry[:NAME_LEN] = akai_name(name)
        entry[VOLUME_TYPE_OFFSET] = type_byte
        struct.pack_into("<H", entry, VOLUME_START_OFFSET, start)
        base = VOLUME_DIR_OFFSET + index * VOLUME_ENTRY_LEN
        header[base : base + VOLUME_ENTRY_LEN] = entry

    for index, (volume_name, files) in enumerate(volumes):
        volume_block = next_block
        next_block += 1
        slot(index, volume_name, volume_type, volume_block)
        allocation[volume_block] = FAT_VOLUME_DIR

        directory = bytearray(BLOCK_SIZE)
        for position, (file_name, type_byte, size, payload) in enumerate(files):
            file_block = next_block
            span = (len(payload) + BLOCK_SIZE - 1) // BLOCK_SIZE or 1
            next_block += span
            image[file_block * BLOCK_SIZE : file_block * BLOCK_SIZE + len(payload)] = payload
            # Chain the extent the way the disc does, so a file's blocks are
            # walkable from the map alone and end where its size says.
            for step in range(span):
                allocation[file_block + step] = (
                    FAT_CHAIN_END if step == span - 1 else file_block + step + 1
                )
            record = bytearray(FILE_ENTRY_LEN)
            record[:NAME_LEN] = akai_name(file_name)
            record[NAME_LEN : NAME_LEN + 4] = b"\x20\x20\x20\x20"
            record[16] = type_byte
            record[17] = size & 0xFF
            record[18] = (size >> 8) & 0xFF
            record[19] = (size >> 16) & 0xFF
            struct.pack_into("<H", record, 20, file_block)
            directory[position * FILE_ENTRY_LEN : (position + 1) * FILE_ENTRY_LEN] = record
        image[volume_block * BLOCK_SIZE : (volume_block + 1) * BLOCK_SIZE] = directory

    for offset, (name, start) in enumerate(stale_slots):
        slot(len(volumes) + offset, name, VOLUME_TYPE_INACTIVE, start)
    for block in phantom_directories:
        allocation[block] = FAT_VOLUME_DIR

    # The constant field a real header carries, and the two fields that restate
    # the block count. Together they are what says "a partition begins here",
    # and the walk reads no partition past the first without them (ADR-0023).
    header[HEADER_PATTERN_OFFSET : HEADER_PATTERN_OFFSET + len(HEADER_PATTERN)] = HEADER_PATTERN
    struct.pack_into("<H", header, HEADER_TAIL_OFFSET, HEADER_TAIL)

    if allocation_map:
        # The map has to fit the header block, as it does on a real partition.
        # A slice assignment past the end would grow the bytearray rather than
        # complain, which moves block 1 and reads as a corrupt filesystem.
        assert FAT_OFFSET + blocks_total * 2 <= BLOCK_SIZE, (
            f"an allocation map for {blocks_total} blocks does not fit the header block"
        )
        struct.pack_into("<H", header, PARTITION_BLOCKS_OFFSET, blocks_total)
        struct.pack_into("<H", header, SIZE_ECHO_OFFSET, (blocks_total + SIZE_ECHO_BIAS) & 0xFFFF)
        packed = struct.pack(f"<{blocks_total}H", *allocation)
        header[FAT_OFFSET : FAT_OFFSET + len(packed)] = packed

    image[0:BLOCK_SIZE] = header
    return bytes(image)


def akai_disc(partitions, *, declared=None, flag: int = 0) -> bytes:
    """Lay partition images end to end and write the disk's partition table.

    ``partitions`` are images from ``akai_partition``, in order; pass a run of
    zero bytes for a partition the image does not hold. The table goes in the
    first one, at the fixed offset a real disc keeps it, and declares each
    partition's size in blocks followed by the disk total.

    ``declared`` overrides the sizes written into the table. Declaring more
    partitions than are present is how an image short of the disk it was made
    from presents -- `Kickin' Lunatic Beats 2 CD1` declares eleven and holds
    one -- and the sizes still have to sum to the total, as they do on all 44
    discs measured.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE, PARTITION_TABLE_OFFSET

    sizes = [len(part) // BLOCK_SIZE for part in partitions]
    listed = list(declared) if declared is not None else sizes
    image = bytearray(b"".join(partitions))
    table = bytearray([len(listed), flag])
    table += struct.pack(f"<{len(listed)}H", *listed)
    table += struct.pack("<H", sum(listed) & 0xFFFF)
    assert PARTITION_TABLE_OFFSET + len(table) <= len(image), (
        "the partition table does not fit in the first partition"
    )
    image[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + len(table)] = table
    return bytes(image)


def akai_sample(
    name: str,
    rate: int = 44100,
    words: int = 64,
    pitch: int = 60,
    loop: tuple[int, int] | None = None,
    dwell: int = 9999,
    cents: int = 0,
    header_len: int | None = None,
    valid: int | None = None,
    sample_id: int = 3,
) -> bytes:
    """A sample header followed by signed 16-bit LE PCM.

    ``loop`` is (start, end) in frames; the header stores the end and the
    length, not the start.

    ``header_len`` is 150 by default, the S1000 length. Pass 192 for the S3000
    variant: the fields are the same and the audio starts 42 bytes later, which
    is what the type byte's high bit selects on a real disc. ``valid`` and
    ``sample_id`` are overridable so a payload can be made *not* the file its
    directory entry names, which no real disc in the collection provides.
    """
    from samplerdisc.fs.akai import NAME_LEN, SAMPLE_HEADER_LEN, SAMPLE_VALID
    from samplerdisc.sample.akai import OFF_LOOP_RECORDS, OFF_LOOPS, OFF_TUNE_CENTS

    header = bytearray(SAMPLE_HEADER_LEN if header_len is None else header_len)
    header[0] = sample_id
    header[1] = 1
    header[2] = pitch
    header[3 : 3 + NAME_LEN] = akai_name(name)
    header[15] = SAMPLE_VALID if valid is None else valid
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


def make_iso9660(
    files: dict[str, bytes],
    label: str = "SAMPLE CD",
    joliet: bool = False,
    short_names: dict[str, str] | None = None,
    joliet_label: str | None = None,
    associated: tuple[str, ...] = (),
    break_joliet_root: bool = False,
) -> bytes:
    """A minimal ISO 9660 image, optionally with a Joliet name space.

    Enough of the standard to exercise the backend: a 16-sector system area, a
    primary volume descriptor, a terminator, a root directory and the file
    extents. No Rock Ridge, no subdirectories.

    ``files`` maps name to payload. The primary tree carries
    ``short_names[name]`` where given and the uppercased name otherwise, so a
    fixture can put several files under one 8.3 name -- which is what Vintage
    Pro does with 61 of them. With ``joliet`` a supplementary descriptor is
    written whose tree carries the ``files`` keys verbatim in UCS-2, pointing
    at the same extents: the two trees differ only in what they call things.

    ``associated`` names get a *second* record apiece, flagged 0x04 and
    pointing at a different, much smaller extent -- an Apple resource fork,
    which is what several ProSamples discs are full of. ``break_joliet_root``
    points the supplementary descriptor's root past the end of the image,
    leaving the primary tree intact: a damaged Joliet name space over a
    readable disc.
    """
    sector = 2048
    short_names = short_names or {}

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

    def pack(records: list[bytes]) -> bytes:
        """A directory extent. Records never straddle a sector boundary."""
        out = bytearray()
        for rec in records:
            if len(out) % sector + len(rec) > sector:
                out += b"\x00" * (sector - len(out) % sector)
            out += rec
        blocks = max(1, (len(out) + sector - 1) // sector)
        return bytes(out).ljust(blocks * sector, b"\x00")

    primary_extent = 19
    joliet_extent = primary_extent + 1 if joliet else 0
    data_extent = (joliet_extent or primary_extent) + 1

    primary = [
        record(b"\x00", primary_extent, sector, 0x02),
        record(b"\x01", primary_extent, sector, 0x02),
    ]
    wide = [
        record(b"\x00", joliet_extent, sector, 0x02),
        record(b"\x01", joliet_extent, sector, 0x02),
    ]
    payloads = bytearray()
    fork = b"rsrc"  # stands in for fork metadata; not audio, and much smaller
    for name, blob in files.items():
        if name in associated:
            # The fork is listed first, exactly as the real discs do it.
            short_fork = short_names.get(name, name.upper()).encode("ascii", "replace")
            short_fork = short_fork.replace(b"?", b"_") + b";1"
            primary.append(record(short_fork, data_extent, len(fork), 4))
            wide.append(
                record(
                    name.encode("utf-16-be") + "\u003b1".encode("utf-16-be"),
                    data_extent,
                    len(fork),
                    4,
                )
            )
            payloads += fork.ljust(sector, b"\x00")
            data_extent += 1
        # A masterer has no way to spell a non-ASCII character in the primary
        # tree, so it substitutes -- which is half of why Joliet exists.
        short = short_names.get(name, name.upper()).encode("ascii", "replace")
        short = short.replace(b"?", b"_") + b";1"
        primary.append(record(short, data_extent, len(blob), 0))
        wide.append(
            record(
                name.encode("utf-16-be") + "\u003b1".encode("utf-16-be"), data_extent, len(blob), 0
            )
        )
        blocks = (len(blob) + sector - 1) // sector
        payloads += blob + b"\x00" * (blocks * sector - len(blob))
        data_extent += blocks

    primary_dir = pack(primary)
    joliet_dir = pack(wide) if joliet else b""

    def descriptor(kind: int, root_extent: int, root_len: int, ident: bytes) -> bytes:
        vd = bytearray(sector)
        vd[0] = kind
        vd[1:6] = b"CD001"
        vd[6] = 1
        vd[40:72] = ident.ljust(32, b"\x00")[:32]
        vd[80:88] = both32(data_extent)
        vd[128:132] = both16(sector)
        vd[156:190] = record(b"\x00", root_extent, root_len, 0x02)[:34]
        return bytes(vd)

    descriptors = [descriptor(1, primary_extent, len(primary_dir), label.ljust(32).encode("ascii"))]
    if joliet:
        svd = bytearray(
            descriptor(
                2,
                joliet_extent,
                len(joliet_dir),
                (joliet_label if joliet_label is not None else label).encode("utf-16-be"),
            )
        )
        # UCS-2 level 3: what every Joliet disc in the collection carries.
        svd[88:91] = b"%/E"
        if break_joliet_root:
            # Root extent past the end of the image. The primary tree is
            # untouched, so a reader that falls back still sees every file.
            svd[156:190] = record(b"\x00", 1 << 20, sector, 0x02)[:34]
        descriptors.append(bytes(svd))

    terminator = bytearray(sector)
    terminator[0] = 255
    terminator[1:6] = b"CD001"
    terminator[6] = 1
    descriptors.append(bytes(terminator))
    if not joliet:
        descriptors.append(b"\x00" * sector)  # spare, so the root lands at 19

    system_area = b"\x00" * (16 * sector)
    return system_area + b"".join(descriptors) + primary_dir + joliet_dir + bytes(payloads)


def tiny_wav(tmp_path, frames: int = 32, rate: int = 44100) -> bytes:
    """A real WAV, built by our own writer, for use as ISO 9660 payload."""
    from samplerdisc.wav import write_wav

    pcm = b"".join(struct.pack("<h", (i * 211) % 8000 - 4000) for i in range(frames))
    path = tmp_path / "t.wav"
    write_wav(path, pcm, rate)
    return path.read_bytes()


def aiff_pcm(frames: int = 32, channels: int = 1) -> bytes:
    """Big-endian PCM, the way an AIFF stores it."""
    return b"".join(struct.pack(">h", (i * 211) % 8000 - 4000) for i in range(frames * channels))


def make_aiff(
    frames: int = 32,
    rate: int = 44100,
    channels: int = 1,
    bits: int = 16,
    pcm: bytes | None = None,
    form: bytes = b"AIFF",
    loop: tuple[int, int] | None = None,
    base_note: int = 60,
    detune: int = 0,
    play_mode: int = 1,
    name: str = "",
    ssnd_offset: int = 0,
    declared_frames: int | None = None,
) -> bytes:
    """One AIFF payload. See docs/formats/aiff.md.

    ``loop`` is a ``(start, end)`` frame pair; supplying it adds the MARK and
    INST chunks that carry a loop and a root key. ``form`` is exposed so a test
    can build the AIFF-C the parser must refuse.
    """
    if pcm is None:
        pcm = aiff_pcm(frames, channels)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return tag + struct.pack(">I", len(body)) + body + (b"\x00" if len(body) % 2 else b"")

    # The 80-bit IEEE extended sample rate: exponent, then a mantissa with an
    # explicit leading bit.
    exponent = 16383 + 63
    mantissa = rate
    while mantissa and not mantissa & (1 << 63):
        mantissa <<= 1
        exponent -= 1
    extended = struct.pack(">HQ", exponent, mantissa) if rate else b"\x00" * 10

    body = chunk(
        b"COMM",
        struct.pack(
            ">HIH", channels, declared_frames if declared_frames is not None else frames, bits
        )
        + extended,
    )
    if name:
        body += chunk(b"NAME", name.encode("ascii"))
    if loop is not None:
        start, end = loop
        markers = struct.pack(">H", 2)
        # Marker names are Pascal strings padded so the count byte and the
        # characters together come to an even length. "L" needs no pad; "END"
        # does, and using both exercises the walk either way.
        for marker_id, position, label in ((1, start, b"L"), (2, end, b"END")):
            pstring = bytes([len(label)]) + label
            markers += (
                struct.pack(">hI", marker_id, position)
                + pstring
                + (b"\x00" if len(pstring) % 2 else b"")
            )
        body += chunk(b"MARK", markers)
        body += chunk(
            b"INST",
            struct.pack(">bbbbbbh", base_note, detune, 0, 127, 0, 127, 0)
            + struct.pack(">hhh", play_mode, 1, 2)
            + struct.pack(">hhh", 0, 0, 0),
        )
    body += chunk(b"SSND", struct.pack(">II", ssnd_offset, 0) + b"\x00" * ssnd_offset + pcm)
    return b"FORM" + struct.pack(">I", 4 + len(body)) + form + body


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


def roland_cluster(cluster: int, seed: int = 11) -> bytes:
    """The 9 216 bytes this fixture writes into one Roland cluster.

    Keyed on the cluster *number*, so every cluster on a synthetic disc holds
    different audio. That is what makes a chain test mean anything: a walk that
    assumes contiguity instead of following the allocation table then returns
    visibly wrong bytes rather than plausible ones.
    """
    from samplerdisc.fs.roland_s7xx import CLUSTER

    return mono_sample_block(frames=CLUSTER // 2, seed=seed + 2 * cluster)


def roland_sample(
    name: str,
    chain,
    *,
    clusters: int | None = None,
    frames: int | None = None,
    key: int = 60,
    loop_mode: int = 1,
    loop: tuple[int, int] = (0, 0),
    loop_start_fraction: int = 0,
    release: tuple[int, int] | None = None,
    start_point: int = 0,
    param_name: str | None = None,
    terminator: int = 0xFFF8,
    seed: int = 11,
) -> dict:
    """One sample for ``roland_s7xx_disc``.

    ``chain`` is the list of clusters actually linked in the allocation table,
    in order -- give it out of sequence to build a fragmented sample.
    ``clusters`` is what the *directory* declares, which defaults to the length
    of the chain and is set shorter to build a chain that runs past its own
    declared count.

    ``frames`` is the furthest address the parameter record references, which
    on this format is the only thing that says where the audio ends -- there is
    no length field. It defaults to exactly filling the declared clusters, and
    ``release`` then parks a few frames at the end, which is the shape 6 188 of
    the 6 392 measured records have.

    ``terminator`` is the value written after the last cluster: real discs use
    0xFFF8, 0xFFFA and 0xFFFE, and all three must end a chain.
    """
    from samplerdisc.fs.roland_s7xx import CLUSTER

    chain = tuple(chain)
    declared = len(chain) if clusters is None else clusters
    if frames is None:
        frames = declared * CLUSTER // 2
    if release is None:
        release = (max(0, frames - 4), frames)
    return {
        "name": name,
        "param_name": name if param_name is None else param_name,
        "chain": chain,
        "clusters": declared,
        "frames": frames,
        "key": key,
        "loop_mode": loop_mode,
        "loop": loop,
        "loop_start_fraction": loop_start_fraction,
        "release": release,
        "start_point": start_point,
        "terminator": terminator,
        "seed": seed,
    }


def roland_s7xx_disc(
    samples,
    *,
    label: str = "ID2:Solo Strngs ",
    version_text: str = "SYS-772 HardDisk Sys Ver. 2.19",
    counts: tuple[int, int, int, int] = (1, 4, 8, 16),
    sample_count: int | None = None,
    fs_blocks: int | None = None,
    filler: int = 0,
    zero_sample_directory: bool = False,
) -> bytes:
    """Build a synthetic Roland ``S770 MR25A`` image.

    ``samples`` is a list of ``roland_sample()`` dicts. Everything is written
    from the backend's own constants (ADR-0008: not one byte comes off a disc),
    so the fixture and the reader cannot drift apart about where a region sits.

    ``filler`` writes that many extra, entirely valid-looking sample entries
    *past* the header's declared count. There is no terminator in this format
    and the count is the only authority, so a reader that scans instead of
    counting picks them up.

    ``zero_sample_directory`` leaves the directory at block 1644 zeroed while
    the header stays plausible -- the ADR-0012 case, where a magic and a
    pointer are structure and nothing has been confirmed.
    """
    from samplerdisc.fs.roland_s7xx import (
        ADDRESS_SHIFT,
        BLOCK,
        CLASS_ORDER,
        CLASS_SAMPLE,
        CLUSTER,
        CLUSTER_BLOCKS,
        DATA_BLOCK,
        DIR_BLOCK,
        ENTRY_LEN,
        FAT_BLOCK,
        FIRST_DATA_CLUSTER,
        LABEL_LEN,
        MAGIC,
        NAME_LEN,
        OFF_COUNTS,
        OFF_ENTRY_CLASS,
        OFF_ENTRY_INDEX,
        OFF_ENTRY_NEXT,
        OFF_ENTRY_PREV,
        OFF_ENTRY_START,
        OFF_FS_BLOCKS,
        OFF_LABEL,
        OFF_MAGIC,
        OFF_PARAM_CLUSTERS,
        OFF_PARAM_KEY,
        OFF_PARAM_LOOP_MODE,
        OFF_PARAM_RELEASE_END,
        OFF_PARAM_RELEASE_START,
        OFF_PARAM_START,
        OFF_PARAM_SUSTAIN_END,
        OFF_PARAM_SUSTAIN_START,
        PARAM_LEN,
        SAMPLE_PARAM_BLOCK,
    )

    specs = list(samples)
    used = [c for spec in specs for c in spec["chain"]] or [FIRST_DATA_CLUSTER]
    highest = max(max(used), FIRST_DATA_CLUSTER)
    if fs_blocks is None:
        # Four clusters of slack, so max_cluster() leaves room above the last
        # one actually written and an extent test is not accidentally exact.
        fs_blocks = DATA_BLOCK + (highest - FIRST_DATA_CLUSTER + 5) * CLUSTER_BLOCKS
    image = bytearray(DATA_BLOCK * BLOCK + (highest - FIRST_DATA_CLUSTER + 1) * CLUSTER)

    # The links at 18/20/22 -- next, prev, own index -- are three consecutive
    # u16s, so they are written in one pack. They are a cross-check and never a
    # walk: entry i is at base + i * ENTRY_LEN and the count comes from the
    # header.
    assert (OFF_ENTRY_PREV, OFF_ENTRY_INDEX) == (OFF_ENTRY_NEXT + 2, OFF_ENTRY_NEXT + 4)

    def name16(text: str) -> bytes:
        return text.encode("ascii")[:NAME_LEN].ljust(NAME_LEN)

    def address(frames: int, fraction: int = 0) -> int:
        """24.8 fixed point: the low byte is a fractional frame."""
        return (frames << ADDRESS_SHIFT) | fraction

    # --- header. The magic is at byte 4; the first four bytes are zero. Both
    # text fields run 31 bytes and are NUL-terminated on a real disc, which is
    # why neither is 32 here.
    image[OFF_MAGIC : OFF_MAGIC + len(MAGIC)] = MAGIC
    image[0x10:0x1F] = b" " * 15
    image[0x20:0x3F] = version_text.encode("ascii")[:31].ljust(31)
    image[0x40:0x5F] = b"       Copyright   Roland      "
    image[OFF_LABEL : OFF_LABEL + LABEL_LEN] = label.encode("ascii")[:LABEL_LEN].ljust(LABEL_LEN)
    struct.pack_into("<I", image, OFF_FS_BLOCKS, fs_blocks)
    declared_samples = len(specs) if sample_count is None else sample_count
    struct.pack_into("<5H", image, OFF_COUNTS, *counts, declared_samples)
    image[OFF_COUNTS + 10 : 0x200] = b"\xff" * (0x200 - OFF_COUNTS - 10)

    # --- the four directories above the samples. Not walked (ADR-0016), but
    # they exist on every disc and a fixture without them is not the format.
    for cls, count in zip(CLASS_ORDER[:4], counts, strict=True):
        base = DIR_BLOCK[cls] * BLOCK
        for index in range(count):
            entry = bytearray(ENTRY_LEN)
            entry[:NAME_LEN] = name16(f"{cls:02X}:object {index:03d}")
            entry[OFF_ENTRY_CLASS] = cls
            nxt = 0x8000 | (index + 1) if index + 1 < count else 0xFFFF
            prev = 0x8000 | (index - 1) if index else 0xFFFF
            struct.pack_into("<HHH", entry, OFF_ENTRY_NEXT, nxt, prev, index)
            image[base + index * ENTRY_LEN : base + (index + 1) * ENTRY_LEN] = entry

    # --- allocation table. Entry 0 is a media marker and entry 1 is unused,
    # exactly as FAT12/16 reserves its first two.
    fat = FAT_BLOCK * BLOCK
    struct.pack_into("<HH", image, fat, 0xFFF8, 0xFFFF)
    for spec in specs:
        chain = spec["chain"]
        for here, nxt in itertools.pairwise(chain):
            struct.pack_into("<H", image, fat + 2 * here, nxt)
        struct.pack_into("<H", image, fat + 2 * chain[-1], spec["terminator"])

    # --- sample directory, sample parameters, and the audio itself.
    entries = specs + [
        roland_sample(f"FIL:filler {i:04d}", (FIRST_DATA_CLUSTER,)) for i in range(filler)
    ]
    dir_base = DIR_BLOCK[CLASS_SAMPLE] * BLOCK
    param_base = SAMPLE_PARAM_BLOCK * BLOCK
    for index, spec in enumerate(entries):
        if not zero_sample_directory:
            entry = bytearray(ENTRY_LEN)
            entry[:NAME_LEN] = name16(spec["name"])
            entry[OFF_ENTRY_CLASS] = CLASS_SAMPLE
            # The doubly-linked list at 18/20/22 is a cross-check, never a walk.
            nxt = 0x8000 | (index + 1) if index + 1 < len(entries) else 0xFFFF
            prev = 0x8000 | (index - 1) if index else 0xFFFF
            struct.pack_into("<HHH", entry, OFF_ENTRY_NEXT, nxt, prev, index)
            struct.pack_into("<HH", entry, OFF_ENTRY_START, spec["chain"][0], spec["clusters"])
            image[dir_base + index * ENTRY_LEN : dir_base + (index + 1) * ENTRY_LEN] = entry

        loop_start, loop_end = spec["loop"]
        record = bytearray(PARAM_LEN)
        record[:NAME_LEN] = name16(spec["param_name"])
        struct.pack_into("<I", record, OFF_PARAM_START, address(spec["start_point"]))
        # The fraction is zero everywhere except the sustain loop start, where
        # 220 real records carry one -- a sub-sample loop tuning.
        fraction = address(loop_start, spec["loop_start_fraction"])
        struct.pack_into("<I", record, OFF_PARAM_SUSTAIN_START, fraction)
        struct.pack_into("<I", record, OFF_PARAM_SUSTAIN_END, address(loop_end))
        struct.pack_into("<I", record, OFF_PARAM_RELEASE_START, address(spec["release"][0]))
        struct.pack_into("<I", record, OFF_PARAM_RELEASE_END, address(spec["release"][1]))
        # Offset 36 holds {0, 1, 2, 4, 5, 6} and is not named in the format doc.
        struct.pack_into("<H", record, 36, 1)
        struct.pack_into("<H", record, OFF_PARAM_CLUSTERS, spec["clusters"])
        record[OFF_PARAM_LOOP_MODE] = spec["loop_mode"]
        record[OFF_PARAM_KEY] = spec["key"]
        image[param_base + index * PARAM_LEN : param_base + (index + 1) * PARAM_LEN] = record

    for spec in specs:
        for cluster in spec["chain"]:
            at = DATA_BLOCK * BLOCK + (cluster - FIRST_DATA_CLUSTER) * CLUSTER
            image[at : at + CLUSTER] = roland_cluster(cluster, spec["seed"])

    return bytes(image)


def _emu3_pointers(head: bytearray, payload_bytes: int, loop, stereo: bool = False) -> None:
    """Write a record's extent and loop pointers.

    Byte offsets from the record's own start, naming the first byte of a word,
    which is what the reference discs hold -- so the end addresses the *last*
    word rather than one past it.

    ``stereo`` writes the two-channel form: the payload is a block split, all
    of the left channel then all of the right, and both pointer sets are
    written -- the right one a mirror of the left, half a payload on. That is
    what 2 656 records across the seven reference discs hold (ADR-0026).
    """
    from samplerdisc.fs.emu3 import (
        OFF_SAMPLE_END_L,
        OFF_SAMPLE_END_R,
        OFF_SAMPLE_LOOP_END_L,
        OFF_SAMPLE_LOOP_END_R,
        OFF_SAMPLE_LOOP_START_L,
        OFF_SAMPLE_LOOP_START_R,
        OFF_SAMPLE_START_R,
        SAMPLE_HEADER_LEN,
    )

    channel_bytes = payload_bytes // 2 if stereo else payload_bytes
    struct.pack_into("<I", head, OFF_SAMPLE_END_L, SAMPLE_HEADER_LEN + channel_bytes - 2)
    if stereo:
        split = SAMPLE_HEADER_LEN + channel_bytes
        struct.pack_into("<I", head, OFF_SAMPLE_START_R, split)
        struct.pack_into("<I", head, OFF_SAMPLE_END_R, split + channel_bytes - 2)
    if loop is None:
        return
    start, end = loop
    struct.pack_into("<I", head, OFF_SAMPLE_LOOP_START_L, SAMPLE_HEADER_LEN + start * 2)
    struct.pack_into("<I", head, OFF_SAMPLE_LOOP_END_L, SAMPLE_HEADER_LEN + end * 2)
    if stereo:
        struct.pack_into("<I", head, OFF_SAMPLE_LOOP_START_R, split + start * 2)
        struct.pack_into("<I", head, OFF_SAMPLE_LOOP_END_R, split + end * 2)


def emu3_disc(
    folders,
    *,
    folder_block: int = 6,
    reserved: int = 2,
    nul_padded: bool = False,
    bank_header: bool = True,
    formula_4000: tuple[str, ...] = (),
    stale_tail: tuple[tuple[str, int, int], ...] = (),
    second_header: str | None = None,
    eiv: bool = False,
    duplicate_sample_dir: bool = False,
    folder_flags: int | None = None,
    total_blocks: int = 4096,
    loops: dict[str, tuple[int, int]] | None = None,
    stereo: tuple[str, ...] = (),
) -> bytes:
    """Build a synthetic EMU3 image.

    ``folders`` is ``[(folder_name, [(bank_name, [(sample_name, rate, frames)])])]``.
    Each folder gets its own 512-byte bank directory, which is the layout that
    matters: reading only the directory the header points at loses every bank
    past the first folder.

    ``bank_header`` False omits the bank header and writes nothing in its
    place: banks are listed from the directory and no samples come out.

    ``formula_4000`` names the banks whose header carries the ``EMU SI-32``
    signature rather than ``EMULATOR``. `protozoa` writes two of them, and
    they are ordinary banks in every other respect.

    ``stale_tail`` writes extra records into every bank's region past the run
    its header declares -- what a disc leaves behind when a bank image is
    written over a longer one. They are inside the region and are not the
    bank's.

    ``second_header`` names a bank to write a second, older copy of into the
    unallocated region above the banks: same name, same shape, fewer records.
    `esi32-gm` carries two such copies and they sit *before* the banks its
    directory points at, so taking the first header of a name reads the wrong
    one.

    A bank given no samples gets a header declaring a zero-length sample area,
    which is what the index banks on `esi32-gm`, `eiiix-1` and `eiiix-2` do.

    ``stereo`` names the samples whose record declares two channels. Their
    payload is a block split -- all of the left channel, then all of the right
    -- and the frame count given for them is the payload's, so each channel
    gets half of it (ADR-0026).

    ``eiv`` True builds the Emulator IV shape instead -- no ``EMULATOR``
    header, and each bank's samples reached through a chained ``E3S1`` sample
    directory. The bank slot is 1 MiB, so the allocation unit the reader has to
    recover is 2048 blocks.

    ``duplicate_sample_dir`` writes the E-IV sample directory a second time,
    which real discs do: two chains then resolve to one base, and listing both
    reports each record twice.

    ``folder_flags`` overrides the folder entries' flags word. ``studio`` writes
    0x0013 and 0x0018 there rather than 0xFFFF, and requiring 0xFFFF loses
    every folder on that disc.

    ``loops`` maps a sample name to ``(start frame, end frame)`` and writes the
    record's left-hand loop pointers accordingly. A record not named here gets
    the extent pointers and zeroed loop pointers, which is a record declaring
    no loop -- so every fixture written before this existed still describes one.
    """
    from samplerdisc.fs.emu3 import (
        BANK_MAGICS,
        BLOCK,
        EIV_CHAIN_STRIDE,
        EIV_MAGIC,
        EIV_RECORD_OFFSET,
        ENTRY_LEN,
        MAGIC,
        OFF_BANK_SAMPLE_BYTES,
        OFF_BANK_SAMPLE_START,
        OFF_EIV_INDEX,
        OFF_EIV_LENGTH,
        OFF_EIV_NAME,
        OFF_EIV_POSITION,
        OFF_SAMPLE_RATE,
        OFF_SAMPLE_RECORD_LEN,
        OFF_SAMPLE_START_L,
        RECORD_LEN_BIAS,
        SAMPLE_AREA_PREAMBLE,
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
    # Every bank's sample directory, concatenated. Their order in the table
    # carries no meaning: a bank is found through the chain, not through where
    # its entries sit, which is what lets `studio` scatter them.
    sample_dir = bytearray()
    sample_dir_block = 32
    index = 0
    for f_index, (folder_name, banks) in enumerate(folders):
        dir_block = bank_block + f_index
        entry = bytearray(ENTRY_LEN)
        entry[:16] = name16(folder_name)
        struct.pack_into("<HH", entry, 18, dir_block, 0xFFFF)
        struct.pack_into("<H", entry, 26, 0xFFFF if folder_flags is None else folder_flags)
        folder_dir += entry

        bank_dir = bytearray()
        for bank_name, samples in banks:
            record = bytearray(ENTRY_LEN)
            record[:16] = name16(bank_name)
            struct.pack_into("<HH", record, 18, index + 1, 1)
            struct.pack_into("<H", record, 26, 0x0081)
            bank_dir += record

            at = data_at + slot * index
            if eiv:
                # The running offset counts from a base the reader has to
                # recover; the records themselves are located only through it.
                position = 64
                for order, (sample_name, rate, frames) in enumerate(samples, start=1):
                    pcm = stereo_audio_block(frames=frames // 2)[: frames * 2]
                    length = SAMPLE_HEADER_LEN + len(pcm)

                    entry32 = bytearray(ENTRY_LEN)
                    entry32[0:4] = EIV_MAGIC
                    struct.pack_into(">I", entry32, OFF_EIV_LENGTH, length)
                    struct.pack_into(">I", entry32, OFF_EIV_POSITION, position)
                    struct.pack_into(">H", entry32, OFF_EIV_INDEX, order)
                    entry32[OFF_EIV_NAME : OFF_EIV_NAME + 16] = name16(sample_name)
                    sample_dir += entry32

                    # The base the running offsets count from is the slot plus
                    # the tag width, so that base - EIV_RECORD_OFFSET is block
                    # aligned exactly as it is on all three reference discs.
                    record = at + EIV_RECORD_OFFSET + position
                    image[record - EIV_RECORD_OFFSET : record - EIV_RECORD_OFFSET + 4] = EIV_MAGIC
                    head = bytearray(SAMPLE_HEADER_LEN)
                    head[2:18] = name16(sample_name)
                    struct.pack_into("<I", head, OFF_SAMPLE_START_L, SAMPLE_HEADER_LEN)
                    struct.pack_into("<I", head, OFF_SAMPLE_RATE, rate)
                    _emu3_pointers(
                        head, len(pcm), (loops or {}).get(sample_name), sample_name in stereo
                    )
                    image[record : record + SAMPLE_HEADER_LEN] = head
                    image[record + SAMPLE_HEADER_LEN : record + length] = pcm
                    position += length + EIV_CHAIN_STRIDE
                index += 1
                continue
            if bank_header:
                magic = BANK_MAGICS[1] if bank_name in formula_4000 else BANK_MAGICS[0]
                image[at : at + len(magic)] = magic
                image[at + 16 : at + 32] = name16(bank_name)
            # The declared sample area starts at 0x30 and its first record
            # sits SAMPLE_AREA_PREAMBLE bytes into it, which is what every
            # populated bank on the reference discs does.
            sample_area = at + 256
            cursor = sample_area + SAMPLE_AREA_PREAMBLE
            first_record = cursor
            for sample_name, rate, frames in samples:
                pcm = stereo_audio_block(frames=frames // 2)[: frames * 2]
                record_len = SAMPLE_HEADER_LEN + len(pcm)
                head = bytearray(SAMPLE_HEADER_LEN)
                head[2:18] = name16(sample_name)
                struct.pack_into("<I", head, OFF_SAMPLE_START_L, SAMPLE_HEADER_LEN)
                struct.pack_into("<I", head, OFF_SAMPLE_RECORD_LEN, record_len - RECORD_LEN_BIAS)
                struct.pack_into("<I", head, OFF_SAMPLE_RATE, rate)
                _emu3_pointers(
                    head, len(pcm), (loops or {}).get(sample_name), sample_name in stereo
                )
                image[cursor : cursor + SAMPLE_HEADER_LEN] = head
                image[cursor + SAMPLE_HEADER_LEN : cursor + record_len] = pcm
                cursor += record_len + 16  # a gap: records are not contiguous
            if bank_header:
                # The header states where its sample area begins and how long
                # its record run is, measured from the first record. That pair
                # is what says which records in the bank's region are the
                # bank's own; a bank with no samples declares a zero-length
                # run, which is how an index bank on a real disc is told apart
                # from one the walk failed to bound.
                struct.pack_into("<I", image, at + OFF_BANK_SAMPLE_START, sample_area - at)
                struct.pack_into("<I", image, at + OFF_BANK_SAMPLE_BYTES, cursor - first_record)
            if stale_tail:
                # What a real disc leaves behind when a bank image is written
                # over a longer one: the previous occupant's last records,
                # inside this bank's region and past the run it declares.
                stale = cursor + 4096
                for stale_name, rate, frames in stale_tail:
                    pcm = stereo_audio_block(frames=frames // 2)[: frames * 2]
                    record_len = SAMPLE_HEADER_LEN + len(pcm)
                    head = bytearray(SAMPLE_HEADER_LEN)
                    head[2:18] = name16(stale_name)
                    struct.pack_into("<I", head, OFF_SAMPLE_START_L, SAMPLE_HEADER_LEN)
                    struct.pack_into(
                        "<I", head, OFF_SAMPLE_RECORD_LEN, record_len - RECORD_LEN_BIAS
                    )
                    struct.pack_into("<I", head, OFF_SAMPLE_RATE, rate)
                    image[stale : stale + SAMPLE_HEADER_LEN] = head
                    image[stale + SAMPLE_HEADER_LEN : stale + record_len] = pcm
                    stale += record_len + 16
            index += 1
        image[dir_block * BLOCK : dir_block * BLOCK + len(bank_dir)] = bank_dir

    if second_header is not None:
        # An older copy of one bank, in a region the directory allocates to
        # nobody, *below* the bank it duplicates -- which is where `esi32-gm`
        # keeps its two. It is a whole bank image: header, declared run, and
        # one record that is not in the copy the directory points at.
        stray = 16 * BLOCK
        magic = BANK_MAGICS[1] if second_header in formula_4000 else BANK_MAGICS[0]
        image[stray : stray + len(magic)] = magic
        image[stray + 16 : stray + 32] = name16(second_header)
        area = stray + 256
        record_at = area + SAMPLE_AREA_PREAMBLE
        pcm = stereo_audio_block(frames=32)[:64]
        record_len = SAMPLE_HEADER_LEN + len(pcm)
        head = bytearray(SAMPLE_HEADER_LEN)
        head[2:18] = name16("Older Revision")
        struct.pack_into("<I", head, OFF_SAMPLE_START_L, SAMPLE_HEADER_LEN)
        struct.pack_into("<I", head, OFF_SAMPLE_RECORD_LEN, record_len - RECORD_LEN_BIAS)
        struct.pack_into("<I", head, OFF_SAMPLE_RATE, 22000)
        image[record_at : record_at + SAMPLE_HEADER_LEN] = head
        image[record_at + SAMPLE_HEADER_LEN : record_at + record_len] = pcm
        struct.pack_into("<I", image, stray + OFF_BANK_SAMPLE_START, area - stray)
        struct.pack_into("<I", image, stray + OFF_BANK_SAMPLE_BYTES, record_len)

    image[folder_block * BLOCK : folder_block * BLOCK + len(folder_dir)] = folder_dir
    if sample_dir:
        table = sample_dir * 2 if duplicate_sample_dir else sample_dir
        base = sample_dir_block * BLOCK
        image[base : base + len(table)] = table
    return bytes(image)
