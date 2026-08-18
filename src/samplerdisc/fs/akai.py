"""AKAI S1000/S3000 filesystem. See docs/formats/akai-fs.md.

Every offset here is documented there against a named reference disc. Do not
change a constant without changing the doc, and vice versa.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from samplerdisc.fs.base import File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

#: Index -> character. 10 is a space, which is the trap: read it as '9' and
#: "KICKIN B0-F1" decodes as "KICKIN9B0-F1", which looks like a real name.
CHARSET = "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-."

#: Allocation unit: four cooked sectors.
BLOCK_SIZE = 8192

NAME_LEN = 12

#: Volume directory in the partition header, 16-byte entries.
VOLUME_DIR_OFFSET = 0xCA
VOLUME_ENTRY_LEN = 16

#: File entries within a volume, 24 bytes each.
FILE_ENTRY_LEN = 24

#: Type nibble: 'p' program, 's' sample. The high nibble varies between S1000
#: and S3000 discs, so mask it rather than comparing the whole byte.
TYPE_PROGRAM = 0x0
TYPE_SAMPLE = 0x3

#: Sample payload header (docs/formats/akai-fs.md).
SAMPLE_HEADER_LEN = 150
SAMPLE_ID = 3
PROGRAM_ID = 1
SAMPLE_VALID = 0x80

_MAX_VOLUMES = 100
_MAX_FILES = 512

#: Volume slots examined by probe(). Enough to see ordering, cheap enough to
#: run at every candidate sector during origin detection.
_PROBE_SLOTS = 8


def decode_name(raw: bytes) -> str:
    """Decode a fixed-width AKAI name. Trailing padding is stripped."""
    return "".join(CHARSET[b] if b < len(CHARSET) else "?" for b in raw).rstrip()


def is_plausible_name(raw: bytes) -> bool:
    return all(b < len(CHARSET) for b in raw)


def is_empty_slot(entry: bytes) -> bool:
    """An unused directory slot is all zeros.

    Emptiness must be tested on the bytes, never on the decoded name: index 0
    is a legitimate '0', so twelve zero bytes decode to "000000000000" rather
    than to nothing.
    """
    return not any(entry)


class AkaiBackend:
    name = "akai"

    def probe(self, image: SectorImage, offset: int) -> bool:
        """Recognise an AKAI partition header.

        Deliberately strict: this runs at every candidate offset during origin
        detection, and a loose probe resolves an origin confidently and wrongly
        (ADR-0005). Requires several consecutive volume entries whose names
        decode cleanly, whose start blocks are ordered and in range, and at
        least one of which is non-empty.
        """
        want = VOLUME_DIR_OFFSET + _PROBE_SLOTS * VOLUME_ENTRY_LEN
        header = image.read(offset, want)
        if len(header) < want:
            return False

        max_block = max((image.size - offset) // BLOCK_SIZE, 1)
        previous = -1
        found = 0
        for index in range(_PROBE_SLOTS):
            base = VOLUME_DIR_OFFSET + index * VOLUME_ENTRY_LEN
            entry = header[base : base + VOLUME_ENTRY_LEN]
            if is_empty_slot(entry):
                # A free slot. Real partitions fill slot 0, so an empty one
                # there means this is not a partition header.
                if index == 0:
                    return False
                continue
            raw_name = entry[:NAME_LEN]
            if not is_plausible_name(raw_name):
                return False
            _type, start = struct.unpack("<HH", entry[NAME_LEN:VOLUME_ENTRY_LEN])
            # Start blocks are ordered and in range; that ordering is what
            # separates a real header from bytes that merely decode cleanly.
            if start == 0 or start > max_block or start <= previous:
                return False
            previous = start
            found += 1
        return found >= 1

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        header = image.read(offset, VOLUME_DIR_OFFSET + _MAX_VOLUMES * VOLUME_ENTRY_LEN)
        max_block = (image.size - offset) // BLOCK_SIZE
        for index in range(_MAX_VOLUMES):
            base = VOLUME_DIR_OFFSET + index * VOLUME_ENTRY_LEN
            entry = header[base : base + VOLUME_ENTRY_LEN]
            if len(entry) < VOLUME_ENTRY_LEN:
                return
            if is_empty_slot(entry):
                continue
            raw_name = entry[:NAME_LEN]
            if not is_plausible_name(raw_name):
                continue
            name = decode_name(raw_name)
            _type, start = struct.unpack("<HH", entry[NAME_LEN:VOLUME_ENTRY_LEN])
            if not name or start == 0 or start > max_block:
                continue
            volume = Volume(name=name, start_block=start)
            volume.files = list(self._files(image, offset, start, max_block))
            yield volume

    def _files(
        self, image: SectorImage, origin: int, start_block: int, max_block: int
    ) -> Iterator[File]:
        directory = image.read(origin + start_block * BLOCK_SIZE, _MAX_FILES * FILE_ENTRY_LEN)
        for index in range(_MAX_FILES):
            entry = directory[index * FILE_ENTRY_LEN : (index + 1) * FILE_ENTRY_LEN]
            if len(entry) < FILE_ENTRY_LEN or is_empty_slot(entry):
                return
            raw_name = entry[:NAME_LEN]
            if not is_plausible_name(raw_name):
                continue
            name = decode_name(raw_name)
            if not name:
                continue
            type_byte = entry[16]
            size = entry[17] | entry[18] << 8 | entry[19] << 16
            (file_start,) = struct.unpack("<H", entry[20:22])
            # Damaged rips are common; skip what cannot be read rather than
            # abandoning the disc.
            if file_start == 0 or file_start > max_block or size <= 0:
                continue
            nibble = type_byte & 0x0F
            if nibble == TYPE_SAMPLE:
                kind = "sample"
            elif nibble == TYPE_PROGRAM:
                kind = "program"
            else:
                kind = f"type-{type_byte:#04x}"
            yield File(name=name, kind=kind, size=size, start_block=file_start)

    def read_file(self, image: SectorImage, origin: int, entry: File) -> bytes:
        return image.read(origin + entry.start_block * BLOCK_SIZE, entry.size)


register(AkaiBackend())
