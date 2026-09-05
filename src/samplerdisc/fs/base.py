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
    #: Byte offset, relative to the backend's origin, that ``start_block``
    #: counts from. 0 where the filesystem has one block numbering for the
    #: whole disc, which is every backend but AKAI.
    #:
    #: An AKAI disc is a *disk* of several partitions and a file's start block
    #: is relative to the partition it lives in, so the same number means a
    #: different place in each one. Keeping the number the directory declares
    #: and carrying its base beside it is what lets a note or a chain check
    #: still speak in the disc's own terms (ADR-0023).
    origin: int = 0
    #: Whatever else the directory knew about this file, as ``(key, value)``
    #: pairs -- a tuple rather than a dict so ``File`` stays frozen and
    #: hashable.
    #:
    #: Some filesystems keep a sample's musical parameters beside the directory
    #: rather than in the payload, so by the time ``parse_sample`` sees the
    #: bytes the root key and loop points are already gone. Roland S-7xx is
    #: one: its 48-byte parameter record lives in a different region of the
    #: disc entirely. ``raw_type`` is a single int and already stretched to
    #: carry a rate for E-mu; stretching it to four values would be the wrong
    #: shape.
    meta: tuple[tuple[str, int], ...] = ()

    def get(self, key: str, default: int = 0) -> int:
        """One ``meta`` value, or ``default`` where the backend set none."""
        for name, value in self.meta:
            if name == key:
                return value
        return default


@dataclass
class Volume:
    name: str
    start_block: int
    files: list[File] = field(default_factory=list)
    #: Byte offset, relative to the backend's origin, that ``start_block``
    #: counts from -- see ``File.origin``.
    origin: int = 0
    #: Which partition of the disc this volume came from, numbered from 1. 0
    #: where the filesystem has no partitions. Volume names repeat across an
    #: AKAI disc's partitions -- nearly every one has a ``VOLUME 001`` -- so
    #: this is what keeps two of them apart in a listing and on disk.
    partition: int = 0
    #: Bytes between where the disc's own bookkeeping puts this volume's
    #: partition and where it was found, 0 -- and meaningless -- where the
    #: filesystem has no partitions.
    #:
    #: Non-zero says the image is short of the disc it was made from: whole
    #: units of the container are missing in front of this volume, so it and
    #: everything after it sit nearer the front than the disc's table declares.
    #: The audio is intact and internally consistent, and *the image is not the
    #: disc* -- which a listing should say rather than leave to be inferred
    #: from a partition count (ADR-0028).
    displaced: int = 0
    #: Why this volume has no files, when that is expected rather than wrong.
    #: A volume with no files and no note is the signature of a probe that
    #: matched something it should not have (ADR-0012), so the two cases must
    #: be distinguishable by something other than a human reading the names.
    note: str = ""
    #: Human-readable disc provenance a volume carries beside (or instead of)
    #: its audio -- one line each. Empty for every volume that holds only
    #: samples. E-mu E-IV ``Credits`` and ``E-mu Systems 96`` text banks are
    #: the only producer today: a sample-free ``FORM/E4B0`` bank whose ``E4P1``
    #: chunks hold author/house/contact lines in their name field, read as
    #: metadata and written to a ``Credits.txt`` sidecar under ``--metadata``.
    #: This is a label field, not the preset it sits in (ADR-0043, ADR-0011).
    credits: list[str] = field(default_factory=list)

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

    def layout(self, image: SectorImage, offset: int) -> str:
        """One line describing how the disc is divided, or "".

        Optional. A backend whose filesystem has structure above the volume --
        AKAI's partitions -- says so here, so ``list`` can report it without
        knowing what a partition is.
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
