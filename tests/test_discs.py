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
import os
import struct
from array import array
from functools import lru_cache
from pathlib import Path

import pytest

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc.container.base import SECTOR_SIZE
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.container.mdsmdf import find_mdf
from samplerdisc.fs.probe import find_origin
from samplerdisc.sample import aiff
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
        *(size for size, _, _, _, _, _ in _EMU3.values()),
        *(size for size, _, _, _, _, _ in _AKAI.values()),
        *(size for size, _, _, _, _ in _AKAI_PAYLOAD.values()),
        *(size for size, *_ in _AKAI_SHORT.values()),
        _AKAI_NOTHING_RECOVERED[1],
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
#: decode silently failing on a disc nobody looked at. `esi32-gm` yields the
#: fewest by far -- 107 of 2 265 -- because that disc declares a loop end past
#: the audio it carries on almost every record, and those are refused rather
#: than clamped (ADR-0025).
#:
#: The stereo counts are D18's pin and they are **not** the count of records
#: satisfying ``start_R == start_L + P/2``, which is 2 721. It is that set
#: minus the 65 whose own ``end_L`` contradicts the split -- 19 on `protozoa`,
#: 40 on `eiiix-1`, 6 on `eiiix-2` -- which measure as unrelated audio and are
#: written mono. The two numbers differing on exactly three discs is what the
#: gate's third condition is for, so a change that loses it fails here rather
#: than shipping `protozoa`'s trombones with another bank's record in the
#: right channel (ADR-0026).
_EMU3 = {
    "esi32-gm": (93_077_504, 10, 2265, 107, 28, "b7964228d84cfc50"),
    "protozoa": (131_690_496, 16, 5852, 1689, 8, "ac4b74a601955ca1"),
    "eiiix-1": (304_128_000, 46, 1189, 1157, 601, "c26ee8fb959b3f91"),
    "eiiix-2": (304_435_200, 46, 1333, 1260, 592, "2d5d002be060cc52"),
    "eiv-analogia": (293_912_576, 12, 449, 449, 279, "5d8faa38572914cb"),
    "eiv-studio": (399_077_376, 230, 2822, 2551, 320, "8802808655deea30"),
    "eiv-vitous": (532_443_136, 44, 828, 826, 828, "66c179be5b78cbd2"),
}


@pytest.mark.parametrize("label", sorted(_EMU3))
def test_emu3_discs_list_their_banks_and_samples(label: str) -> None:
    """Pinned where present, skipped where the shelf is bare -- see _pinned_disc()."""
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
        assert len(volumes["Orbit Presets  X"].files) == 535
        assert len(volumes["Orbit Presets 4k"].files) == 535
        assert len(volumes["Phatt Presets  X"].files) == 470
        assert len(volumes["Phatt Presets 4K"].files) == 239
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
#: The last five columns are for the **displaced partitions alone**, not the
#: whole disc, which is the same reasoning as `_AKAI_FIRST_PARTITION` the other
#: way round: pinned apart, they say what recovery contributed rather than
#: leaving it to be subtracted. `refused` counts payloads that are not the file
#: their entry placed, and it is pinned as tightly as the rest -- 43 of the
#: 15 808 recovered samples, 99.7 % passing, is what says these partitions are
#: the disc's own and not something header-shaped (ADR-0027).
#: ``label: (size, declared, present, {index: displacement in blocks}, volumes,
#: files, samples, written, refused)``.
_AKAI_SHORT = {
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (
        378_443_564, 11, 8, {3: 52, 4: 52, 5: 52, 6: 52, 7: 52, 8: 52, 10: 200},
        121, 7723, 7308, 7293, 15,
    ),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD2": (
        371_768_845, 9, 8, {3: 4, 4: 4, 5: 4, 6: 4, 7: 4, 8: 4, 9: 4},
        100, 6203, 5912, 5912, 0,
    ),
    "AKAI.S3000.Sound.Library.5": (
        294_252_089, 9, 6, {5: 12, 7: 32, 8: 32}, 34, 473, 400, 377, 23,
    ),
    "AKAI.S3000.Sound.Library.6": (
        320_291_524, 9, 8, {3: 68, 4: 68, 5: 68, 6: 68, 7: 68, 8: 68, 9: 68},
        84, 1054, 955, 955, 0,
    ),
    "AKAI.S3000.Sound.Library.7": (
        221_665_577, 11, 4, {3: 5508, 4: 2028, 5: 512}, 20, 660, 546, 546, 0,
    ),
    "Back In Time Rrcords - Elektra Vox AKAI": (
        353_568_222, 13, 6, {3: 488, 5: 964, 7: 1844, 9: 2664, 11: 1928},
        33, 661, 463, 463, 0,
    ),
    "AMG - Global Trance Mission 2 AKAI": (
        392_438_329, 9, 7, {6: 8, 7: 8, 9: 32}, 22, 217, 144, 139, 5,
    ),
    "Audio Factory - Classical Wild Takes AKAI": (
        226_074_906, 11, 10, {8: 16, 9: 16, 10: 16, 11: 16}, 18, 189, 80, 80, 0,
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

    Four things are asserted together and each would fail differently. The
    **displacement per partition** is the finding. The **volume and file counts**
    are the yield. The **written and refused counts** are what says the audio is
    the disc's own: a displaced partition's directory and its audio moved
    together, so the payload check that condemns a misplaced file passes on
    99.7 % of what this recovers. And **every recovered partition's header block
    is distinct** from every other partition's on the disc, which is what
    separates a partition from the stale copies of a header that sit in these
    discs' free space -- 148 byte-identical ones on `ProSamples vol.14`.
    """
    from samplerdisc.fs.akai import BLOCK_SIZE, partition_table, partitions
    from samplerdisc.sample import NotASample, PayloadMismatch

    size, declared, present, displacements, volumes, files, samples, written, refused = _AKAI_SHORT[
        label
    ]
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
        seen = kept = mismatched = 0
        volumes_seen = files_seen = 0
        for volume in origin.backend.volumes(image, origin.offset):
            if volume.partition not in moved:
                continue
            assert volume.displaced == displacements[volume.partition] * BLOCK_SIZE
            volumes_seen += 1
            files_seen += len(volume.files)
            for entry in volume.samples():
                seen += 1
                payload = origin.backend.read_file(image, origin.offset, entry)
                try:
                    origin.backend.parse_sample(entry, payload)
                except PayloadMismatch:
                    mismatched += 1
                except NotASample:
                    pass
                else:
                    kept += 1
        assert (volumes_seen, files_seen, seen, kept, mismatched) == (
            volumes,
            files,
            samples,
            written,
            refused,
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
#: damaged)``, where the last two account for every sample not written:
#: a *mismatch* is a payload that is not the file its entry placed, and
#: *damaged* is one that is that file with a field unusable -- four corrupt
#: rate bytes across the collection, and nothing else (ADR-0027).
#:
#: The eight are chosen to cover every case the collection offers. Four whole
#: S3000 discs, because the 192-byte header was read as 150 on every sample of
#: them and a regression would be silent -- the WAVs would still open. Three
#: discs carrying mismatches, one of which (`Alpha Dance II`) declares six
#: partitions and holds all six, so its 21 refusals are damage the partition
#: table cannot see. And `Advance Orchestra`, which is 2 236 samples with
#: nothing wrong anywhere: the control that says these numbers measure the
#: discs and not the checks.
_AKAI_PAYLOAD = {
    "AKAI.S3000.Sound.Library.1": (264_088_447, 4455, 4451, 3, 1),
    "AKAI.S3000.Sound.Library.2": (298_155_354, 3086, 3083, 0, 3),
    "East Connexion Piano": (277_092_352, 730, 730, 0, 0),
    "AMG - Now CD-Rom for (AKAI)": (521_322_496, 1193, 1193, 0, 0),
    "Best Service - Alpha Dance II AKAI": (309_865_547, 1740, 0, 21, 0),
    "AMG - Kickin' Lunatic Beats 2 AKAI CD1": (378_443_564, 7932, 0, 24, 0),
    "AMG - Loop Soup AKAI": (542_419_100, 3434, 0, 1, 0),
    "AKAI Advance Orchestra Upgrade 97 Vol.1": (545_720_320, 2236, 0, 0, 0),
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

    **The identity.** 65 payloads across the 44 discs are not the file their
    entry placed or are that file with a field unusable, and all 65 were
    already being refused -- as "does not begin with an AKAI sample header",
    which is true of a payload that is mid-audio and of one that is a perfectly
    good sample under the wrong name alike. The mismatch count is pinned as
    tightly as the sample count for ADR-0012's reason: a refusal appearing
    where none was measured is a check that has started condemning real audio,
    and one disappearing is a check that has stopped looking.
    """
    from samplerdisc.sample import NotASample, PayloadMismatch
    from samplerdisc.sample.akai import HEADER_LEN_S1000, HEADER_LEN_S3000

    size, samples, s3000_expected, mismatch_expected, damaged_expected = _AKAI_PAYLOAD[label]
    with open_image(_pinned_disc(label, size)) as image:
        origin = find_origin(image)
        assert origin is not None and origin.backend.name == "akai"
        seen = s3000 = mismatched = damaged = 0
        for volume in origin.backend.volumes(image, origin.offset):
            for entry in volume.samples():
                seen += 1
                payload = origin.backend.read_file(image, origin.offset, entry)
                try:
                    sample = origin.backend.parse_sample(entry, payload)
                except PayloadMismatch:
                    mismatched += 1
                    continue
                except NotASample:
                    damaged += 1
                    continue
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
        assert (seen, s3000, mismatched, damaged) == (
            samples,
            s3000_expected,
            mismatch_expected,
            damaged_expected,
        )


@pytest.mark.parametrize("path", _discs(), ids=_ids(_discs()))
def test_an_akai_payload_is_never_written_under_another_files_name(path: Path) -> None:
    """The general statement, over whatever AKAI discs a contributor has.

    The tables above are this collection's; this is the invariant, and it is
    the one issue #23 asked for: **no AKAI sample is written whose payload
    header names a different file**. It holds trivially now, since such a
    payload is refused -- which is the point. If a future change relaxes the
    name test, or reads the header at an offset where another file's name
    happens to land, this fails on any shelf rather than on ours.
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
