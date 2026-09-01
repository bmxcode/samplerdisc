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

Every file on the two reference discs is a ``.KRZ`` object bank, and this
backend lists those files -- it does not open them. A ``.KRZ`` is a bundle of
Kurzweil objects (programs, keymaps and samples) with its own big-endian
object format, which is a separate deliverable; each file begins with the
four-byte tag ``PRAM`` and that is what the probe confirms a real file by
(ADR-0012, ADR-0035). Turning a ``.KRZ`` bank into WAV is deferred (#60).

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
#: plausible directory pointer (ADR-0012). The bank's interior is a separate
#: format (#60).
KRZ_SIGNATURE = b"PRAM"


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
        """One volume -- FAT16 has no partitions -- holding every ``.KRZ`` file.

        The root directory is a fixed region; a subdirectory is a cluster chain
        like any file, so it is followed and walked in turn. Neither reference
        disc has a subdirectory, but the format allows one and a walk that
        assumed a flat root would silently drop it.
        """
        geo = _geometry(image, offset)
        if geo is None:
            return
        fat = self._read_fat(image, offset, geo)
        root = image.read(
            offset + geo.sector_at(geo.first_root_sector), geo.root_entries * ENTRY_LEN
        )
        volume = Volume(
            name=self._volume_name(image, offset, geo, root), start_block=geo.first_root_sector
        )
        volume.files = list(self._walk(image, offset, geo, fat, root, "", set()))
        if not volume.files:
            # probe() confirmed a file, so an empty walk means the directory was
            # damaged after the first entry rather than genuinely empty -- say
            # so, never leave an unexplained empty volume (ADR-0012).
            volume.note = "KMSI root directory holds no readable .KRZ files"
        yield volume

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

    def _volume_name(self, image: SectorImage, offset: int, geo: _Geometry, root: bytes) -> str:
        """The volume label if the disc set one, else a constant.

        FAT keeps the label in two places -- a root-directory entry with the
        volume-id attribute, and the boot sector's extended field -- and both
        are blank on the reference discs. The directory entry wins where they
        differ, because it is the one a machine actually rewrites.
        """
        for name, attr, _first, _size in _live_entries(root):
            if attr & ATTR_VOLUME_ID and not attr & ATTR_DIRECTORY:
                label = name.replace(".", "").strip("\x00 ")
                if label:
                    return label
        boot = image.read(offset, BOOT_READ)
        if boot[OFF_EXT_BOOT_SIG] == 0x29:
            label = (
                boot[OFF_VOL_LABEL : OFF_VOL_LABEL + VOL_LABEL_LEN].decode("cp437").strip("\x00 ")
            )
            if label:
                return label
        return "KMSI"

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
        self, image: SectorImage, offset: int, geo: _Geometry, fat: bytes, start: int
    ) -> bytes:
        """Every cluster of a chain, coalescing a contiguous run into one read."""
        out = bytearray()
        run_start = run_len = 0
        for cluster in self._chain(fat, start, geo.max_cluster):
            if run_len and cluster == run_start + run_len:
                run_len += 1
                continue
            if run_len:
                out += image.read(offset + geo.cluster_at(run_start), run_len * geo.cluster_bytes)
            run_start, run_len = cluster, 1
        if run_len:
            out += image.read(offset + geo.cluster_at(run_start), run_len * geo.cluster_bytes)
        return bytes(out)

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        """Gather a file's clusters along the FAT chain, truncated to its size.

        A short read is a damaged disc, not an error: the caller gets what the
        disc still holds (per the container's own read contract).
        """
        geo = _geometry(image, offset)
        if geo is None:
            return b""
        fat = self._read_fat(image, offset, geo)
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
        """Not yet: a ``.KRZ`` is an object bank, not a bare sample.

        The audio lives inside the bank's own big-endian object format, which
        is a separate deliverable (#60). Raising here rather than falling back
        to the AKAI parser is what makes ``extract`` skip a ``.KRZ`` cleanly
        with a reason instead of mis-reading a bank as an AKAI sample.
        """
        from samplerdisc.sample import NotASample

        raise NotASample(f"{entry.name}: Kurzweil .KRZ bank parsing is not implemented yet (#60)")


register(KurzweilBackend())
