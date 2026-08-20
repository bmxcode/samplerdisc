"""ISO 9660, for sample CDs whose payload is already WAV or AIFF.

A meaningful share of these collections are not sampler-format discs at all:
libraries converted to Kontakt or plain audio and burned back to an image. They
mount on a modern machine, but they still arrive wrapped in a .nrg or a
compressed .mdx that nothing else opens -- so reading them here costs little
and saves the user a second tool.

Names come from the Joliet supplementary descriptor where the disc carries one,
because the primary descriptor's 8.3 names are lossy and on at least one real
disc are not even unique (ADR-0019). See docs/formats/iso9660.md.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, NamedTuple

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
TYPE_SUPPLEMENTARY = 2
TYPE_TERMINATOR = 255

#: Byte 88 of a supplementary descriptor holds its escape sequences. Joliet
#: uses three, one per UCS-2 level; all three mean the same thing to us.
ESCAPE_OFFSET = 88
JOLIET_ESCAPES = (b"%/@", b"%/C", b"%/E")

#: Directory record flag bit 1 marks a subdirectory.
FLAG_DIRECTORY = 0x02

#: Where the root directory record is embedded in a volume descriptor.
ROOT_RECORD_OFFSET = 156
ROOT_RECORD_SIZE = 34

_MAX_DESCRIPTORS = 16
_MAX_DEPTH = 8


def _both_endian32(data: bytes, offset: int) -> int:
    """ISO 9660 stores 32-bit values twice; the little-endian half is first."""
    return struct.unpack_from("<I", data, offset)[0]


class _Tree(NamedTuple):
    """One name space on the disc: primary, or Joliet."""

    label: str
    extent: int
    length: int
    joliet: bool


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

    def _descriptors(self, image: SectorImage, offset: int) -> Iterator[bytes]:
        for index in range(_MAX_DESCRIPTORS):
            sector = image.read(offset + (PVD_SECTOR + index) * SECTOR_SIZE, SECTOR_SIZE)
            if len(sector) < SECTOR_SIZE or sector[1:6] != MAGIC:
                return
            if sector[0] == TYPE_TERMINATOR:
                return
            yield sector

    def _tree(self, image: SectorImage, offset: int) -> _Tree | None:
        """The name space to walk: Joliet where present, primary otherwise.

        Both describe the same extents, so this is a choice of names and
        nothing else -- no file appears in one and not the other.
        """
        primary: _Tree | None = None
        for sector in self._descriptors(image, offset):
            joliet = sector[0] == TYPE_SUPPLEMENTARY and (
                sector[ESCAPE_OFFSET : ESCAPE_OFFSET + 3] in JOLIET_ESCAPES
            )
            if sector[0] != TYPE_PRIMARY and not joliet:
                continue
            root = sector[ROOT_RECORD_OFFSET : ROOT_RECORD_OFFSET + ROOT_RECORD_SIZE]
            if len(root) < ROOT_RECORD_SIZE:
                continue
            tree = _Tree(
                label=_label(sector[40:72], joliet),
                extent=_both_endian32(root, 2),
                length=_both_endian32(root, 10),
                joliet=joliet,
            )
            if joliet:
                return tree
            if primary is None:
                primary = tree
        return primary

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        tree = self._tree(image, offset)
        if tree is None:
            return
        volume = Volume(name=tree.label or "ISO9660", start_block=tree.extent)
        volume.files = list(
            self._walk(image, offset, tree.extent, tree.length, "", 0, joliet=tree.joliet)
        )
        yield volume

    def _walk(
        self,
        image: SectorImage,
        origin: int,
        extent: int,
        length: int,
        prefix: str,
        depth: int,
        joliet: bool,
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
            name = _decode(raw_name, joliet)
            name = name.split(";", 1)[0]  # strip the version suffix
            full = f"{prefix}{name}"

            if flags & FLAG_DIRECTORY:
                yield from self._walk(
                    image, origin, child_extent, child_length, f"{full}/", depth + 1, joliet
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


def _decode(raw: bytes, joliet: bool) -> str:
    """A directory record's name, from whichever name space it came.

    Joliet is UCS-2 big-endian. An odd length cannot be UCS-2, so the trailing
    byte is dropped rather than allowed to shift every character after it: a
    malformed record costs one name, not the rest of the directory.
    """
    if not joliet:
        return raw.decode("ascii", "replace")
    return raw[: len(raw) - len(raw) % 2].decode("utf-16-be", "replace")


def _label(raw: bytes, joliet: bool) -> str:
    """The volume identifier, up to the first NUL.

    The field is meant to be space-padded, but MagicISO NUL-terminates it and
    leaves whatever was in the buffer behind: Vintage Pro's reads
    ``VintagePro\\x0057``, the ``57`` a fragment of the volume set identifier
    ``20101002_0257``. Reading past the NUL invented a volume named
    "VintagePro 57" that is nowhere on the disc.
    """
    text = _decode(raw, joliet)
    return text.split("\x00", 1)[0].strip()


def _classify(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".wav"):
        return "wav"
    if lower.endswith((".aif", ".aiff")):
        return "aiff"
    return "file"


register(Iso9660Backend())
