"""Disc-backed tests, opt-in via ``SAMPLERDISC_TEST_DISCS``.

No disc image or fragment of one is committed (ADR-0008), so these run against
whatever collection the environment variable points at and skip entirely when
it is unset. That means they cannot assert a fixed list of discs -- a
contributor's directory is not ours. What they can assert is an invariant that
holds for any collection, and the one below is the general statement of the bug
in ADR-0012.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.container.mdsmdf import find_mdf
from samplerdisc.extract import Extracted
from samplerdisc.fs.probe import find_origin
from samplerdisc.sample import aiff, emu_ebl
from samplerdisc.wav import read_header

#: ``.mds`` and not ``.mdf``: the pair is reached through the descriptor, the
#: member that is actually opened, so listing both would open the disc twice.
IMAGE_SUFFIXES = (".iso", ".img", ".mdx", ".nrg", ".bin", ".cdr", ".tao", ".mds")

#: Discs known to carry a filesystem no backend reads. Naming them keeps the
#: "claimed but empty" check below honest: without this, a backend that stopped
#: recognising everything would pass it trivially.
#: Keyed by **size in bytes**. The name is a label for the test id; nothing
#: looks a disc up by it. See _pinned_disc() for why.
_EXPECT_NO_FILESYSTEM = {
    # Roland S-550: a filesystem this project does not read, and unlike the two
    # SampleCell discs (now read as HFS -- D32) no second specimen exists to
    # reverse-engineer it from (docs/README.md "What is not done", ADR-0014).
    "Roland LCD1": 148_690_944,
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
        *(size for size, _, _ in _KURZWEIL.values()),
        *(size for size, _, _ in _ISO9660.values()),
        *(size for size, _, _, _, _, _ in _EMU3.values()),
        *(size for size, _, _, _, _, _ in _AKAI.values()),
        *(size for size, _, _, _, _ in _AKAI_PAYLOAD.values()),
        *(size for size, *_ in _AKAI_SHORT.values()),
        _AKAI_NOTHING_RECOVERED[1],
    }


#: How much of an image is hashed to tell two of one size apart, and the digest
#: for each pinned disc that needs it.
#:
#: Size alone named a disc across the 79 images this suite was built on, and it
#: stopped doing so the moment a whole publisher's series arrived at once: `Vol.
#: 03 - Orchestral` and `Vol. 07 - E-mu Classics` are both exactly 526 723 072
#: bytes, and both `Studio Essentials` discs are 399 077 376. Same mastering
#: run, same disc geometry, different libraries.
#:
#: The tiebreak stays a property of the disc rather than of its filename
#: (ADR-0004): the first megabyte covers the ``EMU3`` header, the folder table
#: and the first bank directory, which is what actually differs. It is
#: consulted **only** where two images share a size, so every other pin is
#: unchanged and no disc needs one until its size collides with something.
_HEAD_BYTES = 1 << 20
_HEAD_DIGEST = {
    "emu-classics": "3882c2319cc27871",
    "eiv-studio": "f1f1c805136d4881",
    # Producer Series Vol. 2 (More Studio Essentials) shares eiv-studio's
    # 399 077 376-byte size (one mastering run, two libraries), so it too needs
    # the first-megabyte digest -- their EMU3 headers and bank directories differ.
    "eiv-studio-vol2": "7914ae592a6999fc",
    # Vol. 10 - Elements of Sound 1MB shares its size with Vol. 11 (the 2MB
    # cut of the same library), so it needs the first-megabyte digest to be
    # told apart -- their bank directories differ.
    "elements1mb": "250858faa4d17ceb",
}


@lru_cache(maxsize=256)
def _head_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.sha256(handle.read(_HEAD_BYTES)).hexdigest()[:16]


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
        # Two files of one size are usually a disc filed twice, and picking
        # either would make the run order-dependent. Where they are genuinely
        # different discs off one mastering run, _HEAD_DIGEST says which is
        # which -- and a label with no digest still fails rather than guessing.
        wanted = _HEAD_DIGEST.get(label)
        matches = tuple(p for p in matches if _head_digest(p) == wanted) if wanted else matches
    if len(matches) > 1:
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
def test_every_claimed_volume_yields_a_file_or_says_why(path: Path) -> None:
    """No backend may claim a **volume** and then produce nothing from it.

    Resolving to None is a legitimate outcome -- the container was understood
    and the filesystem inside it was not, which is what ``export-iso`` is for
    (ADR-0009). Claiming a disc and walking out with zero files and no reason
    is not: it is a probe that matched arbitrary data, and it reports as an
    empty disc rather than as an error (ADR-0005, ADR-0012).

    **Per volume, not per disc**, and that is the whole strength of it. The
    per-disc form lets one volume that extracts cover for every volume that
    does not, which is exactly how the EMU3 index banks of issue #15 stayed
    invisible for as long as they did: those discs always had *some* bank with
    records in it. Of the 79 images measured, three failed the per-volume form
    and none failed the per-disc one -- the six AKAI volumes of issues #16 and
    #17, plus the four on `Kickin' Lunatic Beats 2 CD1` whose blocks the disc
    itself says are volume directories.

    This is deliberately an invariant rather than a table of expected offsets,
    so it holds against whatever collection a contributor has.
    """
    with open_image(path) as image:
        origin = find_origin(image)
        if origin is None:
            return
        volumes = list(origin.backend.volumes(image, origin.offset))
        assert volumes, (
            f"{path.name}: {origin.backend.name} claimed offset {origin.offset} "
            f"but returned no volumes at all"
        )
        # No files is allowed only where the backend says why -- a variant it
        # recognises and deliberately does not extract, or a block the disc's
        # own bookkeeping accounts for. Unexplained emptiness is the ADR-0012
        # signature, and one silent volume is enough to hide a wrong answer.
        unexplained = [v.name for v in volumes if not v.files and not v.note]
        assert not unexplained, (
            f"{path.name}: {origin.backend.name} claimed offset {origin.offset} "
            f"but {len(unexplained)} of {len(volumes)} volumes hold no files and "
            f"give no reason: {unexplained[:5]}"
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
    """A disc that carries a filesystem no backend reads, pinned by size.

    ``find_origin`` must return None rather than claim it at a confident, wrong
    offset -- the failure ADR-0012 exists to reject. Roland's S-550 is the
    standing example: unlike SampleCell's HFS, which D32 now reads, no second
    S-550 specimen exists to reverse-engineer it from (ADR-0014).
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


#: Kurzweil ``KMSI`` (FAT16) discs, pinned by size with the bank and sample
#: counts each yields. These are the collection's first Kurzweil specimens (#60).
#: A ``.KRZ`` is an object bank, so each bank is a volume and its sample objects
#: are that volume's files (ADR-0036). ``label: (size, banks, samples)``.
_KURZWEIL = {
    "gigapack-cd1": (684_702_480, 106, 3846),
    "gigapack-cd2": (684_744_816, 189, 6637),
}


@pytest.mark.parametrize("label", sorted(_KURZWEIL))
def test_kurzweil_discs_resolve_and_enumerate_their_bank_samples(label: str) -> None:
    """Pinned where present, skipped where the shelf is bare -- see _pinned_disc()."""
    size, banks, samples = _KURZWEIL[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        assert origin.backend.name == "kurzweil"
        assert origin.offset == 0
        volumes = list(origin.backend.volumes(image, origin.offset))
        # One volume per .KRZ bank (ADR-0036), each carrying its samples and the
        # whole bank kept as a program for --keep-originals.
        assert len(volumes) == banks
        assert sum(1 for v in volumes for f in v.files if f.kind == "sample") == samples
        assert all(f.kind == "program" for v in volumes for f in v.files if f.kind != "sample")
        # Every claimed volume yields a sample or says why it has none (ADR-0012).
        assert all(any(f.kind == "sample" for f in v.files) or v.note for v in volumes)


@pytest.mark.parametrize("label", sorted(_KURZWEIL))
def test_kurzweil_banks_are_byte_identical_to_the_disc(label: str) -> None:
    """``read_file`` of a whole ``.krz`` follows the FAT chain; check it against
    an independent walk.

    Over a spread of the banks rather than the first few, and against a second
    hand-rolled FAT16 walk rather than ``read_file`` itself -- CD 1 has twelve
    fragmented banks, and a walk that assumed contiguity would return a
    neighbour's bytes on exactly those.
    """
    from samplerdisc.fs import kurzweil as fs

    path = _pinned_disc(label, _KURZWEIL[label][0])
    with open_image(path) as image:
        origin = find_origin(image)
        assert origin is not None
        offset = origin.offset
        geo = fs._geometry(image, offset)
        fat = origin.backend._read_fat(image, offset, geo)
        volumes = list(origin.backend.volumes(image, offset))
        banks = [f for v in volumes for f in v.files if f.kind == "program"]
        for entry in banks[:: max(1, len(banks) // 30)]:
            payload = origin.backend.read_file(image, offset, entry)
            assert len(payload) == entry.size
            assert payload[:4] == fs.KRZ_SIGNATURE
            expected = bytearray()
            cluster = entry.start_block
            seen: set[int] = set()
            while fs.FIRST_DATA_CLUSTER <= cluster <= geo.max_cluster and cluster not in seen:
                seen.add(cluster)
                expected += image.read(offset + geo.cluster_at(cluster), geo.cluster_bytes)
                (cluster,) = struct.unpack_from("<H", fat, 2 * cluster)
                if cluster >= fs.FAT16_EOC:
                    break
            assert payload == bytes(expected[: entry.size]), entry.name


@pytest.mark.parametrize("label", sorted(_KURZWEIL))
def test_kurzweil_samples_decode_to_standard_rates(label: str) -> None:
    """Every sample carries audio at a plausible rate.

    A decoder reading the wrong field offsets would still return audio-shaped
    bytes -- the pool is nothing but PCM -- so coherence alone proves little.
    The period, though, sits at a fixed place in the sample header, and read
    from the wrong one it inverts to an absurd rate; so every rate must fall in
    an audio band, and a majority must land on one of the sampler's standard
    rates (many Kurzweil samples use in-between rates like 30 000, which is why
    this is a majority and not all). The byte-for-byte agreement with mpc2emu is
    what pins the rate exactly; this is the check that runs without that reader.
    """
    size, _banks, samples = _KURZWEIL[label]
    standard = set(_kurzweil_fs().STANDARD_RATES)
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None
        on_grid = checked = 0
        for volume in origin.backend.volumes(image, origin.offset):
            for entry in volume.files:
                if entry.kind != "sample":
                    continue
                checked += 1
                assert 4000 <= entry.raw_type <= 96000, f"{entry.name}: {entry.raw_type}"
                on_grid += entry.raw_type in standard
        assert checked == samples
        assert on_grid >= int(checked * 0.5)


def _kurzweil_fs():
    from samplerdisc.fs import kurzweil

    return kurzweil


def _krz_oracle() -> Path | None:
    """A checkout of lentferj/mpc2emu, whose ``krz_parser`` is the independent
    reader this decode is verified against.

    Set ``SAMPLERDISC_KRZ_ORACLE`` to the repository root. Its ``parse_krz``
    returns each sample as little-endian PCM with a rate, exactly this backend's
    output, so the two are compared byte for byte. Not vendored: it is a
    separate project, so the check skips without it -- the decode's own
    correspondence with it was established when this deliverable was built (see
    ADR-0036).
    """
    root = os.environ.get("SAMPLERDISC_KRZ_ORACLE")
    return Path(root) if root and (Path(root) / "parsers" / "krz_parser.py").is_file() else None


@pytest.mark.skipif(
    _krz_oracle() is None, reason="set SAMPLERDISC_KRZ_ORACLE to an mpc2emu checkout"
)
def test_kurzweil_samples_match_the_mpc2emu_reader() -> None:
    """Byte-for-byte against an independent K2000 reader (ADR-0036).

    mpc2emu names unreferenced samples itself and can hold two same-named
    slots, so samples are matched on content -- ``(rate, pcm)`` -- not name:
    every sample this backend decodes must be one mpc2emu decodes identically,
    with a floor so a broken decoder cannot pass by matching nothing.
    """
    import contextlib
    import io
    import sys
    import tempfile

    oracle_root = _krz_oracle()
    sys.path.insert(0, str(oracle_root))
    cwd = os.getcwd()
    os.chdir(oracle_root)
    try:
        from parsers.krz_parser import parse_krz
    finally:
        os.chdir(cwd)

    label, (size, _banks, _samples) = "gigapack-cd1", _KURZWEIL["gigapack-cd1"]
    checked = matched = 0
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None
        backend, offset = origin.backend, origin.offset
        volumes = list(backend.volumes(image, offset))
        for volume in volumes[:: max(1, len(volumes) // 20)]:
            program = next(f for f in volume.files if f.kind == "program")
            fd, krz_path = tempfile.mkstemp(suffix=".krz")
            with os.fdopen(fd, "wb") as krz:
                krz.write(backend.read_file(image, offset, program))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    bank = parse_krz(krz_path)
            finally:
                os.unlink(krz_path)
            reference = {(sd.sample_rate, sd.data) for sd in bank.samples}
            for entry in volume.files:
                if entry.kind != "sample":
                    continue
                sample = backend.parse_sample(entry, backend.read_file(image, offset, entry))
                checked += 1
                matched += (sample.rate, sample.pcm) in reference
    assert checked >= 100
    assert matched == checked, f"{checked - matched} of {checked} samples disagreed with mpc2emu"


#: ISO 9660 discs pinned by name, with the volume label and file count each
#: must yield. Both carry Joliet, and Vintage Pro is why the backend now reads
#: it (ADR-0019): its primary tree masters 1 061 files under 1 001 8.3 names.
#: ``label: (size in bytes, volume label, files)``.
_ISO9660 = {
    "Digital Sound Factory - E-MU Vintage Pro": (45_558_240, "VintagePro", 1062),
    "Best Service - Brass Super Section (CD2)": (539_584_080, "BSBSS", 2059),
    "Best Service ProSamples vol.42 - Session Instruments": (263_153_664, "PS_42", 1347),
    "Best Service ProSamples vol.43 - Real Drum Kits": (414_228_480, "PS_43", 2801),
}

#: ProSamples discs carrying a full AIFF tree beside a full WAV tree of the
#: same sounds. They are the only ground truth in this project for what a
#: conversion should produce: the publisher shipped the answer (ADR-0024).
#: ``label: (size in bytes, twins, pairs whose AIFF names a root key, pairs
#: that carry a loop on both sides)``.
_AIFF_TWINS = {
    "Best Service ProSamples vol.42 - Session Instruments": (263_153_664, 423, 178, 175),
    "Best Service ProSamples vol.45 - Techno ID": (433_889_280, 850, 20, 20),
}

#: The disc that says the twin trees are not always the same audio. vol.43
#: ships 1 386 AIFF and 1 386 WAV under matching names and **not one pair
#: shares its audio** -- the AIFF are mastered a few frames longer. Pinned
#: because it is what makes deduplicating by name wrong (ADR-0024).
_NO_TWINS = ("Best Service ProSamples vol.43 - Real Drum Kits", 414_228_480, 1386)


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


def _audio_index(backend, image, offset, files) -> tuple[dict, dict]:
    """Every WAV on the disc indexed by its audio, split by whether it carries
    a smpl chunk. Matching on audio and not on name is the point: the two trees
    do not agree on their directory names."""
    plain: dict[bytes, str] = {}
    rich: dict[bytes, bytes] = {}
    for entry in (f for f in files if f.kind == "wav"):
        payload = backend.read_file(image, offset, entry)
        header = read_header(payload)
        if header is None:
            continue
        pcm = payload[header.offset : header.offset + header.length]
        if header.has_smpl:
            rich[pcm] = payload
        else:
            plain[pcm] = entry.name
    return plain, rich


@pytest.mark.parametrize("label", sorted(_AIFF_TWINS))
def test_a_converted_aiff_matches_the_publishers_own_wav_of_the_same_sound(label: str) -> None:
    """The disc is its own oracle.

    Every other sample format here is checked against the bytes it came from,
    which proves the payload was copied and says nothing about whether it was
    understood. These discs carry each sound twice -- once as AIFF, once as WAV
    -- so the publisher's WAV is an independent statement of what the AIFF
    conversion should produce, down to the byte. Nothing else in this project
    has that.
    """
    size, twins, _, _ = _AIFF_TWINS[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        backend, offset = origin.backend, origin.offset
        files = [f for v in backend.volumes(image, offset) for f in v.files]
        plain, rich = _audio_index(backend, image, offset, files)

        matched = 0
        for entry in (f for f in files if f.kind == "aiff"):
            sample = aiff.parse(backend.read_file(image, offset, entry))
            if sample.pcm in plain or sample.pcm in rich:
                matched += 1
        assert matched == twins


@pytest.mark.parametrize("label", sorted(_AIFF_TWINS))
def test_an_aiff_agrees_with_the_smpl_chunk_of_its_wav_twin(label: str) -> None:
    """What settled the loop-end convention, kept so it cannot drift.

    An AIFF marks its loop with two MARK positions and the spec does not say
    whether the frame at the second one is played. The WAV twin's smpl chunk
    does say, and ours is right only if the end marker is exclusive -- which is
    the convention ``SampleLoop`` already used everywhere else.

    Asserted only where each side has something to say. Most of these AIFF
    carry no INST at all, and a file with no root key must not be read as
    claiming one (ADR-0011) -- so the count of pairs that *do* agree is pinned
    too, or an INST that stopped parsing would pass this vacuously.
    """
    size, _, notes, loop_pairs = _AIFF_TWINS[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None
        backend, offset = origin.backend, origin.offset
        files = [f for v in backend.volumes(image, offset) for f in v.files]
        _, rich = _audio_index(backend, image, offset, files)

        notes_seen = loops_seen = 0
        for entry in (f for f in files if f.kind == "aiff"):
            sample = aiff.parse(backend.read_file(image, offset, entry))
            twin = rich.get(sample.pcm)
            if twin is None:
                continue
            note, loops = _smpl(twin)
            if sample.pitch is not None:
                assert sample.pitch == note, entry.name
                notes_seen += 1
            if sample.loops and loops:
                # The disc's own answer to the question the AIFF spec leaves
                # open: our exclusive end, minus one, is the WAV's end.
                assert (sample.loops[0].start, sample.loops[0].end - 1) == loops[0], entry.name
                loops_seen += 1
        assert (notes_seen, loops_seen) == (notes, loop_pairs)


def test_a_disc_whose_twins_are_not_the_same_audio_keeps_both() -> None:
    """vol.43's two trees agree on every name and on no single sound.

    The AIFF are mastered a few frames longer than the WAVs -- 17 638 bytes
    against 17 616 on ``43e-01chh01``. Deduplicating on the name would drop
    1 386 files that are not duplicates of anything, which is why the dedupe
    hashes the audio (ADR-0024).
    """
    label, size, aiff_count = _NO_TWINS
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None
        backend, offset = origin.backend, origin.offset
        files = [f for v in backend.volumes(image, offset) for f in v.files]
        plain, rich = _audio_index(backend, image, offset, files)

        aiffs = [f for f in files if f.kind == "aiff"]
        assert len(aiffs) == aiff_count
        by_name = {f.name.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in aiffs}
        wav_names = {f.name.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in files if f.kind == "wav"}
        # Every AIFF has a same-named WAV ...
        assert by_name <= wav_names
        # ... and not one of them holds the same audio.
        for entry in aiffs:
            sample = aiff.parse(backend.read_file(image, offset, entry))
            assert sample.pcm not in plain and sample.pcm not in rich, entry.name


#: The one disc in hand that carries E-mu Emulator X ``.EBL`` banks: Vintage
#: Pro, all 1 057 samples mono. ``(size, ebl files, samples that convert)`` --
#: 1 061 ``.ebl`` files plus one ``.exb`` bank definition make the 1 062 the
#: listing test counts, and all 1 061 convert.
_EBL_DISC = ("Digital Sound Factory - E-MU Vintage Pro", 45_558_240, 1061)


def test_every_ebl_on_the_disc_converts_to_a_mono_wav() -> None:
    """Vintage Pro read 0 WAV before this backend existed. Every ``.EBL`` now
    parses to a mono sample with a real rate, and none is stereo -- the one
    record shape this build does not convert (issue for the stereo case)."""
    label, size, ebl_count = _EBL_DISC
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "iso9660"
        backend, offset = origin.backend, origin.offset
        files = [f for v in backend.volumes(image, offset) for f in v.files]
        ebls = [f for f in files if f.kind == "ebl"]
        assert len(ebls) == ebl_count
        for entry in ebls:
            sample = emu_ebl.parse(backend.read_file(image, offset, entry))
            assert sample.channels == 1, entry.name
            assert sample.rate > 0 and sample.frames > 0, entry.name


def _ebl_oracle() -> Path | None:
    """The publisher's own renders of the Vintage Pro bank, if present.

    Set ``SAMPLERDISC_EBL_ORACLE`` to mattetti/e-mu-soundbanks' ``E-MU
    Sounds/Vintage Pro`` folder -- 1 057 FLAC. Never committed: these are
    copyrighted DSF renders and the repo's licence is unstated, so like the
    discs they live outside the tree and the check skips without them.
    """
    root = os.environ.get("SAMPLERDISC_EBL_ORACLE")
    return Path(root) if root and Path(root).is_dir() else None


@pytest.mark.skipif(_ebl_oracle() is None, reason="set SAMPLERDISC_EBL_ORACLE to the FLAC renders")
def test_a_converted_ebl_matches_the_publishers_own_render() -> None:
    """The disc's oracle, one step removed: mattetti rendered the whole Vintage
    Pro bank to FLAC, so the publisher's audio says what our conversion should
    produce -- the ADR-0024 pattern, for EBL. Every uniquely-named sample must
    decode to the same rate and the same PCM, byte for byte.

    FLAC is decoded with ``soundfile`` -- test tooling only. The shipped
    converter stays pure-Python (ADR-0001); the oracle just needs reading.
    """
    sf = pytest.importorskip("soundfile")
    oracle_dir = _ebl_oracle()
    # The FLAC is named ``<bank> - <header name>_.flac``; index by the header
    # name so a sample matches its render.
    renders: dict[str, Path] = {}
    for flac in oracle_dir.glob("*.flac"):
        key = flac.stem.split(" - ", 1)[-1].rstrip("_")
        renders[key] = flac

    label, size, _ = _EBL_DISC
    # A header name the disc uses twice cannot be matched to one render, so
    # those are excluded from the byte check rather than counted as failures.
    seen: dict[str, int] = {}
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None
        backend, offset = origin.backend, origin.offset
        samples = []
        for v in backend.volumes(image, offset):
            for entry in (f for f in v.files if f.kind == "ebl"):
                s = emu_ebl.parse(backend.read_file(image, offset, entry))
                seen[s.name] = seen.get(s.name, 0) + 1
                samples.append(s)

        checked = 0
        for s in samples:
            if seen[s.name] > 1:
                continue
            flac = renders.get(s.name.replace(" ", "_"))
            if flac is None:
                continue
            data, rate = sf.read(str(flac), dtype="int16")
            assert rate == s.rate, s.name
            assert data.reshape(-1).tobytes() == s.pcm, s.name
            checked += 1
        # The bank is 1 057 samples; the vast majority match by name. Pin a
        # floor so a broken decoder cannot pass by matching nothing.
        assert checked >= 1000


#: The second EBL bank, read to prove the reader generalises past Vintage Pro:
#: E-mu Classic Series Vol 13 Dance 2000. It is not a disc -- it is loose
#: ``.ebl`` from archive.org's ``emuexbsoundbanks``, used strictly as a local
#: validation input, never committed and never treated as a disc (ADR-0033) --
#: so unlike Vintage Pro it is reached by a plain directory of files, not the
#: container/fs pipeline. Its channel split is 972 mono / 636 stereo, the 636
#: matching the oracle's 636 stereo FLAC exactly.
_DANCE_MONO = 972
_DANCE_STEREO = 636


#: The Dance 2000 bank folder as it is named on archive.org and in mattetti's
#: render tree -- the one bank excluded from the parent-dir sweep below, since
#: it has its own env-var pair.
_DANCE_DIRNAME = "E-MU Classic Series Vol 13 Dance 2000"


def _ebl_dance() -> tuple[Path, Path] | None:
    """The Dance 2000 input tree and its render, if both are present.

    Set ``SAMPLERDISC_EBL_DANCE_INPUT`` to the extracted ``.exb`` tree of loose
    ``.ebl`` and ``SAMPLERDISC_EBL_DANCE_ORACLE`` to mattetti's matching ``E-MU
    Sounds`` render folder. Both are copyrighted and stay outside the tree, so
    the check skips without them.
    """
    src = os.environ.get("SAMPLERDISC_EBL_DANCE_INPUT")
    oracle = os.environ.get("SAMPLERDISC_EBL_DANCE_ORACLE")
    if src and oracle and Path(src).is_dir() and Path(oracle).is_dir():
        return Path(src), Path(oracle)
    return None


def _ebl_extra_banks() -> list[tuple[str, Path, Path]]:
    """Every located stereo-oracle bank beyond Dance 2000 -- Giga Schimme, EW
    PS18 Steinberg Grand, Studio Grand -- as ``(label, input_tree, render_dir)``.

    Point ``SAMPLERDISC_EBL_BANKS`` at the parent of the extracted ``.exb``
    trees (archive.org ``emuexbsoundbanks``) and ``SAMPLERDISC_EBL_RENDERS`` at
    the parent of mattetti's render folders (``E-MU Sounds``); banks pair by an
    identical folder name. All are copyrighted local validation inputs, never
    committed and never treated as discs (ADR-0033). Dance 2000 is skipped here
    -- it keeps its own precise pin above.
    """
    src_root = os.environ.get("SAMPLERDISC_EBL_BANKS")
    render_root = os.environ.get("SAMPLERDISC_EBL_RENDERS")
    if not (src_root and render_root):
        return []
    src_root, render_root = Path(src_root), Path(render_root)
    if not (src_root.is_dir() and render_root.is_dir()):
        return []
    banks: list[tuple[str, Path, Path]] = []
    for sub in sorted(src_root.iterdir()):
        if not sub.is_dir() or sub.name == _DANCE_DIRNAME:
            continue
        # Some banks extract as ``<bank>.exb/`` and some as ``<bank>/``; the
        # render folder is always the bare bank name, so strip a trailing
        # ``.exb`` before pairing by name.
        name = sub.name[:-4] if sub.name.endswith(".exb") else sub.name
        render = render_root / name
        if render.is_dir():
            banks.append((name, sub, render))
    return banks


@dataclass(frozen=True)
class _EblBankResult:
    """What one bank's render proves about the reader: the channel census, the
    render's own stereo count for cross-check, and the byte-exact match counts.
    """

    mono: int
    stereo: int
    failed: int
    render_stereo: int
    checked_mono: int
    checked_stereo: int
    resampled: int


def _check_ebl_bank(sf, src: Path, render_dir: Path) -> _EblBankResult:
    """Parse every ``.ebl`` under ``src`` and match each uniquely-named file to
    its render in ``render_dir``, byte-for-byte and rate-exact.

    The comparison is the same for mono and stereo: ``soundfile`` returns a
    stereo FLAC as interleaved LRLR, which is exactly what ``interleave`` builds,
    so ``data.reshape(-1).tobytes()`` equals the reader's ``pcm`` in both cases.
    A render normalised to a different rate than the record declares (E-mu
    writes rates like 44 001; the record is the authority) is skipped and
    counted, and a name the bank uses twice is skipped (it cannot be matched to
    one render). FLAC is decoded with ``soundfile`` -- test tooling only; the
    converter stays pure-Python (ADR-0001).
    """
    from samplerdisc.sample import NotASample as _NotASample

    renders: dict[str, Path] = {}
    render_stereo = 0
    for flac in render_dir.glob("*.flac"):
        renders[flac.stem.split(" - ", 1)[-1].rstrip("_")] = flac
        if sf.info(str(flac)).channels == 2:
            render_stereo += 1

    mono = stereo = failed = 0
    seen: dict[str, int] = {}
    samples = []
    for path in sorted(src.rglob("*.ebl")):
        try:
            s = emu_ebl.parse(path.read_bytes())
        except _NotASample:
            failed += 1
            continue
        if s.channels == 2:
            stereo += 1
        else:
            mono += 1
        seen[s.name] = seen.get(s.name, 0) + 1
        samples.append(s)

    checked_mono = checked_stereo = resampled = 0
    for s in samples:
        if seen[s.name] > 1:
            continue
        flac = renders.get(s.name.replace(" ", "_"))
        if flac is None:
            continue
        data, rate = sf.read(str(flac), dtype="int16")
        if rate != s.rate:
            resampled += 1
            continue
        assert data.reshape(-1).tobytes() == s.pcm, s.name
        if s.channels == 2:
            checked_stereo += 1
        else:
            checked_mono += 1
    return _EblBankResult(
        mono=mono,
        stereo=stereo,
        failed=failed,
        render_stereo=render_stereo,
        checked_mono=checked_mono,
        checked_stereo=checked_stereo,
        resampled=resampled,
    )


@pytest.mark.skipif(_ebl_dance() is None, reason="set SAMPLERDISC_EBL_DANCE_INPUT/_ORACLE")
def test_both_channels_of_a_second_ebl_bank_match_its_render() -> None:
    """The generalised reader on a bank that is not Vintage Pro. Every loose
    ``.ebl`` classifies to the channel its render carries (972 mono, 636
    stereo), and every uniquely-named file whose render the publisher did not
    resample decodes PCM byte-for-byte -- proving the channel field, the V2
    audio anchor, the trailer/EOF length and now the stereo interleave (#57)
    hold on a second bank, not just the one they were first read on.
    """
    sf = pytest.importorskip("soundfile")
    src, oracle_dir = _ebl_dance()
    r = _check_ebl_bank(sf, src, oracle_dir)

    # The channel census is the ground truth: the reader must split the bank the
    # way the oracle's own stereo/mono FLAC split does, with nothing left over,
    # and the render's own stereo-FLAC count is that split confirmed a second way.
    assert (r.mono, r.stereo, r.failed) == (_DANCE_MONO, _DANCE_STEREO, 0)
    assert r.render_stereo == _DANCE_STEREO
    # Publisher resampling is a rare hand-normalisation; a rate reader that broke
    # would disagree on nearly every file, so cap the skip well below that.
    assert r.resampled <= 5
    # Most files are uniquely named and match; pin floors per channel so a broken
    # mono decode or a broken stereo interleave cannot pass by matching nothing.
    # 816 mono and 375 stereo match by name and rate on this bank.
    assert r.checked_mono >= 800
    assert r.checked_stereo >= 360


@pytest.mark.skipif(not _ebl_extra_banks(), reason="set SAMPLERDISC_EBL_BANKS/_RENDERS")
def test_every_located_stereo_bank_matches_its_render() -> None:
    """The interleave on the stereo grands, not just Dance 2000's drums. Each
    located bank's stereo ``.ebl`` count equals its render's own stereo-FLAC
    count -- a whole-bank channel agreement -- and every uniquely-named file
    that matches by rate is byte-exact, including a real population of stereo
    files so a broken interleave cannot pass on the mono half alone.
    """
    sf = pytest.importorskip("soundfile")
    banks = _ebl_extra_banks()
    for label, src, render_dir in banks:
        r = _check_ebl_bank(sf, src, render_dir)
        assert r.failed == 0, label
        # The publisher's render is a subset of the input -- a bank ships a few
        # more sample ``.ebl`` than were rendered -- so the reader must classify
        # at least as many stereo files as the render carries, never fewer (an
        # anti-undercount census that does not assume every ``.ebl`` was
        # rendered). Every matched file is already asserted byte-exact inside
        # the helper, mono against a raw render and stereo against an interleaved
        # one, so a misclassification could not have matched.
        assert r.stereo >= r.render_stereo > 0, label
        # A real population of stereo files matched, so the interleave is
        # exercised on this bank rather than skipped past.
        assert r.checked_stereo > 0, label
        assert r.resampled <= max(5, (r.mono + r.stereo) // 100), label


def _loose_ebl_root() -> str | None:
    """A directory of loose ``.exb``/``SamplePool`` banks in the clear.

    Point ``SAMPLERDISC_LOOSE_EBL`` at the parent of the extracted Proteus
    1/2/3 trees (archive.org ``e-mu-sample-sets``). Copyrighted local input,
    never committed and never treated as a disc.
    """
    root = os.environ.get("SAMPLERDISC_LOOSE_EBL")
    return root if root and Path(root).is_dir() else None


@pytest.mark.skipif(_loose_ebl_root() is None, reason="set SAMPLERDISC_LOOSE_EBL")
def test_a_loose_ebl_tree_converts_to_wav(tmp_path) -> None:
    """The loose-file source end to end on the real Proteus banks (ADR-0042).

    The decode is oracle-verified above; this guards the ingest and write path
    -- every ``.ebl`` in the tree is discovered, converted to a WAV that exists
    on disk, and none is refused. The Proteus banks are overwhelmingly mono ROM
    samples with the odd genuine stereo (``Snare w/Verb 28K``), classified by
    the same V12 channel byte D34 verified against the renders, so a skip or an
    exception -- not a stereo file -- is the news worth failing on.
    """
    from samplerdisc import banks as banks_src

    root = _loose_ebl_root()
    found = banks_src.find_bank_dirs(root)
    assert found, "no .ebl banks discovered under SAMPLERDISC_LOOSE_EBL"
    written = skipped = 0
    for result in banks_src.extract_banks(root, str(tmp_path)):
        if isinstance(result, Extracted):
            written += 1
            assert result.channels in (1, 2)
            assert Path(result.path).is_file()
        else:
            skipped += 1
    assert written > 0
    assert skipped == 0


def _smpl(payload: bytes) -> tuple[int, list[tuple[int, int]]]:
    """Root key and loop points from a WAV's own smpl chunk."""
    pos = 12
    while pos + 8 <= len(payload):
        tag = payload[pos : pos + 4]
        size = struct.unpack_from("<I", payload, pos + 4)[0]
        if tag == b"smpl":
            body = payload[pos + 8 : pos + 8 + size]
            note = struct.unpack_from("<I", body, 12)[0]
            count = struct.unpack_from("<I", body, 28)[0]
            loops = [
                struct.unpack_from("<II", body, 36 + index * 24 + 8)
                for index in range(count)
                if 36 + index * 24 + 24 <= len(body)
            ]
            return note, loops
        pos += 8 + size + (size & 1)
    return 0, []


#: E-mu ``EMU3`` discs pinned by size, with the volumes and samples each must
#: yield. docs/formats/emu3.md calls these the regression baseline for the
#: shared record parser and until now nothing asserted them: the numbers lived
#: in a table in the doc, which is a note, not a test. ADR-0021 moved four of
#: the seven and there was no failing test to say so.
#: Labelled by the short names docs/formats/emu3.md uses, which is what the
#: measurements there are recorded against.
#: ``label: (size in bytes, volumes, samples, samples carrying a loop, samples
#: the record declares stereo, the SHA-256 of every sample payload on the disc,
#: concatenated in walk order)``.
#:
#: The digest is the pin that matters most. D17 decoded the sample record's
#: pointer block and taught the E-mu path to write a ``smpl`` chunk, which is
#: **additive by construction**: nothing in it touches ``read_file`` or the
#: offset arithmetic, and the digest is what says so rather than the diff. All
#: seven were computed against the release before D17 and none of them moved.
#:
#: The loop counts are pinned as tightly as the sample counts, for the reason
#: the noted-volume counts are on the AKAI table: a loop appearing where none
#: was measured is a gate that has come loose, and one disappearing is the
#: decode silently failing on a disc nobody looked at.
#:
#: **D23 moved every loop count and no digest.** The whole-extent "no loop" is
#: now refused at both ends, not only where it starts at frame 0, so the loops
#: over the entire file that ten discs wrote with a small fixed inset stop being
#: emitted: `ditto-drums` 948 -> 14, `eiiix-1` 1 215 -> 743, `eiv-vitous`
#: 826 -> 198, `eiv-analogia` 449 -> 6. The measurement is in ADR-0030 and the
#: "Loop points" section of the format doc; the discs' *sample* counts, stereo
#: counts and every payload digest are unchanged, which is what says only loop
#: emission moved and the read path did not (ADR-0030).
#:
#: The stereo counts are D18's pin and they are the records whose own pointer
#: block declares two channels *and* closes the left one where the right one
#: opens (ADR-0026). Under D21's extent they are the same four numbers on the
#: four discs that had them -- 28, 8, 601, 592 -- which is the check that
#: changing how long a record is did not change what shape it is. The gate's
#: third condition now rejects **nothing** on any of the ten discs: the 65
#: records it used to catch were records sized from the wrong pointer, and the
#: right size stops them looking like a split at all (ADR-0029).
#:
#: **The four EIII/ESI rows moved in D21 and every digest with them.** The
#: record's extent came from ``+34``, which is the right channel's end pointer
#: and closes the record only where the right-hand set describes it. It does
#: not on 6 092 records of `esi32-gm` and `protozoa`, which came out 92 bytes
#: short, and it silently loses every record that declares its one channel on
#: the right. The three E-IV rows are byte-identical across the change, which
#: is what says the shared parts were not disturbed: those discs size a record
#: from their own big-endian directory and never touch ``+34`` (ADR-0029).
#:
#: `emu-classics`, `vintage` and `ditto-drums` are the discs of issue #39 and
#: the ones D21 was measured against. `ditto-drums` is the whole shape of the
#: bug on one disc: 74 samples before, 948 after.
_EMU3 = {
    "esi32-gm": (93_077_504, 10, 2635, 1350, 28, "35a6c6edfc6f292a"),
    "protozoa": (131_690_496, 16, 6595, 3482, 8, "3530e1e972f100ab"),
    "eiiix-1": (304_128_000, 46, 1248, 743, 601, "c73db948bf4f61cb"),
    "eiiix-2": (304_435_200, 46, 1337, 892, 592, "8bfcddf6d8dbd806"),
    "emu-classics": (526_723_072, 22, 1516, 1133, 185, "e1398c11a9e7cb02"),
    "vintage": (527_030_272, 16, 993, 846, 2, "fbcc378dd173f96c"),
    "ditto-drums": (308_121_600, 48, 979, 14, 0, "47b17bcd6028ec29"),
    # D25 reads the E-IV banks stored as native ``FORM/E4B0`` IFF files, whose
    # samples are ``E3S1`` chunks inside the container rather than a flat record
    # run indexed by a chained directory (ADR-0032). Those banks bound nothing
    # before and were listed empty; now they extract. `eiv-analogia` is the
    # control -- it has no such bank, so its four fields are byte-for-byte what
    # D23/D18 left, which is the check that the new path did not touch the old.
    # `eiv-studio` gains 987 samples (2822 -> 3809), `eiv-vitous` 24 (828 ->
    # 852). Three more E-IV discs are pinned for the first time by this
    # recovery, including `eiv-phatt-cd1`, whose one previously-empty bank alone
    # yields 692 of its 4552. The four residual `Credits`/preset banks that hold
    # no sample chunk stay noted (see _EMU3 volume/note invariant below).
    "eiv-analogia": (293_912_576, 12, 449, 6, 279, "5d8faa38572914cb"),
    "eiv-studio": (399_077_376, 230, 3809, 3029, 320, "25fcc612ea458b0e"),
    "eiv-studio-vol2": (399_077_376, 168, 1665, 1093, 474, "fbe642b97e5cec43"),
    "eiv-vol5": (524_906_496, 96, 1104, 596, 930, "d81594c686b7b932"),
    "eiv-phatt-cd1": (629_764_096, 17, 4552, 944, 898, "a96a570c73e8f181"),
    # D30 reads a fragmented ``FORM/E4B0`` bank along its FAT chain rather than
    # contiguously (ADR-0037). `eiv-vitous`'s ``CES 1`` is the collection's one
    # fragmented located bank: it holds 20 samples across three cluster runs, and
    # the contiguous reader stopped at the first break, stranding 8 (852 -> 860).
    # All 8 are mono one-shots, so the loop and stereo counts do not move; the
    # digest does, because the 8 recovered payloads join the walk. Every other
    # disc is wholly contiguous, so a FAT-chain read is byte-for-byte the
    # contiguous read and no other pin here moves.
    "eiv-vitous": (532_443_136, 44, 860, 208, 828, "d2c43a84af1d7f01"),
    # D24 recovers a bank whose header carries a mis-typed copy of its
    # directory name (ADR-0031). ``ditto-drums`` gains ``PERCUSSION#1   X``'s
    # 31 records above; these two discs were pinned for the first time by it.
    #
    # D27 fixes the separate duplicate-directory-name double-listing D24 left
    # in these totals (ADR-0034, #47). ``located`` is now keyed by directory
    # entry, not by name, so where a disc writes one name twice each entry
    # binds to its own header. ``elements1mb`` writes ``Harpsichord    X``
    # twice with a header apiece -- 11 records and 13, two different banks the
    # old totals read as the 13 twice, so 1465 -> 1463 and the digest moves.
    # ``heavy`` writes ``HvyGtr Maj.Open`` twice with only one header wearing
    # the name; its second entry's predicted address holds a blank-named,
    # byte-identical copy the first entry already yields, so that entry is
    # noted rather than bound (never by address alone -- ADR-0031, ADR-0034),
    # and its 6 duplicate records fall away: 870 -> 864, with 6 fewer loops and
    # 6 fewer stereo. Both discs still list 102 and 68 volumes; the second
    # ``HvyGtr Maj.Open`` volume is now noted, not empty-without-reason.
    "elements1mb": (296_042_496, 102, 1463, 1179, 0, "d7f2c87ea4da9d6f"),
    "heavy": (524_599_296, 68, 864, 674, 739, "7d684c05a5556fd8"),
}


#: The E-IV discs that carry disc provenance in a sample-free ``FORM/E4B0``
#: text bank -- the ``Credits`` and ``E-mu Systems 96`` banks D25 correctly
#: noted as holding no audio. D36 reads their ``E4P1`` name fields (the credit
#: line, never the preset) into a ``Credits.txt`` sidecar under ``--metadata``
#: (ADR-0043). Eight banks, 89 lines across the collection, verified against the
#: discs -- docs/formats/emu3.md, "A FORM with no E3S1 chunk". Per label:
#: (size, credit lines summed over the disc's text-bank volumes, distinct
#: sidecar sections after collapsing byte-identical banks, sidecar lines, one
#: line the disc is known to carry). ``eiv-studio`` writes ``E-mu Systems 96``
#: four times byte-identically, so its 24 volume lines collapse to one 6-line
#: section; the four ``Credits`` discs each carry one bank. Sizes are unique on
#: the shelf, so no first-megabyte digest is needed (eiv-studio already has one
#: for its Vol. 2 twin).
_EMU3_CREDITS = {
    "eiv-studio": (399_077_376, 24, 1, 6, "E-mu Systems 96"),
    "eiv-vol5": (524_906_496, 10, 1, 10, "Franz Pusch"),
    "eiv-hollywood": (660_910_080, 13, 1, 13, "Frank Serafine"),
    "eiv-denny": (493_754_368, 14, 1, 14, "Denny Jaeger"),
    "eiv-phatt-cd2": (503_934_976, 28, 1, 28, "Platinum Phatt"),
}


@pytest.mark.parametrize("label", sorted(_EMU3_CREDITS))
def test_emu3_credits_text_banks_carry_disc_provenance(label: str, tmp_path: Path) -> None:
    """A sample-free ``Credits``/``E-mu Systems 96`` bank still says why it has
    no audio (ADR-0032), and now surfaces its ``E4P1`` name lines as provenance,
    written once per disc as a ``Credits.txt`` sidecar (ADR-0043).
    """
    from samplerdisc.extract import write_credits

    size, total, sections, sidecar_lines, spot = _EMU3_CREDITS[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        volumes = list(origin.backend.volumes(image, origin.offset))
    carrying = [v for v in volumes if v.credits]
    assert carrying, f"{label}: no text bank surfaced any credit line"
    # Every credit-bearing volume is a located, sample-free text bank: the audio
    # note stays accurate and no bank with audio ever contributes a line.
    assert all(not v.files and v.note for v in carrying)
    assert sum(len(v.credits) for v in carrying) == total
    assert spot in {line for v in carrying for line in v.credits}
    result = write_credits(str(tmp_path), [(v.name, v.credits) for v in volumes if v.credits])
    assert result is not None
    assert (result.banks, result.lines) == (sections, sidecar_lines)


#: The seven EMU3 ``.iso`` masters the superblock checksum was cross-checked
#: against in PR #65 (docs/formats/emu3.md, "Independent corroboration"), and
#: which issue #66 names as the pin. The checksum -- the sum mod 2**16 of the
#: 255 u16 LE words over 0x000-0x1FD, stored at 0x1FE -- is the header-integrity
#: gate probe() now applies. Every *other* _EMU3 disc (the E-IV discs and the
#: shared-size twins) exercises the same gate implicitly:
#: test_emu3_discs_list_their_banks_and_samples asserts the emu3 probe accepts
#: it, which now requires the checksum to pass.
_EMU3_CHECKSUM_MASTERS = (
    "esi32-gm",
    "protozoa",
    "eiiix-1",
    "eiiix-2",
    "emu-classics",
    "vintage",
    "ditto-drums",
)


#: The FAT cluster size each reference disc uses, in bytes. This is the ``unit``
#: the per-disc fit measures and the FAT names -- and it is *not* derivable
#: (protozoa uses 1 MiB where its FAT ceiling would allow 256 KiB, so "smallest
#: size that fits" is wrong), so it is pinned per disc, matching the table in
#: docs/formats/emu3.md, "The block-2 FAT" (ADR-0037).
_EMU3_CLUSTER_BYTES = {
    "esi32-gm": 262144,
    "eiiix-1": 262144,
    "eiiix-2": 262144,
    "protozoa": 1048576,
    "eiv-analogia": 1048576,
    "emu-classics": 524288,
    "vintage": 524288,
    "ditto-drums": 524288,
    "eiv-studio": 524288,
    "eiv-vitous": 524288,
}


@pytest.mark.parametrize("label", sorted(_EMU3_CLUSTER_BYTES))
def test_emu3_addresses_are_reproduced_by_the_block_2_fat(label: str) -> None:
    """The FAT is the independent structure the per-disc fit approximates (ADR-0037).

    Every bank/base the reader locates -- by signature scan for EIII, by the
    allocation fit for E-IV -- must begin a real FAT cluster chain, and the byte
    address the FAT gives that first cluster must equal the located address to
    the byte. The fit is measured from the same headers it then places, so this
    is the *external* check it lacks: the block-2 FAT is a different structure,
    and it agrees on every disc. The cluster size it uses is pinned too, because
    it is not derivable (protozoa) and is the constant the doc records.
    """
    from samplerdisc.fs import emu3

    size = _EMU3[label][0]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        backend, offset = origin.backend, origin.offset
        fat = emu3._read_fat(image, offset)
        assert fat and fat[0] == emu3.FAT_RESERVED

        banks = backend._banks(image, offset)
        headers = backend._bank_headers(image, offset)
        located = backend._bank_offsets(banks, headers)

        checked = 0
        placement = backend._placement(banks, headers)
        if placement is not None:
            # EIII: the fit addresses are bytes, so the cluster size is the unit.
            unit_bytes, bias_bytes = placement
            assert unit_bytes == _EMU3_CLUSTER_BYTES[label]
            for index, bank in enumerate(banks):
                at = located.get(index)
                if at is None:
                    continue
                chain = emu3._fat_chain(fat, bank.start)
                assert chain and chain[0] == bank.start, bank.name
                assert unit_bytes * bank.start + bias_bytes == at, bank.name
                checked += 1

        _tags, bound, form, geom = (
            backend._eiv(image, offset, banks)
            if any(index not in located for index in range(len(banks)))
            else ({}, {}, {}, None)
        )
        # geom is None on an all-EIII disc (its unlocated banks are the noted
        # index/code banks, not E-IV); the E-IV corroboration only applies where
        # the disc actually has a FORM or flat E-IV bank.
        if geom is not None:
            unit_blocks, bias_blocks = geom
            assert unit_blocks * emu3.BLOCK == _EMU3_CLUSTER_BYTES[label]
            for bank in banks:
                if bank.start in bound:
                    at = bound[bank.start][0] - emu3.EIV_RECORD_OFFSET  # base carries +8
                elif bank.start in form:
                    at = form[bank.start]
                else:
                    continue
                chain = emu3._fat_chain(fat, bank.start)
                assert chain and chain[0] == bank.start, bank.name
                assert emu3._fat_byte(unit_blocks, bias_blocks, bank.start) == at, bank.name
                checked += 1

        assert checked >= 8, f"{label}: only {checked} addresses corroborated"


def test_emu3_a_fragmented_form_bank_is_read_along_its_chain() -> None:
    """vitous ``CES 1`` is the collection's one fragmented located bank (ADR-0037).

    Its FAT chain is not a single ascending run, so a contiguous read stops at
    the first break; the reader gathers it along the chain instead and recovers
    the samples stranded in the tail. This pins both halves: that the bank really
    is fragmented (or the recovery is untested), and that its extra samples are
    read as ``embedded`` slices of the gathered bank, not flat image addresses.
    """
    from samplerdisc.fs import emu3

    size = _EMU3["eiv-vitous"][0]
    with open_image(_pinned_disc("eiv-vitous", size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        backend, offset = origin.backend, origin.offset
        fat = emu3._read_fat(image, offset)
        banks = backend._banks(image, offset)
        ces = next(b for b in banks if b.name.strip() == "CES 1")
        chain = emu3._fat_chain(fat, ces.start)
        assert not emu3._fat_contiguous(chain), "CES 1 is expected to be fragmented"

        volume = next(v for v in backend.volumes(image, offset) if v.name.strip() == "CES 1")
        samples = [f for f in volume.files if f.kind == "sample"]
        assert len(samples) == 20
        # The tail samples the contiguous read could not reach are embedded
        # slices of the gathered bank; every one must round-trip its own bytes.
        embedded = [f for f in samples if f.get("embedded")]
        assert len(embedded) == 20
        for entry in embedded:
            assert len(backend.read_file(image, offset, entry)) == entry.size


@pytest.mark.parametrize("label", _EMU3_CHECKSUM_MASTERS)
def test_emu3_superblock_checksum_validates_the_header(label: str) -> None:
    """The 0x1FE superblock checksum is self-consistent on every master.

    Asserts both the raw arithmetic and the backend's own
    ``_superblock_checksum_ok`` agree, so the constant in the source and the one
    the doc claims cannot drift (issue #66).
    """
    from samplerdisc.fs.emu3 import (
        OFF_CHECKSUM,
        SUPERBLOCK_LEN,
        _superblock_checksum_ok,
    )

    size = _EMU3[label][0]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        head = image.read(origin.offset, SUPERBLOCK_LEN)
        words = struct.unpack_from(f"<{SUPERBLOCK_LEN // 2}H", head)
        assert sum(words[: OFF_CHECKSUM // 2]) % 0x10000 == words[OFF_CHECKSUM // 2]
        assert _superblock_checksum_ok(head)


@pytest.mark.parametrize("label", sorted(_EMU3))
def test_emu3_discs_list_their_banks_and_samples(label: str) -> None:
    """Pinned where present, skipped where the shelf is bare -- see _pinned_disc().

    Also the implicit full-corpus check on the superblock-checksum gate (#66):
    probe() rejects a header whose 0x1FE checksum does not verify, so requiring
    the emu3 backend to claim every _EMU3 disc requires the checksum to hold on
    each -- confirmed 17/17 across the local collection.
    """
    size, volumes_expected, samples_expected, _, _, _ = _EMU3[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        assert origin.backend.name == "emu3"
        volumes = list(origin.backend.volumes(image, origin.offset))
        assert len(volumes) == volumes_expected
        assert sum(len(v.files) for v in volumes) == samples_expected
        # A volume with no files must say why, on every disc, every time
        # (ADR-0012). This is the same rule as the collection-wide check
        # above, tightened from "some volume explains itself" to "each one
        # does" -- which only a disc whose expected shape is known can ask.
        assert all(v.files or v.note for v in volumes), [v.name for v in volumes if not v.files]


def _deinterleave(pcm: bytes) -> tuple[bytes, bytes]:
    """The two channels of an interleaved buffer, back as they were stored.

    Through ``array`` rather than a byte slice: ``pcm[0::4]`` would take the
    low byte of every left sample and leave its high byte behind. No byteswap
    is needed on either host order, because this regroups 2-byte units and
    never reads their value.
    """
    frames = array("h")
    frames.frombytes(pcm)
    return frames[0::2].tobytes(), frames[1::2].tobytes()


@pytest.mark.parametrize("label", sorted(_EMU3))
def test_emu3_loops_are_decoded_without_disturbing_the_audio(label: str) -> None:
    """The D17 invariant and the D18 one, which are the same invariant
    (ADR-0025, ADR-0026).

    The payload digest is the whole point. D17 decoded the record's pointer
    block and had to add a ``smpl`` chunk while changing nothing else; D18 acts
    on the channel count in that same block, and the audio it writes must be a
    **permutation** of the disc's bytes rather than merely the same length. So
    two things are asserted at once: the digest of every payload as
    ``read_file`` returns it has not moved, and de-interleaving each stereo
    sample reproduces the two blocks the disc stored, byte for byte.

    The loop counts are pinned across the change for the same reason.
    ``(pointer - start) / 2`` is a per-channel frame index either way, so a
    loop that moves is arithmetic that drifted, not a decode that improved.
    Every loop must still lie inside its own sample's frames -- which for a
    stereo sample now means inside its *channel*, a tighter bound than before.
    """
    size, _, samples_expected, loops_expected, stereo_expected, digest_expected = _EMU3[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        digest = hashlib.sha256()
        samples = looped = stereo = 0
        for volume in origin.backend.volumes(image, origin.offset):
            for entry in volume.samples():
                samples += 1
                payload = origin.backend.read_file(image, origin.offset, entry)
                digest.update(payload)
                sample = origin.backend.parse_sample(entry, payload)
                # No root key is stated anywhere in the 92-byte record, on any
                # of the seven discs. Inventing one is what ADR-0025 refuses.
                assert sample.pitch is None
                if sample.channels == 2:
                    stereo += 1
                    half = len(payload) // 2
                    assert sample.frames == half // 2
                    assert _deinterleave(sample.pcm) == (payload[:half], payload[half:]), (
                        f"{entry.name}: the stereo audio is not the disc's own bytes"
                    )
                else:
                    assert sample.pcm == payload[: sample.frames * 2]
                for loop in sample.loops:
                    assert 0 <= loop.start < loop.end <= sample.frames, (
                        f"{entry.name}: loop ({loop.start}, {loop.end}) is not "
                        f"inside {sample.frames} frames"
                    )
                looped += bool(sample.loops)
        assert samples == samples_expected
        assert looped == loops_expected, f"{label}: D18 moved a loop point"
        assert stereo == stereo_expected
        assert digest.hexdigest()[:16] == digest_expected, (
            f"{label}: sample payloads moved -- the read path must be untouched"
        )


#: How the period / pre-start window scores each of `eiv-analogia`'s six
#: residual loops -- the ones kept after D23 refuses the whole-extent "no loop"
#: (ADR-0030). These six were emitted **entirely on the rule the other E-mu
#: discs establish**: the forward shape/join oracle of emu3.md had no power on
#: them, because a near-whole-extent loop has almost no audio after its end for
#: a forward window to correlate (issue #50, recorded in ADR-0025). The
#: period window does -- ``x[t] ~= x[t - P]`` survives on a loop running to the
#: last frame -- and it gives the disc its own per-record confirmation for the
#: first time (ADR-0044).
#:
#: ``confirm`` -- the loop splices at its own period as a clear local maximum
#: (r >= 0.9 and above every off-period lag by a margin), where a wrong period
#: does not. ``flat`` -- scorable but no period structure at any lag: ``Conscience
#: Call`` is a near-whole-extent "no loop" whose start (frame 13 061) sits just
#: past D23's start-side slack, so the refusal did not catch it. ``quiet`` -- the
#: loop end is below the loudness gate and cannot be scored: ``Got Scratch?``
#: ends in near-silence, the same signature ADR-0030's end-energy test reads as
#: a "no loop". So four of the six gain independent confirmation; the two that
#: do not are named here rather than hidden, and their emission is left
#: unchanged -- this is a measurement, not a change to what ships.
_EIV_ANALOGIA_RESIDUAL_LOOPS = {
    "Usnotthem Chorus": "confirm",
    "Trilling Sound": "confirm",
    "The Lost Chord 1": "confirm",
    "The Lost Chord 2": "confirm",
    "Conscience Call": "flat",
    "Got Scratch?": "quiet",
}

#: The pre-start window and its guards, mirroring the shipped parser and the
#: emu3.md "Loop points" oracle: 256 frames before each of the loop start and
#: the loop end, a 15%-of-peak loudness gate on the end window (a metric that
#: rewards silence finds plenty of it), off-period lags at fractions of the
#: period for the local-maximum control, and the margin the period must clear.
_PERIOD_WINDOW = 256
_PERIOD_LOUDNESS = 0.15
_PERIOD_OFF_FRACS = (0.05, 0.25, 0.5, -0.05, -0.25, -0.5)
_PERIOD_MARGIN = 0.10


def test_emu3_eiv_residual_loops_are_confirmed_by_their_period() -> None:
    """The confirmation issue #50 asked for, on the disc itself (ADR-0044).

    The forward shape/join oracle that confirms EIII/ESI loops has no power on
    `eiv-analogia`: its loops are overwhelmingly the whole-extent "no loop",
    which ends within a few frames of the last, so there is no audio after the
    loop end for a forward window to correlate. ADR-0025 recorded that only 34
    of its records scored and those showed nothing, and after D23 refused the
    whole-extent form the disc keeps six loops resting purely on the rule the
    other discs establish.

    The **period / pre-start window** does have power here. A loop of period
    ``P`` makes ``x[t] ~= x[t - P]``, so the 256 frames before the loop end match
    the 256 before the loop start -- a relationship that still exists when the
    loop runs to the last frame, which is most of these. The control is not a
    wrong *start* (for a sustained near-whole-extent tone the lead-in
    self-correlates at any period multiple); it is **lag sensitivity** -- the
    correlation must peak at ``P`` and fall away at off-period lags, the
    signature of a chosen period rather than a self-similar texture.

    Two assertions. Every emitted loop on `eiv-analogia` is pinned by name and
    outcome, so a regression that quietly confirms or refutes one is caught;
    and the same metric is calibrated on `eiv-studio`'s real, forward-confirmed
    loops, so the instrument is shown to have power rather than rubber-stamping.
    No shipped code runs differently -- ``sample.loops`` is what the extractor
    already emits, so the pinned loop counts and payload digests are untouched.
    """
    np = pytest.importorskip("numpy")

    def left_channel(sample):
        frames = np.frombuffer(sample.pcm, dtype="<i2").astype(np.float64)
        return frames[::2] if sample.channels == 2 else frames

    def pearson(u, v):
        u = u - u.mean()
        v = v - v.mean()
        d = math.sqrt(float((u * u).sum()) * float((v * v).sum()))
        return float((u * v).sum() / d) if d > 0 else 0.0

    def score(x, a, b):
        """``confirm`` / ``flat`` / ``quiet`` for a loop of ``(a, b)`` frames."""
        peak = float(np.abs(x).max()) if x.size else 0.0
        if a - _PERIOD_WINDOW < 0 or b - _PERIOD_WINDOW < 0 or peak <= 0:
            return "quiet"
        end = x[b - _PERIOD_WINDOW : b]
        if math.sqrt(float((end * end).mean())) < _PERIOD_LOUDNESS * peak:
            return "quiet"
        r = pearson(x[a - _PERIOD_WINDOW : a], end)
        period = b - a
        best_off = None
        for frac in _PERIOD_OFF_FRACS:
            ap = a + int(frac * period)
            if ap - _PERIOD_WINDOW < 0 or ap > b or ap == a:
                continue
            off = pearson(x[ap - _PERIOD_WINDOW : ap], end)
            best_off = off if best_off is None else max(best_off, off)
        confirmed = r >= 0.9 and (best_off is None or r >= best_off + _PERIOD_MARGIN)
        return "confirm" if confirmed else "flat"

    def emitted_loops(label):
        size = _EMU3[label][0]
        with open_image(_pinned_disc(label, size)) as image:
            origin = find_origin(image)
            assert origin is not None and origin.backend.name == "emu3"
            for volume in origin.backend.volumes(image, origin.offset):
                for entry in volume.samples():
                    payload = origin.backend.read_file(image, origin.offset, entry)
                    sample = origin.backend.parse_sample(entry, payload)
                    if sample.loops:
                        loop = sample.loops[0]
                        yield entry.name, score(left_channel(sample), loop.start, loop.end)

    seen = dict(emitted_loops("eiv-analogia"))
    assert seen == _EIV_ANALOGIA_RESIDUAL_LOOPS, (
        f"eiv-analogia's residual loops no longer score as measured (ADR-0044): {seen}"
    )

    scorable = confirmed = 0
    for _name, outcome in emitted_loops("eiv-studio"):
        if outcome == "quiet":
            continue
        scorable += 1
        confirmed += outcome == "confirm"
    assert scorable >= 500, f"eiv-studio calibration scored too few loops: {scorable}"
    assert confirmed / scorable >= 0.5, (
        "the period window has no power on eiv-studio's real, forward-confirmed "
        f"loops: only {confirmed} of {scorable} confirm -- the instrument that "
        "vindicates analogia's survivors must first work where the forward "
        "oracle already did"
    )


def test_protozoa_gives_each_bank_its_own_records() -> None:
    """The three banks of issue #15, and the two that were invisible.

    ``Orbit Presets 4k`` and ``Phatt Presets 4K`` carry an ``EMU SI-32``
    header rather than an ``EMULATOR`` one. Nothing located them, so the bank
    in front of each swallowed its region and reported its records a second
    time; ``Protozoa       X`` is the disc's index bank and was credited with
    63 records of the Phatt banks' besides. See ADR-0021.
    """
    size = _EMU3["protozoa"][0]
    with open_image(_pinned_disc("protozoa", size)) as image:
        origin = find_origin(image)
        assert origin is not None
        volumes = {v.name: v for v in origin.backend.volumes(image, origin.offset)}
        assert len(volumes["Orbit Presets  X"].files) == 558
        assert len(volumes["Orbit Presets 4k"].files) == 558
        assert len(volumes["Phatt Presets  X"].files) == 493
        assert len(volumes["Phatt Presets 4K"].files) == 255
        # The index bank: empty because the disc made it empty, and saying so
        # is what tells that apart from a bound that failed.
        assert volumes["Protozoa       X"].files == []
        assert volumes["Protozoa       X"].note
        # No two volumes may claim one record. That is the tell the bug was
        # found by, and it is what "a bank reports only its own" means.
        seen: dict[int, str] = {}
        for volume in volumes.values():
            for entry in volume.files:
                assert seen.setdefault(entry.start_block, volume.name) == volume.name, (
                    f"{entry.name} at {entry.start_block} is listed by "
                    f"{seen[entry.start_block]!r} and by {volume.name!r}"
                )


#: The banks of [issue #39](https://github.com/bmxcode/samplerdisc/issues/39),
#: with the samples each yields and the right-hand pointer set that hid them.
#: Twelve banks across three discs claimed a volume, returned nothing and gave
#: no reason, which is the ADR-0012 signature -- and none of them was an index
#: bank, so ``OFF_BANK_SAMPLE_BYTES`` had nothing to say about any of them.
#:
#: They are pinned by the **shape** and not only by the count, because the
#: count alone would pass again the moment a record was found for the wrong
#: reason. Each shape is a different way for ``+34`` -- the right channel's end
#: pointer -- not to describe the record it sits in (ADR-0029):
#:
#: * ``zeroed`` -- the unused side is all zeros, so ``+34`` gives an extent of
#:   2 and the record is rejected as shorter than its own header.
#: * ``frame`` -- the right-hand set names a fixed memory frame rather than
#:   this record, so ``+34`` points past the whole bank region.
#: * ``right`` -- the record's one channel is declared on the right, with the
#:   left zeroed, so the walk's left-hand signature never sees it.
_EMU3_SILENT_BANKS = {
    "emu-classics": (("Vox Haunt      X", 14, "frame"),),
    "vintage": (("Juno Synths", 44, "right"),),
    "ditto-drums": (
        ("TAMJAZ KIT10   X", 28, "zeroed"),
        ("PERCUSSION#2   X", 42, "zeroed"),
        ("TIMPANI HDML   X", 3, "zeroed"),
        ("TIMPANI SFML   X", 3, "zeroed"),
        ("VIBRAPHONE     X", 4, "zeroed"),
        ("MARIMBA        X", 26, "zeroed"),
        ("XYLOPHONE      X", 12, "zeroed"),
        ("CONCERT BELL   X", 5, "zeroed"),
        ("TUBULAR BELL   X", 3, "zeroed"),
        ("OCTABONS       X", 8, "zeroed"),
    ),
}


@pytest.mark.parametrize("label", sorted(_EMU3_SILENT_BANKS))
def test_emu3_banks_that_declared_a_sample_area_and_yielded_nothing(label: str) -> None:
    """Issue #39, pinned by the mechanism rather than by the totals.

    Every one of these banks declares a non-zero sample area, so none of them
    could be explained the way an index bank is (ADR-0021). What they have in
    common is a right-hand pointer set that says nothing about the record it
    sits in, and a walk that took the record's extent from it anyway.

    The shape is asserted on the records themselves, so the day this stops
    holding it says which of the three ways it stopped.
    """
    from samplerdisc.fs.emu3 import SAMPLE_HEADER_LEN

    size = _EMU3[label][0]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        volumes = {v.name: v for v in origin.backend.volumes(image, origin.offset)}
        for name, expected, shape in _EMU3_SILENT_BANKS[label]:
            files = volumes[name].files
            assert len(files) == expected, f"{label}/{name}: {len(files)} samples"
            for entry in files:
                start_l, start_r = entry.get("start_l"), entry.get("start_r")
                end_r = entry.get("end_r")
                if shape == "zeroed":
                    assert (start_l, start_r, end_r) == (SAMPLE_HEADER_LEN, 0, 0)
                elif shape == "right":
                    assert (start_l, start_r) == (0, SAMPLE_HEADER_LEN)
                else:
                    # A fixed allocation frame: the right-hand set opens one
                    # frame past the audio and closes at the end of a second,
                    # the same two numbers on every record of the bank.
                    assert start_l == SAMPLE_HEADER_LEN
                    frame = start_r - SAMPLE_HEADER_LEN
                    assert frame > 0 and frame & (frame - 1) == 0
                    assert end_r == SAMPLE_HEADER_LEN + 2 * frame - 2


#: The banks of [issue #43](https://github.com/bmxcode/samplerdisc/issues/43),
#: with the records each yields and the mis-typed header name that hid it.
#: Five named EIII/ESI banks across three discs claimed a volume, found no
#: header for their directory name and read nothing, and unlike the OS-code
#: slots that share that note they are ordinary sample banks (ADR-0031).
#:
#: They are pinned by the **mechanism** and not only by the count. Each carries
#: a real ``EMULATOR`` header at the address its placement predicts, whose own
#: name at ``+16`` is the directory name corrupted by a shifted space, a case
#: change or a single doubled/dropped character -- which is why keying
#: ``located`` on exact-name equality missed it. The test asserts the bound
#: header's name is that near-copy and is *not* the directory name, so the day
#: this stops holding it says whether the bank went empty, was located wrong,
#: or matched by exact name after all.
_EMU3_RECOVERED_BANKS = {
    "elements1mb": (("Electric Grand X", 9, "Eelectric GrandX"),),
    "ditto-drums": (("PERCUSSION#1   X", 31, "PERCUSSION #1  X"),),
    "heavy": (
        ("HvyGtr FX5     X", 2, "HvyGtr FX5    XX"),
        ("Misc Gtr FX 2MbX", 6, "Misc Gtr FX 2mbX"),
        ("HvGtrFdBkTxtr2Mb", 1, "HvGtrFdBkTxtr2M"),
    ),
}


@pytest.mark.parametrize("label", sorted(_EMU3_RECOVERED_BANKS))
def test_emu3_banks_recovered_from_a_mistyped_header_name(label: str) -> None:
    """Issue #43, pinned by the mis-typed header rather than by the totals.

    A regression here is a bank falling back to its note, or -- worse and
    quieter -- binding a *different* header. Asserting the bound header's own
    name is the corrupted copy, distinct from the directory name, is what tells
    a genuine recovery apart from an exact-name match that would mean the
    corruption was never really there.
    """
    from samplerdisc.fs.emu3 import (
        BANK_NAME_LEN,
        OFF_BANK_NAME,
        _near_name,
        decode_name,
    )

    size = _EMU3[label][0]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        backend = origin.backend
        offset = origin.offset
        banks = backend._banks(image, offset)
        headers = backend._bank_headers(image, offset)
        placement = backend._placement(banks, headers)
        assert placement is not None, f"{label}: no placement fit to recover through"
        unit, bias = placement
        volumes = {v.name: v for v in backend.volumes(image, offset)}
        by_start = {bank.name: bank.start for bank in banks}
        for name, expected, header_name in _EMU3_RECOVERED_BANKS[label]:
            volume = volumes[name]
            assert len(volume.files) == expected, f"{label}/{name}: {len(volume.files)} samples"
            assert not volume.note, f"{label}/{name}: recovered but still noted"
            want = unit * by_start[name] + bias
            raw = image.read(offset + want + OFF_BANK_NAME, BANK_NAME_LEN)
            assert decode_name(raw) == header_name, f"{label}/{name}: header name {raw!r}"
            assert header_name != name, "a recovered header's name is a corrupted copy, not exact"
            assert _near_name(name, header_name)


#: Banks whose last record must end exactly at ``0x30 + 74 + 0x34``, out of the
#: banks that yield records at all. This is the independent half of D21's
#: evidence: the bank header's declared run is a different field, written by a
#: different part of the mastering, from the record's own pointer block, and
#: the two now agree to the byte on 173 of 186 banks. Before D21 they agreed on
#: 86, and 33 of the rest missed by exactly one 92-byte sample header -- which
#: is what ADR-0021 recorded as a loose fit and is really this bug.
_EMU3_RUN_ENDS = {
    "esi32-gm": (7, 7),
    "protozoa": (15, 15),
    "eiiix-1": (44, 39),
    "eiiix-2": (44, 39),
    "emu-classics": (19, 16),
    "vintage": (13, 13),
    "ditto-drums": (45, 45),
    # Pinned by D24; ``heavy`` moved in D27. ``ditto-drums`` gains its recovered
    # ``PERCUSSION#1``; ``heavy``'s two non-exact banks are the ordinary
    # payload-overshoot D21 already documents, not the recovery. D27 drops
    # ``heavy``'s second ``HvyGtr Maj.Open`` entry to a note (its records are a
    # blank-named duplicate the first entry already yields, ADR-0034), so one
    # fewer bank yields records: 65 -> 64, 63 -> 62. ``elements1mb`` is
    # unchanged at (100, 100) -- both its ``Harpsichord    X`` entries still
    # yield records, now from their own headers.
    "elements1mb": (100, 100),
    "heavy": (64, 62),
}


@pytest.mark.parametrize("label", sorted(_EMU3_RUN_ENDS))
def test_an_emu3_banks_records_fill_the_run_its_header_declares(label: str) -> None:
    """The bank header and the record pointers must agree about where the
    records stop.

    The bank is located from its own first record rather than by scanning the
    disc: the header that owns a record is the one whose declared sample area,
    plus the 74-byte preamble, lands exactly on it. That is self-checking --
    a wrong header disagrees rather than being believed -- and it means this
    test says nothing about how the walk found the bank, only about whether
    the two independent statements of the bank's extent match.
    """
    from samplerdisc.fs.emu3 import (
        BANK_MAGICS,
        OFF_BANK_SAMPLE_BYTES,
        OFF_BANK_SAMPLE_START,
        SAMPLE_AREA_PREAMBLE,
        SAMPLE_HEADER_LEN,
    )

    back = 1 << 20
    size, expected_banks, expected_exact = _EMU3[label][0], *_EMU3_RUN_ENDS[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "emu3"
        banks = exact = 0
        for volume in origin.backend.volumes(image, origin.offset):
            if not volume.files:
                continue
            first = min(f.start_block for f in volume.files) - SAMPLE_HEADER_LEN
            window = image.read(origin.offset + max(first - back, 0), min(first, back))
            base = max(first - back, 0)
            located = None
            for at in range(len(window)):
                if not any(window.startswith(magic, at) for magic in BANK_MAGICS):
                    continue
                head = window[at : at + OFF_BANK_SAMPLE_BYTES + 4]
                if len(head) < OFF_BANK_SAMPLE_BYTES + 4:
                    continue
                area, run = struct.unpack_from("<II", head, OFF_BANK_SAMPLE_START)
                if base + at + area + SAMPLE_AREA_PREAMBLE == first:
                    located = (base + at, area, run)
            if located is None:
                continue  # an E-IV bank, reached through its sample directory
            bank_at, area, run = located
            banks += 1
            last = max(f.start_block + f.size for f in volume.files)
            exact += last - bank_at == area + SAMPLE_AREA_PREAMBLE + run
        assert banks == expected_banks
        assert exact == expected_exact, (
            f"{label}: {exact} of {banks} banks end where their header says"
        )


#: AKAI discs pinned by size, with the volumes, files and *noted* volumes each
#: must yield, and the partitions its table declares against the partitions
#: this image holds. The noted count is pinned as tightly as the file count on
#: purpose: a note is what separates an emptiness the disc accounts for from
#: the ADR-0012 signature, so a note appearing where none was measured is a
#: backend explaining away something nobody looked at, and one disappearing is
#: the invariant above losing its teeth. The eight are the discs of issues #16
#: and #17 together with the four counter-examples -- volumes whose type byte
#: is 0 and whose blocks the allocation map calls free, which carry 63 files
#: between them and must keep every one.
#:
#: The two partition columns are the pin on #22, and they differ on purpose:
#: `Kickin' Lunatic Beats 2 CD1` declares eleven partitions and the image holds
#: eight, three of which no rule may recover -- the image is short of the disc
#: rather than the disc being small (ADR-0023, ADR-0028, issue #17). A present
#: count that climbs to the declared one would mean the walk had started
#: accepting positions with no header at them.
#:
#: Three of the nine are the discs a recovery must **not** touch, and they are
#: pinned here for that and nothing else. `Advanced Media Trax 3` is not short
#: -- nine declared, nine present -- and an earlier signature search cost it 22
#: of its 94 volumes, so it is the falsifying case (ADR-0023). `ProSamples
#: vol.14` and `vol.54` are the second: their missing partitions were never
#: written, `vol.54` declaring nine partitions of a 63 488-block disk on a CD of
#: 30 720 blocks, and `vol.14`'s free space carries 148 byte-identical copies of
#: a partition header that a search must not take (ADR-0028).
#: ``label: (size in bytes, volumes, files, noted, partitions declared, present)``.
_AKAI = {
    "AKAI Advance Orchestra Upgrade 97 Vol.1": (545_720_320, 88, 2669, 4, 9, 9),
    "AMG - Loop Soup AKAI": (542_419_100, 60, 4689, 0, 9, 9),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (378_443_564, 139, 8392, 13, 11, 8),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD2": (371_768_845, 120, 7549, 0, 9, 8),
    "Advanced Media Trax 3 - Modern Composer": (759_441_984, 94, 2938, 0, 9, 9),
    "Best Service ProSamples vol.14 - World Grooves": (553_357_312, 15, 757, 0, 9, 5),
    "Best Service ProSamples vol.54 - Techno 138 BPM": (251_658_240, 32, 1212, 0, 9, 4),
    "OMI Universe Of Sounds Vol.1 (Roland S-770,S-750)": (295_837_696, 69, 1653, 1, 5, 5),
    "Back in Time Records - Big Bang": (269_979_648, 137, 2689, 0, 9, 9),
    "Best Service ProSamples vol.01 - Hip Hop and R&B Drumloops": (314_882_048, 41, 492, 1, 9, 5),
    "Best Service ProSamples vol.19 - Pop Brass": (484_558_848, 12, 533, 0, 9, 5),
    "Best Service ProSamples vol.24 - Breakbeat": (505_772_032, 38, 310, 0, 4, 4),
}

#: What each of those discs held when only the partition at the origin was read
#: (#22). Kept beside the table above rather than deleted: these are the
#: numbers every earlier release reported, and pinning them is what shows the
#: new ones are *additional* partitions rather than the same volumes counted
#: differently. ``label: (volumes, files, noted)`` for partition 1 alone.
_AKAI_FIRST_PARTITION = {
    "AKAI Advance Orchestra Upgrade 97 Vol.1": (18, 464, 4),
    "AMG - Loop Soup AKAI": (7, 490, 0),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (18, 669, 5),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD2": (20, 1346, 0),
    "Advanced Media Trax 3 - Modern Composer": (4, 281, 0),
    "Best Service ProSamples vol.14 - World Grooves": (4, 221, 0),
    "Best Service ProSamples vol.54 - Techno 138 BPM": (10, 198, 0),
    "OMI Universe Of Sounds Vol.1 (Roland S-770,S-750)": (28, 900, 1),
    "Back in Time Records - Big Bang": (8, 380, 0),
    "Best Service ProSamples vol.01 - Hip Hop and R&B Drumloops": (7, 82, 0),
    "Best Service ProSamples vol.19 - Pop Brass": (3, 139, 0),
    "Best Service ProSamples vol.24 - Breakbeat": (15, 113, 0),
}


@pytest.mark.parametrize("label", sorted(_AKAI))
def test_akai_discs_list_their_volumes_and_files(label: str) -> None:
    """Pinned where present, skipped where the shelf is bare -- see _pinned_disc()."""
    from samplerdisc.fs.akai import partition_table, partitions

    size, volumes_expected, files_expected, noted_expected, declared, present = _AKAI[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None, f"{label}: no filesystem found"
        assert origin.backend.name == "akai"
        assert origin.offset == 0
        assert len(partition_table(image, origin.offset)) == declared
        assert len(list(partitions(image, origin.offset))) == present
        volumes = list(origin.backend.volumes(image, origin.offset))
        assert len(volumes) == volumes_expected
        assert sum(len(v.files) for v in volumes) == files_expected
        assert sum(1 for v in volumes if v.note) == noted_expected
        # The same rule as the collection-wide check above, tightened from
        # "the collection has no silent volume" to "this disc has none", which
        # only a disc whose expected shape is known can ask (ADR-0012).
        assert all(v.files or v.note for v in volumes), [v.name for v in volumes if not v.files]
        # Every partition read is one the table declares, and each volume knows
        # which -- a volume with no partition would be one read outside the
        # walk, and its block numbers would be relative to nothing (ADR-0023).
        assert {v.partition for v in volumes} <= set(range(1, declared + 1))
        assert all(v.partition for v in volumes)


#: The eight images short of the disc they were made from, and what searching
#: back for their displaced partition headers recovers (ADR-0028, issue #25).
#:
#: The displacements are the finding and are pinned per partition, in AKAI
#: blocks: they are what says the rip lost whole 32 KB container blocks, and
#: they accumulate down the disc because it lost them in several places. Every
#: one is a multiple of 4 blocks -- 32 768 bytes, one MDX block -- and a
#: displacement that stopped being one would mean the search had begun stepping
#: in something that is not the container's unit.
#:
#: The last columns are for the **displaced partitions alone**, not the whole
#: disc, which is the same reasoning as `_AKAI_FIRST_PARTITION` the other way
#: round: pinned apart, they say what recovery contributed rather than leaving
#: it to be subtracted. `refused` counts payloads that are not the file their
#: entry placed. It was 43 across these partitions when D20 shipped -- a gap
#: inside a displaced partition displacing a file a second time, which the
#: partition-level search could not follow; D38 now recovers those by the file's
#: own name and word count, so `refused` is 0 here and `recovered` carries what
#: it caught (ADR-0027, ADR-0045, issue #35).
#: ``label: (size, declared, present, {index: displacement in blocks}, volumes,
#: files, samples, written, refused, recovered)``. ``recovered`` counts, of the
#: written samples in the displaced partitions, how many had *also* slipped by a
#: gap inside the partition and were read back a whole number of container blocks
#: earlier, confirmed by their own name and word count (issue #35, ADR-0045). It
#: is what once was ``refused`` on the three discs that carried a second gap:
#: `Library.5`, `Global Trance Mission 2` and `Kickin' CD1` recover 23, 5 and 15
#: this way, so their displaced partitions now refuse nothing.
_AKAI_SHORT = {
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (
        378_443_564, 11, 8, {3: 52, 4: 52, 5: 52, 6: 52, 7: 52, 8: 52, 10: 200},
        121, 7723, 7308, 7308, 0, 15,
    ),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD2": (
        371_768_845, 9, 8, {3: 4, 4: 4, 5: 4, 6: 4, 7: 4, 8: 4, 9: 4},
        100, 6203, 5912, 5912, 0, 0,
    ),
    "AKAI.S3000.Sound.Library.5": (
        294_252_089, 9, 6, {5: 12, 7: 32, 8: 32}, 34, 473, 400, 400, 0, 23,
    ),
    "AKAI.S3000.Sound.Library.6": (
        320_291_524, 9, 8, {3: 68, 4: 68, 5: 68, 6: 68, 7: 68, 8: 68, 9: 68},
        84, 1054, 955, 955, 0, 0,
    ),
    "AKAI.S3000.Sound.Library.7": (
        221_665_577, 11, 4, {3: 5508, 4: 2028, 5: 512}, 20, 660, 546, 546, 0, 0,
    ),
    "Back In Time Rrcords - Elektra Vox AKAI": (
        353_568_222, 13, 6, {3: 488, 5: 964, 7: 1844, 9: 2664, 11: 1928},
        33, 661, 463, 463, 0, 0,
    ),
    "AMG - Global Trance Mission 2 AKAI": (
        392_438_329, 9, 7, {6: 8, 7: 8, 9: 32}, 22, 217, 144, 144, 0, 5,
    ),
    "Audio Factory - Classical Wild Takes AKAI": (
        226_074_906, 11, 10, {8: 16, 9: 16, 10: 16, 11: 16}, 18, 189, 80, 80, 0, 0,
    ),
}  # fmt: skip

#: The disc that recovers nothing, and the reason it is here rather than absent
#: from the table above. `Alpha Dance I` is short by one container block, and
#: its one missing partition's header sits four AKAI blocks inside partition 4,
#: which is already being read. Refusing it costs the disc everything a
#: recovery could have given it, and that is the conservative half of ADR-0028
#: shown on the one disc where it is the whole answer.
_AKAI_NOTHING_RECOVERED = ("Best Service - Alpha Dance I AKAI", 193_592_710, 5, 4)


@pytest.mark.parametrize("label", sorted(_AKAI_SHORT))
def test_a_short_akai_image_yields_the_partitions_the_lost_blocks_moved(label: str) -> None:
    """The deliverable, per disc (ADR-0028, issue #25).

    Each of these images decodes cleanly and is missing whole 32 KB blocks of
    the disc it was made from, so every partition after a gap sits that much
    nearer the front than the disk's own table puts it. Searching back from the
    declared position in the container's unit, for a header restating the size
    the table gave *that* partition, and never reaching into a partition already
    read, finds 39 of them across the eight.

    Five things are asserted together and each would fail differently. The
    **displacement per partition** is the finding. The **volume and file counts**
    are the yield. The **written, refused and recovered counts** are what says
    the audio is the disc's own: a displaced partition's directory and its audio
    moved together, and where a gap inside one displaced a file a second time D38
    reads it from its own header -- so `refused` is 0 on all eight and
    `recovered` is the residual D20 could not follow (ADR-0045, #35). And
    **every recovered partition's header block is distinct** from every other
    partition's on the disc, which is what separates a partition from the stale
    copies of a header that sit in these discs' free space -- 148 byte-identical
    ones on `ProSamples vol.14`.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE, partition_table, partitions
    from samplerdisc.sample import NotASample, PayloadMismatch

    (
        size,
        declared,
        present,
        displacements,
        volumes,
        files,
        samples,
        written,
        refused,
        recovered_expected,
    ) = _AKAI_SHORT[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "akai"
        found = list(partitions(image, origin.offset))
        assert len(partition_table(image, origin.offset)) == declared
        assert len(found) == present
        assert {p.index: p.displaced // BLOCK_SIZE for p in found if p.displaced} == displacements
        # Every displacement is a whole number of what the container stores.
        assert all(p.displaced % image.granularity == 0 for p in found)
        # Partition 1 is where the table lives, and it can never move: its
        # declared position is 0, so there is nowhere in front of it to search.
        assert found[0].index == 1 and found[0].displaced == 0

        # No two partitions read may overlap, and none may repeat another's
        # header block -- a stale copy of one would do both.
        heads: dict[bytes, int] = {}
        end = 0
        for part in found:
            assert part.offset >= end, f"{label}: partition {part.index} overlaps the one before"
            end = part.offset + part.blocks * BLOCK_SIZE
            head = image.read(origin.offset + part.offset, BLOCK_SIZE)
            assert head not in heads, (
                f"{label}: partition {part.index} has the same header block as {heads[head]}"
            )
            heads[head] = part.index

        moved = {index for index, _ in displacements.items()}
        seen = kept = mismatched = recovered = 0
        volumes_seen = files_seen = 0
        for volume in origin.backend.volumes(image, origin.offset):
            if volume.partition not in moved:
                continue
            assert volume.displaced == displacements[volume.partition] * BLOCK_SIZE
            volumes_seen += 1
            files_seen += len(volume.files)
            for entry in volume.samples():
                seen += 1
                # A gap inside a displaced partition displaces a file again, on
                # top of the partition's own shift: placement reports where the
                # bytes really are and how far, and the read follows it (#35).
                read_offset, displaced = origin.backend.placement(image, origin.offset, entry)
                payload = image.read(read_offset, entry.size)
                try:
                    origin.backend.parse_sample(entry, payload)
                except PayloadMismatch:
                    mismatched += 1
                except NotASample:
                    pass
                else:
                    kept += 1
                    if displaced:
                        recovered += 1
        assert (volumes_seen, files_seen, seen, kept, mismatched, recovered) == (
            volumes,
            files,
            samples,
            written,
            refused,
            recovered_expected,
        )


def test_a_displaced_partition_that_would_overlap_a_present_one_is_refused() -> None:
    """`Alpha Dance I`: the conservative half of the rule, costing a whole disc.

    Its partition 5 is displaced by four AKAI blocks -- one 32 KB container
    block, the same gap as `Kickin' Lunatic Beats 2 CD2` -- and unlike CD2 there
    is no later partition clear of the clash to recover. The header is really
    there and really is partition 5's; reading it would mean two partitions over
    the same bytes, so it stays unread and the disc gains nothing (ADR-0028).
    """
    from samplerdisc.fs.akai import BLOCK_SIZE, displaced_header, partition_header, partitions

    label, size, declared, present = _AKAI_NOTHING_RECOVERED
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "akai"
        found = list(partitions(image, origin.offset))
        assert len(found) == present
        assert not any(p.displaced for p in found)

        last = found[-1]
        assert last.index == declared - 1
        at = last.offset + last.blocks * BLOCK_SIZE
        blocks = partition_header(image, origin.offset + at - 4 * BLOCK_SIZE)
        # The header is there, four blocks inside the partition already read ...
        assert blocks is not None
        # ... and the search stops at that partition's end, so it is never seen.
        assert displaced_header(image, origin.offset, at, blocks, at) is None


@pytest.mark.parametrize("label", sorted(_AKAI_FIRST_PARTITION))
def test_akai_partition_one_holds_exactly_what_it_did_before(label: str) -> None:
    """#22 adds partitions; it must not move a single volume of the first one.

    The whole risk in threading a per-partition origin through the walk is
    getting the arithmetic subtly wrong, and the symptom would not be an error
    -- it would be volumes and files that still list, from the wrong place.
    Partition 1's numbers are the control, because they were measured before
    any of this and nothing about it should touch them.
    """
    volumes_expected, files_expected, noted_expected = _AKAI_FIRST_PARTITION[label]
    with open_image(_pinned_disc(label, _AKAI[label][0])) as image:
        origin = find_origin(image)
        assert origin is not None
        first = [v for v in origin.backend.volumes(image, origin.offset) if v.partition == 1]
        assert len(first) == volumes_expected
        assert sum(len(v.files) for v in first) == files_expected
        assert sum(1 for v in first if v.note) == noted_expected
        # Partition 1 begins at the origin, so its blocks need no adjustment.
        assert {v.origin for v in first} == {0}


def test_loop_soup_reads_all_nine_partitions_and_the_payloads_agree() -> None:
    """The disc issue #22 was written against, end to end.

    `Loop Soup` declares nine partitions and the image holds all nine; six
    carry volumes and the names run on across them -- partition 1 ends at
    `SOUP 115-117` and partition 2 opens at `SOUP 120`, which is what says
    this is the disc's own content and not a coincidence of structure.

    Then the strong half: every sample past the first partition is read back
    and its **payload header** must carry the name its directory entry gives
    it. Two structures written independently, one 8 KB-aligned block apart --
    if the per-partition origin were wrong by so much as a block, the names
    would disagree wholesale rather than the read failing. All 3 200 agree.
    """
    from samplerdisc.fs.akai import decode_name, partitions

    with open_image(
        _pinned_disc("AMG - Loop Soup AKAI", _AKAI["AMG - Loop Soup AKAI"][0])
    ) as image:
        origin = find_origin(image)
        assert origin is not None
        assert len(list(partitions(image, origin.offset))) == 9
        volumes = list(origin.backend.volumes(image, origin.offset))
        opening = {}
        for volume in volumes:
            opening.setdefault(volume.partition, volume.name)
        assert opening[1] == "SOUP 101-103"
        assert opening[2] == "SOUP 120"

        checked = 0
        for volume in volumes:
            if volume.partition == 1:
                continue
            for entry in volume.files:
                if entry.kind != "sample":
                    continue
                payload = origin.backend.read_file(image, origin.offset, entry)
                assert len(payload) == entry.size, f"{volume.name}/{entry.name}: short read"
                assert decode_name(payload[3:15]) == entry.name, (
                    f"partition {volume.partition} {volume.name}/{entry.name}: payload header "
                    f"says {decode_name(payload[3:15])!r}"
                )
                checked += 1
        assert checked == 3200


def test_akai_unused_slots_are_explained_by_the_allocation_map() -> None:
    """The six volumes of issue #16 and the four of #17, and what tells them apart.

    All ten look identical from the volume entry alone: a name, a start block
    inside the image, and nothing at that block a file walk will take. What
    separates them is the partition's own allocation map, and each of the three
    answers below is a different fact about the disc rather than a different
    guess about it (ADR-0022).

    `Advance Orchestra` and the OMI disc keep a start block left over from
    formatting that now points into a file's extent -- the map says those
    blocks hold file data, so no directory was ever there. `Kickin' Lunatic
    Beats 2 CD1` is the other way round: the map says all four blocks *are*
    volume directories, and the image has none at them, because the image is
    short of the disc by four 32 KB blocks. Its `VOLUME 018` is a third case
    again, and the map declines to choose between them.
    """
    expect = {
        "AKAI Advance Orchestra Upgrade 97 Vol.1": {
            "VOLUME 015": "file data",
            "VOLUME 016": "file data",
            "VOLUME 017": "file data",
            "VOLUME 018": "file data",
        },
        "OMI Universe Of Sounds Vol.1 (Roland S-770,S-750)": {"VOLUME 028": "file data"},
        "AMG - Kickin' Lunatic Beats 2 AKAI CD1": {
            "14-TRK06 MF1": "a volume directory",
            "15-TRK06 MF2": "a volume directory",
            "16-TRACK 07": "a volume directory",
            "17-TRK07 MF": "a volume directory",
            "VOLUME 018": "is free",
        },
    }
    for label, wanted in expect.items():
        with open_image(_pinned_disc(label, _AKAI[label][0])) as image:
            origin = find_origin(image)
            assert origin is not None
            # Partition 1: these ten volumes were measured there, and a name is
            # not unique across a disc's partitions (ADR-0023).
            volumes = {
                v.name: v for v in origin.backend.volumes(image, origin.offset) if v.partition == 1
            }
            for name, fragment in wanted.items():
                volume = volumes[name]
                assert not volume.files, f"{label}: {name} unexpectedly lists files"
                assert fragment in volume.note, f"{label}: {name}: {volume.note!r}"


def test_akai_keeps_the_files_of_a_volume_the_allocation_map_calls_free() -> None:
    """A free block under a volume that *does* list files is not grounds to drop it.

    Four volumes across three discs have a type byte of 0 and sit on blocks the
    allocation map marks free, and every one holds a real directory: these are
    volumes that were deleted, on read-only media that never reused the blocks.
    They carry 63 files between them, so the one-line fix of rejecting type 0 --
    or of trusting the map as an allocation flag rather than reading it as an
    explanation -- costs real audio. This is the test that says so.
    """
    expect = {
        "Back in Time Records - Big Bang": ("VOLUME 008", 14),
        "Best Service ProSamples vol.01 - Hip Hop and R&B Drumloops": ("VOLUME 007", 10),
        "Best Service ProSamples vol.19 - Pop Brass": ("VOLUME 003", 37),
        "Best Service ProSamples vol.24 - Breakbeat": ("VOLUME 015", 2),
    }
    from samplerdisc.fs.akai import FAT_FREE, allocation_map

    total = 0
    for label, (name, count) in expect.items():
        with open_image(_pinned_disc(label, _AKAI[label][0])) as image:
            origin = find_origin(image)
            assert origin is not None
            allocation = allocation_map(image, origin.offset)
            volume = {
                v.name: v for v in origin.backend.volumes(image, origin.offset) if v.partition == 1
            }[name]
            assert allocation[volume.start_block] == FAT_FREE, label
            assert len(volume.files) == count, label
            assert not volume.note
            total += len(volume.files)
    assert total == 63


#: AKAI discs pinned by what their **payloads** say, as opposed to what their
#: directories say above. ``label: (size, samples, s3000 headers, mismatches,
#: damaged, recovered)``, where mismatches, damaged and recovered account for
#: every sample not written at its declared position: a *mismatch* is a payload
#: that is not the file its entry placed and could not be found elsewhere, a
#: *damaged* one is that file with a field unusable -- four corrupt rate bytes
#: across the collection, and nothing else -- and a *recovered* one is a sample
#: displaced by a gap inside its partition, read back from its own header a whole
#: number of container blocks earlier (ADR-0027, ADR-0045, issue #35).
#:
#: The eight are chosen to cover every case the collection offers. Four whole
#: S3000 discs, because the 192-byte header was read as 150 on every sample of
#: them and a regression would be silent -- the WAVs would still open. Three
#: discs that carried mismatches before D38, one of which (`Alpha Dance II`)
#: declares six partitions and holds all six, so its 21 displaced samples are
#: damage the partition table cannot see -- all 21 now recovered. `Loop Soup`
#: keeps its one true mismatch, a record whose start block lands mid-sample with
#: no header to find. And `Advance Orchestra`, 2 236 samples with nothing wrong
#: anywhere: the control that says these numbers measure the discs, not the
#: checks.
_AKAI_PAYLOAD = {
    "AKAI.S3000.Sound.Library.1": (264_088_447, 4455, 4454, 0, 1, 3),
    "AKAI.S3000.Sound.Library.2": (298_155_354, 3086, 3083, 0, 3, 0),
    "East Connexion Piano": (277_092_352, 730, 730, 0, 0, 0),
    "AMG - Now CD-Rom for (AKAI)": (521_322_496, 1193, 1193, 0, 0, 0),
    "Best Service - Alpha Dance II AKAI": (309_865_547, 1740, 0, 0, 0, 21),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (378_443_564, 7932, 0, 0, 0, 24),
    "AMG - Loop Soup AKAI": (542_419_100, 3434, 0, 1, 0, 0),
    "AKAI Advance Orchestra Upgrade 97 Vol.1": (545_720_320, 2236, 0, 0, 0, 0),
}


@pytest.mark.parametrize("label", sorted(_AKAI_PAYLOAD))
def test_akai_payloads_are_the_files_their_directory_entries_placed(label: str) -> None:
    """Every payload accepted must be the file its entry named, at the right length.

    Two findings pinned together, because ruling out the false positive for one
    is what found the other (ADR-0027).

    **The header length.** S3000-family samples put 192 bytes in front of the
    audio and S1000 ones 150, and the directory's type byte says which in its
    high bit. Reading a 192 at 150 does not fail -- it writes a WAV that opens,
    holding 42 bytes of header as PCM at the front, 21 frames short at the end,
    with every loop point 21 frames out. That was happening to **13 451 of the
    56 490** AKAI samples read before D20, on nine discs, and four of them are
    pinned here whole.

    **The identity.** A payload that is not the file its entry placed is refused
    -- unless the reason is a run of blocks lost inside its partition, in which
    case D38 finds the real bytes a whole number of container blocks earlier by
    the entry's own name and word count and reads them there (ADR-0045). So a
    displaced sample now counts as `recovered`, not `mismatched`: `Alpha Dance
    II`'s 21, `Kickin' CD1`'s 24 and `Library.1`'s 3 all move columns. What stays
    a mismatch is a payload with no such header to find -- `Loop Soup`'s one
    mid-sample record. Each of mismatch, damaged and recovered is pinned as
    tightly as the sample count for ADR-0012's reason: a refusal appearing where
    none was measured is a check condemning real audio, one disappearing is a
    check that stopped looking, and a recovery appearing where none was is the
    search reaching a file it should not.
    """
    from samplerdisc.sample import NotASample, PayloadMismatch
    from samplerdisc.sample.akai import HEADER_LEN_S1000, HEADER_LEN_S3000

    size, samples, s3000_expected, mismatch_expected, damaged_expected, recovered_expected = (
        _AKAI_PAYLOAD[label]
    )
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "akai"
        seen = s3000 = mismatched = damaged = recovered = 0
        for volume in origin.backend.volumes(image, origin.offset):
            for entry in volume.samples():
                seen += 1
                # placement relocates a sample the rip displaced inside its
                # partition to where its own header sits; read_file follows it,
                # so the identity below is checked at the recovered offset and a
                # recovered sample is no longer a mismatch (ADR-0045, #35).
                read_offset, displaced = origin.backend.placement(image, origin.offset, entry)
                payload = image.read(read_offset, entry.size)
                try:
                    sample = origin.backend.parse_sample(entry, payload)
                except PayloadMismatch:
                    mismatched += 1
                    continue
                except NotASample:
                    damaged += 1
                    continue
                if displaced:
                    recovered += 1
                assert sample.header_len in (HEADER_LEN_S1000, HEADER_LEN_S3000)
                if sample.header_len == HEADER_LEN_S3000:
                    s3000 += 1
                # The generation bit chose the length; the payload's own word
                # count against the directory's declared size is what confirms
                # it, and the two are written by different structures. Across
                # the collection this holds for 72 190 of 72 190 accepted
                # payloads -- which is what makes the rule a finding rather
                # than a reading that happens to fit (ADR-0020, ADR-0027).
                (words,) = struct.unpack_from("<I", payload, 26)
                assert entry.size == words * 2 + sample.header_len, (
                    f"{volume.name}/{entry.name}: size {entry.size}, "
                    f"{words} words, header {sample.header_len}"
                )
                # And the audio is the disc's own bytes from that offset, not
                # merely the right number of them. A count cannot see a 42-byte
                # slip; this is the check that would have caught it.
                assert sample.pcm == payload[sample.header_len : sample.header_len + words * 2]
        assert (seen, s3000, mismatched, damaged, recovered) == (
            samples,
            s3000_expected,
            mismatch_expected,
            damaged_expected,
            recovered_expected,
        )


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_an_akai_payload_is_never_written_under_another_files_name(path: Path) -> None:
    """The general statement, over whatever AKAI discs a contributor has.

    The tables above are this collection's; this is the invariant, and it is
    the one issue #23 asked for: **no AKAI sample is written whose payload
    header names a different file**. It stopped holding trivially with D38: 102
    samples that were refused are now written, each read from a position the
    recovery *chose*, and this is what says the recovery chose right -- the
    header it landed on carries the entry's own name. If the search ever reads a
    header at an offset where a different file's name happens to land, or a
    future change relaxes the name test, this fails on any shelf rather than on
    ours (ADR-0045).
    """
    from samplerdisc.fs.akai import NAME_LEN, decode_name
    from samplerdisc.sample import NotASample
    from samplerdisc.sample.akai import OFF_NAME

    with open_image(path) as image:
        origin = find_origin(image)
        if origin is None or origin.backend.name != "akai":
            return
        wrong = []
        for volume in origin.backend.volumes(image, origin.offset):
            for entry in volume.samples():
                payload = origin.backend.read_file(image, origin.offset, entry)
                try:
                    sample = origin.backend.parse_sample(entry, payload)
                except NotASample:
                    continue
                header_name = decode_name(payload[OFF_NAME : OFF_NAME + NAME_LEN])
                if header_name != entry.name or sample.name != entry.name:
                    wrong.append(
                        f"partition {volume.partition} {volume.name}/{entry.name}: "
                        f"payload header says {header_name!r}"
                    )
        assert not wrong, (
            f"{path.name}: {len(wrong)} samples written under a name their payload "
            f"header does not carry, first: {wrong[:3]}"
        )


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_an_akai_file_chain_is_as_long_as_its_declared_size(path: Path) -> None:
    """The allocation map has to agree with the directory about every file.

    This is what makes the map evidence rather than a hopeful reading of the
    bytes that follow the volume directory: walk each file's chain of blocks
    and it must be exactly as long as the size the directory declares, which
    the map and the directory state independently of one another. Across the
    44 AKAI discs measured it holds for **14 607 of 14 607** files, exactly,
    with no disc disagreeing anywhere.

    Volumes the map calls free are excluded, and that exclusion is a finding
    rather than a fudge: those five are deleted volumes, so their blocks were
    returned to the free list and their chains genuinely no longer describe
    the audio still sitting in them. Their 63 files are the reason the
    exclusion has to be by what the map says and not by a tolerance -- on
    `ProSamples vol.19` they are 37 of 139 files, so any rate loose enough to
    pass there would be loose enough to hide a real fault on a larger disc.

    **Per partition**, each against its own map, since #22: a block number
    counts from the partition it is in, so checking every file against the
    first partition's map would compare the wrong two things and pass or fail
    for the wrong reason. Extended to all 276 partitions the agreement is 68
    267 of 68 284 files, and every one of the 17 exceptions is a `MULTI FILE`
    -- kind ``multi``, all on `AKAI.S3000.Sound.Library.1` -- whose chain runs
    exactly one block past what its size needs. They are named here rather
    than tolerated, so a second kind of disagreement fails.
    """
    from samplerdisc.fs.akai import (
        BLOCK_SIZE,
        FAT_FREE,
        FAT_VOLUME_DIR,
        allocation_map,
        partitions,
    )

    with open_image(path) as image:
        origin = find_origin(image)
        if origin is None or origin.backend.name != "akai":
            return
        maps = {
            part.offset: allocation_map(image, origin.offset + part.offset)
            for part in partitions(image, origin.offset)
        }
        assert maps.get(0), f"{path.name}: no allocation map"
        disagreed = []
        for volume in origin.backend.volumes(image, origin.offset):
            allocation = maps.get(volume.origin, [])
            if not allocation:
                continue
            if volume.start_block < len(allocation) and allocation[volume.start_block] == FAT_FREE:
                continue
            for entry in volume.files:
                want = -(-entry.size // BLOCK_SIZE)
                block, length, seen = entry.start_block, 0, set()
                while 0 <= block < len(allocation) and block not in seen and length <= want:
                    seen.add(block)
                    length += 1
                    if allocation[block] >= FAT_VOLUME_DIR:
                        break
                    block = allocation[block]
                if length == want:
                    continue
                if entry.kind == "multi" and length == want + 1:
                    # The one exception, and it is the same on all 17: a multi
                    # is allocated a block more than its size needs.
                    continue
                disagreed.append(
                    f"partition {volume.partition} {volume.name}/{entry.name} "
                    f"({entry.kind}): {length} blocks, wanted {want}"
                )
        assert not disagreed, (
            f"{path.name}: {len(disagreed)} files whose chain is not as long as the "
            f"size their directory declares, first: {disagreed[:3]}"
        )


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


#: SampleCell HFS discs, pinned by size, with the file count their catalog
#: declares (D32, ADR-0039). Verified against ``machfs``, an independent HFS
#: reader, in ``test_hfs_forks_match_an_independent_reader`` below.
_HFS = {
    "sonic-images-v1": (295_833_600, "Sonic Images V1", 926),
    "sonic-images-v2": (295_731_200, "Sonic Images V2", 404),
}


@pytest.mark.parametrize("label", sorted(_HFS))
def test_hfs_discs_resolve_and_list_their_catalog(label: str) -> None:
    """A SampleCell disc reads as one HFS volume with its declared file count.

    The count is the whole catalog -- AIFF samples, SampleCell instrument
    documents, and the handful of Finder/system files -- because that is what
    ``list`` walks. No volume may come back empty without a note (ADR-0012).
    """
    size, name, files = _HFS[label]
    path = _pinned_disc(label, size)
    with open_image(path) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "hfs"
        volumes = list(origin.backend.volumes(image, origin.offset))
    assert len(volumes) == 1
    assert volumes[0].name == name
    assert len(volumes[0].files) == files
    assert volumes[0].files or volumes[0].note


@pytest.mark.parametrize("label", sorted(_HFS))
def test_hfs_forks_match_an_independent_reader(label: str) -> None:
    """Every fork we read is byte-identical to what ``machfs`` reads.

    ``machfs`` is a pure-Python HFS implementation with no shared lineage with
    this backend, so agreement on all ~900 forks is real cross-checking of the
    B-tree walk, the extent resolution and the fork sizes -- the EBL/KRZ oracle
    pattern, for a filesystem the host's own ``hdiutil`` no longer mounts
    (modern macOS dropped legacy HFS). Both forks are checked: the data fork
    (the audio, and the AIFF path) and the resource fork (the SDII parameters,
    D33/ADR-0040). Skips where ``machfs`` is not installed.
    """
    machfs = pytest.importorskip("machfs")
    from samplerdisc.fs.hfs import APPLE_BLOCK, HfsBackend

    size, _, _ = _HFS[label]
    path = _pinned_disc(label, size)
    with open_image(path) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "hfs"
        ours = {
            entry.name: (
                origin.backend.read_file(image, origin.offset, entry),
                origin.backend.read_resource_fork(image, origin.offset, entry),
            )
            for volume in origin.backend.volumes(image, origin.offset)
            for entry in volume.files
        }
        part_start = next(HfsBackend()._hfs_partitions(image, 0))
    with path.open("rb") as handle:
        handle.seek(part_start * APPLE_BLOCK)
        volume_bytes = handle.read()

    reference = machfs.Volume()
    reference.read(volume_bytes)
    checked = 0
    rsrc_checked = 0

    def visit(folder, prefix: str) -> None:
        nonlocal checked, rsrc_checked
        for name, obj in folder.items():
            full = f"{prefix}{name}"
            if isinstance(obj, machfs.Folder):
                visit(obj, full + "/")
            elif full in ours:  # machfs lists zero-length forks we skip; ignore those
                data_fork, rsrc_fork = ours[full]
                assert data_fork == obj.data, f"data fork mismatch on {full}"
                assert rsrc_fork == obj.rsrc, f"resource fork mismatch on {full}"
                checked += 1
                if obj.rsrc:
                    rsrc_checked += 1

    visit(reference, "")
    assert checked > 100, f"machfs matched only {checked} forks; expected the whole library"
    # sonic-images-v2 carries the 24 Sd2f resource forks; v1 carries none, so
    # this only asserts the resource-fork walk ran where there was one to read.
    if label == "sonic-images-v2":
        assert rsrc_checked >= 24, f"expected the SDII resource forks; matched {rsrc_checked}"


def test_hfs_sd2_files_decode_and_match_the_disc() -> None:
    """The Sd2f files on ``sonic-images-v2`` decode, verified against the disc.

    The audio is the data fork, which ``machfs`` returns byte-for-byte, so our
    little-endian PCM swapped back to big-endian must equal it exactly -- the
    "payload is the disc's own bytes" oracle AKAI uses, needing no Mac fork
    magic. The rate/width/channels come from the resource fork's ``STR ``
    resources; on this disc all 24 are uniformly 16-bit, 44 100 Hz, stereo
    (D33/ADR-0040). ``sonic-images-v1`` carries none.
    """
    machfs = pytest.importorskip("machfs")
    from samplerdisc.fs.hfs import APPLE_BLOCK, HfsBackend
    from samplerdisc.sample import sd2
    from samplerdisc.sample.aiff import _swap

    v2_size = _HFS["sonic-images-v2"][0]
    path = _pinned_disc("sonic-images-v2", v2_size)
    with open_image(path) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "hfs"
        sd2_entries = [
            entry
            for volume in origin.backend.volumes(image, origin.offset)
            for entry in volume.files
            if entry.kind == "sd2"
        ]
        assert len(sd2_entries) == 24
        decoded = 0
        for entry in sd2_entries:
            data_fork = origin.backend.read_file(image, origin.offset, entry)
            rsrc_fork = origin.backend.read_resource_fork(image, origin.offset, entry)
            sample = sd2.parse(data_fork, rsrc_fork, fallback_name=entry.name)
            assert (sample.width, sample.rate, sample.channels) == (2, 44100, 2)
            assert sample.frames > 0
            # The audio is a verbatim byte-swap of the data fork machfs returns.
            assert _swap(sample.pcm, sample.width) == data_fork[: len(sample.pcm)]
            decoded += 1
        assert decoded == 24
        part_start = next(HfsBackend()._hfs_partitions(image, 0))

    with path.open("rb") as handle:
        handle.seek(part_start * APPLE_BLOCK)
        reference = machfs.Volume()
        reference.read(handle.read())

    def count_sd2(folder) -> int:
        total = 0
        for obj in folder.values():
            if isinstance(obj, machfs.Folder):
                total += count_sd2(obj)
            elif getattr(obj, "type", b"") == b"Sd2f":
                total += 1
        return total

    assert count_sd2(reference) == 24


def test_hfs_v1_has_no_sd2_files() -> None:
    """``sonic-images-v1`` carries no Sd2f, so nothing new is claimed there."""
    v1_size = _HFS["sonic-images-v1"][0]
    path = _pinned_disc("sonic-images-v1", v1_size)
    with open_image(path) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "hfs"
        sd2_entries = [
            entry
            for volume in origin.backend.volumes(image, origin.offset)
            for entry in volume.files
            if entry.kind == "sd2"
        ]
    assert sd2_entries == []
