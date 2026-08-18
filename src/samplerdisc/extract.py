"""Disc in, WAV files out.

The deliverable is uncompressed WAV that works anywhere (ADR-0011): audio is
copied, never converted, and what the disc knows about a sample -- root key,
tuning -- rides along in the WAV's own smpl chunk.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from samplerdisc.sample.akai import NotASample, parse
from samplerdisc.wav import write_wav

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage
    from samplerdisc.fs.base import Backend, Volume

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._+#-]")


def safe_name(name: str) -> str:
    """Make an AKAI name safe as a filename.

    AKAI names are fixed-width and arrive padded, and carry '#' and '+'. Empty
    or dot-only results would be unopenable, so they fall back to a placeholder.
    """
    cleaned = _UNSAFE.sub("_", name).strip().rstrip(".")
    return cleaned or "unnamed"


def unique_path(directory: str, stem: str, suffix: str = ".wav") -> str:
    """Avoid collisions after sanitising, which can map two names onto one."""
    candidate = os.path.join(directory, stem + suffix)
    if not os.path.exists(candidate):
        return candidate
    for n in range(2, 1000):
        candidate = os.path.join(directory, f"{stem}_{n}{suffix}")
        if not os.path.exists(candidate):
            return candidate
    raise OSError(f"cannot find a free filename for {stem!r} in {directory}")


@dataclass
class Extracted:
    volume: str
    name: str
    path: str
    rate: int
    frames: int
    pitch: int


@dataclass
class Skipped:
    volume: str
    name: str
    reason: str


def extract_volume(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    out_dir: str,
) -> Iterator[Extracted | Skipped]:
    """Write every sample in one volume. Programs are listed elsewhere, not written."""
    made = False
    for entry in volume.files:
        if entry.kind != "sample":
            continue
        try:
            payload = backend.read_file(image, origin, entry)
        except OSError as exc:  # pragma: no cover - filesystem-level failure
            yield Skipped(volume.name, entry.name, f"unreadable: {exc}")
            continue
        if not payload:
            yield Skipped(volume.name, entry.name, "no data on disc")
            continue
        try:
            sample = parse(payload, fallback_name=entry.name)
        except NotASample as exc:
            yield Skipped(volume.name, entry.name, str(exc))
            continue
        if sample.frames == 0:
            yield Skipped(volume.name, entry.name, "zero-length sample")
            continue

        if not made:
            os.makedirs(out_dir, exist_ok=True)
            made = True
        path = unique_path(out_dir, safe_name(entry.name))
        write_wav(
            path,
            sample.pcm,
            rate=sample.rate,
            midi_note=sample.pitch,
            name=sample.name,
        )
        yield Extracted(
            volume=volume.name,
            name=entry.name,
            path=path,
            rate=sample.rate,
            frames=sample.frames,
            pitch=sample.pitch,
        )


def extract_disc(
    image: SectorImage,
    backend: Backend,
    origin: int,
    out_root: str,
) -> Iterator[Extracted | Skipped]:
    """Write every sample on the disc, one directory per volume."""
    for volume in backend.volumes(image, origin):
        out_dir = os.path.join(out_root, safe_name(volume.name))
        yield from extract_volume(image, backend, origin, volume, out_dir)
