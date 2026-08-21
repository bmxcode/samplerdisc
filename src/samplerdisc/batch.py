"""Convert a directory of disc images in one pass, and record what happened.

A collection is the real use case: dozens of images from different sites in
different containers, some of which will not open. One bad disc must not stop
the run, and the manifest is how a user finds the ones that need attention.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from samplerdisc.audiocd import detect as detect_audio_cd
from samplerdisc.audiocd import extract_tracks
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.extract import Extracted, Joined, Kept, Skipped, extract_disc, safe_name
from samplerdisc.fs.probe import find_origin

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Extensions worth opening. Detection is by signature (ADR-0004), but walking
#: a directory needs some filter or every README becomes a candidate disc.
IMAGE_SUFFIXES = {
    ".mdx", ".nrg", ".iso", ".img", ".bin", ".mds", ".cdr", ".tao", ".ccd",
}  # fmt: skip


@dataclass
class DiscReport:
    source: str
    container: str | None = None
    filesystem: str | None = None
    origin: int | None = None
    volumes: list[dict[str, Any]] = field(default_factory=list)
    samples: int = 0
    stereo_pairs: int = 0
    originals: int = 0
    audio_tracks: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.samples > 0 or self.audio_tracks > 0)


def find_images(root: str) -> list[str]:
    """Every plausible disc image under ``root``, in stable order.

    Companion files are excluded by simply not listing their suffixes: a
    ``.cue`` describes its ``.bin`` and a ``.mdf`` holds data for its ``.mds``,
    so each pair is reached once, through the member that is actually opened.
    """
    found: list[str] = []
    for directory, _dirs, files in os.walk(root):
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in IMAGE_SUFFIXES:
                found.append(os.path.join(directory, name))
    return sorted(found)


def convert_disc(
    path: str, out_root: str, join_stereo: bool = True, keep_originals: bool = False
) -> DiscReport:
    """Convert one image. Never raises: a failure becomes a report."""
    report = DiscReport(source=path)
    try:
        # An audio CD has no filesystem to find -- the sectors are the audio.
        sheet = detect_audio_cd(path)
        if sheet is not None:
            report.container = "audio-cd"
            report.filesystem = "none (Red Book audio)"
            out_dir = os.path.join(out_root, safe_name(os.path.splitext(os.path.basename(path))[0]))
            for _track in extract_tracks(path, sheet, out_dir):
                report.audio_tracks += 1
            return report

        report.container = sniff(path)
        with open_image(path) as image:
            origin = find_origin(image)
            if origin is None:
                report.error = "no recognised filesystem"
                return report
            report.filesystem = origin.backend.name
            report.origin = origin.offset

            out_dir = os.path.join(out_root, safe_name(os.path.splitext(os.path.basename(path))[0]))
            # Keyed by partition *and* name: nearly every partition of an AKAI
            # disc has a "VOLUME 001", and keying by name alone reported nine
            # volumes' samples as one entry (ADR-0023).
            volumes: dict[tuple[int, str], dict[str, Any]] = {}
            results = extract_disc(
                image, origin.backend, origin.offset, out_dir, join_stereo, keep_originals
            )
            for result in results:
                if isinstance(result, Extracted):
                    report.samples += 1
                    entry = volumes.setdefault(
                        (result.partition, result.volume),
                        {"name": result.volume, "partition": result.partition, "samples": 0},
                    )
                    entry["samples"] += 1
                elif isinstance(result, Joined):
                    report.stereo_pairs += 1
                elif isinstance(result, Kept):
                    report.originals += 1
                elif isinstance(result, Skipped):
                    report.skipped.append(
                        {
                            "volume": result.volume,
                            "partition": result.partition,
                            "name": result.name,
                            "reason": result.reason,
                        }
                    )
            report.volumes = list(volumes.values())
    except (OSError, ValueError) as exc:
        # One unreadable disc must not end the run.
        report.error = str(exc)
    return report


def convert_tree(
    root: str, out_root: str, join_stereo: bool = True, keep_originals: bool = False
) -> Iterator[DiscReport]:
    for path in find_images(root):
        yield convert_disc(path, out_root, join_stereo, keep_originals)


def write_manifest(path: str, reports: list[DiscReport]) -> None:
    payload = {
        "discs": [asdict(report) for report in reports],
        "totals": {
            "discs": len(reports),
            "converted": sum(1 for r in reports if r.ok),
            "failed": sum(1 for r in reports if not r.ok),
            "samples": sum(r.samples for r in reports),
            "stereo_pairs": sum(r.stereo_pairs for r in reports),
            "audio_tracks": sum(r.audio_tracks for r in reports),
            "originals": sum(r.originals for r in reports),
            "skipped": sum(len(r.skipped) for r in reports),
        },
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as out:
        json.dump(payload, out, indent=2)
        out.write("\n")
