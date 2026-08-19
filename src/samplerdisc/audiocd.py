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
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from samplerdisc import cue as cuesheet
from samplerdisc.wav import write_wav, write_wav_streaming

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage

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


#: Windows sampled across an image when judging whether it holds CD audio, and
#: how many bytes each. Spread rather than contiguous: a sample CD is mostly
#: silence between hits, and one window can easily land in a gap.
_GATE_WINDOWS = 12
_GATE_WINDOW_BYTES = 1 << 16

#: A window quieter than this carries no evidence either way.
_GATE_SILENCE = 8

#: Interleaved stereo makes a lag-1 step a hop between channels and a lag-2
#: step a move along one channel, so lag-1 differences dominate. Mono data read
#: as stereo inverts that: lag-1 is a single step in time and lag-2 is two, so
#: the ratio sits near 0.5. Measured across the reference discs, audio CDs land
#: at 5.1-14.0 and every sampler disc at or below 1.01 -- including Roland
#: discs whose payload is smooth enough to fool a plain smoothness test.
_GATE_STEREO_RATIO = 2.0

#: Each channel must also look like a waveform rather than noise. Audio CDs
#: measure 0.10-0.25 here; uniform noise sits near 1.33.
_GATE_SMOOTHNESS = 0.75

#: Read size when streaming a whole disc to one WAV.
_WHOLE_DISC_CHUNK = 1 << 22


def _window_stats(buf: bytes) -> tuple[float, float] | None:
    """(lag-1 / lag-2, lag-2 / mean) for ``buf`` read as 16-bit LE stereo."""
    if len(buf) < 4096:
        return None
    values = struct.unpack(f"<{len(buf) // 2}h", buf[: len(buf) // 2 * 2])
    mean = sum(map(abs, values)) / len(values)
    if mean < _GATE_SILENCE:
        return None
    lag1 = sum(abs(values[i] - values[i - 1]) for i in range(1, len(values))) / (len(values) - 1)
    lag2 = sum(abs(values[i] - values[i - 2]) for i in range(2, len(values))) / (len(values) - 2)
    if lag2 == 0:
        return None
    return lag1 / lag2, lag2 / mean


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def looks_like_cd_audio(image: SectorImage) -> bool:
    """Does this image's stream look like 44.1 kHz 16-bit stereo PCM?

    This answers a narrower question than "is this an audio CD", and it cannot
    replace a cue sheet: track boundaries are not in the bytes, which is why
    ``detect`` still requires one. What it is good for is telling a user whose
    disc yielded no filesystem *why* -- an image of a Red Book disc decodes
    perfectly and then has nothing to walk, which otherwise looks identical to
    a container we got wrong.

    Deliberately conservative. It is consulted only when no backend claimed the
    disc, and it must not fire on a sampler disc whose payload happens to be
    smooth -- see the constants above for the measured margins.
    """
    stats = []
    for index in range(_GATE_WINDOWS):
        offset = (image.size // (_GATE_WINDOWS + 1)) * (index + 1)
        offset -= offset % 4
        window = _window_stats(image.read(offset, _GATE_WINDOW_BYTES))
        if window is not None:
            stats.append(window)
    if len(stats) < 3:
        # Too little to judge. Say no rather than guess.
        return False
    return (
        _median([s[0] for s in stats]) > _GATE_STEREO_RATIO
        and _median([s[1] for s in stats]) < _GATE_SMOOTHNESS
    )


def write_whole_disc(image: SectorImage, out_path: str | os.PathLike[str]) -> int:
    """Write an image's entire stream as one stereo WAV. Returns frames.

    For a disc with no filesystem whose content is CD audio. The bytes are
    copied verbatim -- a raw audio sector is already 588 stereo frames of
    signed 16-bit LE PCM, so this is a header in front of the stream and
    nothing else (ADR-0011).
    """
    frame_bytes = CDDA_CHANNELS * CDDA_WIDTH
    total = (image.size // frame_bytes) * frame_bytes

    def stream():
        done = 0
        while done < total:
            chunk = image.read(done, min(_WHOLE_DISC_CHUNK, total - done))
            if not chunk:
                # Tail damage. The declared length must still be met, so pad
                # with silence rather than writing a truncated data chunk.
                yield b"\x00" * (total - done)
                return
            done += len(chunk)
            yield chunk

    write_wav_streaming(
        out_path,
        stream(),
        total_bytes=total,
        rate=CDDA_RATE,
        channels=CDDA_CHANNELS,
        sample_width=CDDA_WIDTH,
    )
    return total // frame_bytes


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
