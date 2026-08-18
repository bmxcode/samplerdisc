"""Unwrap any container to a flat ISO, without consulting the filesystem.

This is the escape hatch, not a convenience: it is what a user gets when the
container is one we understand and the filesystem inside it is not. It must stay
a faithful unwrap -- no trimming, reordering or "fixing" of sectors. See ADR-0009.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from samplerdisc.container.mdx import MdxImage

if TYPE_CHECKING:
    from collections.abc import Callable

    from samplerdisc.container.base import SectorImage

_CHUNK = 1 << 22


def export_iso(
    image: SectorImage,
    out_path: str | os.PathLike[str],
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Write ``image``'s cooked stream to ``out_path``. Returns bytes written."""
    total = image.size
    written = 0
    with open(out_path, "wb") as out:
        # MDX blocks are sequential-only, so streaming avoids re-inflating.
        if isinstance(image, MdxImage):
            for chunk in image.iter_sectors():
                out.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
        else:
            while written < total:
                chunk = image.read(written, min(_CHUNK, total - written))
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
    return written
