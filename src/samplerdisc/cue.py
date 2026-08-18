"""Cue sheet parsing.

A cue describes what the tracks of a `.bin` are. For a data disc it names the
sector size; for an audio disc it is the only place track boundaries and titles
exist at all, since Red Book audio carries no filesystem.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: Frames per second in CD timecode.
FRAMES_PER_SECOND = 75

_TRACK = re.compile(r"^\s*TRACK\s+(\d+)\s+(\S+)", re.IGNORECASE)
_INDEX = re.compile(r"^\s*INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)", re.IGNORECASE)
_TITLE = re.compile(r'^\s*TITLE\s+"?(.*?)"?\s*$', re.IGNORECASE)
_FILE = re.compile(r'^\s*FILE\s+"?(.+?)"?\s+(\S+)\s*$', re.IGNORECASE)


def msf_to_lba(minutes: int, seconds: int, frames: int) -> int:
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames


@dataclass
class CueTrack:
    number: int
    mode: str  # "AUDIO", "MODE1/2352", ...
    title: str = ""
    start_lba: int = 0

    @property
    def is_audio(self) -> bool:
        return self.mode.upper().startswith("AUDIO")

    @property
    def sector_size(self) -> int | None:
        if self.is_audio:
            return 2352
        if "/" in self.mode:
            try:
                return int(self.mode.split("/", 1)[1])
            except ValueError:
                return None
        return None


@dataclass
class CueSheet:
    data_file: str | None
    tracks: list[CueTrack]

    @property
    def all_audio(self) -> bool:
        return bool(self.tracks) and all(t.is_audio for t in self.tracks)

    def data_sector_size(self) -> int | None:
        for track in self.tracks:
            if not track.is_audio:
                return track.sector_size
        return None


def parse(text: str) -> CueSheet:
    """Parse a cue sheet. Unknown commands are ignored rather than fatal."""
    tracks: list[CueTrack] = []
    data_file: str | None = None
    current: CueTrack | None = None
    # A TITLE before the first TRACK is the disc's, not a track's.
    for line in text.splitlines():
        file_match = _FILE.match(line)
        if file_match and data_file is None:
            data_file = file_match.group(1)
            continue
        track_match = _TRACK.match(line)
        if track_match:
            current = CueTrack(number=int(track_match.group(1)), mode=track_match.group(2))
            tracks.append(current)
            continue
        if current is None:
            continue
        title_match = _TITLE.match(line)
        if title_match:
            current.title = title_match.group(1).strip()
            continue
        index_match = _INDEX.match(line)
        if index_match and int(index_match.group(1)) == 1:
            current.start_lba = msf_to_lba(*(int(g) for g in index_match.groups()[1:]))
    return CueSheet(data_file=data_file, tracks=tracks)


def find(image_path: str | os.PathLike[str]) -> str | None:
    """Locate a cue sheet beside an image, tolerating case differences."""
    stem, _ = os.path.splitext(os.fspath(image_path))
    for candidate in (stem + ".cue", stem + ".CUE", stem + ".Cue"):
        if os.path.exists(candidate):
            return candidate
    return None


def load(image_path: str | os.PathLike[str]) -> CueSheet | None:
    path = find(image_path)
    if path is None:
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse(fh.read())
