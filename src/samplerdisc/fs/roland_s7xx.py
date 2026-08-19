"""Roland ``S770 MR25A`` filesystem. See docs/formats/roland-s7xx.md.

One on-disc format covers the S-770, S-750 and S-760, across system disks from
Ver. 1.04 to Ver. 2.25. It is not the S-550 format, which shares no magic, no
addressing and no directory record -- see ADR-0014.

The filesystem is a fixed block map, not a chain of pointers: the header
declares how many objects of each class exist, and every directory sits at a
constant 512-block. Only the sample *data* is chased, through a DOS-style FAT
at sector 257.

Every offset here is documented in the format doc against nine named discs --
four read end to end, five confirmed by range-fetching four regions each. Do
not change a constant without changing the doc, and vice versa.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from samplerdisc.fs.base import File, Volume, register

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

#: At byte 4, not byte 0 -- the first four bytes are zero.
#:
#: This is the *only* thing to probe on. The free-text field at 0x20 reads
#: "SYS-772 HardDisk Sys Ver. N.NN" on most discs and "S-760 System Disk
#: Ver.2.23Y" on L-CDX-02, so a probe keyed on "SYS-772" would silently drop
#: the whole L-CDX series while the format underneath is identical.
MAGIC = b"S770 MR25A"
OFF_MAGIC = 4

#: Addressing is in 512-byte blocks, not the 2048-byte cooked sector. That
#: ratio of four is where an off-by-four hides.
BLOCK = 512

#: 18 blocks. Not a power of two, which is the sort of thing one talks oneself
#: out of -- so see the format doc for the three independent measurements.
CLUSTER_BLOCKS = 18
CLUSTER = CLUSTER_BLOCKS * BLOCK

OFF_LABEL = 0x100
LABEL_LEN = 16
#: u32 LE, filesystem size in blocks. A bound on the highest legal cluster and
#: nothing more: it is not derivable and does not divide by CLUSTER on any of
#: the four reference discs.
OFF_FS_BLOCKS = 0x110
#: Five u16 LE counts: volumes, performances, patches, partials, samples.
OFF_COUNTS = 0x114

#: Allocation table: u16 LE per cluster, indexed by cluster number. Entries 0
#: and 1 are reserved and the first data cluster is 2, exactly as FAT12/16 does
#: it.
#:
#: 2 is the first *addressable* cluster, not the first *allocated* one -- the
#: four L-CDX discs start their first sample at cluster 116. Read the start
#: cluster from the directory; never assume where the data begins.
FAT_BLOCK = 1028
FIRST_DATA_CLUSTER = 2

#: Any value at or above this ends a chain, and the exact figure is load
#: bearing in both directions.
#:
#: Too high and a marker reads as a cluster: 0xFFF8 and 0xFFFA occur locally,
#: 0xFFFE remotely, so testing for 0xFFF8 alone runs a chain off the end of its
#: own file and into the next one.
#:
#: Too low and a cluster reads as a marker. The largest partition observed
#: declares 1 184 980 blocks, which is (1184980 - 5548) / 18 = 65 524 clusters
#: numbered 2..65 525 -- that is 0xFFF5, and l-cdx-01's last sample really does
#: occupy the top of it. A floor of 0xFFF0 silently drops that sample and
#: would truncate any chain passing through those five clusters.
#:
#: 0xFFF6 is above every cluster number the arithmetic can produce and below
#: every marker ever seen.
CHAIN_END = 0xFFF6

#: Where the sample data starts -- and it is exactly where the sample parameter
#: area ends: 8192 records of 48 bytes is precisely the 768 blocks from
#: SAMPLE_PARAM_BLOCK to here. The layout closes.
DATA_BLOCK = 5548

CLASS_VOLUME = 0x40
CLASS_PERFORMANCE = 0x41
CLASS_PATCH = 0x42
CLASS_PARTIAL = 0x43
CLASS_SAMPLE = 0x44

#: One directory per class, each at a constant block on all four reference
#: discs, each sized to exactly the distance to the next.
DIR_BLOCK = {
    CLASS_VOLUME: 1284,
    CLASS_PERFORMANCE: 1292,
    CLASS_PATCH: 1324,
    CLASS_PARTIAL: 1388,
    CLASS_SAMPLE: 1644,
}
DIR_CAPACITY = {
    CLASS_VOLUME: 128,
    CLASS_PERFORMANCE: 512,
    CLASS_PATCH: 1024,
    CLASS_PARTIAL: 4096,
    CLASS_SAMPLE: 8192,
}
#: The header's counts are in the same order as the classes above.
CLASS_ORDER = (CLASS_VOLUME, CLASS_PERFORMANCE, CLASS_PATCH, CLASS_PARTIAL, CLASS_SAMPLE)

ENTRY_LEN = 32
NAME_LEN = 16
OFF_ENTRY_CLASS = 16
OFF_ENTRY_START = 28
OFF_ENTRY_CLUSTERS = 30
#: Next/prev/own-index links. Present, cross-checkable, and not needed: entry i
#: is at base + i * ENTRY_LEN and the count comes from the header.
OFF_ENTRY_NEXT = 18
OFF_ENTRY_PREV = 20
OFF_ENTRY_INDEX = 22

#: Sample parameters, index-parallel to the sample directory. The relation is
#: the index and only the index -- northstar carries 7 records whose name is a
#: stale copy of a since-renamed directory entry, so matching on name drops
#: them silently.
SAMPLE_PARAM_BLOCK = 4780
PARAM_LEN = 48

#: Five 24.8 fixed-point addresses: a start point and **two loops**, which is
#: the S-7xx's own model -- a sustain loop and a release loop.
#:
#: The sustain pair was established by measuring every ordered pair of the five
#: for splice smoothness and for waveform-shape match; 20 -> 24 wins both, on
#: all five discs, and the loop start was not assumed. The release pair was
#: then forced by the records that do not fit any single-loop reading: on 166
#: samples (28, 32) is a verbatim copy of (20, 24), and on 6188 it is a handful
#: of frames parked at the end of the sample. Between them those two shapes
#: plus 38 damaged records account for all 6392.
OFF_PARAM_START = 16
OFF_PARAM_SUSTAIN_START = 20
OFF_PARAM_SUSTAIN_END = 24
OFF_PARAM_RELEASE_START = 28
OFF_PARAM_RELEASE_END = 32

#: None of the five is a length, and there is no length field. The end of the
#: audio is the furthest address the record references -- a sample must at
#: least reach the last point it points at.
#:
#: That is not a convenience: every single field fails on its own. 32 holds the
#: *cluster count* on 29 records ("STR:ArcBss f C_2" reads 13 against a real
#: end of 56 647 frames, so sizing a read from it emits 26 bytes of a 113 KB
#: sample as a WAV that opens perfectly and is silent), and 28 falls short of
#: the sustain loop on 166. Taking the furthest fits the allocation on 99.91%
#: of samples, contains its own loop on 100%, and closes the cluster
#: arithmetic on 99.84% -- better than 32 alone (99.4%) or 28 alone (97.3%).
END_ADDRESS_FIELDS = (OFF_PARAM_SUSTAIN_END, OFF_PARAM_RELEASE_START, OFF_PARAM_RELEASE_END)
OFF_PARAM_CLUSTERS = 42
#: An *open* enum: {0, 1, 2, 4} on four discs and 16 on l-cdx-01, the S-760.
#: Never gate on it -- rejecting an unknown value would have dropped 144 of
#: that disc's samples on the strength of a set four discs agreed on.
#:
#: It gates *playback*, not validity. Mode-0 samples carry loop addresses that
#: splice just as cleanly as mode-1 ones (80.6% against 86.5%), so a zero here
#: says the sampler does not loop the sample -- not that the addresses are
#: junk. Emit a loop when this is non-zero; conclude nothing when it is zero.
#: What the non-zero values distinguish is not established.
OFF_PARAM_LOOP_MODE = 44
OFF_PARAM_KEY = 45

#: Addresses are 24.8 fixed point: the low byte is a fractional sample, so the
#: frame address is the u32 shifted right by 8. Reading one as a plain u32
#: gives a byte address 256 times too large, which still lands inside a large
#: disc and so does not look wrong.
ADDRESS_SHIFT = 8

#: Measured, not decoded, and the measurement has a known blind spot: 44100 and
#: 22050 differ by exactly one octave, which is the interval pitch estimation
#: resolves worst and that an original-key byte can itself be wrong by. What
#: the measurement does establish is that every sample shares one rate and that
#: it is 44100 * 2**k -- every ratio measured lands within a few percent of an
#: exact power of two -- and that the majority land on k=0. No field in the
#: 48-byte record stratifies it. See ADR-0018 for what that exposes.
SAMPLE_RATE = 44100

#: Names are ASCII 32..126 plus 0x7F, over 4420 names on four discs. 0x7F is
#: the stereo side marker -- Roland's spelling of AKAI's "-L"/"-R".
STEREO_SIDE_MARKER = "\x7f"


def decode_name(raw: bytes) -> str:
    """A 16-byte directory name as text.

    Names are ASCII 32..126 plus 0x7F, which is Roland's stereo side marker and
    is deliberately *kept*: it is what pairs a sample with its other half, and
    ``extract`` sanitises it out of the filename later.
    """
    return raw.decode("ascii", "replace").rstrip("\x00 ").strip(" ")


def is_plausible_name(raw: bytes) -> bool:
    """Printable text, optionally NUL-padded.

    No name in 6 392 measured carries a NUL, but requiring their absence buys
    nothing and the E-mu backend was bitten once by assuming a padding style
    (ADR-0015), so trailing NULs are tolerated and the text before them is what
    must be printable. 0x7F is printable for this purpose.
    """
    text = raw.split(b"\x00", 1)[0]
    if not text.strip():
        return False
    return all(32 <= b <= 127 for b in text)


def max_cluster(fs_blocks: int) -> int:
    """Highest cluster number the declared partition size can hold.

    Bounds every walk, so a damaged extent or a corrupt chain cannot address
    outside the filesystem -- and it is the *disc's own* statement of its size
    rather than a constant, so it tightens automatically on a small disc.

    On the largest partition seen this returns 65 525, which is exactly
    CHAIN_END - 1. The two agree because CHAIN_END was chosen from this
    arithmetic; the cap is belt and braces against an absurd header.
    """
    if fs_blocks <= DATA_BLOCK:
        return FIRST_DATA_CLUSTER
    clusters = (fs_blocks - DATA_BLOCK) // CLUSTER_BLOCKS
    return min(FIRST_DATA_CLUSTER + clusters - 1, CHAIN_END - 1)


class RolandS7xxBackend:
    name = "roland_s7xx"

    def probe(self, image: SectorImage, offset: int) -> bool:
        """``S770 MR25A`` plus a sample directory whose first entry resolves.

        Two reads and no scan. The magic is ten bytes at a fixed offset, which
        is far stronger than AKAI's volume table -- but ADR-0012 is explicit
        that a magic plus a pointer is still only structure, and names this
        backend in its "watch for": the pointer must be followed and the thing
        it points at confirmed. So this reads the header's declared counts,
        checks each against its directory's capacity, and then opens the sample
        directory and requires a real entry with a real extent.
        """
        head = image.read(offset, OFF_COUNTS + 10)
        if len(head) < OFF_COUNTS + 10:
            return False
        if head[OFF_MAGIC : OFF_MAGIC + len(MAGIC)] != MAGIC:
            return False
        counts = struct.unpack_from("<5H", head, OFF_COUNTS)
        if any(n > DIR_CAPACITY[cls] for n, cls in zip(counts, CLASS_ORDER, strict=True)):
            return False
        if not 1 <= counts[4] <= DIR_CAPACITY[CLASS_SAMPLE]:
            return False
        (fs_blocks,) = struct.unpack_from("<I", head, OFF_FS_BLOCKS)
        if fs_blocks <= DATA_BLOCK:
            return False
        entry = image.read(offset + DIR_BLOCK[CLASS_SAMPLE] * BLOCK, ENTRY_LEN)
        return self._entry_extent(entry, max_cluster(fs_blocks)) is not None

    def _entry_extent(self, entry: bytes, top: int) -> tuple[str, int, int] | None:
        """(name, first cluster, cluster count) if this is a usable sample."""
        if len(entry) < ENTRY_LEN or entry[OFF_ENTRY_CLASS] != CLASS_SAMPLE:
            return None
        raw = entry[:NAME_LEN]
        if not is_plausible_name(raw):
            return None
        name = decode_name(raw)
        if not name:
            return None
        start, clusters = struct.unpack_from("<HH", entry, OFF_ENTRY_START)
        if clusters == 0 or start < FIRST_DATA_CLUSTER or start + clusters > top + 1:
            return None
        return name, start, clusters

    def _header(self, image: SectorImage, offset: int) -> tuple[str, tuple[int, ...], int]:
        head = image.read(offset, OFF_COUNTS + 10)
        label = decode_name(head[OFF_LABEL : OFF_LABEL + LABEL_LEN])
        counts = struct.unpack_from("<5H", head, OFF_COUNTS)
        (fs_blocks,) = struct.unpack_from("<I", head, OFF_FS_BLOCKS)
        return label, counts, fs_blocks

    def volumes(self, image: SectorImage, offset: int) -> Iterator[Volume]:
        """One volume, named from the ``ID<n>:`` label, holding every sample.

        The disc does have a hierarchy -- volume, performance, patch, partial,
        sample -- and this does not walk it (ADR-0016). Samples live in one
        flat global directory; what the chain above them provides is grouping,
        and two of its four record formats are undecoded. One verified volume
        beats thirteen guessed ones.
        """
        label, counts, fs_blocks = self._header(image, offset)
        volume = Volume(name=label or "S-7xx", start_block=DATA_BLOCK)
        volume.files = list(self._samples(image, offset, counts[4], fs_blocks))
        yield volume

    def _samples(
        self, image: SectorImage, offset: int, count: int, fs_blocks: int
    ) -> Iterator[File]:
        """Read exactly ``count`` directory entries -- never scan for an end.

        The header declares how many samples exist, so there is no terminator
        to mistake filler for. That is the failure this format simply does not
        have, and it is worth naming: on E-mu, walking past the last bank into
        0x42 filler produced entries that decoded perfectly plausibly.

        A malformed entry is skipped rather than ending the walk, because the
        count is the authority and one damaged slot must not hide the rest.
        """
        top = max_cluster(fs_blocks)
        directory = image.read(offset + DIR_BLOCK[CLASS_SAMPLE] * BLOCK, count * ENTRY_LEN)
        params = image.read(offset + SAMPLE_PARAM_BLOCK * BLOCK, count * PARAM_LEN)
        for index in range(count):
            entry = directory[index * ENTRY_LEN : (index + 1) * ENTRY_LEN]
            extent = self._entry_extent(entry, top)
            if extent is None:
                continue
            name, start, clusters = extent
            record = params[index * PARAM_LEN : (index + 1) * PARAM_LEN]
            yield self._file(name, start, clusters, record, top)

    def _file(self, name: str, start: int, clusters: int, record: bytes, top: int) -> File:
        """Join a directory entry to its parameter record -- by index, only.

        The two are index-parallel and the parameter record's *name* can be
        stale: NorthStar carries 7 samples the directory has since renamed. So
        the name comes from the directory and the pairing is never checked
        against it. Matching on name would drop exactly those 7, silently.
        """
        allocated = clusters * CLUSTER
        frames = 0
        key = loop_mode = loop_start = loop_end = point = 0
        release_start = release_end = 0
        if len(record) >= PARAM_LEN:

            def address(at: int) -> int:
                return struct.unpack_from("<I", record, at)[0] >> ADDRESS_SHIFT

            point = address(OFF_PARAM_START)
            loop_start = address(OFF_PARAM_SUSTAIN_START)
            loop_end = address(OFF_PARAM_SUSTAIN_END)
            release_start = address(OFF_PARAM_RELEASE_START)
            release_end = address(OFF_PARAM_RELEASE_END)
            frames = max(address(at) for at in END_ADDRESS_FIELDS)
            loop_mode = record[OFF_PARAM_LOOP_MODE]
            key = record[OFF_PARAM_KEY]
        # Clamp rather than trust, in the one direction that can be checked:
        # Edirol's "BRS:Cpm Tpt G_3A" declares 203 415 frames against 28
        # clusters, which hold 129 024. Reading the declared length would walk
        # straight into the next sample and report its audio as this one's -- a
        # longer file, not an error.
        #
        # The opposite direction cannot be clamped, only avoided, which is why
        # the end point is read from offset 28 and not 32. See OFF_PARAM_LENGTH.
        size = min(frames * 2, allocated) if frames else allocated
        return File(
            name=name,
            kind="sample",
            size=size,
            start_block=start,
            raw_type=loop_mode,
            meta=(
                ("rate", SAMPLE_RATE),
                ("key", key),
                ("clusters", clusters),
                ("loop_mode", loop_mode),
                ("loop_start", loop_start),
                ("loop_end", loop_end),
                ("release_start", release_start),
                ("release_end", release_end),
                ("start_point", point),
                ("declared_frames", frames),
                # This disc's own cluster ceiling, so read_file can bound the
                # chain without re-reading the header once per file.
                ("top_cluster", top),
            ),
        )

    def _chain(
        self, image: SectorImage, offset: int, start: int, clusters: int, top: int
    ) -> list[int]:
        """Follow the allocation table, bounded three ways.

        By the declared cluster count, by a terminator, and by the table's own
        range. All 6 392 chains measured are contiguous and that is *not* used:
        it is the same coincidence that held on E-mu's simple discs and broke
        on 41 of 46 banks on another, and here being wrong would splice a
        neighbour's audio onto the end of a sample.

        Reads a window rather than two bytes per hop, because a contiguous
        chain -- which is the common case -- then costs one read.
        """
        base = offset + FAT_BLOCK * BLOCK
        window = image.read(base + 2 * start, 2 * (clusters + 8))
        out: list[int] = []
        cluster = start
        while len(out) < clusters:
            out.append(cluster)
            index = cluster - start
            if 0 <= index < len(window) // 2:
                (nxt,) = struct.unpack_from("<H", window, 2 * index)
            else:
                raw = image.read(base + 2 * cluster, 2)
                if len(raw) < 2:
                    break
                (nxt,) = struct.unpack("<H", raw)
            if nxt >= CHAIN_END or not FIRST_DATA_CLUSTER <= nxt <= top:
                break
            cluster = nxt
        return out

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        """Gather a sample's clusters along the chain, in runs.

        A short read is a damaged disc, not an error: the caller gets what the
        disc still holds.
        """
        clusters = entry.get("clusters")
        if not clusters:
            return b""
        top = entry.get("top_cluster", CHAIN_END - 1)
        chain = self._chain(image, offset, entry.start_block, clusters, top)
        out = bytearray()
        run_start = run_len = 0
        for cluster in chain:
            if run_len and cluster == run_start + run_len:
                run_len += 1
                continue
            if run_len:
                out += self._read_run(image, offset, run_start, run_len)
            run_start, run_len = cluster, 1
        if run_len:
            out += self._read_run(image, offset, run_start, run_len)
        return bytes(out[: entry.size])

    def _read_run(self, image: SectorImage, offset: int, first: int, count: int) -> bytes:
        at = DATA_BLOCK * BLOCK + (first - FIRST_DATA_CLUSTER) * CLUSTER
        return image.read(offset + at, count * CLUSTER)

    def parse_sample(self, entry: File, payload: bytes):
        """The parameters travelled on the File; the payload is already PCM.

        Everything this needs was read from the 48-byte parameter record during
        the directory walk, because on this format that record lives at block
        4780 and the audio lives past block 5548 -- there is no header in front
        of the samples to parse.
        """
        from samplerdisc.sample import roland_s7xx as sample_roland

        return sample_roland.parse(
            payload,
            rate=entry.get("rate", SAMPLE_RATE),
            key=entry.get("key"),
            loop_mode=entry.get("loop_mode"),
            loop_start=entry.get("loop_start"),
            loop_end=entry.get("loop_end"),
            fallback_name=entry.name,
        )

    def original_suffix(self, entry: File) -> str:
        return ".s7s" if entry.kind == "sample" else ".bin"


register(RolandS7xxBackend())
