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

#: Any value at or above this ends a chain. 0xFFF8 and 0xFFFA occur locally and
#: 0xFFFE was seen remotely; testing for 0xFFF8 alone runs a chain off the end
#: of its own file and into the next one.
CHAIN_END = 0xFFF0

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
OFF_PARAM_START = 16
OFF_PARAM_SUSTAIN = 20
OFF_PARAM_END = 32
OFF_PARAM_CLUSTERS = 42
#: An *open* enum: the four local discs show only {0, 1, 2, 4} and l-cdx-01
#: opens with 16. Carry the byte through and never gate on it -- rejecting an
#: unknown value here would drop most of that disc on the strength of a set
#: four discs happened to agree on.
OFF_PARAM_LOOP_MODE = 44
OFF_PARAM_KEY = 45

#: Addresses are 24.8 fixed point: the low byte is a fractional sample, so the
#: frame address is the u32 shifted right by 8. Reading one as a plain u32
#: gives a byte address 256 times too large, which still lands inside a large
#: disc and so does not look wrong.
ADDRESS_SHIFT = 8

#: Measured, not decoded. Pitch against the original-key byte lands on 44100 on
#: every sample checked across four discs, and no rate field has been
#: identified. See ADR-0018 for what that exposes.
SAMPLE_RATE = 44100

#: Names are ASCII 32..126 plus 0x7F, over 4420 names on four discs. 0x7F is
#: the stereo side marker -- Roland's spelling of AKAI's "-L"/"-R".
STEREO_SIDE_MARKER = "\x7f"
