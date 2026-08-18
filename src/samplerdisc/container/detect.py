"""Open a disc image by looking at it, not at its name. See ADR-0004."""

from __future__ import annotations

import os

from samplerdisc.container.base import SectorImage
from samplerdisc.container.flat import FlatImage
from samplerdisc.container.mdsmdf import open_mds
from samplerdisc.container.mdx import MdxImage, looks_mdx
from samplerdisc.container.nrg import NrgImage, looks_nrg
from samplerdisc.container.rawcd import RawCdImage, find_cue, looks_raw, parse_cue_sector_size

RAW_SECTOR_SIZE = 2352


def sniff(path: str | os.PathLike[str]) -> str:
    """Return the container kind for ``path``: mdx, nrg, rawcd, mdsmdf or flat.

    Head and tail signatures decide. The extension is consulted only for the
    split .mds/.mdf pair, whose descriptor has no signature we read, and as a
    last resort when nothing matched.
    """
    path = os.fspath(path)
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(16)
        tail = b""
        if size >= 12:
            fh.seek(size - 12)
            tail = fh.read(12)

    if looks_mdx(head):
        return "mdx"
    if looks_nrg(tail):
        return "nrg"
    if looks_raw(head):
        return "rawcd"
    if path.lower().endswith(".mds"):
        return "mdsmdf"

    # No signature. A cue sheet is the next best authority, since a cooked image
    # has nothing distinctive at byte 0 -- an AKAI partition header and an
    # ISO 9660 system area look nothing like each other and neither is a magic.
    cue = find_cue(path)
    if cue is not None:
        with open(cue, encoding="utf-8", errors="replace") as fh:
            if parse_cue_sector_size(fh.read()) == RAW_SECTOR_SIZE:
                return "rawcd"
    return "flat"


def open_image(path: str | os.PathLike[str]) -> SectorImage:
    """Open any supported container as a flat cooked-sector stream."""
    kind = sniff(path)
    if kind == "mdx":
        return MdxImage(path)
    if kind == "nrg":
        return NrgImage(path)
    if kind == "rawcd":
        return RawCdImage(path)
    if kind == "mdsmdf":
        return open_mds(path)
    return FlatImage(path)
