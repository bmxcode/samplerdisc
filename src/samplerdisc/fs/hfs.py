"""HFS behind an Apple Partition Map, for Digidesign SampleCell libraries.

A SampleCell disc is not a sampler-format disc at all. The card was a Mac
NuBus/PCI sampler, so its libraries shipped as ordinary Macintosh media:
magneto-optical cartridges carrying an Apple Partition Map, an ``Apple_HFS``
partition, and inside it a standard HFS volume. The audio is plain **AIFF**.

So this backend is the same shape as ``fs/iso9660.py`` -- a general-purpose
filesystem whose payload the tool already converts -- and it earns its place
the same way (ADR-0009, and the argument in ``fs/iso9660.py``'s docstring):
these discs still arrive wrapped in a ``.nrg`` or a raw ``.bin`` that nothing
else opens, so reading them costs one module and saves a second tool. What
tips it from "document it" to "build it" is that the byte oracle is free -- the
host's own ``hdiutil`` reads the same image, so the walk is verifiable to the
bar EBL and KRZ are held to (ADR-0039).

Nothing is added at the sample layer: an AIFF entry rides the existing
``extract`` path (``entry.kind == "aiff"``), dedup and all. See
docs/formats/hfs.md; the numbers here are verified against ``Sonic Images V1``
and ``V2``.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, NamedTuple

from samplerdisc.fs.base import DEFAULT_ORIGINAL_SUFFIX, File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

#: The Apple Driver Descriptor Record at block 0, and the map entries at block 1
#: on. Both are keyed by a two-byte signature; neither is ours.
DDR_SIG = b"ER"
APM_SIG = b"PM"
#: Apple always numbers these structures in 512-byte blocks, whatever the
#: container's cooked sector size is.
APPLE_BLOCK = 512
#: The partition map begins at block 1, directly behind the block-0 DDR.
APM_SIG_BLOCK = 1
#: The partition type we want. The map also carries the map's own entry, the
#: disk driver (``Silverlining`` on these discs) and free space, none of which
#: hold a filesystem.
APPLE_HFS = b"Apple_HFS"

#: HFS Master Directory Block: two 512-byte blocks into the volume, signature
#: ``0x4244`` (``'BD'``). (An HFS+ volume would read ``H+``; these are plain
#: HFS, and the boundary is noted in the format doc rather than guessed at.)
MDB_OFFSET = 2 * APPLE_BLOCK
HFS_SIG = 0x4244

#: Catalog record types, and the B-tree node type for a leaf.
REC_FOLDER = 0x01
REC_FILE = 0x02
REC_FOLDER_THREAD = 0x03
NODE_LEAF = 0xFF

#: The root directory is always CNID 2.
ROOT_CNID = 2
#: Data fork, in the extents-overflow B-tree key. (Resource forks are 0xFF and
#: deliberately not read -- see ``_classify``.)
FORK_DATA = 0x00

#: Guard rails: these are rips, and a corrupt ``fLink`` must not loop forever
#: and a fork's extent list must not grow without bound (ADR: degrade, never
#: crash).
_MAX_NODES = 1 << 16
_MAX_EXTENTS = 64


class _Extent(NamedTuple):
    start: int  # allocation block
    count: int  # allocation blocks


class _Volume(NamedTuple):
    """The MDB fields the walk needs, resolved against one HFS partition."""

    name: str
    part_start: int  # 512-byte blocks from the backend origin
    al_blk_start: int  # drAlBlSt, in 512-byte blocks
    al_blk_size: int  # drAlBlkSiz, in bytes
    catalog_size: int
    catalog_extents: list[_Extent]
    extents_size: int
    extents_extents: list[_Extent]


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _extent_rec(data: bytes, off: int) -> list[_Extent]:
    """One HFS extent record: three (startBlock, blockCount) pairs."""
    return [_Extent(_u16(data, off + i * 4), _u16(data, off + i * 4 + 2)) for i in range(3)]


def _mac_roman(raw: bytes) -> str:
    """A catalog name. HFS names are Mac OS Roman, not ASCII or UTF-8."""
    return raw.decode("mac_roman", "replace")


class HfsBackend:
    name = "hfs"

    # -- origin probe -----------------------------------------------------

    def probe(self, image: SectorImage, offset: int) -> bool:
        """The Driver Descriptor Record, then a partition map behind it.

        Cheap: two short reads. Specific: ``'ER'`` at byte 0 is only two bytes,
        so on its own it would match a run of audio -- but ``'ER'`` *and* a
        512-byte block size *and* a ``'PM'`` partition map with a sane entry
        count directly behind it is a signature nothing but an Apple disk
        carries. The Apple_HFS scan is left to ``volumes`` so the probe stays
        two reads at every candidate offset (ADR-0005).
        """
        ddr = image.read(offset, 6)
        if len(ddr) < 6 or ddr[0:2] != DDR_SIG or _u16(ddr, 2) != APPLE_BLOCK:
            return False
        entry = image.read(offset + APPLE_BLOCK, 8)
        if len(entry) < 8 or entry[0:2] != APM_SIG:
            return False
        map_blocks = _u32(entry, 4)
        return 1 <= map_blocks <= 256

    # -- filesystem walk --------------------------------------------------

    def _hfs_partitions(self, image: SectorImage, offset: int) -> Iterator[int]:
        """Every ``Apple_HFS`` partition start, in 512-byte blocks.

        The map's own first entry declares how many entries there are; each is a
        512-byte block. SampleCell Vol. 1 carries four (map, driver, HFS, free),
        Vol. 2 one -- the map is *read*, never assumed, so both are the same code.
        """
        first = image.read(offset + APM_SIG_BLOCK * APPLE_BLOCK, APPLE_BLOCK)
        if len(first) < 84 or first[0:2] != APM_SIG:
            return
        count = _u32(first, 4)
        for index in range(min(count, 256)):
            entry = image.read(offset + (APM_SIG_BLOCK + index) * APPLE_BLOCK, APPLE_BLOCK)
            if len(entry) < 84 or entry[0:2] != APM_SIG:
                return
            if entry[48:80].split(b"\x00", 1)[0] == APPLE_HFS:
                yield _u32(entry, 8)

    def _read_mdb(self, image: SectorImage, offset: int, part_start: int) -> _Volume | None:
        base = offset + part_start * APPLE_BLOCK
        mdb = image.read(base + MDB_OFFSET, APPLE_BLOCK)
        if len(mdb) < 162 or _u16(mdb, 0) != HFS_SIG:
            return None
        name_len = min(mdb[36], 27)
        return _Volume(
            name=_mac_roman(mdb[37 : 37 + name_len]).strip(),
            part_start=part_start,
            al_blk_start=_u16(mdb, 28),
            al_blk_size=_u32(mdb, 20),
            extents_size=_u32(mdb, 130),
            extents_extents=_extent_rec(mdb, 134),
            catalog_size=_u32(mdb, 146),
            catalog_extents=_extent_rec(mdb, 150),
        )

    def _fork_offset(self, offset: int, vol: _Volume, block: int) -> int:
        """Absolute byte offset of one allocation block of this volume."""
        return offset + (vol.part_start + vol.al_blk_start) * APPLE_BLOCK + block * vol.al_blk_size

    def _read_fork(
        self, image: SectorImage, offset: int, vol: _Volume, extents: list[_Extent], size: int
    ) -> bytes:
        buf = bytearray()
        for start, count in extents:
            if count == 0:
                continue
            buf += image.read(self._fork_offset(offset, vol, start), count * vol.al_blk_size)
            if size and len(buf) >= size:
                break
        return bytes(buf[:size]) if size else bytes(buf)

    def _extents_overflow(
        self, image: SectorImage, offset: int, vol: _Volume
    ) -> dict[tuple[int, int, int], list[_Extent]]:
        """The extents-overflow B-tree, as ``(fork, cnid, startABN) -> extents``.

        A fork longer than the three extents its catalog record holds is
        continued here. On these once-written cartridges files are contiguous
        and this is almost always empty, but reading it is what keeps a
        fragmented file from being silently truncated.
        """
        if not vol.extents_size:
            return {}
        data = self._read_fork(image, offset, vol, vol.extents_extents, vol.extents_size)
        overflow: dict[tuple[int, int, int], list[_Extent]] = {}
        for rec in _btree_leaf_records(data):
            if rec[0] < 7:  # key length: fork(1) cnid(4) startABN(2)
                continue
            fork = rec[1]
            cnid = _u32(rec, 2)
            start_abn = _u16(rec, 6)
            body = 1 + rec[0]
            body += body % 2
            if len(rec) >= body + 12:
                overflow[(fork, cnid, start_abn)] = _extent_rec(rec, body)
        return overflow

    def _full_extents(
        self,
        first: list[_Extent],
        size_blocks: int,
        overflow: dict[tuple[int, int, int], list[_Extent]],
        cnid: int,
        fork: int = FORK_DATA,
    ) -> list[_Extent]:
        """First three extents, continued through the overflow tree if needed."""
        extents = [e for e in first if e.count]
        covered = sum(e.count for e in extents)
        while covered < size_blocks and len(extents) < _MAX_EXTENTS:
            more = overflow.get((fork, cnid, covered))
            if not more:
                break
            for e in more:
                if e.count:
                    extents.append(e)
                    covered += e.count
        return extents

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        for part_start in self._hfs_partitions(image, offset):
            vol = self._read_mdb(image, offset, part_start)
            if vol is None:
                continue
            yield self._walk(image, offset, vol)

    def _walk(self, image: SectorImage, offset: int, vol: _Volume) -> Volume:
        overflow = self._extents_overflow(image, offset, vol)
        blk = vol.al_blk_size or 1
        catalog_blocks = (vol.catalog_size + blk - 1) // blk
        catalog_extents = self._full_extents(vol.catalog_extents, catalog_blocks, overflow, cnid=4)
        catalog = self._read_fork(image, offset, vol, catalog_extents, vol.catalog_size)

        folders: dict[int, tuple[int, str]] = {}
        files: list[tuple[int, str, int, list[_Extent], int, bytes]] = []
        for rec in _btree_leaf_records(catalog):
            key_len = rec[0]
            if key_len < 6:
                continue
            parent = _u32(rec, 2)
            name_len = min(rec[6], 31)
            name = _mac_roman(rec[7 : 7 + name_len])
            body = 1 + key_len
            body += body % 2
            data = rec[body:]
            if not data:
                continue
            kind = data[0]
            if kind == REC_FOLDER and len(data) >= 10:
                folders[_u32(data, 6)] = (parent, name)
            elif kind == REC_FILE and len(data) >= 86:
                ostype = data[4:8]
                cnid = _u32(data, 20)
                logical = _u32(data, 26)
                first = _extent_rec(data, 74)
                size_blocks = (logical + blk - 1) // blk
                extents = self._full_extents(first, size_blocks, overflow, cnid)
                files.append((parent, name, logical, extents, cnid, ostype))

        entries: list[File] = []
        for parent, name, logical, extents, _cnid, ostype in files:
            full = _path(folders, parent, name)
            entries.append(
                File(
                    name=full,
                    kind=_classify(name, ostype),
                    size=logical,
                    start_block=extents[0].start if extents else 0,
                    raw_type=int.from_bytes(ostype, "big"),
                    meta=_pack_extents(vol, extents),
                )
            )

        note = "" if entries else "no files in the HFS catalog"
        volume = Volume(name=vol.name or "HFS", start_block=vol.part_start, note=note)
        volume.files = entries
        return volume

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        al_blk_size = entry.get("albksz")
        fork_base = entry.get("forkbase")
        buf = bytearray()
        index = 0
        while True:
            count = entry.get(f"x{index}c")
            if count <= 0:
                break
            start = entry.get(f"x{index}s")
            buf += image.read(offset + fork_base + start * al_blk_size, count * al_blk_size)
            index += 1
        return bytes(buf[: entry.size])

    def original_suffix(self, entry: File) -> str:
        """A suffix for a kept SampleCell instrument file.

        HFS names carry no extension, so the file's four-character Finder type
        is the only thing that names the original faithfully: an ``SCin`` kept
        as ``.bin`` is unopenable and unidentifiable. Where the type is not
        printable, the default applies.
        """
        if entry.raw_type:
            ostype = entry.raw_type.to_bytes(4, "big").rstrip(b"\x00 ")
            text = ostype.decode("ascii", "ignore")
            if text.isalnum():
                return "." + text.lower()
        return DEFAULT_ORIGINAL_SUFFIX


def _pack_extents(vol: _Volume, extents: list[_Extent]) -> tuple[tuple[str, int], ...]:
    """Carry a fork's byte layout on the frozen ``File``.

    ``read_file`` gets only the ``File`` and the backend origin, so everything
    it needs to resolve allocation blocks to bytes rides in ``meta``: the fork
    base (relative to origin) and block size, then the extent list as numbered
    pairs. A zero ``count`` terminates the list, and an allocation block of 0 is
    valid, which is why the terminator is the count and not the start.
    """
    fork_base = (vol.part_start + vol.al_blk_start) * APPLE_BLOCK
    meta: list[tuple[str, int]] = [("forkbase", fork_base), ("albksz", vol.al_blk_size)]
    for index, extent in enumerate(extents):
        meta.append((f"x{index}s", extent.start))
        meta.append((f"x{index}c", extent.count))
    return tuple(meta)


def _path(folders: dict[int, tuple[int, str]], parent: int, name: str) -> str:
    """A file's path from the volume root, over the folder chain.

    Bounded by the folder count so a cycle in a damaged catalog cannot loop.
    """
    parts = [name]
    seen = 0
    while parent != ROOT_CNID and parent in folders and seen <= len(folders):
        parent, folder_name = folders[parent]
        parts.append(folder_name)
        seen += 1
    return "/".join(reversed(parts))


#: SampleCell's own instrument and setup documents: an instrument (``SCin``), a
#: setup (``SCsi``) and a mix document (``MixD``). They are to a SampleCell disc
#: what a program is to an AKAI one -- the key ranges and zone maps a WAV cannot
#: carry -- so they are kept under the same "program" vocabulary --keep-originals
#: understands, and left to ConvertWithMoss (ADR-0011).
_PROGRAM_TYPES = (b"SCin", b"SCsi", b"MixD")


def _classify(name: str, ostype: bytes) -> str:
    lower = name.lower()
    if lower.endswith((".aif", ".aiff")) or ostype == b"AIFF":
        return "aiff"
    if lower.endswith(".wav") or ostype == b"WAVE":
        return "wav"
    if ostype == b"Sd2f":
        # Sound Designer II keeps its audio in the HFS *resource* fork, with the
        # sample rate and width in a resource beside it -- a different and harder
        # format than the flat-PCM AIFF this backend reads. Listed, not read.
        return "sd2"
    if ostype in _PROGRAM_TYPES or lower.endswith(".exb"):
        return "program"
    return "file"


def _btree_leaf_records(tree: bytes) -> Iterator[bytes]:
    """Every leaf record of an HFS B*-tree, in key order.

    The header node (node 0) names the node size and the first leaf; leaves are
    then chained forward by ``ndFLink``. Records inside a node are found through
    the offset table at the node's tail -- a two-byte offset per record, stored
    in reverse. This is the one traversal the catalog and the extents-overflow
    tree share.
    """
    if len(tree) < APPLE_BLOCK:
        return
    node_size = _u16(tree, 14 + 18) or APPLE_BLOCK
    first_leaf = _u32(tree, 14 + 10)
    node_index = first_leaf
    visited = 0
    while node_index and visited < _MAX_NODES:
        start = node_index * node_size
        node = tree[start : start + node_size]
        if len(node) < node_size:
            return
        node_type = node[8]
        num_recs = _u16(node, 10)
        if node_type == NODE_LEAF:
            for r in range(num_recs):
                off = _u16(node, node_size - 2 * (r + 1))
                end = _u16(node, node_size - 2 * (r + 2))
                if 0 < off < end <= node_size:
                    yield node[off:end]
        node_index = _u32(node, 0)  # ndFLink
        visited += 1


register(HfsBackend())
