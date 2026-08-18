"""Nero NRG, v1 and v2. See docs/formats/nrg.md.

Everything in NRG is big-endian. The footer must be parsed: an NRG is not an
ISO with junk on the end, and treating it as one reads a real disc as empty.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

from samplerdisc.container.base import SECTOR_SIZE, SectorImage
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.rawcd import RAW_SECTOR_SIZE, RawCdImage

MAGIC_V2 = b"NER5"
MAGIC_V1 = b"NERO"

#: Sectors of pregap in front of track 1, when the image includes it.
PREGAP_SECTORS = 150

#: DAOX/DAOI mode codes that mean audio rather than data.
_AUDIO_MODES = {0x07, 0x10}

_DAO_HEADER_LEN = 22  # u32 size + upc[14] + pad + toc type + first + last


class Track(NamedTuple):
    sector_size: int
    mode: int
    start: int  # byte offset into the file
    end: int  # byte offset into the file

    @property
    def is_audio(self) -> bool:
        return self.mode in _AUDIO_MODES


def looks_nrg(tail12: bytes) -> bool:
    """``tail12`` is the last 12 bytes of the file."""
    return tail12[:4] == MAGIC_V2 or tail12[4:8] == MAGIC_V1


def _footer_offset(fh, file_size: int) -> int:
    """Locate the first chunk. v2 is checked first, deliberately.

    A v1 magic cannot appear at EOF-12, but reading 8 bytes where v1 wrote 4
    produces a plausible-looking huge offset rather than a miss, so the wrong
    order fails quietly.
    """
    fh.seek(file_size - 12)
    tail = fh.read(12)
    if tail[:4] == MAGIC_V2:
        return struct.unpack(">Q", tail[4:12])[0]
    if tail[4:8] == MAGIC_V1:
        return struct.unpack(">I", tail[8:12])[0]
    raise ValueError("not an NRG image: no NER5 or NERO trailer")


def parse_chunks(footer: bytes) -> list[tuple[bytes, bytes]]:
    """Split the footer into (id, body) pairs, stopping at END!."""
    chunks: list[tuple[bytes, bytes]] = []
    pos = 0
    while pos + 8 <= len(footer):
        chunk_id = footer[pos : pos + 4]
        (length,) = struct.unpack_from(">I", footer, pos + 4)
        body = footer[pos + 8 : pos + 8 + length]
        chunks.append((chunk_id, body))
        pos += 8 + length
        if chunk_id == b"END!":
            break
    return chunks


def parse_dao(body: bytes, wide: bool) -> list[Track]:
    """Parse a DAOX (``wide``) or DAOI track table.

    Track block, verified against docs/formats/nrg.md:
    ``isrc[12] + u16 sector_size + u16 mode + u16 pad`` then three offsets,
    64-bit for DAOX and 32-bit for DAOI.
    """
    offset_fmt, offset_len = (">Q", 8) if wide else (">I", 4)
    block_len = 18 + 3 * offset_len
    tracks: list[Track] = []
    pos = _DAO_HEADER_LEN
    while pos + block_len <= len(body):
        sector_size, mode = struct.unpack_from(">HH", body, pos + 12)
        (start,) = struct.unpack_from(offset_fmt, body, pos + 18 + offset_len)
        (end,) = struct.unpack_from(offset_fmt, body, pos + 18 + 2 * offset_len)
        tracks.append(Track(sector_size, mode, start, end))
        pos += block_len
    return tracks


def parse_cuex(body: bytes) -> list[tuple[int, int]]:
    """Return (control, LBA) pairs from a CUEX chunk.

    8 bytes per entry: adr/control, track, index, pad, s32 BE LBA. Control 0x41
    is a data track; track 0xAA is the lead-out.

    CUES is deliberately not parsed here. It encodes position as MSF rather than
    a 32-bit LBA, and no reference disc using it was available to verify the
    layout against -- guessing it would put unverified struct offsets behind a
    fallback that already only runs when DAO is missing.
    """
    entries: list[tuple[int, int]] = []
    for pos in range(0, len(body) - 7, 8):
        control = body[pos]
        (lba,) = struct.unpack_from(">i", body, pos + 4)
        entries.append((control, lba))
    return entries


class NrgImage(SectorImage):
    """Presents the data track of an NRG as a flat cooked-sector stream."""

    kind = "nrg"

    def __init__(self, path):
        self._inner: SectorImage | None = None
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            start = _footer_offset(fh, file_size)
            if not 0 < start < file_size:
                raise ValueError(f"{path}: implausible NRG footer offset {start}")
            fh.seek(start)
            footer = fh.read(file_size - start)

        chunks = parse_chunks(footer)
        self.tracks = self._tracks_from(chunks, file_size)
        if not self.tracks:
            raise ValueError(f"{path}: NRG describes no readable data track")

        track = self.tracks[0]
        self.track = track
        if track.sector_size == RAW_SECTOR_SIZE:
            self._inner = RawCdImage(path, track.start, track.end)
        elif track.sector_size == SECTOR_SIZE:
            self._inner = FlatImage(path, track.start, track.end)
        else:
            raise ValueError(f"{path}: unsupported NRG sector size {track.sector_size}")

    def _tracks_from(self, chunks, file_size: int) -> list[Track]:
        for chunk_id, body in chunks:
            if chunk_id in (b"DAOX", b"DAOI"):
                tracks = parse_dao(body, wide=chunk_id == b"DAOX")
                data = [t for t in tracks if not t.is_audio]
                if data:
                    return data
        # No DAO chunk: fall back to the cue table. Track 1 index 1 sits at LBA 0,
        # and the file includes the pregap, so data begins PREGAP_SECTORS in.
        for chunk_id, body in chunks:
            if chunk_id == b"CUEX":
                entries = parse_cuex(body)
                leadout = max((lba for _control, lba in entries), default=0)
                if leadout > 0:
                    start = PREGAP_SECTORS * SECTOR_SIZE
                    end = min((leadout + PREGAP_SECTORS) * SECTOR_SIZE, file_size)
                    return [Track(SECTOR_SIZE, 0, start, end)]
        return []

    @property
    def size(self) -> int:
        assert self._inner is not None
        return self._inner.size

    def read(self, offset: int, length: int) -> bytes:
        assert self._inner is not None
        return self._inner.read(offset, length)

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()
