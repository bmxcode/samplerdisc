"""E-mu ``EMU3`` filesystem. See docs/formats/emu3.md.

One on-disc format spans three product lines the archives file separately --
EIIIX, ESI/Formula 4000 and E-IV all write ``EMU3`` at byte 0 and the same
folder and bank directories (ADR-0014). The *bank interior* is not shared, and
that is the one place this module branches: EIII/ESI banks carry an
``EMULATOR 3X`` header and are located by it, while E-IV banks carry none and
are reached through a chained ``E3S1`` sample directory instead (ADR-0020).

Every offset here is documented in the format doc against a named disc. Do not
change a constant without changing the doc, and vice versa.
"""

from __future__ import annotations

import re
import struct
from itertools import pairwise
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

#: u32 LE, bytes of sample data in the bank. Reads **zero** on 4 of the 112
#: located banks and non-zero on the rest: one index bank on each of
#: `esi32-gm`, `eiiix-1` and `eiiix-2`, which carry the library's contents list
#: and no audio at all, plus `protozoa`'s last bank, whose bound is wrong for a
#: separate reason and which is why this is read only *after* the walk has
#: already come back empty. It is the difference between a bank that yields
#: nothing because it holds nothing and one that yields nothing because the
#: walk is wrong -- which ADR-0012 says must not be left to a human reading the
#: names.
OFF_BANK_SAMPLE_BYTES = 0x34

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

#: E-IV banks carry no ``EMULATOR`` header -- there is not one occurrence of
#: the string on any of the three reference discs. Their samples are reached
#: through a per-bank *sample directory* of 32-byte ``E3S1`` entries instead.
#:
#: These fields are BIG-endian. They are the only big-endian structure in the
#: format; the sample payload and every EIII field are little-endian, and
#: docs/formats/emu3.md records how convincingly that got read the wrong way
#: round once already.
EIV_MAGIC = b"E3S1"
OFF_EIV_LENGTH = 4
OFF_EIV_POSITION = 8
OFF_EIV_INDEX = 12
OFF_EIV_NAME = 14

#: ``E3S1`` has two uses, which is why the tag count runs at roughly twice the
#: record count. It is the directory entry above, and it is also the eight
#: bytes immediately before a sample record.
EIV_RECORD_OFFSET = 8

#: Consecutive directory entries advance the running offset by the sample's own
#: length plus ten -- eight for the next record's tag and two spare. This is a
#: *declared* relation, not physical adjacency, which is why it survives
#: `studio`, whose entries are scattered rather than packed into a table.
EIV_CHAIN_STRIDE = 10

#: Candidate allocation units in 512-byte blocks, measured 2048 on `analogia`
#: and 1024 on `studio` and `vitous`. The unit is fitted per disc and then only
#: ever used to *confirm* a bank against an independently located chain, never
#: to place one -- ADR-0015's objection to arithmetic on ``start`` stands.
EIV_UNITS = (256, 512, 1024, 2048, 4096, 8192)

_SCAN_CHUNK = 1 << 23

#: Enough to cover a directory entry (32) and a record's header reached at
#: +8 (8 + 92), with room to spare, so a tag near a chunk edge still resolves.
_EIV_WINDOW = 128


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
    """Walk one 32-byte directory, stopping at zeros or a foreign record.

    ``flags`` of ``None`` skips the flags test. That is for the folder table,
    whose identity comes from the header pointer at ``OFF_FOLDER_BLOCK`` rather
    than from a word inside its entries -- see _folders().
    """
    data = image.read(offset + block * BLOCK, limit * ENTRY_LEN)
    for index in range(len(data) // ENTRY_LEN):
        entry = data[index * ENTRY_LEN : (index + 1) * ENTRY_LEN]
        if not any(entry):
            return
        if flags is not None:
            (word,) = struct.unpack_from("<H", entry, OFF_ENTRY_FLAGS)
            if word not in flags:
                return
        raw = entry[:ENTRY_NAME_LEN]
        if not is_plausible_name(raw):
            return
        start, length = struct.unpack_from("<HH", entry, OFF_ENTRY_START)
        yield decode_name(raw), start, length


class _EivEntry(NamedTuple):
    """One 32-byte ``E3S1`` sample-directory entry."""

    tag: int
    length: int
    position: int
    index: int
    name: str


def _eiv_scan(image: SectorImage) -> dict[int, bytes]:
    """Every ``E3S1`` tag in the image, with the bytes that follow it."""
    found: dict[int, bytes] = {}
    position = 0
    carry = b""
    while position < image.size:
        chunk = image.read(position, _SCAN_CHUNK)
        if not chunk:
            break
        haystack = carry + chunk
        base = position - len(carry)
        for match in re.finditer(re.escape(EIV_MAGIC), haystack):
            at = match.start()
            window = haystack[at : at + _EIV_WINDOW]
            if len(window) == _EIV_WINDOW or base + at + len(window) >= image.size:
                found[base + at] = window
        carry = haystack[-_EIV_WINDOW:]
        position += len(chunk)
    return found


def _eiv_record_name(window: bytes) -> str | None:
    """The name of the sample record eight bytes into ``window``, if any.

    A record is confirmed by its own tag and its name, *not* by the header
    length at ``OFF_SAMPLE_HEADER_LEN``. That field reads 92 on most E-IV
    records and 0 on 547 of `studio`'s, so requiring it drops a fifth of the
    disc -- and it is not needed, because the directory already says where the
    record is and what it is called.
    """
    at = EIV_RECORD_OFFSET + SAMPLE_NAME_OFFSET
    raw = window[at : at + ENTRY_NAME_LEN]
    if len(raw) < ENTRY_NAME_LEN or not is_plausible_name(raw):
        return None
    return decode_name(raw) or None


def _eiv_entries(tags: dict[int, bytes]) -> list[_EivEntry]:
    entries = []
    for tag in sorted(tags):
        window = tags[tag]
        raw = window[OFF_EIV_NAME : OFF_EIV_NAME + ENTRY_NAME_LEN]
        if len(raw) < ENTRY_NAME_LEN or not is_plausible_name(raw):
            continue
        name = decode_name(raw)
        if not name:
            continue
        entries.append(
            _EivEntry(
                tag,
                struct.unpack_from(">I", window, OFF_EIV_LENGTH)[0],
                struct.unpack_from(">I", window, OFF_EIV_POSITION)[0],
                struct.unpack_from(">H", window, OFF_EIV_INDEX)[0],
                name,
            )
        )
    return entries


def _eiv_chains(entries: list[_EivEntry]) -> list[list[_EivEntry]]:
    """Split the directory into per-bank runs at a break in its own chain.

    Two things must hold across a step: the running offset advances by exactly
    the declared length plus ``EIV_CHAIN_STRIDE``, and the index increments.
    Both are self-checking, which is what makes the split exact rather than a
    heuristic -- segmenting on physical stride-32 runs instead gives 935 runs
    for `studio`'s banks and is simply wrong.
    """
    if not entries:
        return []
    chains: list[list[_EivEntry]] = []
    current = [entries[0]]
    for previous, entry in pairwise(entries):
        if (
            entry.position == previous.position + previous.length + EIV_CHAIN_STRIDE
            and entry.index == previous.index + 1
        ):
            current.append(entry)
        else:
            chains.append(current)
            current = [entry]
    chains.append(current)
    return chains


def _eiv_bases(
    tags: dict[int, bytes], chains: list[list[_EivEntry]]
) -> tuple[dict[int, list[_EivEntry]], set[int]]:
    """Resolve each chain to the byte address its running offsets count from.

    A chain is kept only when *every* one of its entries finds a record with
    the right name at ``base + position``. A chain that does not fully confirm
    is dropped rather than partly believed: a bank reporting a plausible
    subset of someone else's samples is the failure this whole design is
    shaped to avoid.

    Single-entry chains are resolved too but reported separately. They carry no
    chain invariant -- there is no second term to check one against -- so they
    are not allowed to influence the allocation-unit fit; they are only ever
    confirmed by a fit the corroborated chains already agreed on.
    """
    by_name: dict[str, list[int]] = {}
    for tag, window in tags.items():
        name = _eiv_record_name(window)
        if name is not None:
            by_name.setdefault(name, []).append(tag + EIV_RECORD_OFFSET)
    located = {position for positions in by_name.values() for position in positions}

    bases: dict[int, dict[int, _EivEntry]] = {}
    corroborated: set[int] = set()
    for chain in chains:
        votes: dict[int, int] = {}
        for entry in chain:
            for at in by_name.get(entry.name, ()):
                votes[at - entry.position] = votes.get(at - entry.position, 0) + 1
        if not votes:
            continue
        base = max(votes, key=lambda candidate: (votes[candidate], -candidate))
        confirmed = all(
            base + entry.position in located
            and _eiv_record_name(tags.get(base + entry.position - EIV_RECORD_OFFSET, b""))
            == entry.name
            for entry in chain
        )
        if confirmed:
            # Two chains can resolve to one base -- a bank whose directory is
            # written twice, or split and recovered in halves. Concatenating
            # them lists the same record under two entries, which on
            # `analogia` produced 509 samples at 449 distinct addresses and 60
            # byte-identical WAVs. One record at one address is one sample.
            seen = bases.setdefault(base, {})
            for entry in chain:
                seen.setdefault(entry.position, entry)
            if len(chain) > 1:
                corroborated.add(base)
    return {base: list(seen.values()) for base, seen in bases.items()}, corroborated


def _eiv_unit(
    corroborated: list[int], bases: list[int], starts: list[int]
) -> tuple[int, int] | None:
    """Fit ``base == BLOCK * (unit * start + bias) + EIV_RECORD_OFFSET``.

    Measured 2048 blocks on `analogia` and 1024 on `studio` and `vitous`, with
    a per-disc bias -- no header field predicts either, which is exactly what
    ADR-0015 found. The difference from what that record rejected is that
    nothing is *placed* by this: a bank is bound only where the address it
    predicts already holds a confirmed chain, so a bad fit binds nothing
    rather than binding wrongly.
    """

    def blocks(addresses):
        for address in addresses:
            aligned = address - EIV_RECORD_OFFSET
            if aligned % BLOCK == 0:
                yield aligned // BLOCK

    strong = set(blocks(corroborated))
    every = set(blocks(bases))
    unique = set(starts)
    best: tuple[int, int, int, int] | None = None
    for unit in EIV_UNITS:
        for bias in {block - unit * start for block in strong for start in unique}:
            # A fit that puts any bank at a negative address is not a fit. This
            # is what separates the true (unit, bias) from the one shifted by a
            # whole unit, which explains just as many chains by pairing every
            # base with its neighbour's start -- and would hand each bank the
            # samples of the bank before it.
            if any(unit * start + bias < 0 for start in unique):
                continue
            predicted = {unit * start + bias for start in unique}
            score = (len(strong & predicted), len(every & predicted))
            if score[0] and (best is None or score > (best[0], best[1])):
                best = (score[0], score[1], unit, bias)
    # Two independent agreements are the minimum that pins both unknowns down.
    # One (base, start) pair is satisfied by *every* unit at some bias, so a
    # single corroborated chain would fit arbitrarily and bind that bank's
    # samples to whichever start the tie-break happened to pick. Refusing
    # leaves every bank listed with its note, which is the honest outcome.
    if best is None or best[0] < 2:
        return None
    return best[2], best[3]


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
        # No flags test here. FOLDER_FLAGS is 0xFFFF on four reference discs,
        # but `studio` writes 0x0013 and 0x0018 on its first two folders, and
        # requiring 0xFFFF makes the walk abort on entry 0, find no folders at
        # all and silently fall back to the single directory at OFF_BANK_BLOCK
        # -- 77 banks of the 230 that disc actually has. The folder table does
        # not need the test: the header pointer already says what it is, and
        # every disc terminates it with a zeroed entry.
        found = [
            (name, start)
            for name, start, _ in _entries(image, offset, folder_block, None, _MAX_FOLDERS)
        ]
        # A disc with no folder table still has the bank directory the header
        # points at. Falling back to it keeps such a disc readable; using it
        # *instead* of the folders would lose every bank past the first folder,
        # which is 6 banks of 12 on the E-IV reference disc.
        return found or [("", bank_block)]

    def _banks(self, image: SectorImage, offset: int) -> list[_Bank]:
        """Every bank, from every folder's own directory.

        Each directory is bounded by the next folder's start block. Folder
        directories sit two to six blocks apart on `studio`, so an unbounded
        walk runs out of one and into the next, reporting the neighbour's banks
        twice -- the same "bound it by the next located structure" rule the
        sample walk needs, one layer up.
        """
        folders = self._folders(image, offset)
        starts = sorted({start for _, start in folders})
        banks: list[_Bank] = []
        for folder, block in folders:
            after = [s for s in starts if s > block]
            limit = (
                min((after[0] - block) * BLOCK // ENTRY_LEN, _MAX_ENTRIES)
                if after
                else _MAX_ENTRIES
            )
            for name, start, length in _entries(image, offset, block, BANK_FLAGS, limit):
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

    def _eiv(self, image: SectorImage, banks: list[_Bank]):
        """Locate E-IV sample directories and bind them to banks by address.

        Returns ``(tags, bound)`` where ``bound`` maps a bank's ``start`` to
        the ``(base, entries)`` proven to live at the address that start
        predicts. A bank absent from the map has no confirmed samples and
        stays listed with its note.
        """
        tags = _eiv_scan(image)
        bases, corroborated = _eiv_bases(tags, _eiv_chains(_eiv_entries(tags)))
        if not corroborated:
            return tags, {}
        fitted = _eiv_unit(sorted(corroborated), sorted(bases), [bank.start for bank in banks])
        if fitted is None:
            return tags, {}
        unit, bias = fitted
        bound: dict[int, tuple[int, list[_EivEntry]]] = {}
        for bank in banks:
            base = BLOCK * (unit * bank.start + bias) + EIV_RECORD_OFFSET
            entries = bases.get(base)
            if entries is not None:
                bound[bank.start] = (base, entries)
        return tags, bound

    def _eiv_samples(self, tags: dict[int, bytes], base: int, entries) -> Iterator[File]:
        """One bank's samples, sized by the directory rather than the record.

        The record's own length field is not usable on E-IV: ``+34`` plus the
        EIII bias of two matches the distance to the next record on 0 of 522,
        0 of 3893 and 0 of 934 consecutive pairs across the three discs, and no
        other offset survives all three either. The directory's big-endian
        length does, on every sample of all three.
        """
        for entry in entries:
            record = base + entry.position
            window = tags.get(record - EIV_RECORD_OFFSET)
            if window is None:
                continue
            size = entry.length - SAMPLE_HEADER_LEN
            if size <= 0 or size % 2:
                continue
            (rate,) = struct.unpack_from("<I", window, EIV_RECORD_OFFSET + OFF_SAMPLE_RATE)
            if not MIN_RATE <= rate <= MAX_RATE:
                continue
            yield File(
                name=entry.name,
                kind="sample",
                size=size,
                start_block=record + SAMPLE_HEADER_LEN,
                raw_type=rate,
            )

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        located = self._bank_offsets(image, offset)
        # A bank ends where the next one begins. The directory's length field
        # would be the obvious bound and is not usable -- see _bank_offsets --
        # so the bound comes from the same measured positions as the starts.
        # Without it a bank's sample walk runs into its neighbour and reports
        # that neighbour's samples as its own, which looks entirely plausible.
        boundaries = sorted(located.values())
        banks = self._banks(image, offset)
        # The E-IV scan is a pass over the image, so it runs once and only when
        # a bank actually needs it. An all-EIII disc never pays for it.
        eiv_tags: dict[int, bytes] = {}
        eiv_bound: dict[int, tuple[int, list[_EivEntry]]] = {}
        if any(bank.name not in located for bank in banks):
            eiv_tags, eiv_bound = self._eiv(image, banks)
        for bank in banks:
            volume = Volume(name=bank.name, start_block=bank.start)
            at = located.get(bank.name)
            if at is None:
                found = eiv_bound.get(bank.start)
                if found is None:
                    # An E-IV bank with no confirmed sample directory. Real,
                    # correctly named, and not guessed at -- the note is what
                    # tells this apart from a probe that matched garbage
                    # (ADR-0012), and the disc-backed suite asserts it.
                    volume.note = "no sample directory found for this bank; listed only"
                else:
                    volume.files = list(self._eiv_samples(eiv_tags, *found))
            else:
                after = [b for b in boundaries if b > at]
                limit = after[0] if after else image.size
                volume.files = list(self._samples(image, offset, at, limit))
                if not volume.files and self._declares_no_samples(image, offset, at):
                    # An index bank: correctly located, correctly bounded, and
                    # empty because the disc made it empty. Not noting it
                    # leaves it looking exactly like a mis-bounded bank.
                    volume.note = "the bank header declares a zero-length sample area"
            yield volume

    def _declares_no_samples(self, image: SectorImage, offset: int, bank_at: int) -> bool:
        """Whether the bank header itself says its sample area is empty.

        A header too short to hold the field is *not* an explanation. That is
        the tail-damage case, where the honest answer is that this bank was not
        read, and letting it pass as "declared empty" would hide exactly the
        thing the note exists to make visible.
        """
        want = OFF_BANK_SAMPLE_BYTES + 4
        head = image.read(offset + bank_at, want)
        if len(head) < want:
            return False
        return struct.unpack_from("<I", head, OFF_BANK_SAMPLE_BYTES)[0] == 0

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
