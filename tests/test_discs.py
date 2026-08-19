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
from pathlib import Path

import pytest

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc.container.detect import open_image
from samplerdisc.fs.probe import find_origin

IMAGE_SUFFIXES = (".iso", ".img", ".mdx", ".nrg", ".bin", ".cdr", ".tao")

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
    root = _collection()
    if root is None:
        return []
    return sorted(p for p in root.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


pytestmark = pytest.mark.skipif(
    _collection() is None,
    reason="set SAMPLERDISC_TEST_DISCS to a directory of disc images",
)


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


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
        files = sum(len(volume.files) for volume in origin.backend.volumes(image, origin.offset))
        assert files > 0, (
            f"{path.name}: {origin.backend.name} claimed offset {origin.offset} "
            f"but every volume came back empty"
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
