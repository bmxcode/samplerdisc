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

from samplerdisc.sample.akai import AkaiSample, NotASample, parse
from samplerdisc.stereo import find_pairs, interleave
from samplerdisc.wav import Loop, write_wav

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage
    from samplerdisc.fs.base import Backend, File, Volume

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._+#-]")

#: Kinds that are already audio files and need copying, not decoding.
_AUDIO_FILE_KINDS = frozenset({"wav", "aiff"})


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


@dataclass
class Joined:
    """A stereo file rebuilt from an -L/-R pair. The mono halves are kept."""

    volume: str
    name: str
    path: str
    rate: int
    frames: int


def extract_volume(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    out_dir: str,
    join_stereo: bool = True,
) -> Iterator[Extracted | Skipped | Joined]:
    """Write every sample in one volume. Programs are listed elsewhere, not written."""
    made = False
    parsed: dict[str, AkaiSample] = {}
    for entry in volume.files:
        if entry.kind in _AUDIO_FILE_KINDS:
            # Already an audio file -- an ISO 9660 disc whose payload is plain
            # WAV or AIFF. Copy it out untouched; there is nothing to decode.
            if not made:
                os.makedirs(out_dir, exist_ok=True)
                made = True
            result = _copy_audio(image, backend, origin, volume, entry, out_dir)
            yield result
            continue
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
            cents=sample.cents,
            loops=_wav_loops(sample),
            name=sample.name,
        )
        parsed[entry.name] = sample
        yield Extracted(
            volume=volume.name,
            name=entry.name,
            path=path,
            rate=sample.rate,
            frames=sample.frames,
            pitch=sample.pitch,
        )

    if join_stereo:
        yield from _join_pairs(volume.name, parsed, out_dir)


def _join_pairs(
    volume_name: str, parsed: dict[str, AkaiSample], out_dir: str
) -> Iterator[Skipped | Joined]:
    pairs = find_pairs(list(parsed))
    if not pairs:
        return
    stereo_dir = os.path.join(out_dir, "stereo")
    made = False
    for pair in pairs:
        left = parsed[pair.left]
        right = parsed[pair.right]
        if left.rate != right.rate:
            # Different rates means these are not two halves of one sound,
            # whatever the names say.
            yield Skipped(
                volume_name,
                pair.base,
                f"rate mismatch between halves ({left.rate} vs {right.rate})",
            )
            continue
        if not made:
            os.makedirs(stereo_dir, exist_ok=True)
            made = True
        path = unique_path(stereo_dir, safe_name(pair.base))
        pcm = interleave(left.pcm, right.pcm)
        frames = len(pcm) // 4
        write_wav(
            path,
            pcm,
            rate=left.rate,
            channels=2,
            midi_note=left.pitch,
            cents=left.cents,
            # Loop points are frame offsets, so they carry over unchanged from
            # the left half to the interleaved file.
            loops=_wav_loops(left),
            name=pair.base,
        )
        yield Joined(volume=volume_name, name=pair.base, path=path, rate=left.rate, frames=frames)


def _wav_loops(sample: AkaiSample) -> list[Loop]:
    """AKAI loop ends are exclusive; the RIFF smpl chunk wants them inclusive."""
    return [Loop(start=loop.start, end=loop.end - 1) for loop in sample.loops]


def _copy_audio(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    entry: File,
    out_dir: str,
) -> Extracted | Skipped:
    payload = backend.read_file(image, origin, entry)
    if not payload:
        return Skipped(volume.name, entry.name, "no data on disc")
    stem, suffix = os.path.splitext(os.path.basename(entry.name))
    path = unique_path(out_dir, safe_name(stem), suffix.lower() or ".wav")
    with open(path, "wb") as out:
        out.write(payload)
    return Extracted(
        volume=volume.name,
        name=entry.name,
        path=path,
        rate=0,
        frames=0,
        pitch=0,
    )


def extract_disc(
    image: SectorImage,
    backend: Backend,
    origin: int,
    out_root: str,
    join_stereo: bool = True,
) -> Iterator[Extracted | Skipped | Joined]:
    """Write every sample on the disc, one directory per volume."""
    for volume in backend.volumes(image, origin):
        out_dir = os.path.join(out_root, safe_name(volume.name))
        yield from extract_volume(image, backend, origin, volume, out_dir, join_stereo)
