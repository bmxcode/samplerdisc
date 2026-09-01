"""Kurzweil ``KMSI`` disc filesystem. See docs/formats/kurzweil.md.

The native disc format of the Kurzweil K2000/K2500 family is not a bespoke
allocation scheme at all: it is a plain **FAT16** filesystem whose boot sector
carries the OEM name ``KMSI`` (Kurzweil Music Systems Inc.). What identifies a
disc as Kurzweil's rather than any other FAT is that eight-byte label, so that
-- not "a FAT is present" -- is what this backend probes on (ADR-0004,
ADR-0035). The 512-byte logical sectors of the FAT sit byte-contiguous inside
the container's 2048-byte cooked stream; the ``rawcd`` container already did
the 2352->2048 de-interleave, so this layer addresses the cooked stream in
512-byte FAT units from the probe offset.

Every file on the two reference discs is a ``.KRZ`` object bank: a bundle of
Kurzweil objects (programs, keymaps and samples) sharing one big-endian PCM
pool, opening with the four-byte tag ``PRAM`` that the probe confirms a real
file by (ADR-0012, ADR-0035). This backend walks a bank's object directory,
lists it as a volume, and enumerates the sample objects inside it as that
volume's files -- the extent, rate and loop each sample declares come from the
directory, and the pool audio it points at is carried to WAV by
``sample/kurzweil.py``. The whole bank is also listed as one ``program`` so
``--keep-originals`` writes the ``.krz`` out for ConvertWithMoss, which reads
the object format this backend does not (ADR-0011). See
docs/formats/kurzweil-krz.md for the bank interior (#63).

Every constant here is documented in the format doc against the two
``Gigapack I & II (Kurzweil)`` discs. Do not change a constant without changing
the doc, and vice versa.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from samplerdisc.fs.base import DEFAULT_ORIGINAL_SUFFIX, File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

#: The OEM name a Kurzweil-formatted volume writes at boot-sector offset 3.
#: Byte-identical on both reference discs. This is the whole detection story:
#: a generic MS-DOS FAT disc carries "MSDOS5.0", "MSWIN4.1" or a mkfs string
#: here, never "KMSI", so probing on it will not claim someone's DOS CD.
OEM_NAME = b"KMSI    "
OFF_OEM = 3

#: The BPB (BIOS Parameter Block) fields this backend reads, as byte offsets
#: into the boot sector. Standard FAT layout; the values in the comments are
#: what both Gigapack discs hold.
OFF_JMP = 0  # 0xE9 0x00 0x00 on both discs (a near jump; 0xEB..0x90 is the other legal form)
OFF_BYTES_PER_SEC = 11  # u16 LE, 512
OFF_SEC_PER_CLUS = 13  # u8, 32 -> a 16 KB cluster
OFF_RSVD = 14  # u16 LE, 1 (the boot sector itself)
OFF_NUM_FATS = 16  # u8, 2
OFF_ROOT_ENT = 17  # u16 LE, 512 (a fixed root directory, as FAT12/16 has)
OFF_TOT16 = 19  # u16 LE, 0 -> use the 32-bit count
OFF_MEDIA = 21  # u8, 0xF8 (fixed disk)
OFF_FAT_SZ16 = 22  # u16 LE, 142 sectors per FAT
OFF_TOT32 = 32  # u32 LE, 1 163 264 sectors
OFF_EXT_BOOT_SIG = 38  # u8, 0x29 -> the volume-id/label/type fields that follow are present
OFF_VOL_LABEL = 43  # 11 bytes, blank on both discs
VOL_LABEL_LEN = 11

BOOT_READ = 62  # enough to cover the BPB and the extended boot fields

#: A FAT logical sector. The BPB declares this (``BYTES_PER_SEC``); the constant
#: names the ratio of four hidden inside the cooked 2048-byte sector -- four
#: FAT sectors to one CD sector -- which is exactly where an off-by-four would
#: hide.
LOGICAL_SECTOR = 512

#: The two reserved FAT slots, then the first addressable cluster is 2 --
#: exactly as FAT12/16 numbers them.
FIRST_DATA_CLUSTER = 2

#: FAT16 end-of-chain. Any entry at or above this ends a cluster chain; 0xFFF7
#: alone marks a bad cluster. Both fall out of the same test.
FAT16_EOC = 0xFFF8

#: FAT16 holds this many clusters, give or take: fewer is FAT12 and more is
#: FAT32, and both pack their allocation table differently. Both discs sit at
#: 36 342 clusters, squarely inside. The backend reads FAT16 only, and the
#: probe declines anything else rather than misread a FAT12 table with FAT16
#: arithmetic (ADR-0035).
FAT12_MAX_CLUSTERS = 4085
FAT16_MAX_CLUSTERS = 65525

#: 32-byte 8.3 directory entries.
ENTRY_LEN = 32
OFF_ENTRY_ATTR = 11
OFF_ENTRY_FIRST_CLUS = 26  # u16 LE (the high word at 20 is 0 on FAT16)
OFF_ENTRY_SIZE = 28  # u32 LE
NAME_LEN = 8
EXT_LEN = 3

#: Directory-entry attribute bits and the two sentinel first-bytes.
ATTR_VOLUME_ID = 0x08
ATTR_DIRECTORY = 0x10
ATTR_LFN = 0x0F  # read-only+hidden+system+volume -> a VFAT long-name fragment, skipped
FREE_ENTRY = 0xE5  # this slot is deleted/free
END_OF_DIR = 0x00  # no entry here and none after: the directory ends

#: The four-byte tag every ``.KRZ`` object bank opens with -- 295 of 295 files
#: across both discs, the 1012-byte ``DRUM KIT`` on CD 2 included. It is what
#: the probe confirms the first file *is* a Kurzweil object and not just a
#: plausible directory pointer (ADR-0012).
KRZ_SIGNATURE = b"PRAM"

#: The ``.KRZ`` object bank interior (docs/formats/kurzweil-krz.md), all
#: big-endian. Past a 32-byte header sits an object directory: a chain of
#: length-prefixed records, each opening with a signed be32 equal to the
#: *negative* of its own length. A non-negative value is the end marker, and
#: the shared PCM pool begins at the byte offset the header names.
KRZ_HEADER_LEN = 8  # the PRAM tag and the u32 that follows it
OFF_POOL_START = 4  # u32: byte offset where the PCM pool begins (a.k.a. osize)
OBJ_DIR_START = 32  # first object record, past the header
OBJ_HDR_MIN = 10  # bytes needed before the name to read a record's header
OBJ_HASH = 4  # u16 type|id hash; its top bits are the object type
OBJ_OFS = 8  # u16; body = record + 8 + this (past a name of nl+3 or nl+4 bytes)
OBJ_NAME = 10  # the name string starts here
OBJ_NAME_MAX = 16  # a name is at most this; a full field carries no NUL terminator
OBJ_BODY_BASE = 8  # body = record + OBJ_BODY_BASE + ofs

#: An object's type and id are packed into the hash. Types with the 0x8000 bit
#: set (all this backend reads) put the type in the top six bits; a sample is
#: type 38. The lower-bit conditional decode a general reader needs for song and
#: effect objects is not reproduced here, because those objects are never read.
OBJ_TYPE_SHIFT = 10
OBJ_TYPE_SAMPLE = 38

#: The sample object's body: a 12-byte ``KSample`` header then one 32-byte
#: ``Soundfilehead`` per channel. ``num_headers`` is a count minus one (0 mono,
#: 1 stereo); the stereo bit is bit 0 of the byte at ``KSAMPLE_FLAGS``, and a
#: header count above one *without* that bit is a group of mono samples at
#: different root keys, not a stereo pair.
KSAMPLE_NUM_HEADERS = 2  # u16, channel count minus one
KSAMPLE_FLAGS = 6  # u8, bit 0 = stereo
KSAMPLE_HEADERS = 12  # first Soundfilehead, relative to the body
SFH_LEN = 32
STEREO_FLAG = 0x01

#: ``Soundfilehead`` fields, as byte offsets into a 32-byte header. Frame
#: addresses index the pool in 16-bit words. The rate is stored as a nanosecond
#: period, not a frequency; ``sample/kurzweil.py`` turns it back into Hz.
SFH_ROOT_KEY = 0  # u8, MIDI note the sample plays at
SFH_FLAGS = 1  # u8: 0x40 loads the sample, 0x80 CLEAR means it loops
SFH_START = 8  # i32, first PCM word (absolute pool frame)
SFH_LOOP_START = 16  # i32, loop start frame
SFH_LOOP_END = 20  # i32, loop end frame (NOT the PCM end -- see _bank_samples)
SFH_PERIOD = 28  # u32, sample period in nanoseconds = round(1e9 / rate)
SFH_HAS_DATA = 0x40  # flag bit: the header carries loaded PCM
SFH_ONE_SHOT = 0x80  # flag bit: SET means one-shot, CLEAR means looped

#: The rate is a nanosecond period, and ``1e9 / period`` does not invert back to
#: a round number -- a 44 100 Hz sample reads as 44 101. Snap to the nearest of
#: these within a couple of Hz, the values a Kurzweil records at; a genuinely
#: odd rate that matches none is kept as read. Matches ConvertWithMoss.
STANDARD_RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 96000)
RATE_SNAP_HZ = 2

#: The byte that precedes the ``L``/``R`` side in a stereo half's name. Some
#: stereo samples are one object with two channels (handled here); others are a
#: pair of mono objects named ``...\x7fL`` / ``...\x7fR``, which the stereo
#: joiner pairs on exactly this character (ADR-0017), so it is kept in the name
#: the backend reports and ``safe_name`` sanitises it out of the final filename.
STEREO_MARKER = 0x7F

#: How large a prefix of a bank to read to *enumerate* its samples. The object
#: directory sits at the front and is a few tens of KB even on the busiest bank;
#: the megabytes of PCM after it are read only when a sample is extracted, never
#: to list one. The bank's header names the directory's exact end, so a rare
#: directory larger than this is still read in full rather than truncated.
DIR_SCAN_BYTES = 512 * 1024


@dataclass(frozen=True)
class _BankSample:
    """One extractable sample located inside a ``.KRZ`` bank.

    A mono sample is one channel; a stereo sample is one object carrying two
    planar channels, ``channel_bytes`` each, which the sample layer interleaves.
    ``data_off`` is a byte offset into the bank's own stream (the shared PCM
    pool), not the disc. ``root`` is the MIDI note the sample plays at, and
    ``loop`` is sample-relative with an inclusive-ish end, or ``None`` for a
    one-shot.
    """

    name: str
    rate: int
    root: int
    channels: int
    data_off: int
    data_off_right: int
    channel_bytes: int
    loop: tuple[int, int] | None


def _object_name(raw: bytes) -> str:
    """A sample object's name, to its first NUL and capped at 16, latin-1.

    The cap is load-bearing: a name that fills the 16-byte field exactly has no
    terminator, and reading to the (padded, rounded) body offset would return
    trailing block bytes as name characters. The ``0x7f`` that precedes an
    ``L``/``R`` side on a stereo half is inside the name and kept; trailing
    padding is trimmed, but a space run before a stereo marker is left for the
    joiner's own whitespace handling.
    """
    return raw.split(b"\x00", 1)[0][:OBJ_NAME_MAX].decode("latin1", "replace").rstrip()


def _headers(bank: bytes, body: int, count: int) -> list[dict[str, int]]:
    """The ``Soundfilehead`` records of one sample object."""
    out = []
    for i in range(count):
        ho = body + KSAMPLE_HEADERS + i * SFH_LEN
        if ho + SFH_LEN > len(bank):
            break
        flags = bank[ho + SFH_FLAGS]
        start, _alt, loop_s, loop_e = struct.unpack_from(">4i", bank, ho + SFH_START)
        period = struct.unpack_from(">I", bank, ho + SFH_PERIOD)[0]
        out.append(
            {
                "root": bank[ho + SFH_ROOT_KEY],
                "start": start,
                "loop_start": loop_s,
                "loop_end": loop_e,
                "period": period,
                "has_data": flags & SFH_HAS_DATA,
                "looped": not flags & SFH_ONE_SHOT,
            }
        )
    return out


def _bank_samples(bank: bytes, full_size: int) -> list[_BankSample]:
    """Every extractable sample in a ``.KRZ`` bank, in directory order.

    ``bank`` need only reach the end of the object directory; ``full_size`` is
    the bank's whole length (from its directory entry), which fixes the pool's
    frame count without reading the pool. A sample object carries one or more
    channel headers: the stereo bit makes two of them one stereo sample, and any
    other header with loaded audio is its own mono sample (a group of mono
    samples at different root keys shares one object). A header's stored end is
    its *loop* end, not the audio end, so the true extent runs to the next
    sample's start in the pool -- which also keeps a post-loop decay tail. A
    header with no loaded audio (an empty ``NewSample`` slot) is skipped.
    """
    if len(bank) < KRZ_HEADER_LEN or bank[:4] != KRZ_SIGNATURE:
        return []
    pool_start = struct.unpack_from(">i", bank, OFF_POOL_START)[0]
    pool_frames = (full_size - pool_start) // 2
    if pool_start <= 0 or pool_frames <= 0:
        return []
    limit = len(bank)
    off = OBJ_DIR_START
    objects: list[tuple[str, int, list[dict[str, int]]]] = []
    starts: set[int] = set()
    while off + OBJ_HDR_MIN <= limit:
        length = -struct.unpack_from(">i", bank, off)[0]
        if length <= 0 or off + length > limit:
            break  # the end marker (or an overrun): the directory is done
        hash_ = struct.unpack_from(">H", bank, off + OBJ_HASH)[0]
        if hash_ >> OBJ_TYPE_SHIFT == OBJ_TYPE_SAMPLE:
            ofs = struct.unpack_from(">H", bank, off + OBJ_OFS)[0]
            body = off + OBJ_BODY_BASE + ofs
            if body + KSAMPLE_HEADERS <= off + length:
                num = struct.unpack_from(">h", bank, body + KSAMPLE_NUM_HEADERS)[0]
                stereo = bank[body + KSAMPLE_FLAGS] & STEREO_FLAG
                headers = _headers(bank, body, num + 1)
                name = _object_name(bank[off + OBJ_NAME : body])
                objects.append((name, stereo, headers))
                starts.update(h["start"] for h in headers if h["has_data"])
        off += length
    # A header's true PCM end is the next loaded sample's start anywhere in the
    # pool (the stored end is only the loop end), capped at the pool itself.
    ordered = [*sorted(starts), pool_frames]

    def next_start(after: int) -> int:
        for value in ordered:
            if value > after:
                return value
        return pool_frames

    out: list[_BankSample] = []
    for name, stereo, headers in objects:
        loaded = [h for h in headers if h["has_data"]]
        if stereo and len(loaded) >= 2:
            out.append(
                _stereo_sample(name, loaded[0], loaded[1], pool_start, pool_frames, next_start)
            )
            continue
        for index, header in enumerate(loaded):
            part = f"{name} {index + 1}" if len(loaded) > 1 else name
            out.append(_mono_sample(part, header, pool_start, pool_frames, next_start))
    return [s for s in out if s is not None]


def _snap_rate(hz: float) -> int:
    for standard in STANDARD_RATES:
        if abs(hz - standard) <= RATE_SNAP_HZ:
            return standard
    return round(hz)


def _rate_and_loop(header: dict[str, int], start: int) -> tuple[int, tuple[int, int] | None]:
    rate = _snap_rate(1_000_000_000 / header["period"]) if header["period"] else 0
    loop = None
    if header["looped"]:
        loop = (header["loop_start"] - start, header["loop_end"] - start)
    return rate, loop


def _mono_sample(name, header, pool_start, pool_frames, next_start) -> _BankSample | None:
    start = header["start"]
    end = min(next_start(start), pool_frames)
    if not 0 <= start < end:
        return None
    rate, loop = _rate_and_loop(header, start)
    return _BankSample(
        name=name,
        rate=rate,
        root=header["root"],
        channels=1,
        data_off=pool_start + start * 2,
        data_off_right=0,
        channel_bytes=(end - start) * 2,
        loop=loop,
    )


def _stereo_sample(name, left, right, pool_start, pool_frames, next_start) -> _BankSample | None:
    ls, rs = left["start"], right["start"]
    left_len = min(next_start(ls), pool_frames) - ls
    right_len = min(next_start(rs), pool_frames) - rs
    channel = min(left_len, right_len)  # planar channels are equal; be defensive
    if channel <= 0:
        return None
    rate, loop = _rate_and_loop(left, ls)
    return _BankSample(
        name=name,
        rate=rate,
        root=left["root"],
        channels=2,
        data_off=pool_start + ls * 2,
        data_off_right=pool_start + rs * 2,
        channel_bytes=channel * 2,
        loop=loop,
    )


@dataclass(frozen=True)
class _Geometry:
    """The FAT layout derived from one boot sector, all in cooked bytes.

    Sector numbers are *logical* (512-byte) sectors; ``at`` turns a logical
    sector into a cooked-stream byte offset relative to the filesystem origin.
    """

    bytes_per_sec: int
    sec_per_clus: int
    num_fats: int
    root_entries: int
    fat_sectors: int
    total_sectors: int
    first_fat_sector: int
    first_root_sector: int
    root_sectors: int
    first_data_sector: int
    cluster_count: int

    @property
    def cluster_bytes(self) -> int:
        return self.sec_per_clus * self.bytes_per_sec

    @property
    def max_cluster(self) -> int:
        """Highest cluster number the data region can hold (2..this)."""
        return FIRST_DATA_CLUSTER + self.cluster_count - 1

    @property
    def is_fat16(self) -> bool:
        return FAT12_MAX_CLUSTERS <= self.cluster_count < FAT16_MAX_CLUSTERS

    def sector_at(self, sector: int) -> int:
        return sector * self.bytes_per_sec

    def cluster_at(self, cluster: int) -> int:
        return self.sector_at(
            self.first_data_sector + (cluster - FIRST_DATA_CLUSTER) * self.sec_per_clus
        )


def _geometry(image: SectorImage, offset: int) -> _Geometry | None:
    """Parse and sanity-check the boot sector at ``offset``.

    Returns ``None`` on anything that is not a KMSI FAT16 boot sector, so both
    ``probe`` and the walk share one reading and cannot disagree about where a
    region sits.
    """
    boot = image.read(offset, BOOT_READ)
    if len(boot) < BOOT_READ:
        return None
    if boot[OFF_OEM : OFF_OEM + len(OEM_NAME)] != OEM_NAME:
        return None
    if boot[OFF_JMP] not in (0xE9, 0xEB):
        return None
    bytes_per_sec = struct.unpack_from("<H", boot, OFF_BYTES_PER_SEC)[0]
    sec_per_clus = boot[OFF_SEC_PER_CLUS]
    rsvd = struct.unpack_from("<H", boot, OFF_RSVD)[0]
    num_fats = boot[OFF_NUM_FATS]
    root_entries = struct.unpack_from("<H", boot, OFF_ROOT_ENT)[0]
    tot16 = struct.unpack_from("<H", boot, OFF_TOT16)[0]
    media = boot[OFF_MEDIA]
    fat_sectors = struct.unpack_from("<H", boot, OFF_FAT_SZ16)[0]
    tot32 = struct.unpack_from("<I", boot, OFF_TOT32)[0]

    # A KMSI volume is 512-byte-sectored, and the reader's cluster/sector
    # arithmetic below assumes it; the OEM name already made this specific, so
    # this is a guard against a truncated or overwritten header rather than a
    # discriminator.
    if bytes_per_sec != LOGICAL_SECTOR:
        return None
    if sec_per_clus == 0 or sec_per_clus & (sec_per_clus - 1):  # must be a power of two
        return None
    if num_fats not in (1, 2) or rsvd == 0 or root_entries == 0 or fat_sectors == 0:
        return None
    if media < 0xF0:
        return None
    total_sectors = tot32 or tot16
    root_sectors = (root_entries * ENTRY_LEN + bytes_per_sec - 1) // bytes_per_sec
    first_fat_sector = rsvd
    first_root_sector = rsvd + num_fats * fat_sectors
    first_data_sector = first_root_sector + root_sectors
    if total_sectors <= first_data_sector:
        return None
    cluster_count = (total_sectors - first_data_sector) // sec_per_clus
    geo = _Geometry(
        bytes_per_sec=bytes_per_sec,
        sec_per_clus=sec_per_clus,
        num_fats=num_fats,
        root_entries=root_entries,
        fat_sectors=fat_sectors,
        total_sectors=total_sectors,
        first_fat_sector=first_fat_sector,
        first_root_sector=first_root_sector,
        root_sectors=root_sectors,
        first_data_sector=first_data_sector,
        cluster_count=cluster_count,
    )
    return geo if geo.is_fat16 else None


def _decode_name(raw_name: bytes, raw_ext: bytes) -> str:
    """An 8.3 entry as ``NAME.EXT``, in the disc's own upper case.

    Names are code page 437; the printable range is what a listing shows, and
    the trailing space padding is what a real 8.3 field carries. 0x05 as the
    first byte is DOS's escape for a leading 0xE5 (a real KANJI first byte that
    would otherwise read as the free-slot marker); it is restored so such a name
    is not silently truncated.
    """
    name = bytearray(raw_name)
    if name[:1] == b"\x05":
        name[0] = FREE_ENTRY
    stem = bytes(name).decode("cp437").rstrip(" ")
    ext = raw_ext.decode("cp437").rstrip(" ")
    return f"{stem}.{ext}" if ext else stem


def _is_plausible_8_3(raw_name: bytes, raw_ext: bytes) -> bool:
    """No control bytes in the 8.3 field, and a non-empty stem.

    Cheap and only as strict as it must be: the free/end sentinels and the LFN
    attribute are handled by the caller, so this just rejects a slot that
    decodes to control characters -- the shape a run of zeros or of audio takes.
    """
    field = raw_name + raw_ext
    if all(b == 0 for b in field):
        return False
    if not any(b > 0x20 for b in raw_name):
        return False
    return all(b >= 0x20 for b in field)


def _live_entries(directory: bytes) -> Iterator[tuple[str, int, int, int]]:
    """Walk 32-byte entries, yielding ``(name, attr, first_cluster, size)``.

    Stops at the end-of-directory sentinel; skips free slots and VFAT long-name
    fragments. Does not filter by attribute beyond that -- the caller decides
    what a volume label or a subdirectory means.
    """
    for base in range(0, len(directory) - ENTRY_LEN + 1, ENTRY_LEN):
        entry = directory[base : base + ENTRY_LEN]
        first = entry[0]
        if first == END_OF_DIR:
            return
        if first == FREE_ENTRY:
            continue
        attr = entry[OFF_ENTRY_ATTR]
        if attr == ATTR_LFN:
            continue
        raw_name = entry[:NAME_LEN]
        raw_ext = entry[NAME_LEN : NAME_LEN + EXT_LEN]
        if not _is_plausible_8_3(raw_name, raw_ext):
            continue
        first_cluster = struct.unpack_from("<H", entry, OFF_ENTRY_FIRST_CLUS)[0]
        size = struct.unpack_from("<I", entry, OFF_ENTRY_SIZE)[0]
        yield _decode_name(raw_name, raw_ext), attr, first_cluster, size


class KurzweilBackend:
    name = "kurzweil"

    def __init__(self) -> None:
        #: The last bank read in full, keyed by ``(id(image), offset, cluster)``.
        #: A volume's samples are extracted back to back and all slice the same
        #: bank, so a one-slot cache turns the per-sample reads into one read of
        #: the bank rather than one of the whole disc per sample.
        self._bank_cache: tuple[tuple[int, int, int], bytes] | None = None

    def probe(self, image: SectorImage, offset: int) -> bool:
        """A ``KMSI`` FAT16 boot sector whose first real file leads with ``PRAM``.

        Two-stage per ADR-0005/0012. The OEM name is the specific half: it is an
        eight-byte string no non-Kurzweil FAT carries, so it will not match a
        run of zeros or of audio. But a magic plus a directory pointer is still
        only structure (ADR-0012 names exactly this), so the second half opens
        the root directory, finds the first real file, and confirms the bytes it
        points at begin with the ``.KRZ`` object tag -- the same thing the walk
        will read. A directory that merely decodes is not enough.
        """
        geo = _geometry(image, offset)
        if geo is None:
            return False
        root = image.read(
            offset + geo.sector_at(geo.first_root_sector), geo.root_entries * ENTRY_LEN
        )
        for _name, attr, first_cluster, size in _live_entries(root):
            if attr & (ATTR_VOLUME_ID | ATTR_DIRECTORY):
                continue
            if size == 0 or not FIRST_DATA_CLUSTER <= first_cluster <= geo.max_cluster:
                continue
            head = image.read(offset + geo.cluster_at(first_cluster), len(KRZ_SIGNATURE))
            return head == KRZ_SIGNATURE
        return False

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        """One volume per ``.KRZ`` bank, its samples the volume's files.

        FAT16 has no partitions, so the disc is a flat set of banks; each bank
        is a bundle of samples, which makes a bank the natural volume and its
        sample objects its files -- the same shape an E-mu bank takes
        (ADR-0032). A subdirectory is a cluster chain like any file and is
        walked in turn; neither reference disc has one, but a flat-root walk
        would silently drop it.
        """
        geo = _geometry(image, offset)
        if geo is None:
            return
        fat = self._read_fat(image, offset, geo)
        root = image.read(
            offset + geo.sector_at(geo.first_root_sector), geo.root_entries * ENTRY_LEN
        )
        any_bank = False
        for bank in self._walk(image, offset, geo, fat, root, "", set()):
            any_bank = True
            yield self._bank_volume(image, offset, geo, fat, bank)
        if not any_bank:
            # probe() confirmed a file, so an empty walk means the directory was
            # damaged after the first entry rather than genuinely empty -- say
            # so, never leave the disc looking simply blank (ADR-0012).
            volume = Volume(name="KMSI", start_block=geo.first_root_sector)
            volume.note = "KMSI root directory holds no readable .KRZ files"
            yield volume

    def _bank_volume(
        self,
        image: SectorImage,
        offset: int,
        geo: _Geometry,
        fat: bytes,
        bank: File,
    ) -> Volume:
        """One bank as a volume: its samples, then the whole ``.krz`` to keep.

        Only the front of the bank -- the object directory -- is read to
        enumerate; the pool is left on the disc until a sample is extracted. The
        whole bank is added as one ``program`` so ``--keep-originals`` writes the
        ``.krz`` out, while the WAV path, which acts on ``sample`` entries alone,
        passes it by. A bank whose objects are all programs and keymaps -- the
        1012-byte ``DRUM KIT`` is one -- yields no samples, and the note says so
        rather than leaving an empty-looking volume unexplained (ADR-0012).
        """
        volume = Volume(name=bank.name, start_block=bank.start_block)
        prefix = self._directory_prefix(image, offset, geo, fat, bank)
        files: list[File] = []
        for sample in _bank_samples(prefix, bank.size):
            files.append(
                File(
                    name=sample.name,
                    kind="sample",
                    size=sample.channel_bytes * sample.channels,
                    start_block=bank.start_block,
                    raw_type=sample.rate,
                    meta=(
                        ("data_off", sample.data_off),
                        ("data_off_right", sample.data_off_right),
                        ("channels", sample.channels),
                        ("channel_bytes", sample.channel_bytes),
                        ("root", sample.root),
                        ("has_loop", 1 if sample.loop else 0),
                        ("loop_start", sample.loop[0] if sample.loop else 0),
                        ("loop_end", sample.loop[1] if sample.loop else 0),
                        # An object inside a bank, not a file the disc placed:
                        # its bytes are a slice of the bank kept whole below, so
                        # --keep-originals writes the .krz, not each raw slice.
                        ("embedded", 1),
                    ),
                )
            )
        files.append(
            File(name=bank.name, kind="program", size=bank.size, start_block=bank.start_block)
        )
        volume.files = files
        if not any(f.kind == "sample" for f in files):
            volume.note = "the bank holds programs or keymaps and no samples; listed only"
        return volume

    def _directory_prefix(
        self, image: SectorImage, offset: int, geo: _Geometry, fat: bytes, bank: File
    ) -> bytes:
        """Enough of a bank to enumerate its samples -- the object directory.

        The header names where the pool begins, which is the directory's end, so
        a first bounded read almost always suffices; only a bank whose directory
        is somehow larger than the bound is read again, in full, rather than
        enumerated short.
        """
        prefix = self._read_chain(image, offset, geo, fat, bank.start_block, DIR_SCAN_BYTES)
        if len(prefix) >= KRZ_HEADER_LEN:
            pool_start = struct.unpack_from(">i", prefix, OFF_POOL_START)[0]
            if 0 < len(prefix) < pool_start <= bank.size:
                prefix = self._read_chain(image, offset, geo, fat, bank.start_block, pool_start)
        return prefix

    def _walk(
        self,
        image: SectorImage,
        offset: int,
        geo: _Geometry,
        fat: bytes,
        directory: bytes,
        prefix: str,
        seen_dirs: set[int],
    ) -> Iterator[File]:
        for name, attr, first_cluster, size in _live_entries(directory):
            if attr & ATTR_VOLUME_ID:
                continue
            if attr & ATTR_DIRECTORY:
                stem = name.split(".", 1)[0]
                if stem in (".", "..") or first_cluster < FIRST_DATA_CLUSTER:
                    continue
                if first_cluster in seen_dirs:  # a self-referential chain cannot loop the walk
                    continue
                seen_dirs.add(first_cluster)
                sub = self._read_chain(image, offset, geo, fat, first_cluster)
                yield from self._walk(image, offset, geo, fat, sub, f"{prefix}{name}/", seen_dirs)
                continue
            if not FIRST_DATA_CLUSTER <= first_cluster <= geo.max_cluster:
                continue
            yield File(name=f"{prefix}{name}", kind="bank", size=size, start_block=first_cluster)

    def _read_fat(self, image: SectorImage, offset: int, geo: _Geometry) -> bytes:
        return image.read(
            offset + geo.sector_at(geo.first_fat_sector), geo.fat_sectors * geo.bytes_per_sec
        )

    def _chain(self, fat: bytes, start: int, max_cluster: int) -> list[int]:
        """The cluster chain from ``start``, bounded three ways.

        By the FAT16 end-of-chain marker, by the table's own range, and by a
        visited set -- a corrupt table that pointed a cluster back into its own
        chain would otherwise spin. All observed files are fragmented, so the
        chain is followed and never assumed contiguous.
        """
        out: list[int] = []
        cluster = start
        seen: set[int] = set()
        while FIRST_DATA_CLUSTER <= cluster <= max_cluster and cluster not in seen:
            out.append(cluster)
            seen.add(cluster)
            if 2 * cluster + 2 > len(fat):
                break
            nxt = struct.unpack_from("<H", fat, 2 * cluster)[0]
            if nxt >= FAT16_EOC or not FIRST_DATA_CLUSTER <= nxt <= max_cluster:
                break
            cluster = nxt
        return out

    def _read_chain(
        self,
        image: SectorImage,
        offset: int,
        geo: _Geometry,
        fat: bytes,
        start: int,
        max_bytes: int | None = None,
    ) -> bytes:
        """The chain's clusters, coalescing a contiguous run into one read.

        ``max_bytes`` stops the walk once that many bytes are in hand -- used to
        read a bank's front matter without pulling its whole PCM pool off the
        disc. It bounds the pending run too, so a contiguous bank is not read
        whole just because its clusters never break into a second run.
        """
        out = bytearray()
        run_start = run_len = 0
        for cluster in self._chain(fat, start, geo.max_cluster):
            if run_len and cluster == run_start + run_len:
                run_len += 1
            else:
                if run_len:
                    out += image.read(
                        offset + geo.cluster_at(run_start), run_len * geo.cluster_bytes
                    )
                run_start, run_len = cluster, 1
            if max_bytes is not None and len(out) + run_len * geo.cluster_bytes >= max_bytes:
                break
        if run_len:
            out += image.read(offset + geo.cluster_at(run_start), run_len * geo.cluster_bytes)
        return bytes(out) if max_bytes is None else bytes(out[:max_bytes])

    def _bank_bytes(
        self, image: SectorImage, offset: int, geo: _Geometry, fat: bytes, cluster: int
    ) -> bytes:
        """The whole bank at ``cluster``, from a one-slot cache where it can be."""
        key = (id(image), offset, cluster)
        cached = self._bank_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        bank = self._read_chain(image, offset, geo, fat, cluster)
        self._bank_cache = (key, bank)
        return bank

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        """The bytes of one entry: a bank's whole ``.krz``, or a sample's slice.

        A ``program`` entry is the whole bank, gathered along its FAT chain and
        truncated to its size. A ``sample`` entry is an object inside a bank, so
        its bytes are a window into the bank's shared PCM pool -- the bank is
        read (once, cached) and sliced. A short read is a damaged disc, not an
        error: the caller gets what the disc still holds.
        """
        geo = _geometry(image, offset)
        if geo is None:
            return b""
        fat = self._read_fat(image, offset, geo)
        if entry.get("embedded"):
            bank = self._bank_bytes(image, offset, geo, fat, entry.start_block)
            data_off = entry.get("data_off")
            channel = entry.get("channel_bytes")
            if entry.get("channels") == 2:
                # Stereo is planar: the whole left channel, then the whole
                # right, each addressed separately. Hand the sample layer the
                # two channels back to back for it to interleave.
                right = entry.get("data_off_right")
                return bank[data_off : data_off + channel] + bank[right : right + channel]
            return bank[data_off : data_off + channel]
        return self._read_chain(image, offset, geo, fat, entry.start_block)[: entry.size]

    def layout(self, image: SectorImage, offset: int) -> str:
        geo = _geometry(image, offset)
        if geo is None:
            return ""
        return (
            f"FAT16 (KMSI/Kurzweil), {geo.cluster_bytes // 1024} KB clusters, "
            f"{geo.cluster_count} clusters"
        )

    def original_suffix(self, entry: File) -> str:
        """The file's own extension -- ``.krz`` on both discs.

        Like ISO 9660 and unlike a sampler's own filesystem, this one has real
        filenames that already carry the suffix, so it is taken from the name
        rather than inferred from a type byte.
        """
        _, suffix = os.path.splitext(entry.name)
        return suffix.lower() or DEFAULT_ORIGINAL_SUFFIX

    def parse_sample(self, entry: File, payload: bytes):
        """Carry one sample object's pool slice to WAV-ready PCM.

        The rate and loop the object declared were read from the bank directory
        and travel on ``entry``; ``payload`` is the big-endian pool slice
        ``read_file`` returned. The sample layer reverses each value's bytes to
        little-endian and applies the loop (ADR-0011, ADR-0024). Passing them
        here rather than sniffing the payload keeps ``sample/`` free of any
        Kurzweil bookkeeping (ADR-0003).
        """
        from samplerdisc.sample import kurzweil

        loop = (entry.get("loop_start"), entry.get("loop_end")) if entry.get("has_loop") else None
        return kurzweil.parse(
            payload,
            rate=entry.raw_type,
            name=entry.name,
            loop=loop,
            root=entry.get("root"),
            channels=entry.get("channels") or 1,
            channel_bytes=entry.get("channel_bytes"),
        )


register(KurzweilBackend())
