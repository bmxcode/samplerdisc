"""Find where the filesystem actually starts.

The container reports where its *track* starts. That is not always where the
filesystem starts: a Nero image of an AKAI disc puts 150 sectors of zeroed
pregap in front of one, and hybrid discs carry an ISO 9660 track ahead of the
sampler partition.

Getting this wrong does not raise -- it reports an empty disc. See ADR-0005.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.fs.base import backends

if TYPE_CHECKING:
    from samplerdisc.container.base import SectorImage
    from samplerdisc.fs.base import Backend

#: How far in to look. Generous enough for a 150-sector pregap or a small
#: ISO 9660 track ahead of the real filesystem, bounded so a disc with no
#: recognisable filesystem fails quickly rather than scanning half a gigabyte.
DEFAULT_SEARCH_SECTORS = 4096


class Origin(NamedTuple):
    offset: int
    backend: Backend


def find_origin(
    image: SectorImage,
    search_sectors: int = DEFAULT_SEARCH_SECTORS,
    candidates: list[Backend] | None = None,
) -> Origin | None:
    """Locate the first offset a registered backend recognises.

    Returns None when nothing matches, which is a real outcome: the container
    was understood and the filesystem inside it was not. That is what
    ``export-iso`` exists for (ADR-0009).
    """
    available = backends() if candidates is None else candidates
    if not available:
        return None
    limit = min(search_sectors, max(image.sectors, 1))
    for sector in range(limit):
        offset = sector * SECTOR_SIZE
        for backend in available:
            if backend.probe(image, offset):
                return Origin(offset, backend)
    return None
