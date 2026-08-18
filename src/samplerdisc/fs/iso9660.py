"""ISO 9660, for sample CDs whose payload is already WAV or AIFF.

A meaningful share of these collections are not sampler-format discs at all:
libraries converted to Kontakt or plain audio and burned back to an image. They
mount on a modern machine, but they still arrive wrapped in a .nrg or a
compressed .mdx that nothing else opens -- so reading them here costs little
and saves the user a second tool.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.fs.base import File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

MAGIC = b"CD001"

#: The volume descriptors start after a 16-sector system area.
PVD_SECTOR = 16
PVD_MAGIC_OFFSET = 1
TYPE_PRIMARY = 1
TYPE_TERMINATOR = 255

#: Directory record flag bit 1 marks a subdirectory.
FLAG_DIRECTORY = 0x02

_MAX_DESCRIPTORS = 16
_MAX_DEPTH = 8


def _both_endian32(data: bytes, offset: int) -> int:
    """ISO 9660 stores 32-bit values twice; the little-endian half is first."""
    return struct.unpack_from("<I", data, offset)[0]


class Iso9660Backend:
    name = "iso9660"

    def probe(self, image: SectorImage, offset: int) -> bool:
        """A primary volume descriptor sits 16 sectors into the filesystem."""
        sector = image.read(offset + PVD_SECTOR * SECTOR_SIZE, 8)
        return (
            len(sector) >= 6
            and sector[PVD_MAGIC_OFFSET : PVD_MAGIC_OFFSET + 5] == MAGIC
            and sector[0] in (TYPE_PRIMARY, 0, 2)
        )

    def _primary(self, image: SectorImage, offset: int) -> bytes | None:
        for index in range(_MAX_DESCRIPTORS):
            sector = image.read(offset + (PVD_SECTOR + index) * SECTOR_SIZE, SECTOR_SIZE)
            if len(sector) < SECTOR_SIZE or sector[1:6] != MAGIC:
                return None
            if sector[0] == TYPE_PRIMARY:
                return sector
            if sector[0] == TYPE_TERMINATOR:
                return None
        return None

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        pvd = self._primary(image, offset)
        if pvd is None:
            return
        label = pvd[40:72].decode("ascii", "replace").strip() or "ISO9660"
        # The root directory record is embedded in the PVD at byte 156.
        root = pvd[156:190]
        root_extent = _both_endian32(root, 2)
        root_length = _both_endian32(root, 10)

        volume = Volume(name=label, start_block=root_extent)
        volume.files = list(self._walk(image, offset, root_extent, root_length, prefix="", depth=0))
        yield volume

    def _walk(
        self,
        image: SectorImage,
        origin: int,
        extent: int,
        length: int,
        prefix: str,
        depth: int,
    ) -> Iterator[File]:
        if depth > _MAX_DEPTH:
            return
        data = image.read(origin + extent * SECTOR_SIZE, length)
        pos = 0
        while pos < len(data):
            record_len = data[pos]
            if record_len == 0:
                # Records never straddle a sector; skip to the next one.
                pos = (pos // SECTOR_SIZE + 1) * SECTOR_SIZE
                if pos >= len(data):
                    return
                continue
            record = data[pos : pos + record_len]
            if len(record) < 33:
                return
            child_extent = _both_endian32(record, 2)
            child_length = _both_endian32(record, 10)
            flags = record[25]
            name_len = record[32]
            raw_name = record[33 : 33 + name_len]
            pos += record_len

            if name_len == 1 and raw_name in (b"\x00", b"\x01"):
                continue  # . and ..
            name = raw_name.decode("ascii", "replace")
            name = name.split(";", 1)[0]  # strip the version suffix
            full = f"{prefix}{name}"

            if flags & FLAG_DIRECTORY:
                yield from self._walk(
                    image, origin, child_extent, child_length, f"{full}/", depth + 1
                )
            else:
                yield File(
                    name=full,
                    kind=_classify(name),
                    size=child_length,
                    start_block=child_extent,
                )

    def read_file(self, image: SectorImage, origin: int, entry: File) -> bytes:
        return image.read(origin + entry.start_block * SECTOR_SIZE, entry.size)


def _classify(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".wav"):
        return "wav"
    if lower.endswith((".aif", ".aiff")):
        return "aiff"
    return "file"


register(Iso9660Backend())
