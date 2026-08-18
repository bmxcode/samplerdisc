"""MDS descriptor beside MDF data -- the split form of what MDX merges.

Unverified against a reference disc. No .mds/.mdf pair was available while this
was written, so rather than commit struct offsets nobody has checked, geometry
is sniffed from the .mdf the same way a bare .bin is: sync pattern means raw
2352-byte sectors, otherwise cooked 2048. That is correct for single-track data
discs, which is what sampler CD-ROMs are.

What this does not do is read the MDS at all -- so a multi-track or offset image
will be read from byte 0. If you have such a disc, teach this module the MDS
track table and add it to docs/formats/.
"""

from __future__ import annotations

import os

from samplerdisc.container.base import SectorImage
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.rawcd import RawCdImage, looks_raw


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
