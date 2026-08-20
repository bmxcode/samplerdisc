"""MDS descriptor beside MDF data -- the split form of what MDX merges.

The descriptor shares its 16-byte ``MEDIA DESCRIPTOR`` magic with the merged
.mdx, so the two cannot be told apart by the magic alone. The major version at
0x10 does it: 1 on the split descriptor, 2 on the merged image. Testing the
magic first sent every real .mds to the MDX parser, where a zero read out of a
field that is not a descriptor offset surfaced as ``implausible descriptor
offset 0`` -- see docs/formats/mdx.md and ADR-0004.

The descriptor itself is still not parsed. Geometry is sniffed from the .mdf
the same way a bare .bin is: sync pattern means raw 2352-byte sectors,
otherwise cooked 2048. That is correct for a single-track data disc, which is
what these are, and it is confirmed on the one pair in hand -- `Back In Time
Records Korg Universe vol.1 1CD AKAI` reads as 260 287 cooked sectors carrying
an AKAI filesystem, and the descriptor holds that same 260 287 in a u32 at 0x5C.

What this does not do is read the MDS at all -- so a multi-track or offset image
will be read from byte 0. If you have such a disc, teach this module the MDS
track table and add it to docs/formats/.
"""

from __future__ import annotations

import os

from samplerdisc.container.base import SectorImage
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.mdx import MAGIC, SPLIT_VERSION_MAJOR, VERSION_OFFSET
from samplerdisc.container.rawcd import RawCdImage, looks_raw


def looks_mds(head: bytes) -> bool:
    """The split descriptor: the shared magic with the split major version.

    ``head`` must reach past ``VERSION_OFFSET``; 16 bytes is the magic and one
    short of the byte that matters.
    """
    return (
        head.startswith(MAGIC)
        and len(head) > VERSION_OFFSET
        and head[VERSION_OFFSET] == SPLIT_VERSION_MAJOR
    )


def find_mdf(mds_path: str | os.PathLike[str]) -> str | None:
    """Locate the data file beside a descriptor, tolerating case differences."""
    stem, _ = os.path.splitext(os.fspath(mds_path))
    for candidate in (stem + ".mdf", stem + ".MDF", stem + ".Mdf"):
        if os.path.exists(candidate):
            return candidate
    return None


def open_mds(mds_path: str | os.PathLike[str]) -> SectorImage:
    mdf = find_mdf(mds_path)
    if mdf is None:
        raise ValueError(f"{mds_path}: no matching .mdf beside the descriptor")
    with open(mdf, "rb") as fh:
        head = fh.read(16)
    image: SectorImage = RawCdImage(mdf) if looks_raw(head) else FlatImage(mdf)
    image.kind = "mdsmdf"
    return image
