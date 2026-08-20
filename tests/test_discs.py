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
from functools import lru_cache
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
#: Keyed by **size in bytes**. The name is a label for the test id; nothing
#: looks a disc up by it. See _pinned_disc() for why.
_EXPECT_NO_FILESYSTEM = {
    "OMI Universe of Sounds Sonic Images Vol. 1 (SampleCell)": 295_833_600,
    "OMI Universe of Sounds Sonic Images Vol. 2 (SampleCell)": 295_731_200,
}


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


def _pinned_sizes() -> set[int]:
    """Every size any test below pins, across all three tables."""
    return {
        *_EXPECT_NO_FILESYSTEM.values(),
        *(size for size, _ in _ROLAND_S7XX.values()),
        *(size for size, _, _ in _ISO9660.values()),
    }


@lru_cache(maxsize=1)
def _by_size() -> dict[int, tuple[Path, ...]]:
    """The collection indexed by file size, built once per run."""
    found: dict[int, list[Path]] = {}
    for path in _discs():
        found.setdefault(path.stat().st_size, []).append(path)
    return {size: tuple(paths) for size, paths in found.items()}


def _pinned_disc(label: str, size: int) -> Path:
    """One pinned disc, found by size, or the right one of skip and fail.

    **Size, not filename.** A filename is a label someone types and can retype;
    a size is a property of the disc. These discs come off archive.org and
    personal FTPs and get renamed on the shelf -- `BSBSSD2.bin` became
    `Best Service - Brass Super Section (CD2).bin`, and because the lookup was
    by stem its ISO 9660 test skipped from that moment on. That is half the
    regression coverage for ADR-0019, silently off, in a green suite. It is the
    same reasoning as ADR-0004 one layer out: identify a disc by what it *is*,
    not by what someone called it.

    **Skip and fail are different failures and must not be confused.** A
    contributor with no discs has to skip -- their shelf is not ours, and that
    is the whole premise of this module. A collection that resolves other
    pinned discs but not this one is not that: it is a pin that has gone stale,
    or a disc that was moved away, and skipping there is how the rename above
    stayed invisible. So the test skips only when *nothing* pinned resolves.
    """
    matches = _by_size().get(size, ())
    if len(matches) > 1:
        # Sizes are distinct across all 79 images measured. Two files of
        # exactly one size are far more likely a disc filed twice than a
        # coincidence, and picking either would make the run order-dependent.
        listed = ", ".join(str(p.name) for p in matches)
        pytest.fail(f"{label}: {len(matches)} images are exactly {size} bytes: {listed}")
    if matches:
        return matches[0]
    if _by_size().keys() & _pinned_sizes():
        pytest.fail(
            f"{label}: no image of exactly {size} bytes in this collection, but other "
            f"pinned discs are here -- the disc was moved away, or it was re-ripped and "
            f"the pin needs remeasuring. Skipping this would hide it."
        )
    pytest.skip(f"{label} not in this collection")


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


@pytest.mark.parametrize("label", sorted(_EXPECT_NO_FILESYSTEM))
def test_known_unreadable_discs_are_not_claimed(label: str) -> None:
    """The discs that provoked ADR-0012, pinned by name where they are present.

    Both carry a filesystem this project does not read -- ``EMU3`` and
    Digidesign SampleCell's ``ER`` -- and both were reported as AKAI at a
    confident, wrong offset before the probe asked whether a volume held a file.
    """
    path = _pinned_disc(label, _EXPECT_NO_FILESYSTEM[label])
    with open_image(path) as image:
        origin = find_origin(image)
    assert origin is None, f"{label} was claimed by {origin.backend.name if origin else '?'}"


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
#: ``label: (size in bytes, samples)``.
_ROLAND_S7XX = {
    "Roland - LCDP05 Solo Strings": (130_344_960, 890),
    "Edirol - Brass Section vol.1 - Solos (Roland Sxx CD-ROM)": (162_271_232, 1016),
    "NorthStar - Global Instruments - Volume 1 (S7xx)": (296_032_256, 1284),
    "AMG - Now CD-ROM (Roland)": (681_140_224, 1230),
    "Roland - L-CDX-01 - Rhythm Section Instruments (Roland Sxx CD-ROM)": (629_149_696, 1972),
}


@pytest.mark.parametrize("label", sorted(_ROLAND_S7XX))
def test_roland_s7xx_discs_resolve_and_list_their_declared_samples(label: str) -> None:
    """Pinned where present, skipped where the shelf is bare -- see _pinned_disc()."""
    size, expected = _ROLAND_S7XX[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        assert origin.backend.name == "roland_s7xx"
        assert origin.offset == 0
        volumes = list(origin.backend.volumes(image, origin.offset))
        # One flat volume, named from the ID<n>: label -- ADR-0016.
        assert len(volumes) == 1
        assert volumes[0].name.startswith("ID")
        samples = [f for f in volumes[0].files if f.kind == "sample"]
        assert len(samples) == expected


@pytest.mark.parametrize("label", sorted(_ROLAND_S7XX))
def test_roland_s7xx_payloads_are_byte_identical_to_the_disc(label: str) -> None:
    """The WAV data chunk is a copy, so the bytes must survive the round trip.

    Checked against a second, independent walk of the allocation table rather
    than against ``read_file`` itself, and over a spread of the disc rather
    than its first few entries -- the samples that broke during development
    were in the middle.
    """
    path = _pinned_disc(label, _ROLAND_S7XX[label][0])
    from samplerdisc.fs import roland_s7xx as fs

    with open_image(path) as image:
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


#: ISO 9660 discs pinned by name, with the volume label and file count each
#: must yield. Both carry Joliet, and Vintage Pro is why the backend now reads
#: it (ADR-0019): its primary tree masters 1 061 files under 1 001 8.3 names.
#: ``label: (size in bytes, volume label, files)``.
_ISO9660 = {
    "Digital Sound Factory - E-MU Vintage Pro": (45_558_240, "VintagePro", 1062),
    "Best Service - Brass Super Section (CD2)": (539_584_080, "BSBSS", 2059),
}


@pytest.mark.parametrize("label", sorted(_ISO9660))
def test_iso9660_discs_list_every_file_under_a_distinct_path(label: str) -> None:
    """Distinctness is the assertion, not the count.

    A count alone passed throughout the bug: the walk always found all 1 062 of
    Vintage Pro's files, and 60 of them arrived wearing another file's name.
    """
    size, volume_label, count = _ISO9660[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        assert origin.backend.name == "iso9660"
        volumes = list(origin.backend.volumes(image, origin.offset))
        assert len(volumes) == 1
        assert volumes[0].name == volume_label
        names = [f.name for f in volumes[0].files]
        assert len(names) == count
        assert len(set(names)) == count


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_an_iso9660_volume_lists_no_path_twice(path: Path) -> None:
    """On a hierarchical filesystem two entries under one path means one of
    them is not what it claims.

    Scoped to ISO 9660 deliberately, and the scope is the point rather than a
    convenience. There a ``File.name`` is a *path*, and the filesystem itself
    guarantees it is unique within its directory, so a repeat is our error.
    On the sampler filesystems it is a *name*, and a repeat is the disc's own:
    an AKAI program and its sample share one name by convention -- ``WELCOME``
    on `AMG - Now CD-Rom for (AKAI)` is a program and a sample -- and E-mu
    records are located by signature, so `Protozoa` really does carry two
    ``Agogo Bell`` records at different extents. Asserting distinctness there
    would be asserting something about the libraries, not about this code.

    This is the check a file *count* cannot make, and it is worth having as an
    invariant rather than a table: every ISO 9660 disc walked the right number
    of records throughout the 8.3-collision bug and throughout the
    resource-fork bug. What was wrong both times was that some of those
    records wore another file's name.

    Extraction survives a collision -- ``unique_path`` suffixes -- so the cost
    is not a lost file but an unusable one: two different extents written out
    as ``X.wav`` and ``X_2.wav`` with nothing saying which is the audio.
    """
    with open_image(path) as image:
        origin = find_origin(image)
        if origin is None or origin.backend.name != "iso9660":
            return
        for volume in origin.backend.volumes(image, origin.offset):
            names = [f.name for f in volume.files]
            duplicated = sorted({n for n in names if names.count(n) > 1})
            assert not duplicated, (
                f"{path.name}: volume {volume.name!r} lists "
                f"{len(names) - len(set(names))} entries under a path it already used, "
                f"first: {duplicated[:3]}"
            )
