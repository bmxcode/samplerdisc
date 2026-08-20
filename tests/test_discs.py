"""Disc-backed tests, opt-in via ``SAMPLERDISC_TEST_DISCS``.

No disc image or fragment of one is committed (ADR-0008), so these run against
whatever collection the environment variable points at and skip entirely when
it is unset. That means they cannot assert a fixed list of discs -- a
contributor's directory is not ours. What they can assert is an invariant that
holds for any collection, and the one below is the general statement of the bug
in ADR-0012.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.container.mdsmdf import find_mdf
from samplerdisc.fs.probe import find_origin

#: ``.mds`` and not ``.mdf``: the pair is reached through the descriptor, the
#: member that is actually opened, so listing both would open the disc twice.
IMAGE_SUFFIXES = (".iso", ".img", ".mdx", ".nrg", ".bin", ".cdr", ".tao", ".mds")

#: Discs known to carry a filesystem no backend reads. Naming them keeps the
#: "claimed but empty" check below honest: without this, a backend that stopped
#: recognising everything would pass it trivially.
_EXPECT_NO_FILESYSTEM = (
    "OMI Universe of Sounds Sonic Images Vol. 1 (SampleCell)",
    "OMI Universe of Sounds Sonic Images Vol. 2 (SampleCell)",
)


def _collection() -> Path | None:
    root = os.environ.get("SAMPLERDISC_TEST_DISCS")
    if not root:
        return None
    path = Path(root)
    return path if path.is_dir() else None


def _discs() -> list[Path]:
    """Every disc image under the collection root, at any depth.

    Recursive rather than one level deep, because a collection that grows
    stops being flat: filing discs by state -- active, archive, blocked -- or
    one directory per disc is the obvious way to organise a few hundred
    gigabytes, and a shallow scan then finds nothing.

    That failure is silent by construction. These tests skip when the variable
    is unset, so a scan that matches no files is indistinguishable from a
    contributor who has no discs: pytest reports skips either way and the suite
    stays green while asserting nothing at all. ``test_the_collection_is_not
    _silently_empty`` below is what makes it visible.
    """
    root = _collection()
    if root is None:
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix.lower() in IMAGE_SUFFIXES
        and path.is_file()
        # Skip dotted directories -- a .git or a Spotlight index below the root
        # is not a disc collection.
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


pytestmark = pytest.mark.skipif(
    _collection() is None,
    reason="set SAMPLERDISC_TEST_DISCS to a directory of disc images",
)


def test_the_collection_is_not_silently_empty() -> None:
    """A root that is set but yields no images is a mistake, not an empty shelf.

    Every other test here skips when it finds nothing, which is right for a
    contributor with no discs -- but it means pointing the variable at the
    wrong directory produces a green run that asserted nothing. If someone went
    to the trouble of setting it, finding zero images is worth failing over.
    """
    root = _collection()
    assert root is not None
    assert _discs(), (
        f"SAMPLERDISC_TEST_DISCS={root} contains no disc images at any depth "
        f"(looked for {', '.join(IMAGE_SUFFIXES)})"
    )


def _ids(paths: list[Path]) -> list[str]:
    """Name a test by its path below the root, not by its filename.

    Two discs in different directories can share a name -- the same library
    filed under both ``active`` and ``archive``, say -- and pytest needs the
    ids to be distinct or it silently appends a counter and you can no longer
    tell which disc failed.
    """
    root = _collection()
    return [str(p.relative_to(root)) if root else p.name for p in paths]


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_a_claimed_disc_yields_at_least_one_file(path: Path) -> None:
    """No backend may claim a disc and then produce nothing.

    Resolving to None is a legitimate outcome -- the container was understood
    and the filesystem inside it was not, which is what ``export-iso`` is for
    (ADR-0009). Claiming a disc and walking out with zero files in every volume
    is not: it is a probe that matched arbitrary data, and it reports as an
    empty disc rather than as an error (ADR-0005, ADR-0012).

    This is deliberately an invariant rather than a table of expected offsets,
    so it holds against whatever collection a contributor has.
    """
    with open_image(path) as image:
        origin = find_origin(image)
        if origin is None:
            return
        volumes = list(origin.backend.volumes(image, origin.offset))
        files = sum(len(volume.files) for volume in volumes)
        if files:
            return
        # No files is allowed only when a backend says why -- a variant it
        # recognises and deliberately does not extract. Unexplained emptiness
        # is the ADR-0012 signature.
        explained = [v for v in volumes if v.note]
        assert volumes and explained, (
            f"{path.name}: {origin.backend.name} claimed offset {origin.offset} "
            f"but returned {len(volumes)} volumes, no files and no explanation"
        )


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_origin_resolution_is_deterministic(path: Path) -> None:
    """Opening the same image twice must resolve the same way.

    Cheap, and it catches a probe whose result depends on read caching or on
    how much of the image happened to be touched first.
    """
    with open_image(path) as image:
        first = find_origin(image)
    with open_image(path) as image:
        second = find_origin(image)
    assert (first is None) == (second is None)
    if first is not None and second is not None:
        assert (first.offset, first.backend.name) == (second.offset, second.backend.name)


@pytest.mark.parametrize("stem", _EXPECT_NO_FILESYSTEM)
def test_known_unreadable_discs_are_not_claimed(stem: str) -> None:
    """The discs that provoked ADR-0012, pinned by name where they are present.

    Both carry a filesystem this project does not read -- ``EMU3`` and
    Digidesign SampleCell's ``ER`` -- and both were reported as AKAI at a
    confident, wrong offset before the probe asked whether a volume held a file.
    """
    root = _collection()
    assert root is not None
    matches = [p for p in _discs() if p.stem == stem]
    if not matches:
        pytest.skip(f"{stem} not in this collection")
    with open_image(matches[0]) as image:
        origin = find_origin(image)
    assert origin is None, f"{stem} was claimed by {origin.backend.name if origin else '?'}"


def _mds_pairs() -> list[Path]:
    return [p for p in _discs() if p.suffix.lower() == ".mds" and find_mdf(p) is not None]


@pytest.mark.parametrize("path", _mds_pairs(), ids=_ids(_mds_pairs()))
def test_a_split_mds_routes_to_its_mdf_and_not_to_the_mdx_parser(path: Path) -> None:
    """The descriptor and the data file must describe the same disc.

    The split .mds shares its 16-byte magic with the merged .mdx, and testing
    that magic alone sent every real .mds to the MDX parser -- which read a
    zero out of a field that is not a descriptor offset and refused the file.
    The synthetic fixture pins the version byte; this pins the consequence, on
    a real pair: opening the descriptor has to give the same stream as opening
    the .mdf beside it, which is what the merged parser could never do.
    """
    assert sniff(path) == "mdsmdf"
    mdf = find_mdf(path)
    assert mdf is not None
    with open_image(path) as through_descriptor, open_image(mdf) as direct:
        assert through_descriptor.kind == "mdsmdf"
        assert through_descriptor.size == direct.size
        assert through_descriptor.size % SECTOR_SIZE == 0
        # A spread rather than the head: the geometry sniff picks a stride, and
        # a wrong one agrees at sector 0 and diverges everywhere after it.
        sectors = through_descriptor.size // SECTOR_SIZE
        for index in range(0, sectors, max(1, sectors // 40)):
            at = index * SECTOR_SIZE
            assert through_descriptor.read(at, SECTOR_SIZE) == direct.read(at, SECTOR_SIZE)


#: Discs whose filesystem is pinned by name, with the backend that must claim
#: them and the sample count its header declares. ADR-0005 asks for the
#: resolved origin to be asserted per backend rather than covered incidentally,
#: and the counts are the strongest available check on the walk: they are read
#: from the header, so a backend that stops early or runs long disagrees with
#: the disc's own arithmetic rather than with a number someone wrote down.
_ROLAND_S7XX = {
    "Roland - LCDP05 Solo Strings": 890,
    "Edirol - Brass Section vol.1 - Solos (Roland Sxx CD-ROM)": 1016,
    "NorthStar - Global Instruments - Volume 1 (S7xx)": 1284,
    "AMG - Now CD-ROM (Roland)": 1230,
    "Roland - L-CDX-01 - Rhythm Section Instruments (Roland Sxx CD-ROM)": 1972,
}


@pytest.mark.parametrize("stem", sorted(_ROLAND_S7XX))
def test_roland_s7xx_discs_resolve_and_list_their_declared_samples(stem: str) -> None:
    """Pinned where present, skipped where not -- a contributor's shelf is not ours."""
    matches = [p for p in _discs() if p.stem == stem]
    if not matches:
        pytest.skip(f"{stem} not in this collection")
    with open_image(matches[0]) as image:
        origin = find_origin(image)
        assert origin is not None, f"{stem}: no filesystem found"
        assert origin.backend.name == "roland_s7xx"
        assert origin.offset == 0
        volumes = list(origin.backend.volumes(image, origin.offset))
        # One flat volume, named from the ID<n>: label -- ADR-0016.
        assert len(volumes) == 1
        assert volumes[0].name.startswith("ID")
        samples = [f for f in volumes[0].files if f.kind == "sample"]
        assert len(samples) == _ROLAND_S7XX[stem]


@pytest.mark.parametrize("stem", sorted(_ROLAND_S7XX))
def test_roland_s7xx_payloads_are_byte_identical_to_the_disc(stem: str) -> None:
    """The WAV data chunk is a copy, so the bytes must survive the round trip.

    Checked against a second, independent walk of the allocation table rather
    than against ``read_file`` itself, and over a spread of the disc rather
    than its first few entries -- the samples that broke during development
    were in the middle.
    """
    matches = [p for p in _discs() if p.stem == stem]
    if not matches:
        pytest.skip(f"{stem} not in this collection")
    from samplerdisc.fs import roland_s7xx as fs

    with open_image(matches[0]) as image:
        origin = find_origin(image)
        assert origin is not None
        volume = next(iter(origin.backend.volumes(image, origin.offset)))
        samples = [f for f in volume.files if f.kind == "sample"]
        for entry in samples[:: max(1, len(samples) // 40)]:
            payload = origin.backend.read_file(image, origin.offset, entry)
            assert len(payload) == entry.size
            # Rebuild the extent from the table by hand and compare.
            expected = bytearray()
            cluster = entry.start_block
            for _ in range(entry.get("clusters")):
                at = fs.DATA_BLOCK * fs.BLOCK + (cluster - fs.FIRST_DATA_CLUSTER) * fs.CLUSTER
                expected += image.read(origin.offset + at, fs.CLUSTER)
                (cluster,) = struct.unpack(
                    "<H", image.read(origin.offset + fs.FAT_BLOCK * fs.BLOCK + 2 * cluster, 2)
                )
                if cluster >= fs.CHAIN_END:
                    break
            assert payload == bytes(expected[: entry.size]), entry.name
