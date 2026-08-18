"""The container contract: a disc image seen as flat cooked sectors.

Nothing in this package knows what a sampler is. See ADR-0003.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

#: Cooked CD sector size. Everything above ``container/`` reads in these units.
SECTOR_SIZE = 2048


class SectorImage(ABC):
    """Read-only view of a disc image as a flat stream of 2048-byte sectors.

    ``origin`` is where the *track* starts, in cooked-stream bytes. It is not
    necessarily where a filesystem starts -- a Nero image puts 150 sectors of
    zeroed pregap in front of one. Resolving that is the origin probe's job,
    not the container's. See ADR-0005.
    """

    kind: str = "unknown"

    @property
    @abstractmethod
    def size(self) -> int:
        """Length of the cooked stream, in bytes."""

    @abstractmethod
    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` cooked bytes from ``offset``.

        Reads past the end return what is available rather than raising: these
        rips frequently have tail damage, and a short read is recoverable where
        a traceback is not.
        """

    @property
    def sectors(self) -> int:
        return self.size // SECTOR_SIZE

    @property
    def origin(self) -> int:
        """Cooked-stream offset at which the data track begins."""
        return 0

    def close(self) -> None:  # noqa: B027 - optional hook; only file-backed containers hold a handle
        """Release any held resources. Subclasses that own a file override this."""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} kind={self.kind} size={self.size} sectors={self.sectors}>"


class _FileBacked(SectorImage):
    """Shared plumbing for containers that read from a byte range of a file."""

    def __init__(self, path: str | os.PathLike[str], start: int = 0, end: int | None = None):
        self._path = os.fspath(path)
        # The image owns this handle for its lifetime; released in close().
        self._fh = open(self._path, "rb")  # noqa: SIM115
        file_size = os.path.getsize(self._path)
        self._start = start
        self._end = file_size if end is None else min(end, file_size)
        if self._end < self._start:
            raise ValueError(
                f"{self._path}: track ends ({self._end}) before it starts ({self._start})"
            )

    @property
    def path(self) -> str:
        return self._path

    def _raw(self, offset: int, length: int) -> bytes:
        """Read from the underlying file, clamped to the track window."""
        if length <= 0:
            return b""
        pos = self._start + offset
        if pos >= self._end:
            return b""
        self._fh.seek(pos)
        return self._fh.read(min(length, self._end - pos))

    def close(self) -> None:
        self._fh.close()
