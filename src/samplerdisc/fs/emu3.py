"""E-mu ``EMU3`` filesystem. See docs/formats/emu3.md.

One on-disc format spans three product lines the archives file separately --
EIIIX, ESI/Formula 4000 and E-IV all write ``EMU3`` at byte 0 and the same
folder and bank directories. The *bank interior* is not shared: EIII/ESI banks
carry an ``EMULATOR 3X`` header and E-IV banks do not, so samples are read from
the former and the latter is listed but not extracted. See ADR-0014.

Every offset here is documented in the format doc against a named disc. Do not
change a constant without changing the doc, and vice versa.
"""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING, NamedTuple

from samplerdisc.fs.base import File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

MAGIC = b"EMU3"

#: Directory addressing is in 512-byte blocks, not the 2048-byte cooked sector.
BLOCK = 512

#: Header fields, all u32 LE. ``FOLDER_BLOCK + FOLDER_RESERVED == BANK_BLOCK``
#: holds on every disc measured, so the third is derived and the first is the
#: authority -- see the note on folders in volumes().
OFF_FOLDER_BLOCK = 0x08
OFF_FOLDER_RESERVED = 0x0C
OFF_BANK_BLOCK = 0x10

#: Folder and bank share one 32-byte record shape and are told apart by the
#: flags word alone. Reading the folder table as banks yields plausible names
#: and nonsense extents, which is the trap docs/formats/emu3.md records.
ENTRY_LEN = 32
ENTRY_NAME_LEN = 16
OFF_ENTRY_START = 18
OFF_ENTRY_FLAGS = 26

FOLDER_FLAGS = 0xFFFF
BANK_FLAGS = frozenset({0x0080, 0x0081})

#: A directory ends at a zeroed entry or at anything that is not a bank. Both
#: occur: four discs terminate on zeros, Protozoa runs into 0x42 filler that
#: decodes as a perfectly plausible entry.
_MAX_ENTRIES = 512
_MAX_FOLDERS = 64

#: EIII/ESI bank header. The name repeats the directory entry, which is what
#: lets a bank be located by signature rather than by arithmetic.
BANK_MAGIC = b"EMULATOR"
OFF_BANK_NAME = 16
BANK_NAME_LEN = 16

#: Sample record, relative to its own start. A record begins two bytes before
#: its name; those two bytes are zero on every record after the first.
SAMPLE_NAME_OFFSET = 2
OFF_SAMPLE_HEADER_LEN = 22
OFF_SAMPLE_RECORD_LEN = 34
OFF_SAMPLE_RATE = 54

#: Records sit back to back and each declares its own length two short of the
#: distance to the next, verified across a 12-record chain.
RECORD_LEN_BIAS = 2

#: Every EIII/ESI sample header measured is this long. Treated as a validity
#: check rather than a constant, since it is read from the record.
SAMPLE_HEADER_LEN = 92

MIN_RATE = 4000
MAX_RATE = 50000

_SCAN_CHUNK = 1 << 23


def decode_name(raw: bytes) -> str:
    """Bank and sample names are plain ASCII, space padded."""
    return raw.decode("ascii", "replace").rstrip("\x00 ").strip()


def is_plausible_name(raw: bytes) -> bool:
    """Printable text, padded to width with spaces *or* NULs.

    Both occur, and requiring one of them is a silent truncation: the E-IV
    reference disc NUL-pads, and rejecting that dropped 4 of its 12 banks with
    no error and a listing that looked complete. A hex dump renders NUL as '.'
    exactly like a full stop, so the padding style is easy to misread.
    """
    text = raw.split(b"\x00", 1)[0]
    if not text.strip():
        return False
    if not all(32 <= b < 127 for b in text):
        return False
    return set(raw[len(text) :]) <= {0}


class _Bank(NamedTuple):
    name: str
    folder: str
    start: int
    length: int


def _entries(image: SectorImage, offset: int, block: int, flags, limit: int):
    """Walk one 32-byte directory, stopping at zeros or a foreign record."""
    data = image.read(offset + block * BLOCK, limit * ENTRY_LEN)
    for index in range(len(data) // ENTRY_LEN):
        entry = data[index * ENTRY_LEN : (index + 1) * ENTRY_LEN]
        if not any(entry):
            return
        (word,) = struct.unpack_from("<H", entry, OFF_ENTRY_FLAGS)
        if word not in flags:
            return
        raw = entry[:ENTRY_NAME_LEN]
        if not is_plausible_name(raw):
            return
        start, length = struct.unpack_from("<HH", entry, OFF_ENTRY_START)
        yield decode_name(raw), start, length


class Emu3Backend:
    name = "emu3"

    def probe(self, image: SectorImage, offset: int) -> bool:
        """``EMU3`` plus a folder table that actually resolves.

        The magic is four bytes, which is not enough on its own (ADR-0012), so
        the header's own arithmetic is checked and the directory it points at
        must yield a bank.
        """
        head = image.read(offset, 0x40)
        if len(head) < 0x40 or not head.startswith(MAGIC):
            return False
        folder = struct.unpack_from("<I", head, OFF_FOLDER_BLOCK)[0]
        reserved = struct.unpack_from("<I", head, OFF_FOLDER_RESERVED)[0]
        banks = struct.unpack_from("<I", head, OFF_BANK_BLOCK)[0]
        if folder + reserved != banks or not 0 < folder < banks:
            return False
        return any(True for _ in _entries(image, offset, banks, BANK_FLAGS, 4))

    def _folders(self, image: SectorImage, offset: int) -> list[tuple[str, int]]:
        head = image.read(offset, 0x40)
        folder_block = struct.unpack_from("<I", head, OFF_FOLDER_BLOCK)[0]
        bank_block = struct.unpack_from("<I", head, OFF_BANK_BLOCK)[0]
        found = [
            (name, start)
            for name, start, _ in _entries(
                image, offset, folder_block, {FOLDER_FLAGS}, _MAX_FOLDERS
            )
        ]
        # A disc with no folder table still has the bank directory the header
        # points at. Falling back to it keeps such a disc readable; using it
        # *instead* of the folders would lose every bank past the first folder,
        # which is 6 banks of 12 on the E-IV reference disc.
        return found or [("", bank_block)]

    def _banks(self, image: SectorImage, offset: int) -> list[_Bank]:
        banks: list[_Bank] = []
        for folder, block in self._folders(image, offset):
            for name, start, length in _entries(image, offset, block, BANK_FLAGS, _MAX_ENTRIES):
                banks.append(_Bank(name, folder, start, length))
        return banks

    def _bank_offsets(self, image: SectorImage, offset: int) -> dict[str, int]:
        """Locate EIII/ESI banks by their own header, keyed on bank name.

        The directory's start field is not a usable byte address: the implied
        allocation unit measures 256 KiB on three reference discs and 1 MiB on
        another, and no header field predicts which. The bank header repeats
        the directory name verbatim, so matching on it is both exact and
        self-checking -- and it is the same reasoning as ADR-0004, applied a
        layer down.

        Returns an empty map for a disc whose banks carry no header, which is
        the E-IV case and is why those list without extracting.
        """
        found: dict[str, int] = {}
        position = 0
        carry = b""
        while position < image.size:
            chunk = image.read(position, _SCAN_CHUNK)
            if not chunk:
                break
            haystack = carry + chunk
            base = position - len(carry)
            for match in re.finditer(re.escape(BANK_MAGIC), haystack):
                at = match.start()
                raw = haystack[at + OFF_BANK_NAME : at + OFF_BANK_NAME + BANK_NAME_LEN]
                if len(raw) == BANK_NAME_LEN and is_plausible_name(raw):
                    found.setdefault(decode_name(raw), base + at)
            carry = haystack[-64:]
            position += len(chunk)
        return found

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        located = self._bank_offsets(image, offset)
        # A bank ends where the next one begins. The directory's length field
        # would be the obvious bound and is not usable -- see _bank_offsets --
        # so the bound comes from the same measured positions as the starts.
        # Without it a bank's sample walk runs into its neighbour and reports
        # that neighbour's samples as its own, which looks entirely plausible.
        boundaries = sorted(located.values())
        for bank in self._banks(image, offset):
            volume = Volume(name=bank.name, start_block=bank.start)
            at = located.get(bank.name)
            if at is None:
                # No EMULATOR header: an E-IV bank, whose interior this project
                # has one specimen of and does not guess at (ADR-0015). The
                # bank is real and its name is right, so it is listed.
                volume.note = "bank interior not recognised (E-IV); listed only"
            else:
                after = [b for b in boundaries if b > at]
                limit = after[0] if after else image.size
                volume.files = list(self._samples(image, offset, at, limit))
            yield volume

    def _samples(self, image: SectorImage, offset: int, bank_at: int, limit: int) -> Iterator[File]:
        """Enumerate a bank's sample records by signature, within its bounds.

        Chaining on the declared length is the obvious walk and it does not
        hold: records sit back to back in runs -- a 15-record piano
        multisample on the reference disc -- and then a gap appears, after
        which the "next" record lands inside PCM and decodes as noise. So the
        records are found rather than followed.

        The signature is specific enough to survive a scan through megabytes of
        audio: the header-length field must equal exactly ``SAMPLE_HEADER_LEN``,
        the rate must be plausible, and sixteen bytes must be printable. On the
        reference bank that yields 452 records with 452 distinct, sensible
        names totalling 7.00 MiB inside a bank declaring 8 MiB.
        """
        window = image.read(offset + bank_at, max(limit - bank_at, 0))
        needle = struct.pack("<I", SAMPLE_HEADER_LEN)
        for match in re.finditer(re.escape(needle), window):
            at = match.start() - OFF_SAMPLE_HEADER_LEN
            if at < 0:
                continue
            record = self._parse_record(window[at : at + SAMPLE_HEADER_LEN])
            if record is None:
                continue
            name, header_len, record_len, rate = record
            if at + record_len > len(window):
                continue
            yield File(
                name=name,
                kind="sample",
                size=record_len - header_len,
                start_block=bank_at + at + header_len,
                raw_type=rate,
            )

    def _parse_record(self, head: bytes) -> tuple[str, int, int, int] | None:
        raw = head[SAMPLE_NAME_OFFSET : SAMPLE_NAME_OFFSET + ENTRY_NAME_LEN]
        if not is_plausible_name(raw):
            return None
        name = decode_name(raw)
        if not name:
            return None
        (header_len,) = struct.unpack_from("<I", head, OFF_SAMPLE_HEADER_LEN)
        (declared,) = struct.unpack_from("<I", head, OFF_SAMPLE_RECORD_LEN)
        (rate,) = struct.unpack_from("<I", head, OFF_SAMPLE_RATE)
        record_len = declared + RECORD_LEN_BIAS
        if header_len != SAMPLE_HEADER_LEN or record_len <= header_len:
            return None
        if not MIN_RATE <= rate <= MAX_RATE:
            return None
        return name, header_len, record_len, rate

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        return image.read(offset + entry.start_block, entry.size)

    def parse_sample(self, entry: File, payload: bytes):
        """The record's rate travelled on the File; the payload is already PCM."""
        from samplerdisc.sample import emu3 as sample_emu3

        return sample_emu3.parse(payload, rate=entry.raw_type, fallback_name=entry.name)

    def original_suffix(self, entry: File) -> str:
        return ".e3s" if entry.kind == "sample" else ".bin"


register(Emu3Backend())
