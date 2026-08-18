"""Raw CD images: 2352-byte sectors carrying 2048 bytes of user data.

See docs/formats/rawcd.md.
"""

from __future__ import annotations

import os
import re

from samplerdisc.container.base import SECTOR_SIZE, _FileBacked

#: 12-byte sync at the head of every raw MODE1/MODE2 sector.
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"

RAW_SECTOR_SIZE = 2352
#: Sync (12) + address and mode (4) precede the user data.
USER_DATA_OFFSET = 16

_TRACK_RE = re.compile(r"^\s*TRACK\s+(\d+)\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def parse_cue_sector_size(cue_text: str) -> int | None:
    """Return the sector size of the first data track named in a cue sheet.

    ``MODE1/2352`` is raw, ``MODE1/2048`` cooked. Audio tracks are ignored --
    this project wants the data track. Returns None if nothing usable is found.
    """
    for _number, mode in _TRACK_RE.findall(cue_text):
        mode = mode.upper()
        if mode.startswith("AUDIO"):
            continue
        if "/" in mode:
            try:
                return int(mode.split("/", 1)[1])
            except ValueError:
                continue
    return None


def find_cue(image_path: str | os.PathLike[str]) -> str | None:
    """Locate a cue sheet beside an image, tolerating case differences."""
    path = os.fspath(image_path)
    stem, _ = os.path.splitext(path)
    for candidate in (stem + ".cue", stem + ".CUE", stem + ".Cue"):
        if os.path.exists(candidate):
            return candidate
    return None


def looks_raw(head: bytes) -> bool:
    return head.startswith(SYNC)


class RawCdImage(_FileBacked):
    """De-interleaves 2352-byte sectors down to their 2048-byte payload."""

    kind = "rawcd"

    def __init__(self, path, start: int = 0, end: int | None = None):
        super().__init__(path, start, end)
        self._raw_sectors = (self._end - self._start) // RAW_SECTOR_SIZE

    @property
    def size(self) -> int:
        return self._raw_sectors * SECTOR_SIZE

    def read(self, offset: int, length: int) -> bytes:
        if length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        first = offset // SECTOR_SIZE
        last = (offset + length - 1) // SECTOR_SIZE
        out = bytearray()
        for index in range(first, last + 1):
            raw = self._raw(index * RAW_SECTOR_SIZE, RAW_SECTOR_SIZE)
            out += raw[USER_DATA_OFFSET : USER_DATA_OFFSET + SECTOR_SIZE]
        skip = offset - first * SECTOR_SIZE
        return bytes(out[skip : skip + length])
