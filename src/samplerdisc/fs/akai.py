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

#: Fields within a volume entry. The type is a **byte** at 12, and 13 is a
#: separate field -- reading the pair as one u16 inflates the type by 256 per
#: volume on the one disc where 13 is not zero. See docs/formats/akai-fs.md.
VOLUME_TYPE_OFFSET = 12
VOLUME_INDEX_OFFSET = 13
VOLUME_START_OFFSET = 14

#: Volume type byte: which sampler owns the volume, or 0 for one the sampler
#: will not load. Counted across 44 discs: 338 type 1, 91 type 7, 9 type 3,
#: 10 type 0. It is NOT an allocation flag -- four type-0 volumes carry 63
#: files between them, which is why the allocation map below does that job.
VOLUME_TYPE_INACTIVE = 0
VOLUME_TYPES = {0: "inactive", 1: "S1000", 3: "S3000", 7: "CD3000"}

#: File entries within a volume, 24 bytes each.
FILE_ENTRY_LEN = 24

#: The type byte is ASCII. S3000 discs set the high bit -- 0xF3 for 's', 0xF0
#: for 'p' -- so mask with 0x7F, never with 0x0F: the low nibble alone cannot
#: tell 'd' (0x64, drum settings) from 't' (0x74).
TYPE_MASK = 0x7F

#: A cleared type byte marks a deleted entry, not a file.
TYPE_DELETED = 0x00

#: Type letters seen on real discs. 'q' and 't' appear once each and have not
#: been identified, but they are letters an AKAI wrote, so they end an entry
#: rather than a directory. Anything outside this set means the walk has left
#: the directory -- an unallocated volume can point at a block of filler, and
#: without this every byte of it reads as a file.
VALID_TYPE_LETTERS = frozenset("psdxmqt")
TYPE_KINDS = {
    "p": "program",
    "s": "sample",
    "d": "drum-settings",
    "x": "effects",
    "m": "multi",
}

#: Sample payload header (docs/formats/akai-fs.md).
SAMPLE_HEADER_LEN = 150
SAMPLE_ID = 3
PROGRAM_ID = 1
SAMPLE_VALID = 0x80

_MAX_VOLUMES = 100

#: The partition header's first u16: the partition's size in blocks, which is
#: also the number of entries in the allocation map. A partition is far smaller
#: than the disc -- 3840 to 7680 blocks across the 44 discs measured, against
#: images of 27 000 to 82 000 -- so this bounds the map, never the image.
PARTITION_BLOCKS_OFFSET = 0x00

#: The partition's **block allocation map**, one u16 per block, immediately
#: after the volume directory's hundred slots. This is the disc's own record of
#: what each block holds, and it is what tells a live volume from a slot that
#: was formatted and never used -- a question the volume entry itself cannot
#: answer. Verified across all 44 AKAI discs: every one of 14 607 files has a
#: chain of exactly ceil(size / BLOCK_SIZE) blocks, counting the files of the
#: five deleted volumes out -- their blocks went back to the free list, so
#: their chains no longer describe the audio still sitting in them.
#: See docs/formats/akai-fs.md and ADR-0022.
FAT_OFFSET = VOLUME_DIR_OFFSET + _MAX_VOLUMES * VOLUME_ENTRY_LEN

#: Allocation map codes. Anything below FAT_VOLUME_DIR is the next block of a
#: chain, so a file's extent is walked by following them to FAT_CHAIN_END.
FAT_FREE = 0x0000
FAT_VOLUME_DIR = 0x4000
FAT_CHAIN_END = 0xC000

#: A volume's file directory is one block. Reading further walks into the next
#: block, which is file data, and yields entries assembled from audio.
_MAX_FILES = BLOCK_SIZE // FILE_ENTRY_LEN

#: Volume slots examined by probe(). Enough to see ordering, cheap enough to
#: run at every candidate sector during origin detection.
_PROBE_SLOTS = 8

#: File entries probe() reads from the first allocated volume before accepting
#: an origin. Deep enough to see past a run of deleted entries, shallow enough
#: to stay one short read.
_PROBE_FILE_ENTRIES = 8


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


def allocation_map(image: SectorImage, offset: int) -> list[int]:
    """The partition's block allocation map, or ``[]`` when it cannot be read.

    Bounded by the partition's own declared block count rather than by the
    image, which is the whole point: the map is the disc speaking about itself,
    so a disc that declares nothing usable gets no map and no notes derived
    from one, instead of a map invented out of whatever follows the header.
    """
    declared = image.read(offset + PARTITION_BLOCKS_OFFSET, 2)
    if len(declared) < 2:
        return []
    (blocks,) = struct.unpack("<H", declared)
    available = max((image.size - offset) // BLOCK_SIZE, 0)
    if not 0 < blocks <= available:
        return []
    raw = image.read(offset + FAT_OFFSET, blocks * 2)
    usable = len(raw) // 2
    return list(struct.unpack(f"<{usable}H", raw[: usable * 2]))


def why_empty(allocation: list[int], start_block: int) -> str:
    """Why a volume holding no files holds none, in the disc's own words.

    Every branch reports what the allocation map *declares* about the block and
    stops there. It deliberately does not diagnose: a free block under a volume
    that lists nothing is a slot formatted and never used on one disc and a
    damaged image on another, and the map cannot tell them apart. Saying which
    would be inventing the half that is not written down (ADR-0022).

    An empty string means the map does not account for the emptiness, which is
    the ADR-0012 signature and has to stay visible as such.
    """
    if not 0 <= start_block < len(allocation):
        return ""
    code = allocation[start_block]
    if code == FAT_FREE:
        return f"block {start_block} is free in the partition's allocation map"
    if code == FAT_VOLUME_DIR:
        return (
            f"the partition's allocation map marks block {start_block} a volume "
            f"directory, but no file entry could be read there"
        )
    if 0 < code < FAT_VOLUME_DIR or code == FAT_CHAIN_END:
        return (
            f"the partition's allocation map assigns block {start_block} to file "
            f"data, not to a volume directory"
        )
    return (
        f"the partition's allocation map does not mark block {start_block} a "
        f"volume directory (code 0x{code:04x})"
    )


class AkaiBackend:
    name = "akai"

    def probe(self, image: SectorImage, offset: int) -> bool:
        """Recognise an AKAI partition header.

        Deliberately strict: this runs at every candidate offset during origin
        detection, and a loose probe resolves an origin confidently and wrongly
        (ADR-0005). Two things must hold. The volume entries must have names
        that decode cleanly and start blocks that are ordered and in range --
        and then the first allocated volume must actually yield a file.

        The second half is not belt-and-braces. The first half alone matched
        arbitrary data on two non-AKAI discs (ADR-0012), and the structural
        checks cannot tell that on their own: a directory that merely looks
        plausible produces volumes with no files in them, not an error.
        """
        want = VOLUME_DIR_OFFSET + _PROBE_SLOTS * VOLUME_ENTRY_LEN
        header = image.read(offset, want)
        if len(header) < want:
            return False

        max_block = max((image.size - offset) // BLOCK_SIZE, 1)
        previous = -1
        found = 0
        first_start = 0
        for index in range(_PROBE_SLOTS):
            base = VOLUME_DIR_OFFSET + index * VOLUME_ENTRY_LEN
            entry = header[base : base + VOLUME_ENTRY_LEN]
            if is_empty_slot(entry):
                continue
            raw_name = entry[:NAME_LEN]
            if not is_plausible_name(raw_name):
                return False
            (start,) = struct.unpack("<H", entry[VOLUME_START_OFFSET:VOLUME_ENTRY_LEN])
            if start == 0:
                # AKAI pre-formats every slot with a default name like
                # "VOLUME 008", so an unused one is a named entry -- not an
                # empty slot, and not a reason to reject. Pointing at block 0
                # is one way an unused slot presents and not the only one:
                # three discs keep a stale start block from formatting
                # instead, which the allocation map is what settles
                # (ADR-0022). Here it is only skipped as a probe candidate.
                continue
            # Start blocks are ordered and in range; that ordering is what
            # separates a real header from bytes that merely decode cleanly.
            if start > max_block or start <= previous:
                return False
            previous = start
            found += 1
            first_start = first_start if first_start else start
        if found == 0:
            return False
        # Ordering and clean names are not enough on their own. Arbitrary data
        # mid-disc satisfies both often enough to matter: an E-mu EMU3 disc and
        # a SampleCell disc each resolved confidently to a wrong offset here,
        # yielding volumes with names like "010000000000" and zero files in
        # every one. So the probe finishes by asking the question the walk will
        # ask -- does a volume actually hold a file? -- rather than trusting
        # that a plausible-looking directory is one. See ADR-0012.
        return self._directory_looks_real(image, offset, first_start)

    def _directory_looks_real(self, image: SectorImage, offset: int, start_block: int) -> bool:
        """Does a volume's file directory yield a file the walk would accept?

        The tests below are deliberately the ones ``_files`` applies, type byte
        included. When a probe accepts an entry the walk then rejects, the disc
        comes back as volumes containing nothing -- which reads as an empty
        disc rather than as a wrong answer, and is exactly how the false
        positives in ADR-0012 presented.
        """
        directory = image.read(
            offset + start_block * BLOCK_SIZE, _PROBE_FILE_ENTRIES * FILE_ENTRY_LEN
        )
        if len(directory) < FILE_ENTRY_LEN:
            return False
        for index in range(len(directory) // FILE_ENTRY_LEN):
            entry = directory[index * FILE_ENTRY_LEN : (index + 1) * FILE_ENTRY_LEN]
            if is_empty_slot(entry):
                continue
            if not is_plausible_name(entry[:NAME_LEN]) or not decode_name(entry[:NAME_LEN]):
                return False
            type_byte = entry[16]
            if type_byte == TYPE_DELETED:
                # A deletion does not end the directory, and must not end this
                # check either -- the live entries can sit behind it.
                continue
            if chr(type_byte & TYPE_MASK) not in VALID_TYPE_LETTERS:
                return False
            size = entry[17] | entry[18] << 8 | entry[19] << 16
            (file_start,) = struct.unpack("<H", entry[20:22])
            if size > 0 and file_start > 0:
                return True
        return False

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        header = image.read(offset, VOLUME_DIR_OFFSET + _MAX_VOLUMES * VOLUME_ENTRY_LEN)
        max_block = (image.size - offset) // BLOCK_SIZE
        # Read once for the whole partition: 7680 entries is 15 KB at the
        # largest seen, against a walk that opens a block per volume anyway.
        allocation = allocation_map(image, offset)
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
            (start,) = struct.unpack("<H", entry[VOLUME_START_OFFSET:VOLUME_ENTRY_LEN])
            if not name or start == 0 or start > max_block:
                continue
            volume = Volume(name=name, start_block=start)
            volume.files = list(self._files(image, offset, start, max_block))
            if not volume.files:
                # A volume that lists nothing has to say why, and the answer
                # comes from the disc rather than from a judgement about how
                # plausible its directory looks (ADR-0012, ADR-0022). A slot
                # is still listed either way: the four type-0 volumes on this
                # collection that read as free carry 63 files between them,
                # so "the map calls it free" is not grounds for dropping one.
                volume.note = why_empty(allocation, start)
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
                return
            name = decode_name(raw_name)
            if not name:
                return
            type_byte = entry[16]
            size = entry[17] | entry[18] << 8 | entry[19] << 16
            (file_start,) = struct.unpack("<H", entry[20:22])
            # Damaged rips are common; skip what cannot be read rather than
            # abandoning the disc.
            if file_start == 0 or file_start > max_block or size <= 0:
                continue
            if type_byte == TYPE_DELETED:
                # A deleted file keeps its name but loses its type, and its
                # blocks go back to the free list (0xFF-filled). Skipping the
                # entry rather than stopping: a deletion mid-directory must not
                # truncate everything after it.
                continue
            letter = chr(type_byte & TYPE_MASK)
            if letter not in VALID_TYPE_LETTERS:
                return
            kind = TYPE_KINDS.get(letter, f"type-{letter}")
            yield File(
                name=name,
                kind=kind,
                size=size,
                start_block=file_start,
                raw_type=type_byte,
            )

    def read_file(self, image: SectorImage, origin: int, entry: File) -> bytes:
        return image.read(origin + entry.start_block * BLOCK_SIZE, entry.size)

    def original_suffix(self, entry: File) -> str:
        """Name an original after the machine that wrote it.

        The type byte's high bit distinguishes an S3000-family disc from an
        S1000 one, so the generation is read off the disc rather than assumed:
        ``.s3p``/``.s3s`` or ``.s1p``/``.s1s``. This is naming only -- the bytes
        are whatever the sampler stored, unaltered.
        """
        letter = chr(entry.raw_type & TYPE_MASK)
        if letter not in ("p", "s"):
            letter = "x"
        generation = "s3" if entry.raw_type & 0x80 else "s1"
        return f".{generation}{letter}"


register(AkaiBackend())
