"""The filesystem backend contract, and the registry the origin probe asks.

One module per sampler filesystem, all implementing ``Backend``. Adding a
manufacturer is a module plus a ``register()`` call and nothing else -- see
ADR-0003.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from samplerdisc.container.base import SectorImage


@dataclass(frozen=True)
class File:
    """One file inside a volume."""

    name: str
    kind: str  # "sample", "program", or a backend-specific label
    size: int
    start_block: int
    #: The filesystem's own type byte, kept so a backend can name the original
    #: faithfully. 0 where the filesystem has no such concept.
    raw_type: int = 0


@dataclass
class Volume:
    name: str
    start_block: int
    files: list[File] = field(default_factory=list)
    #: Why this volume has no files, when that is expected rather than wrong.
    #: A volume with no files and no note is the signature of a probe that
    #: matched something it should not have (ADR-0012), so the two cases must
    #: be distinguishable by something other than a human reading the names.
    note: str = ""

    def samples(self) -> Iterator[File]:
        return (f for f in self.files if f.kind == "sample")


@runtime_checkable
class Backend(Protocol):
    """A sampler filesystem reader."""

    name: str

    def probe(self, image: SectorImage, offset: int) -> bool:
        """Cheap, specific check for this filesystem at ``offset``.

        Runs at every candidate offset during origin detection, so it must be
        cheap -- and specific enough not to match a run of zeros or of audio. A
        loose probe resolves an origin confidently and wrongly, which is the
        silent failure ADR-0005 exists to prevent.
        """
        ...

    def volumes(self, image: SectorImage, offset: int) -> Iterable[Volume]:
        """Walk the filesystem rooted at ``offset``."""
        ...

    def read_file(self, image: SectorImage, offset: int, entry: File) -> bytes:
        """Return the raw bytes of one file."""
        ...

    def original_suffix(self, entry: File) -> str:
        """Filename suffix for this file's bytes as stored on disc.

        Optional; ``DEFAULT_ORIGINAL_SUFFIX`` is used when a backend has no
        opinion.
        """
        ...

    def parse_sample(self, entry: File, payload: bytes):
        """Turn one file's bytes into something with name/rate/frames/pcm.

        Optional. A backend that does not implement it gets the AKAI sample
        parser, which is what every disc used before a second sample format
        existed. Keeping this on the backend rather than sniffing the payload
        is what stops ``sample/`` growing a brand check (ADR-0003).
        """
        ...


#: Used when a backend does not implement ``original_suffix``.
DEFAULT_ORIGINAL_SUFFIX = ".bin"


def original_suffix(backend: Backend, entry: File) -> str:
    hook = getattr(backend, "original_suffix", None)
    return hook(entry) if hook is not None else DEFAULT_ORIGINAL_SUFFIX


_REGISTRY: list[Backend] = []


def register(backend: Backend) -> Backend:
    _REGISTRY.append(backend)
    return backend


def backends() -> list[Backend]:
    return list(_REGISTRY)
