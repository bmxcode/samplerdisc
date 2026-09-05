"""E-mu ``EMU3`` filesystem. See docs/formats/emu3.md.

One on-disc format spans three product lines the archives file separately --
EIIIX, ESI/Formula 4000 and E-IV all write ``EMU3`` at byte 0 and the same
folder and bank directories (ADR-0014). The *bank interior* is not shared, and
that is the one place this module branches: EIII/ESI banks carry an
``EMULATOR``-family header and are located by it, while E-IV banks carry none
and are reached through a chained ``E3S1`` sample directory instead (ADR-0020).
A located bank owns the records inside the run its own header declares, and
nothing else that happens to lie in its region (ADR-0021).

Every offset here is documented in the format doc against a named disc. Do not
change a constant without changing the doc, and vice versa.
"""

from __future__ import annotations

import re
import struct
from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING, NamedTuple

from samplerdisc.fs.base import File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

MAGIC = b"EMU3"

#: Directory addressing is in 512-byte blocks, not the 2048-byte cooked sector.
BLOCK = 512

#: The real allocation table. A FAT begins at block 2 of every EMU3 master and
#: is a flat array of u16 LE cluster-chain entries -- EMU's own variant of a
#: classic FAT (docs/formats/emu3.md, "The block-2 FAT"; mpc2emu
#: EMU3_ISO_FORMAT.md). ``fat[0]`` is a reserved media slot; clusters are
#: numbered from ``FIRST_CLUSTER``, and a directory entry's ``start`` field is a
#: cluster index. The table runs from block 2 up to the folder table at
#: ``OFF_FOLDER_BLOCK`` -- so its extent is read from the header, never assumed
#: (mpc2emu's fixed blocks 2-6 hold only on its own corpus; ``0x08`` takes
#: {6, 7, 9} across ours).
#:
#: ``unit * start + bias`` (the per-disc fits below) is exactly ``block(start)``
#: -- the block address of cluster ``start`` -- so a bank's own header address
#: is what the FAT predicts for its first cluster. The fit and the FAT agree to
#: the byte on every disc; the FAT is the *independent* structure that
#: corroborates it, and it is the authority when a file is fragmented, which the
#: linear fit cannot express. See docs/formats/emu3.md and ADR-0037.
OFF_FAT_START_BLOCK = 2
FAT_RESERVED = 0x8000
FAT_EOC = 0x7FFF
FIRST_CLUSTER = 1

#: Header fields, all u32 LE. ``FOLDER_BLOCK + FOLDER_RESERVED == BANK_BLOCK``
#: holds on every disc measured, so the third is derived and the first is the
#: authority -- see the note on folders in volumes().
OFF_FOLDER_BLOCK = 0x08
OFF_FOLDER_RESERVED = 0x0C
OFF_BANK_BLOCK = 0x10

#: The 512-byte header block carries a superblock checksum: the sum modulo
#: 2**16 of the 255 u16 LE words over bytes 0x000-0x1FD, stored as a u16 LE at
#: 0x1FE. It holds on every EMU3 master (docs/formats/emu3.md, "The superblock
#: checksum" and "Independent corroboration") and, being a sum over the whole
#: block, fails on a truncated or mis-offset header -- so probe() gates on it to
#: reject a wrong container track start before the directory walk (ADR-0005,
#: issue #66).
SUPERBLOCK_LEN = 0x200
OFF_CHECKSUM = 0x1FE

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
#:
#: The 16-byte signature reads ``"EMULATOR 3X    \0"`` on EIIIX and ESI,
#: ``"EMULATOR THREE \0"`` on EIII and ``"EMU SI-32 v3   \0"`` on the two
#: Formula 4000 banks of `protozoa`. Matching the family prefix rather than
#: the whole field is deliberate: a ROM revision that changes the version
#: suffix would otherwise hide a bank, and the name at ``OFF_BANK_NAME`` --
#: which has to match a directory entry -- is what actually confirms the hit.
#:
#: `protozoa` is why the second family is here at all. ``Orbit Presets 4k``
#: and ``Phatt Presets 4K`` are ordinary banks with an ordinary interior; they
#: were invisible only because their header says ``EMU SI-32`` where their
#: neighbours say ``EMULATOR``, and an unlocated bank hands its region to the
#: bank in front of it.
BANK_MAGICS = (b"EMULATOR", b"EMU SI-32")
OFF_BANK_NAME = 16
BANK_NAME_LEN = 16

#: u32 LE, bytes before the bank's sample area, and the anchor the walk starts
#: from. Every record a bank owns lies at or after it.
OFF_BANK_SAMPLE_START = 0x30

#: The first record of a populated bank starts exactly this far into the
#: declared sample area -- on 107 of the 110 populated banks of the four
#: EIII/ESI reference discs, and on none of them any earlier.
#: ``OFF_BANK_SAMPLE_BYTES`` measures the run from there, so the run ends at
#: ``0x30 + SAMPLE_AREA_PREAMBLE + 0x34``, where the last record ends exactly
#: (72 banks) or one 92-byte header short (19). The remaining 19 are looser in
#: both directions -- 11 whose last record's payload overshoots, 8 whose run
#: has slack -- which is why the run gates where a record *starts* and never
#: where its audio ends.
SAMPLE_AREA_PREAMBLE = 74

#: u32 LE, the length of the bank's record run, measured from its first
#: record. Together with OFF_BANK_SAMPLE_START this is the bank's own
#: statement of which records are its own, and it is the bound the walk uses
#: (ADR-0021). Reads **zero** on 4 of the 114 located banks: one index bank on
#: each of `esi32-gm`, `eiiix-1` and `eiiix-2`, plus `protozoa`'s ``Protozoa
#: X`` -- each of which carries the library's contents list and no audio.
#:
#: A zero here therefore makes the run empty, and the note that follows an
#: empty walk restates the bound rather than corroborating it independently.
#: That is a real loss and it is taken deliberately: the alternative measured
#: on `protozoa` was to credit ``Protozoa       X`` with 63 records that are,
#: name for name, the Phatt banks' (ADR-0021).
OFF_BANK_SAMPLE_BYTES = 0x34

#: Sample record, relative to its own start. A record begins two bytes before
#: its name; those two bytes are zero on every record after the first on the
#: EIII discs, and are not on `ditto-drums`, so nothing is tested on them.
SAMPLE_NAME_OFFSET = 2
OFF_SAMPLE_RATE = 54

#: The eight-pointer block, and the reason the fields either side of it read as
#: nonsense when sampled at four-byte strides from ``+18``. Every one is a
#: **byte offset from the record's own start**, naming the first byte of a
#: 16-bit word, and they come in (left, right) pairs -- the EIII is a
#: stereo-capable sampler and writes a pointer per channel (ADR-0025).
#:
#: ``OFF_SAMPLE_START_L`` is the field this walk scans for. It reads 92 because
#: the header is 92 bytes and the audio begins immediately after it, so the
#: same value serves as the record signature and as the start pointer -- which
#: is what it always was. It reads **0** on 542 of `studio`'s records and 146
#: of `analogia`'s: those declare no left channel and put 92 at
#: ``OFF_SAMPLE_START_R`` instead, which is a different value of a working
#: field rather than a broken one.
#:
#: An earlier revision of this module gave ``+34`` a second name,
#: ``OFF_SAMPLE_RECORD_LEN``, and took the record's extent from it
#: unconditionally. It is the **right channel's** end, and it closes the record
#: only where the right-hand set is what describes this record's audio. Four
#: shapes on seven discs say otherwise, and ``record_extent`` below is the rule
#: that replaced it (ADR-0029).
OFF_SAMPLE_START_L = 22
OFF_SAMPLE_START_R = 26
OFF_SAMPLE_END_L = 30
OFF_SAMPLE_END_R = 34
OFF_SAMPLE_LOOP_START_L = 38
OFF_SAMPLE_LOOP_START_R = 42
OFF_SAMPLE_LOOP_END_L = 46
OFF_SAMPLE_LOOP_END_R = 50

#: The two channels' pointer sets, each as ``(start, end, loop start, loop
#: end)``. The set whose start reads 92 is the one that describes the audio;
#: the other is its mirror, or zeroed where the record declares one channel.
POINTER_SETS = (
    (OFF_SAMPLE_START_L, OFF_SAMPLE_END_L, OFF_SAMPLE_LOOP_START_L, OFF_SAMPLE_LOOP_END_L),
    (OFF_SAMPLE_START_R, OFF_SAMPLE_END_R, OFF_SAMPLE_LOOP_START_R, OFF_SAMPLE_LOOP_END_R),
)

#: What the pointers are carried on the ``File`` as. The filesystem layer reads
#: them and does not judge them; which set describes the audio, and whether the
#: loop it names is usable, is decided in ``sample/emu3.py`` -- the same split
#: Roland S-7xx uses, where the parameters also arrive beside the audio rather
#: than in front of it.
POINTER_KEYS = (
    ("start_l", "end_l", "loop_start_l", "loop_end_l"),
    ("start_r", "end_r", "loop_start_r", "loop_end_r"),
)

#: An end pointer names the first byte of the *last* word rather than one past
#: it, so the extent it closes runs two bytes further on. ``END_POINTER_BIAS``
#: in sample/emu3.py is the same fact seen from the loop side.
END_POINTER_BIAS = 2

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

#: An E-IV bank also occurs as a native ``FORM/E4B0`` IFF bank file -- presets
#: and samples in one container -- rather than as a flat run of records indexed
#: by a chained ``E3S1`` directory. Each embedded sample is an ``E3S1`` IFF
#: *chunk*: the four-byte tag, a big-endian u32 size, then an ordinary sample
#: record (the 92-byte header and its PCM). The chunk size plays the part the
#: directory's big-endian length plays for a flat bank, and the record inside
#: is exactly what the flat path reads at ``EIV_RECORD_OFFSET`` -- so the same
#: record, pointer, loop and stereo path applies unchanged.
#:
#: The single per-disc allocation fit predicts a FORM bank's base as it does a
#: flat bank's: the ``FORM`` tag sits at ``BLOCK * (unit * start + bias)``,
#: exactly where a flat bank's first ``E3S1`` record prefix would. Only the
#: interior differs. See docs/formats/emu3.md, "The FORM/E4B0 bank" (ADR-0032).
EIV_FORM_MAGIC = b"FORM"
EIV_FORM_TYPE = b"E4B0"
OFF_FORM_SIZE = 4
OFF_FORM_TYPE = 8
FORM_HEADER_LEN = 12

#: A preset chunk inside a ``FORM/E4B0`` bank. Its body opens with the same
#: two-byte prefix and 16-byte name field an ``E3S1`` sample record does, so the
#: name reads at ``SAMPLE_NAME_OFFSET``. On a bank that carries audio the preset
#: is the instrument definition and is left to ConvertWithMoss (ADR-0011); the
#: only ``E4P1`` this project reads is the *name line* of a sample-free text
#: bank (``Credits``, ``E-mu Systems 96``), as disc provenance (ADR-0043).
EIV_PRESET_MAGIC = b"E4P1"

#: An IFF chunk header: a four-byte id and a big-endian u32 size. The E-IV
#: sample record is the body that follows it.
IFF_CHUNK_HEADER = 8

_SCAN_CHUNK = 1 << 23

#: Enough to cover a directory entry (32) and a record's header reached at
#: +8 (8 + 92), with room to spare, so a tag near a chunk edge still resolves.
_EIV_WINDOW = 128


def decode_name(raw: bytes) -> str:
    """Bank and sample names are plain ASCII, space padded."""
    return raw.decode("ascii", "replace").rstrip("\x00 ").strip()


def _levenshtein(a: str, b: str) -> int:
    """Edit distance, iterative single-row -- small strings, called rarely."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _near_name(directory: str, header: str) -> bool:
    """Whether a bank header's own name is a corrupted copy of the directory's.

    A handful of banks carry a header whose 16-byte name field at
    ``OFF_BANK_NAME`` is the directory's name mis-typed by the mastering: a
    doubled or dropped character and a shifted space, never more. Normalising
    away case and spaces and allowing a single further edit matches every one
    measured and clears the things that are genuinely a different bank by a wide
    margin (see docs/formats/emu3.md, "A header's name can be a corrupted copy
    of the directory's", and ADR-0031):

    * ``Electric Grand X`` / ``Eelectric GrandX`` -- one insert
    * ``PERCUSSION#1   X`` / ``PERCUSSION #1  X`` -- equal once spaces go
    * ``HvyGtr FX5     X`` / ``HvyGtr FX5    XX`` -- one insert
    * ``Misc Gtr FX 2MbX`` / ``Misc Gtr FX 2mbX`` -- equal once case folds
    * ``HvGtrFdBkTxtr2Mb`` / ``HvGtrFdBkTxtr2M`` -- one delete

    against the operating-system slots, whose header addresses happen to fall on
    another bank's header entirely: ``E3 Main Code`` / ``Ditto Drums    X`` and
    ``E3X Main Code`` / ``DAVE W  KIT1   X`` are both a dozen edits apart. The
    gate is what keeps the placement arithmetic from binding an OS slot to the
    audio it points at by accident.
    """

    def norm(name: str) -> str:
        return name.lower().replace(" ", "")

    return _levenshtein(norm(directory), norm(header)) <= 1


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


def sample_pointers(head: bytes) -> tuple[tuple[str, int], ...]:
    """The eight-pointer block off a record header, as ``File.meta`` pairs.

    Read and carried, not judged: a pointer that is zero, odd or past the end
    of the audio travels exactly as the disc wrote it, and ``sample/emu3.py``
    decides what is usable. Keeping the reading here and the judgement there is
    what stops a loop rule from having to be re-derived if a fourth E-mu
    generation turns up with a ninth pointer.

    Returns ``()`` for a header too short to hold the block, which is tail
    damage: a record that was not fully read must not present as one that
    declared nothing.
    """
    if len(head) < OFF_SAMPLE_LOOP_END_R + 4:
        return ()
    return tuple(
        (key, struct.unpack_from("<I", head, offset)[0])
        for keys, offsets in zip(POINTER_KEYS, POINTER_SETS, strict=True)
        for key, offset in zip(keys, offsets, strict=True)
    )


def record_extent(head: bytes) -> int | None:
    """How far the record runs from its own start, or ``None`` if it says nothing.

    **The set that opens the audio is the set that closes it.** A record's
    audio begins immediately after its 92-byte header, so the pointer set
    describing it starts at ``SAMPLE_HEADER_LEN`` -- which is the rule
    ``sample/emu3.py`` already used to pick a loop, and never applied to the
    extent. Taking ``+34`` as the record length instead is right only where the
    right-hand set happens to describe this record, and four shapes across the
    seven EIII/ESI reference discs say it does not (ADR-0029):

    * ``start_r == start_l - 92`` with ``end_r == end_l - 92`` -- the same
      channel written from the payload's start rather than the record's. The
      extent taken from ``+34`` is **92 bytes short**, on 2 127 records of
      `esi32-gm` and 3 965 of `protozoa`.
    * ``start_r == end_r == 0`` -- the unused side zeroed. ``+34`` gives an
      extent of 2, which is shorter than the header, so the record is rejected
      outright: 872 records on `ditto-drums`, nine of its ten silent banks.
    * ``start_r == 92 + F`` and ``end_r == 92 + 2F - 2`` for a constant memory
      frame ``F`` -- 1 MiB on `emu-classics`, 2 MiB on `eiiix-1`. ``+34`` then
      names an address past the whole bank region and the record is dropped as
      unreadable.
    * the one channel declared on the **right**: ``start_r == 92`` and the
      left set not opening the audio, which on 1 371 of the 1 429 is
      ``start_l == 0`` exactly. docs/formats/emu3.md records 542 of
      `eiv-studio`'s that way; the EIII walk never looked, so 353 on
      `esi32-gm`, 607 on `protozoa` and all of `vintage`'s ``Juno Synths``
      were never listed at all.

    The exception is a genuine two-channel record, where the payload is both
    blocks and the far end is the right channel's: the right block opens
    exactly where the left one closes and the two are the same length. That is
    ADR-0026's gate stated from the pointer side instead of the payload side --
    the same three conditions, without needing the size the caller is asking
    for, so there is no circularity here.

    ``None`` for a header too short to hold the block, or one where neither set
    opens the audio. Both are refusals rather than guesses: a record that was
    not read must not present as one that declared nothing.
    """
    if len(head) < OFF_SAMPLE_END_R + 4:
        return None
    start_l, start_r, end_l, end_r = struct.unpack_from("<4I", head, OFF_SAMPLE_START_L)
    if (
        start_l == SAMPLE_HEADER_LEN
        and start_r == end_l + END_POINTER_BIAS
        and end_r - start_r == end_l - start_l
    ):
        return end_r + END_POINTER_BIAS
    # Both sets open the audio on many EIII records, and then they disagree
    # about where it ends by a few bytes in either direction. The stride to the
    # next record follows the larger on every disc measured.
    declared = [
        end for start, end in ((start_l, end_l), (start_r, end_r)) if start == SAMPLE_HEADER_LEN
    ]
    if not declared:
        return None
    return max(declared) + END_POINTER_BIAS


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


def _eiv_scan(image: SectorImage, offset: int) -> dict[int, bytes]:
    """Every ``E3S1`` tag in the image, with the bytes that follow it.

    Keyed by address relative to ``offset`` -- the filesystem origin -- and
    scanned from there, for the reason _bank_headers() is: the addresses feed
    reads taken at ``offset + address``, and the filesystem does not always
    begin at byte 0 (ADR-0005).
    """
    found: dict[int, bytes] = {}
    position = offset
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
                found[base + at - offset] = window
        carry = haystack[-_EIV_WINDOW:]
        position += len(chunk)
    return found


def _eiv_record_name(window: bytes) -> str | None:
    """The name of the sample record eight bytes into ``window``, if any.

    A record is confirmed by its own tag and its name, *not* by the header
    length at ``OFF_SAMPLE_START_L``. That field reads 92 on most E-IV
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


def _form_e3s1_chunks(image: SectorImage, at: int) -> Iterator[tuple[int, int]]:
    """Walk a ``FORM/E4B0`` bank's top-level ``E3S1`` sample chunks.

    ``at`` is the image-absolute offset of the ``FORM`` tag. Yields
    ``(record_offset, record_length)`` for each embedded sample -- the absolute
    offset of the chunk body, which is a sample record, and its declared length.

    The declared FORM size **understates** the container by a few bytes on
    every reference disc: the last ``E3S1`` chunk's body ends 4 to 12 bytes past
    it, and only the next region's bytes follow. So the declared size bounds
    where a chunk may *begin* -- past it lies garbage that decodes as an
    enormous chunk -- while a chunk's body is bounded by the image alone. A
    chunk whose body is not wholly present is dropped, so a truncated bank
    degrades to the samples that survive rather than raising (ADR-0012).
    """
    head = image.read(at, FORM_HEADER_LEN)
    if (
        len(head) < FORM_HEADER_LEN
        or head[:4] != EIV_FORM_MAGIC
        or head[OFF_FORM_TYPE : OFF_FORM_TYPE + 4] != EIV_FORM_TYPE
    ):
        return
    (form_size,) = struct.unpack_from(">I", head, OFF_FORM_SIZE)
    header_end = min(at + IFF_CHUNK_HEADER + form_size, image.size)
    position = at + FORM_HEADER_LEN
    while position + IFF_CHUNK_HEADER <= header_end:
        header = image.read(position, IFF_CHUNK_HEADER)
        if len(header) < IFF_CHUNK_HEADER:
            return
        tag = header[:4]
        (size,) = struct.unpack_from(">I", header, 4)
        if size <= 0:
            return
        body = position + IFF_CHUNK_HEADER
        if body + size > image.size:
            return  # tail damage: the chunk body is not wholly present.
        if tag == EIV_MAGIC:
            yield body, size
        # IFF pads an odd chunk to a two-byte boundary.
        position = body + size + (size & 1)


def _form_e4p1_credits(image: SectorImage, at: int) -> list[str]:
    """The credit lines a sample-free ``FORM/E4B0`` text bank carries.

    ``at`` is the image-absolute offset of the ``FORM`` tag. Walks the container
    the same way ``_form_e3s1_chunks`` does -- declared chunk sizes from the
    header, the size bounding where a chunk may *begin* -- and reads the 16-byte
    name field of each ``E4P1`` preset chunk, which sits at ``SAMPLE_NAME_OFFSET``
    exactly as a sample record's does. On the ``Credits`` and ``E-mu Systems 96``
    banks that name field holds one line of disc provenance (author, house,
    contact, thanks); the preset parameters beside it are never read (ADR-0043).

    Only the *name* is read, so this is metadata, not the preset ADR-0011
    defers. A chunk whose body is not wholly present, or whose name is not
    plausible, is skipped -- tail damage degrades to the lines that survive
    rather than raising (ADR-0012).
    """
    head = image.read(at, FORM_HEADER_LEN)
    if (
        len(head) < FORM_HEADER_LEN
        or head[:4] != EIV_FORM_MAGIC
        or head[OFF_FORM_TYPE : OFF_FORM_TYPE + 4] != EIV_FORM_TYPE
    ):
        return []
    (form_size,) = struct.unpack_from(">I", head, OFF_FORM_SIZE)
    header_end = min(at + IFF_CHUNK_HEADER + form_size, image.size)
    position = at + FORM_HEADER_LEN
    lines: list[str] = []
    while position + IFF_CHUNK_HEADER <= header_end:
        header = image.read(position, IFF_CHUNK_HEADER)
        if len(header) < IFF_CHUNK_HEADER:
            break
        tag = header[:4]
        (size,) = struct.unpack_from(">I", header, 4)
        if size <= 0:
            break
        body = position + IFF_CHUNK_HEADER
        if body + size > image.size:
            break  # tail damage: the chunk body is not wholly present.
        if tag == EIV_PRESET_MAGIC:
            raw = image.read(body + SAMPLE_NAME_OFFSET, ENTRY_NAME_LEN)
            if len(raw) == ENTRY_NAME_LEN and is_plausible_name(raw):
                name = decode_name(raw)
                if name:
                    lines.append(name)
        # IFF pads an odd chunk to a two-byte boundary.
        position = body + size + (size & 1)
    return lines


def _read_fat(image: SectorImage, offset: int) -> list[int]:
    """The block-2 FAT as a list of u16 LE cluster-chain entries.

    Its extent is blocks ``2 .. OFF_FOLDER_BLOCK-1`` -- read from the header, not
    assumed, because the folder table's block varies per disc and the FAT fills
    the gap before it. ``fat[0]`` is the reserved media slot; every other entry
    is the next cluster in a chain or ``FAT_EOC``. Returns ``[]`` for a header
    that places the folder table at or before the FAT, which is damage.
    """
    head = image.read(offset, OFF_BANK_BLOCK + 4)
    if len(head) < OFF_BANK_BLOCK + 4:
        return []
    folder_block = struct.unpack_from("<I", head, OFF_FOLDER_BLOCK)[0]
    if folder_block <= OFF_FAT_START_BLOCK:
        return []
    raw = image.read(
        offset + OFF_FAT_START_BLOCK * BLOCK, (folder_block - OFF_FAT_START_BLOCK) * BLOCK
    )
    return list(struct.unpack_from(f"<{len(raw) // 2}H", raw))


def _fat_chain(fat: list[int], start: int) -> list[int]:
    """The cluster chain from ``start``, bounded three ways.

    By the end-of-chain marker (``FAT_EOC``; the reserved ``0x8000`` and any gap
    fall out of the same test), by the table's own range, and by a visited set,
    so a table that pointed a cluster back into its own chain degrades rather
    than spins (ADR-0012). Returns ``[]`` for a ``start`` outside the table.
    """
    out: list[int] = []
    cluster = start
    seen: set[int] = set()
    while FIRST_CLUSTER <= cluster < len(fat) and cluster not in seen:
        out.append(cluster)
        seen.add(cluster)
        nxt = fat[cluster]
        if nxt >= FAT_EOC or nxt < FIRST_CLUSTER:
            break
        cluster = nxt
    return out


def _fat_contiguous(chain: list[int]) -> bool:
    """Whether a chain's clusters ascend by one -- the file is unfragmented.

    Nine of the ten reference discs are wholly contiguous, and the tenth is one
    fragmented bank (vitous ``CES 1``). A contiguous bank reads the same whether
    its bytes are gathered along the chain or read straight from the image, so
    this is what lets the contiguous path stay byte-for-byte the current one.
    """
    return all(chain[i + 1] == chain[i] + 1 for i in range(len(chain) - 1))


def _fat_byte(unit: int, bias: int, cluster: int) -> int:
    """The offset-relative first byte of ``cluster``.

    ``unit * cluster + bias`` is the block address of the cluster (the same
    linear form the per-disc fit measures; ``unit * start + bias`` is just this
    at the bank's own first cluster), so the byte address is that times
    ``BLOCK``. The fit and the FAT are the same arithmetic seen from two sides.
    """
    return BLOCK * (unit * cluster + bias)


def _form_bank_bytes(
    image: SectorImage, offset: int, fat: list[int], unit: int, bias: int, start_cluster: int
) -> bytes:
    """A ``FORM/E4B0`` bank gathered along its FAT chain, contiguous runs coalesced.

    Used only for a fragmented bank; a contiguous one is read straight from the
    image on the current path. Coalescing a run into one read keeps the gather
    to a handful of ``image.read`` calls even for a bank split into a few
    fragments -- the same shape ``fs/kurzweil.py`` uses for its FAT16 chains.
    """
    cluster_bytes = unit * BLOCK
    out = bytearray()
    run_start = run_len = 0
    for cluster in _fat_chain(fat, start_cluster):
        if run_len and cluster == run_start + run_len:
            run_len += 1
        else:
            if run_len:
                at = offset + _fat_byte(unit, bias, run_start)
                out += image.read(at, run_len * cluster_bytes)
            run_start, run_len = cluster, 1
    if run_len:
        out += image.read(offset + _fat_byte(unit, bias, run_start), run_len * cluster_bytes)
    return bytes(out)


def _form_chunks_in_buffer(buf: bytes) -> Iterator[tuple[int, int]]:
    """Walk a gathered ``FORM/E4B0`` bank's top-level ``E3S1`` chunks.

    The buffer-relative twin of ``_form_e3s1_chunks``: the bank is already
    gathered along its chain, so a chunk body is bounded by the buffer rather
    than the image. Yields ``(body_offset_in_buffer, record_length)``.
    """
    if (
        len(buf) < FORM_HEADER_LEN
        or buf[:4] != EIV_FORM_MAGIC
        or buf[OFF_FORM_TYPE : OFF_FORM_TYPE + 4] != EIV_FORM_TYPE
    ):
        return
    (form_size,) = struct.unpack_from(">I", buf, OFF_FORM_SIZE)
    header_end = min(IFF_CHUNK_HEADER + form_size, len(buf))
    position = FORM_HEADER_LEN
    while position + IFF_CHUNK_HEADER <= header_end:
        tag = buf[position : position + 4]
        (size,) = struct.unpack_from(">I", buf, position + 4)
        if size <= 0:
            return
        body = position + IFF_CHUNK_HEADER
        if body + size > len(buf):
            return  # tail damage: the chunk body is not wholly present.
        if tag == EIV_MAGIC:
            yield body, size
        position = body + size + (size & 1)


def _superblock_checksum_ok(head: bytes) -> bool:
    """Whether the header block's checksum at ``OFF_CHECKSUM`` is self-consistent.

    See the ``SUPERBLOCK_LEN``/``OFF_CHECKSUM`` note above. A header short of a
    whole block cannot carry the checksum and is rejected; a header at the wrong
    offset sums to something other than its stored word.
    """
    if len(head) < SUPERBLOCK_LEN:
        return False
    words = struct.unpack_from(f"<{SUPERBLOCK_LEN // 2}H", head)
    return sum(words[: OFF_CHECKSUM // 2]) % 0x10000 == words[OFF_CHECKSUM // 2]


class Emu3Backend:
    name = "emu3"

    def __init__(self) -> None:
        #: The last fragmented ``FORM`` bank gathered along its chain, keyed by
        #: ``(id(image), offset, start_cluster)``. A bank's samples are extracted
        #: back to back and all slice the same gathered buffer, so a one-slot
        #: cache turns the per-sample reads into one gather -- the same shape
        #: ``fs/kurzweil.py`` uses. Only a fragmented bank ever reaches it.
        self._form_cache: tuple[tuple[int, int, int], bytes] | None = None

    def probe(self, image: SectorImage, offset: int) -> bool:
        """``EMU3``, a valid superblock checksum, and a folder table that resolves.

        The magic is four bytes, which is not enough on its own (ADR-0012). The
        superblock checksum is the strong gate: it sums the whole header block,
        so a truncated rip or a wrong container track start fails it here rather
        than walking a garbage directory (ADR-0005, issue #66). The magic is
        checked first, because an all-zeros block sums to its own zeroed
        checksum and would pass the sum on its own. The header's own arithmetic
        is then checked and the directory it points at must yield a bank.
        """
        head = image.read(offset, SUPERBLOCK_LEN)
        if not head.startswith(MAGIC) or not _superblock_checksum_ok(head):
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

    def _bank_headers(self, image: SectorImage, offset: int) -> list[tuple[int, str]]:
        """Every bank header on the image, as ``(address, bank name)``.

        Addresses are relative to ``offset`` -- the filesystem origin, not the
        start of the file -- so that the scan agrees with every read below,
        which is taken at ``offset + address``. The scan itself begins at
        ``offset``: a header sitting in a pregap or an earlier track ahead of
        the filesystem is not this filesystem's, and byte 0 is not where the
        filesystem always starts (ADR-0005).

        Duplicates are kept. A disc writes the same bank twice -- an older
        revision left in an unallocated region, or a copy running off the end
        of the image -- and which of them a directory entry means is decided
        in _bank_offsets(), not here.

        Returns an empty list for a disc whose banks carry no header, which is
        the E-IV case and is why those are reached through a sample directory.
        """
        found: list[tuple[int, str]] = []
        pattern = re.compile(b"|".join(re.escape(magic) for magic in BANK_MAGICS))
        position = offset
        carry = b""
        while position < image.size:
            chunk = image.read(position, _SCAN_CHUNK)
            if not chunk:
                break
            haystack = carry + chunk
            base = position - len(carry)
            for match in pattern.finditer(haystack):
                at = match.start()
                raw = haystack[at + OFF_BANK_NAME : at + OFF_BANK_NAME + BANK_NAME_LEN]
                if len(raw) == BANK_NAME_LEN and is_plausible_name(raw):
                    found.append((base + at - offset, decode_name(raw)))
            carry = haystack[-64:]
            position += len(chunk)
        return sorted(set(found))

    def _placement(
        self, banks: list[_Bank], headers: list[tuple[int, str]]
    ) -> tuple[int, int] | None:
        """Fit ``header address == unit * start + bias`` across the disc.

        ADR-0015 refused to *place* a bank by arithmetic on ``start`` and that
        stands: nothing here places anything. The fit is measured from headers
        already located by signature, and its only use is to say which of two
        headers wearing the same name the directory entry meant -- exactly the
        way ADR-0020 fits an allocation unit for E-IV and then only ever uses
        it to confirm a chain it found independently.

        Only banks whose name resolves to a single header may vote. A name
        written twice is the question being asked, so it cannot also be the
        evidence. Measured: 45 of 45 votes agree on `eiiix-1` and `eiiix-2`,
        14 of 14 on `protozoa`, 6 of 6 on `esi32-gm`.
        """
        at_name: dict[str, list[int]] = {}
        for at, name in headers:
            at_name.setdefault(name, []).append(at)
        fixed = [(b.start, at_name[b.name][0]) for b in banks if len(at_name.get(b.name, ())) == 1]
        best: tuple[int, int, int] | None = None
        for first_start, first_at in fixed:
            for start, at in fixed:
                span = start - first_start
                gap = at - first_at
                if span <= 0 or gap <= 0 or gap % span:
                    continue
                unit = gap // span
                bias = first_at - unit * first_start
                agree = sum(1 for s, a in fixed if unit * s + bias == a)
                if best is None or agree > best[0]:
                    best = (agree, unit, bias)
        # A fit derived from a pair is satisfied by that pair for free, so two
        # agreements prove nothing; three is the first that is corroborated.
        # Below that the disc has not shown a placement rule and the first
        # header of each name is as good an answer as any.
        if best is None or best[0] < 3:
            return None
        return best[1], best[2]

    def _bank_offsets(self, banks: list[_Bank], headers: list[tuple[int, str]]) -> dict[int, int]:
        """The header each directory entry binds to, keyed by the entry's index.

        Keyed by entry and **not** by name, because a directory may write one
        name twice and the two entries then sit at different addresses. Keying
        by name collapses both onto one header and lists its records under each
        -- the same audio read twice, which is a different failure from the one
        ADR-0031 recovers and is filed as #47 (ADR-0034). `elements1mb` writes
        ``Harpsichord    X`` twice with a real header apiece; `heavy` writes
        ``HvyGtr Maj.Open`` twice, and only one of the two headers wears the
        name.

        Keying on the name alone and keeping the first hit also reads the wrong
        copy where a disc holds two headers of one name. `esi32-gm` carries an
        older revision of ``2.5M Drums+SFX X`` and ``1.3M Drums+SFX X`` in a
        region its directory does not allocate, both *before* the banks the
        directory points at; `protozoa` carries a second ``Phatt Presets  X``
        after them. Whichever end you take, one of those discs is read wrong.

        So a name written once binds to its single header, or -- where the disc
        holds two of that name -- to the one the placement fit predicts
        (ADR-0021). A name written twice cannot share a header, so each entry
        binds only to the header at its *own* predicted address; an entry whose
        prediction lands on no same-named header is left to the recovery below
        or to its note, never collapsed onto its twin's header.

        An entry no header names exactly is then given one last chance: the
        header sitting at the address its placement predicts, when that header
        carries a near-copy of the entry's name (ADR-0031). Five banks across
        three discs -- ``Electric Grand X``, ``PERCUSSION#1   X``, ``HvyGtr FX5
        X``, ``Misc Gtr FX 2MbX``, ``HvGtrFdBkTxtr2Mb`` -- have a real
        ``EMULATOR`` header the mastering mis-typed the name on, and were listed
        empty with a note where their audio was plainly there. This never
        *places* a bank: the header is one the signature scan already found, and
        the name at ``+16`` is what confirms it -- the same instrument the
        placement fit already uses to arbitrate a name written twice, one step
        wider.
        """
        at_name: dict[str, list[int]] = {}
        for at, name in headers:
            at_name.setdefault(name, []).append(at)
        entries_of = Counter(bank.name for bank in banks)

        # A name written once binds to its first header; a name written twice
        # cannot, so it waits for the placement fit to give each entry its own.
        found: dict[int, int] = {}
        for index, bank in enumerate(banks):
            addresses = at_name.get(bank.name)
            if addresses and entries_of[bank.name] == 1:
                found[index] = addresses[0]

        placement = self._placement(banks, headers)
        if placement is None:
            return found
        unit, bias = placement
        # Placement is authoritative about which header an entry means. For a
        # name written once this only re-picks between two same-named headers
        # (ADR-0021); for a name written twice it is what assigns each entry the
        # header at its own predicted address, splitting the two apart.
        for index, bank in enumerate(banks):
            want = unit * bank.start + bias
            if want in at_name.get(bank.name, ()):
                found[index] = want
        # Recovery. ``taken`` is every address already bound, so an entry can
        # never be bound to a header another entry owns -- which keeps
        # ``ditto-drums``'s ``E3 Main Code`` off the ``Ditto Drums    X`` header
        # its arithmetic lands on, and keeps `heavy`'s first ``HvyGtr Maj.Open``
        # entry off the blank-named header at its predicted address, whose name
        # confirms nothing and whose audio the second entry already yields
        # (ADR-0034). ``by_address`` names the header actually sitting at
        # ``want``; an entry whose predicted address holds no header, or one
        # whose name is not a near-copy of it, keeps its note.
        by_address = {at: name for at, name in headers}
        taken = set(found.values())
        for index, bank in enumerate(banks):
            if index in found:
                continue
            want = unit * bank.start + bias
            header_name = by_address.get(want)
            if header_name is None or want in taken:
                continue
            if _near_name(bank.name, header_name):
                found[index] = want
                taken.add(want)
        return found

    def _declared_run(
        self, image: SectorImage, offset: int, bank_at: int
    ) -> tuple[int, int] | None:
        """The bank's own statement of its record run, relative to the bank.

        ``(start, end)`` where ``start`` is ``0x30``, the bytes before the
        sample area, and ``end`` is one ``0x34`` past the first record. A
        header too short to hold both fields returns ``None``: that is tail
        damage, and a bank that was not read must not come back looking like
        a bank that declared nothing.
        """
        want = OFF_BANK_SAMPLE_BYTES + 4
        head = image.read(offset + bank_at, want)
        if len(head) < want:
            return None
        start, length = struct.unpack_from("<II", head, OFF_BANK_SAMPLE_START)
        return start, start + SAMPLE_AREA_PREAMBLE + length

    def _eiv(self, image: SectorImage, offset: int, banks: list[_Bank]):
        """Locate E-IV banks and bind each to the samples at its predicted base.

        Returns ``(tags, bound, form_bound, geom)``. ``bound`` maps a bank's
        ``start`` to the ``(base, entries)`` of the confirmed flat ``E3S1``
        directory that lives at the address that start predicts. ``form_bound``
        maps a bank's ``start`` to the offset-relative address of a ``FORM/E4B0``
        IFF bank sitting there instead -- the native E-IV bank file, whose
        samples are ``E3S1`` chunks rather than a flat record run (ADR-0032).
        ``geom`` is the fitted ``(unit, bias)`` -- the cluster geometry the FORM
        read follows the FAT chain with, so a fragmented bank is gathered from
        the right clusters (ADR-0037); ``None`` when no bank needs the E-IV path.
        The single per-disc allocation fit places both interiors; only the
        interior differs, so a bank binds one way or the other, never both.

        Every address is relative to ``offset``, the filesystem origin. A bank
        in neither map has no samples the disc lets us reach and stays noted.
        """
        tags = _eiv_scan(image, offset)
        bases, corroborated = _eiv_bases(tags, _eiv_chains(_eiv_entries(tags)))
        if not corroborated:
            return tags, {}, {}, None
        fitted = _eiv_unit(sorted(corroborated), sorted(bases), [bank.start for bank in banks])
        if fitted is None:
            return tags, {}, {}, None
        unit, bias = fitted
        bound: dict[int, tuple[int, list[_EivEntry]]] = {}
        form_bound: dict[int, int] = {}
        for bank in banks:
            block = unit * bank.start + bias
            if block < 0:
                continue
            base = BLOCK * block + EIV_RECORD_OFFSET
            entries = bases.get(base)
            if entries is not None:
                bound[bank.start] = (base, entries)
                continue
            # No flat directory here -- but the same address may hold the FORM
            # tag of a native E-IV bank file. ``base - EIV_RECORD_OFFSET`` is the
            # block-aligned address a flat bank's first record prefix would sit
            # at, and it is where the FORM starts.
            form_at = BLOCK * block
            head = image.read(offset + form_at, FORM_HEADER_LEN)
            if (
                len(head) >= FORM_HEADER_LEN
                and head[:4] == EIV_FORM_MAGIC
                and head[OFF_FORM_TYPE : OFF_FORM_TYPE + 4] == EIV_FORM_TYPE
            ):
                form_bound[bank.start] = form_at
        return tags, bound, form_bound, (unit, bias)

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
                # The tag window already holds the record's header, so the
                # pointers cost no extra read on either path.
                meta=sample_pointers(window[EIV_RECORD_OFFSET:]),
            )

    def _eiv_form_samples(
        self,
        image: SectorImage,
        offset: int,
        fat: list[int],
        unit: int,
        bias: int,
        start_cluster: int,
        form_at: int,
    ) -> Iterator[File]:
        """One ``FORM/E4B0`` bank's samples, one per embedded ``E3S1`` chunk.

        **A contiguous bank is read straight from the image, byte for byte the
        way it always was.** Nine of the ten reference discs are wholly
        contiguous and so is every FORM bank but one, so this branch is what
        every current sample except ``CES 1``'s takes -- the FAT changes nothing
        it does not have to.

        **A fragmented bank is gathered along its FAT chain first.** ``CES 1`` on
        `eiv-vitous` is split into three runs, and the contiguous read stops at
        the first break, stranding eight real samples in the tail. Gathering the
        bank from the clusters the FAT names recovers them, and their PCM (which
        may straddle a fragment boundary) is read the same way in ``read_file``,
        through the ``embedded`` route ``fs/kurzweil.py`` uses for a sample that
        is a slice of a bank rather than a file the disc placed (ADR-0037).
        """
        if _fat_contiguous(_fat_chain(fat, start_cluster)):
            yield from self._eiv_form_samples_flat(image, offset, form_at)
            return
        buf = _form_bank_bytes(image, offset, fat, unit, bias, start_cluster)
        for body, length in _form_chunks_in_buffer(buf):
            head = buf[body : body + SAMPLE_HEADER_LEN]
            if len(head) < SAMPLE_HEADER_LEN:
                continue
            raw = head[SAMPLE_NAME_OFFSET : SAMPLE_NAME_OFFSET + ENTRY_NAME_LEN]
            if not is_plausible_name(raw):
                continue
            name = decode_name(raw)
            if not name:
                continue
            size = length - SAMPLE_HEADER_LEN
            if size <= 0 or size % 2:
                continue
            (rate,) = struct.unpack_from("<I", head, OFF_SAMPLE_RATE)
            if not MIN_RATE <= rate <= MAX_RATE:
                continue
            yield File(
                name=name,
                kind="sample",
                size=size,
                # An object inside a gathered bank, not a flat image address:
                # ``read_file`` re-gathers the chain and slices at ``data_off``,
                # carrying ``unit``/``bias`` so it can without re-fitting.
                start_block=start_cluster,
                raw_type=rate,
                meta=(
                    *sample_pointers(head),
                    ("embedded", 1),
                    ("data_off", body + SAMPLE_HEADER_LEN),
                    ("unit", unit),
                    ("bias", bias),
                ),
            )

    def _eiv_form_samples_flat(
        self, image: SectorImage, offset: int, form_at: int
    ) -> Iterator[File]:
        """A contiguous ``FORM/E4B0`` bank's samples, read straight from the image.

        The chunk body is an ordinary sample record, so this is the flat path
        with the IFF chunk header standing in for the ``E3S1`` directory: the
        chunk's big-endian size is the record length, and the record's own
        header carries the name, rate and pointer block the rest of the E-mu
        path reads. A chunk whose record does not parse -- a short body from
        tail damage, an implausible name, a length that is not a positive even
        number of PCM bytes -- is dropped, never guessed at (ADR-0012).
        """
        for record, length in _form_e3s1_chunks(image, offset + form_at):
            head = image.read(record, SAMPLE_HEADER_LEN)
            if len(head) < SAMPLE_HEADER_LEN:
                continue
            raw = head[SAMPLE_NAME_OFFSET : SAMPLE_NAME_OFFSET + ENTRY_NAME_LEN]
            if not is_plausible_name(raw):
                continue
            name = decode_name(raw)
            if not name:
                continue
            size = length - SAMPLE_HEADER_LEN
            if size <= 0 or size % 2:
                continue
            (rate,) = struct.unpack_from("<I", head, OFF_SAMPLE_RATE)
            if not MIN_RATE <= rate <= MAX_RATE:
                continue
            yield File(
                name=name,
                kind="sample",
                size=size,
                start_block=record - offset + SAMPLE_HEADER_LEN,
                raw_type=rate,
                meta=sample_pointers(head),
            )

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        banks = self._banks(image, offset)
        headers = self._bank_headers(image, offset)
        located = self._bank_offsets(banks, headers)
        # A bank ends where its own header says its records end, and no later
        # than the next bank header on the disc. Neither bound is enough
        # alone: the next header is 16 MiB away where `protozoa` gives a bank
        # 8 MiB of records, and a header damaged in the rip would declare a
        # run reaching into whatever follows it.
        boundaries = sorted({at for at, _ in headers})
        # The E-IV scan is a pass over the image, so it runs once and only when
        # a bank actually needs it. An all-EIII disc never pays for it.
        eiv_tags: dict[int, bytes] = {}
        eiv_bound: dict[int, tuple[int, list[_EivEntry]]] = {}
        eiv_form: dict[int, int] = {}
        eiv_geom: tuple[int, int] | None = None
        eiv_fat: list[int] = []
        if any(index not in located for index in range(len(banks))):
            eiv_tags, eiv_bound, eiv_form, eiv_geom = self._eiv(image, offset, banks)
            if eiv_form:
                # The FAT is read only when a FORM bank is present -- to follow
                # its chain in case the bank is fragmented (ADR-0037).
                eiv_fat = _read_fat(image, offset)
        for index, bank in enumerate(banks):
            volume = Volume(name=bank.name, start_block=bank.start)
            at = located.get(index)
            if at is None:
                found = eiv_bound.get(bank.start)
                form_at = eiv_form.get(bank.start)
                if found is not None:
                    volume.files = list(self._eiv_samples(eiv_tags, *found))
                elif form_at is not None and eiv_geom is not None:
                    # A native ``FORM/E4B0`` E-IV bank: its samples are the
                    # ``E3S1`` chunks inside the IFF container (ADR-0032), read
                    # along the FAT chain so a fragmented bank is gathered from
                    # the right clusters (ADR-0037).
                    unit, bias = eiv_geom
                    volume.files = list(
                        self._eiv_form_samples(
                            image, offset, eiv_fat, unit, bias, bank.start, form_at
                        )
                    )
                    if not volume.files:
                        # A FORM the disc placed here that holds no sample
                        # chunk -- the ``Credits`` text banks and a few
                        # preset/globals banks. Correctly located and genuinely
                        # sample-free, which the note must say rather than
                        # borrowing the "no sample directory" wording, now that
                        # a bank without a flat directory may still carry audio.
                        volume.note = "the bank holds presets or text and no samples; listed only"
                        # The audio note stays accurate, but these banks carry
                        # disc provenance in their ``E4P1`` name fields -- read
                        # it as metadata for a ``Credits.txt`` sidecar, the name
                        # line alone and never the preset (ADR-0043).
                        volume.credits = _form_e4p1_credits(image, offset + form_at)
                elif located:
                    # A bank the directory lists and no header on the disc
                    # claims. On an EIII/ESI disc that is the sampler's own
                    # code -- ``E3 Main Code``, ``E3X Main Code`` -- which is
                    # a bank slot holding an operating system and no audio.
                    # Saying "no sample directory" here was borrowed from the
                    # E-IV case and named a structure this disc never has.
                    volume.note = "no bank header found for this bank; listed only"
                else:
                    # An E-IV bank with neither a confirmed sample directory nor
                    # a FORM at its predicted base. Real, correctly named, and
                    # not guessed at -- the note is what tells this apart from a
                    # probe that matched garbage (ADR-0012).
                    volume.note = "no sample directory found for this bank; listed only"
            else:
                after = [b for b in boundaries if b > at]
                limit = after[0] if after else image.size
                run = self._declared_run(image, offset, at)
                # The run says where the bank's records *start*. Its last
                # record's payload may run past the declared end -- 8 records
                # across `eiiix-1` and `eiiix-2` do -- so the run gates the
                # record, and the next header still gates the read.
                span = run if run is not None else (0, limit - at)
                volume.files = list(self._samples(image, offset, at, span, limit))
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

    def _samples(
        self,
        image: SectorImage,
        offset: int,
        bank_at: int,
        span: tuple[int, int],
        limit: int,
    ) -> Iterator[File]:
        """Enumerate a bank's sample records by signature, within its bounds.

        Chaining on the declared length is the obvious walk and it does not
        hold: records sit back to back in runs -- a 15-record piano
        multisample on the reference disc -- and then a gap appears, after
        which the "next" record lands inside PCM and decodes as noise. So the
        records are found rather than followed.

        The signature is specific enough to survive a scan through megabytes of
        audio: one of the two start pointers must open the audio at exactly
        ``SAMPLE_HEADER_LEN``, the rate must be plausible, and sixteen bytes
        must be printable. On the reference bank that yields 531 records with
        531 distinct, sensible names totalling 8 248 316 bytes, which is that
        bank's declared run to the byte.

        **Either** start, not only the left one. A record may declare its one
        channel on the right, with the left zeroed, and scanning for the left
        pointer alone makes those invisible rather than wrong -- all of
        `vintage`'s ``Juno Synths``, and 980 records across the four EIII/ESI
        reference discs that were never listed (ADR-0029). The two anchors are
        deduplicated by address, and the result is yielded in address order so
        that which anchor found a record cannot change what is written.

        Specific is not the same as exclusive, which is why ``span`` matters
        as much as the signature does. A bank's region holds whatever the
        mastering left there as well as the bank, and a record found outside
        the declared run is real -- it is simply another bank's (ADR-0021).
        ``span`` gates where a record may start; ``limit`` is how far the
        window reaches, and a record may declare a payload that runs past the
        span but not past the window.
        """
        first, last = span
        window = image.read(offset + bank_at, max(limit - bank_at, 0))
        needle = struct.pack("<I", SAMPLE_HEADER_LEN)
        found: dict[int, File] = {}
        for match in re.finditer(re.escape(needle), window):
            for anchor in (OFF_SAMPLE_START_L, OFF_SAMPLE_START_R):
                at = match.start() - anchor
                if at < 0 or at in found or not first <= at < last:
                    continue
                record = self._parse_record(window[at : at + SAMPLE_HEADER_LEN])
                if record is None:
                    continue
                name, extent, rate = record
                if at + extent > len(window):
                    continue
                found[at] = File(
                    name=name,
                    kind="sample",
                    size=extent - SAMPLE_HEADER_LEN,
                    start_block=bank_at + at + SAMPLE_HEADER_LEN,
                    raw_type=rate,
                    meta=sample_pointers(window[at : at + SAMPLE_HEADER_LEN]),
                )
        for at in sorted(found):
            yield found[at]

    def _parse_record(self, head: bytes) -> tuple[str, int, int] | None:
        raw = head[SAMPLE_NAME_OFFSET : SAMPLE_NAME_OFFSET + ENTRY_NAME_LEN]
        if not is_plausible_name(raw):
            return None
        name = decode_name(raw)
        if not name:
            return None
        # The header length is the constant 92, not something read out of the
        # record: ``+22`` is a start pointer and reads 0 where the record
        # declares its channel on the right (ADR-0029).
        extent = record_extent(head)
        if extent is None or extent <= SAMPLE_HEADER_LEN:
            return None
        (rate,) = struct.unpack_from("<I", head, OFF_SAMPLE_RATE)
        if not MIN_RATE <= rate <= MAX_RATE:
            return None
        return name, extent, rate

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        """One entry's bytes.

        Every EIII and E-IV record but a fragmented FORM bank's is a flat run at
        a byte address the disc placed, so the common path is one read. A sample
        marked ``embedded`` is an object inside a fragmented ``FORM`` bank whose
        PCM may straddle a cluster-fragment boundary, so its bytes are a slice of
        the bank gathered along the FAT chain -- the bank is gathered once,
        cached, and sliced (ADR-0037), the same route ``fs/kurzweil.py`` takes.
        """
        if entry.get("embedded"):
            return self._form_sample_bytes(image, offset, entry)
        return image.read(offset + entry.start_block, entry.size)

    def _form_sample_bytes(self, image: SectorImage, offset: int, entry: File) -> bytes:
        key = (id(image), offset, entry.start_block)
        cached = self._form_cache
        if cached is None or cached[0] != key:
            fat = _read_fat(image, offset)
            buf = _form_bank_bytes(
                image, offset, fat, entry.get("unit"), entry.get("bias"), entry.start_block
            )
            self._form_cache = cached = (key, buf)
        data_off = entry.get("data_off")
        return cached[1][data_off : data_off + entry.size]

    def parse_sample(self, entry: File, payload: bytes):
        """The record's rate and pointers travelled on the File; the payload is
        already PCM.

        The 92 header bytes are in hand during the walk and gone by the time
        the audio is read, so the loop pointers come across on the ``File``
        rather than being parsed out of the payload -- the same route the
        Roland parameters take, for the same reason.
        """
        from samplerdisc.sample import emu3 as sample_emu3

        return sample_emu3.parse(
            payload,
            rate=entry.raw_type,
            fallback_name=entry.name,
            pointers={key: entry.get(key) for key in sum(POINTER_KEYS, ())} if entry.meta else {},
        )

    def original_suffix(self, entry: File) -> str:
        return ".e3s" if entry.kind == "sample" else ".bin"


register(Emu3Backend())
