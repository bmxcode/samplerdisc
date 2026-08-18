"""Red Book audio CDs.

Not a CD-ROM: no filesystem, no partition, nothing to walk. The sectors *are*
the audio. A raw 2352-byte CD audio sector is already 16-bit 44.1 kHz stereo
little-endian PCM, so a track becomes a WAV by putting a header in front of it
-- the same "copy, never convert" guarantee as the sampler path (ADR-0011).

These discs sit in the same archives as the sampler CD-ROMs and are easy to
mistake for one, so recognising them is as useful as converting them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from samplerdisc import cue as cuesheet
from samplerdisc.wav import write_wav

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A raw CD audio sector: 588 stereo frames of 16-bit samples.
AUDIO_SECTOR_SIZE = 2352
CDDA_RATE = 44100
CDDA_CHANNELS = 2
CDDA_WIDTH = 2


@dataclass
class AudioTrack:
    number: int
    title: str
    path: str
    frames: int

    @property
    def seconds(self) -> float:
        return self.frames / CDDA_RATE


def detect(image_path: str | os.PathLike[str]) -> cuesheet.CueSheet | None:
    """Return the cue sheet if ``image_path`` is an audio CD, else None.

    Requires a cue: without one there is no way to know where tracks begin, and
    nothing in the bytes distinguishes CD audio from any other PCM.
    """
    sheet = cuesheet.load(image_path)
    if sheet is None or not sheet.all_audio:
        return None
    if os.path.getsize(image_path) % AUDIO_SECTOR_SIZE != 0:
        return None
    return sheet


def track_name(track: cuesheet.CueTrack) -> str:
    return track.title or f"Track {track.number:02d}"


def extract_tracks(
    image_path: str | os.PathLike[str],
    sheet: cuesheet.CueSheet,
    out_dir: str,
) -> Iterator[AudioTrack]:
    """Write each audio track as a stereo WAV."""
    from samplerdisc.extract import safe_name, unique_path

    size = os.path.getsize(image_path)
    total_sectors = size // AUDIO_SECTOR_SIZE
    os.makedirs(out_dir, exist_ok=True)

    starts = [t.start_lba for t in sheet.tracks]
    with open(image_path, "rb") as source:
        for index, track in enumerate(sheet.tracks):
            start = starts[index]
            end = starts[index + 1] if index + 1 < len(starts) else total_sectors
            if end <= start or start >= total_sectors:
                continue
            end = min(end, total_sectors)
            source.seek(start * AUDIO_SECTOR_SIZE)
            pcm = source.read((end - start) * AUDIO_SECTOR_SIZE)
            if not pcm:
                continue
            name = track_name(track)
            path = unique_path(out_dir, safe_name(name))
            write_wav(
                path,
                pcm,
                rate=CDDA_RATE,
                channels=CDDA_CHANNELS,
                sample_width=CDDA_WIDTH,
                name=name,
            )
            yield AudioTrack(
                number=track.number,
                title=name,
                path=path,
                frames=len(pcm) // (CDDA_CHANNELS * CDDA_WIDTH),
            )
