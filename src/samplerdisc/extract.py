"""Disc in, WAV files out.

The deliverable is uncompressed WAV that works anywhere (ADR-0011): sample
values are never altered, and what the disc knows about a sample -- root key,
tuning -- rides along in the WAV's own smpl chunk.

Sampler payloads are copied into the data chunk unchanged. AIFF is the single
exception, and only in byte order: its samples are big-endian and a WAV's are
little-endian, so the bytes within each sample are reversed and the values are
left alone (ADR-0024).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from samplerdisc.fs.base import original_suffix
from samplerdisc.sample import NotASample, PayloadMismatch, aiff
from samplerdisc.sample.akai import parse
from samplerdisc.stereo import find_pairs, interleave
from samplerdisc.wav import LOOP_FORWARD, Loop, read_header, write_wav

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samplerdisc.container.base import SectorImage
    from samplerdisc.fs.base import Backend, File, Volume


class _Pairable(Protocol):
    """What the stereo joiner needs of a parsed sample.

    Deliberately not ``AkaiSample``: joining used to be gated on that class, so
    every non-AKAI format came out mono however its halves were named. On a
    Roland disc that is most of the disc -- 1 110 of NorthStar's 1 284 samples
    are one half of a pair.
    """

    name: str
    rate: int
    frames: int
    pcm: bytes


_UNSAFE = re.compile(r"[^A-Za-z0-9 ._+#-]")

#: Kinds --keep-originals writes out verbatim. Programs are here because they
#: carry the key ranges and envelopes, which the WAVs cannot: dropping them
#: loses the only copy. Drum settings and effects are not, being unusable
#: without the hardware.
_KEEP_KINDS = frozenset({"sample", "program"})

#: Originals live beside the WAVs, not among them.
ORIGINALS_DIR = "original"


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
    #: Which partition of the disc the volume came from, 0 where the
    #: filesystem has no partitions. AKAI volume names repeat across
    #: partitions, so the name alone does not identify a volume (ADR-0023).
    partition: int = 0
    #: Channels in the file written. 2 where the sample was stereo *on the
    #: disc* -- an E-mu record whose pointer block declares two channels
    #: (ADR-0026) or a stereo AIFF -- which is a different thing from the
    #: ``Joined`` file an -L/-R pair produces, and counted apart from it.
    channels: int = 1


@dataclass
class Skipped:
    volume: str
    name: str
    reason: str
    partition: int = 0
    #: True where the entry was read and understood and deliberately not
    #: written -- its audio is already out under another name. Damage and a
    #: duplicate are both "skipped" and they are not the same news, so the
    #: summary must be able to tell them apart (ADR-0024).
    duplicate: bool = False
    #: True where the payload is not the file this entry placed -- the
    #: filesystem repeats a file's identity in its payload and the two
    #: disagree. Counted apart for ADR-0024's reason one step on: "damaged or
    #: unreadable" is true of a payload that is mid-audio and of one that is a
    #: perfectly good sample under the wrong name, and only the second says the
    #: directory and the data have come apart (ADR-0027).
    mismatch: bool = False


@dataclass
class Kept:
    """One file's bytes, exactly as the sampler stored them."""

    volume: str
    name: str
    path: str
    kind: str
    partition: int = 0


@dataclass
class Joined:
    """A stereo file rebuilt from an -L/-R pair. The mono halves are kept."""

    volume: str
    name: str
    path: str
    rate: int
    frames: int
    partition: int = 0


def extract_volume(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    out_dir: str,
    join_stereo: bool = True,
    keep_originals: bool = False,
) -> Iterator[Extracted | Skipped | Joined | Kept]:
    """Write every sample in one volume as WAV.

    With ``keep_originals`` the on-disc bytes of samples *and* programs are
    written alongside, untouched.
    """
    made = False
    originals_made = False
    parsed: dict[str, _Pairable] = {}
    #: sha256 of each WAV payload written, against the name it was written
    #: from and whether it carried a smpl chunk, so a duplicate can say which
    #: file already holds the audio and whether it holds the metadata too.
    written_audio: dict[bytes, tuple[str, bool]] = {}
    deferred: list[File] = []
    for entry in volume.files:
        if keep_originals and entry.kind in _KEEP_KINDS:
            payload = backend.read_file(image, origin, entry)
            if payload:
                if not originals_made:
                    os.makedirs(os.path.join(out_dir, ORIGINALS_DIR), exist_ok=True)
                    originals_made = True
                kept_path = unique_path(
                    os.path.join(out_dir, ORIGINALS_DIR),
                    *_original_name(backend, entry),
                )
                with open(kept_path, "wb") as out:
                    out.write(payload)
                yield Kept(
                    volume=volume.name,
                    name=entry.name,
                    path=kept_path,
                    kind=entry.kind,
                    partition=volume.partition,
                )
        if entry.kind == "aiff":
            # Held back until the WAVs of this volume have been written, so a
            # twin can be recognised. Not stylistic: the AIFF tree sorts ahead
            # of the WAV tree on every ProSamples disc, so a forward pass meets
            # the AIFF with nothing yet to compare it against (ADR-0024).
            deferred.append(entry)
            continue
        if entry.kind == "wav":
            # Already a WAV -- an ISO 9660 disc whose payload is plain audio.
            # Copied untouched: it is the publisher's own file and carries the
            # smpl, acid and LIST chunks we would otherwise have to rebuild.
            if not made:
                os.makedirs(out_dir, exist_ok=True)
                made = True
            result, digest, has_smpl = _copy_wav(image, backend, origin, volume, entry, out_dir)
            if digest is not None:
                written_audio.setdefault(digest, (entry.name, has_smpl))
            yield result
            continue
        if entry.kind != "sample":
            continue
        try:
            payload = backend.read_file(image, origin, entry)
        except OSError as exc:  # pragma: no cover - filesystem-level failure
            yield Skipped(volume.name, entry.name, f"unreadable: {exc}", volume.partition)
            continue
        if not payload:
            yield Skipped(volume.name, entry.name, "no data on disc", volume.partition)
            continue
        try:
            sample = _parse_sample(backend, entry, payload)
        except PayloadMismatch as exc:
            # Caught ahead of NotASample, which it subclasses: the payload may
            # be usable audio and is still refused, because it is not the file
            # the directory placed here and writing it puts one sample's sound
            # under another's name (ADR-0027).
            yield Skipped(volume.name, entry.name, str(exc), volume.partition, mismatch=True)
            continue
        except NotASample as exc:
            yield Skipped(volume.name, entry.name, str(exc), volume.partition)
            continue
        if sample.frames == 0:
            yield Skipped(volume.name, entry.name, "zero-length sample", volume.partition)
            continue

        if not made:
            os.makedirs(out_dir, exist_ok=True)
            made = True
        path = unique_path(out_dir, safe_name(entry.name))
        # A format that does not carry root key, tuning or loops writes a plain
        # WAV rather than a wrong one.
        pitch = getattr(sample, "pitch", None)
        # A format whose sample is stereo on the disc says so; the rest are
        # mono, and one channel is the honest default rather than a guess.
        channels = getattr(sample, "channels", 1)
        write_wav(
            path,
            sample.pcm,
            rate=sample.rate,
            channels=channels,
            midi_note=pitch,
            cents=getattr(sample, "cents", 0.0),
            loops=_wav_loops(sample),
            name=sample.name or entry.name,
        )
        if channels == 1:
            # Only mono files can be halves of an -L/-R pair: ``interleave``
            # takes two mono buffers, and a sample that is already stereo is
            # not one side of anything. No sample on the seven E-mu discs is
            # both -- 2 656 declare two channels, 12 are name-paired, and the
            # two sets do not intersect -- so this changes nothing today and
            # is here so it cannot start to (ADR-0026).
            parsed[entry.name] = sample
        yield Extracted(
            volume=volume.name,
            name=entry.name,
            path=path,
            rate=sample.rate,
            frames=sample.frames,
            pitch=pitch if pitch is not None else 0,
            partition=volume.partition,
            channels=channels,
        )

    for entry in deferred:
        if not made:
            os.makedirs(out_dir, exist_ok=True)
            made = True
        yield _convert_aiff(image, backend, origin, volume, entry, out_dir, written_audio)

    if join_stereo:
        yield from _join_pairs(volume, parsed, out_dir)


def _join_pairs(
    volume: Volume, parsed: dict[str, _Pairable], out_dir: str
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
                volume.name,
                pair.base,
                f"rate mismatch between halves ({left.rate} vs {right.rate})",
                volume.partition,
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
            channels=2,
            rate=left.rate,
            # Root key, tuning and loops are optional: a format that does not
            # carry one writes a plain WAV rather than an invented value.
            midi_note=getattr(left, "pitch", None),
            cents=getattr(left, "cents", 0.0),
            # Loop points are frame offsets, so they carry over unchanged from
            # the left half to the interleaved file.
            loops=_wav_loops(left),
            name=pair.base,
        )
        yield Joined(
            volume=volume.name,
            name=pair.base,
            path=path,
            rate=left.rate,
            frames=frames,
            partition=volume.partition,
        )


def _parse_sample(backend: Backend, entry, payload: bytes):
    hook = getattr(backend, "parse_sample", None)
    if hook is not None:
        return hook(entry, payload)
    return parse(payload, fallback_name=entry.name)


def _wav_loops(sample) -> list[Loop]:
    """AKAI loop ends are exclusive; the RIFF smpl chunk wants them inclusive.

    A sample format with no loop information yields none, rather than an
    invented one.
    """
    return [
        Loop(
            start=loop.start,
            end=loop.end - 1,
            loop_type=getattr(loop, "loop_type", LOOP_FORWARD),
        )
        for loop in getattr(sample, "loops", ())
    ]


def _original_name(backend: Backend, entry: File) -> tuple[str, str]:
    """Stem and suffix for one file kept verbatim.

    A sampler filesystem has names and a type byte, so the suffix is supplied
    and appended. ISO 9660 has real filenames that already carry it, and
    appending it again gives ``BONGOS M.exs.exs``.
    """
    suffix = original_suffix(backend, entry)
    name = entry.name
    if suffix and name.lower().endswith(suffix.lower()):
        name = name[: -len(suffix)]
    return safe_name(name), suffix


def _copy_wav(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    entry: File,
    out_dir: str,
) -> tuple[Extracted | Skipped, bytes | None, bool]:
    """Write one already-WAV payload out untouched.

    Returns the record and a digest of the audio it holds, so the AIFF pass can
    recognise the same sound arriving a second time. The digest covers the data
    chunk alone, not the file: the two trees of a ProSamples disc differ in
    their metadata chunks and agree on every audio byte.
    """
    payload = backend.read_file(image, origin, entry)
    if not payload:
        return Skipped(volume.name, entry.name, "no data on disc", volume.partition), None, False
    stem, suffix = os.path.splitext(os.path.basename(entry.name))
    path = unique_path(out_dir, safe_name(stem), suffix.lower() or ".wav")
    with open(path, "wb") as out:
        out.write(payload)
    header = read_header(payload)
    digest = None
    if header is not None:
        digest = hashlib.sha256(payload[header.offset : header.offset + header.length]).digest()
    return (
        Extracted(
            volume=volume.name,
            name=entry.name,
            path=path,
            # A payload whose header will not parse is still written -- it is
            # the disc's own bytes -- but it cannot be described, and zero is
            # the honest answer rather than a guess.
            rate=header.rate if header else 0,
            frames=header.frames if header else 0,
            pitch=0,
            partition=volume.partition,
            channels=header.channels if header else 1,
        ),
        digest,
        bool(header and header.has_smpl),
    )


def _convert_aiff(
    image: SectorImage,
    backend: Backend,
    origin: int,
    volume: Volume,
    entry: File,
    out_dir: str,
    written_audio: dict[bytes, str],
) -> Extracted | Skipped:
    """Write one AIFF payload as a WAV, unless its audio is already out.

    Best Service mastered these discs with a full AIFF tree beside a full WAV
    tree of the same sounds, so converting both writes every sample twice for
    no extra audio. The twin is recognised by its PCM and not by its name:
    vol.43 carries pairs that share a name and differ by eleven frames, and
    those are two different sounds (ADR-0024).
    """
    payload = backend.read_file(image, origin, entry)
    if not payload:
        return Skipped(volume.name, entry.name, "no data on disc", volume.partition)
    try:
        sample = aiff.parse(payload, fallback_name=os.path.basename(entry.name))
    except NotASample as exc:
        return Skipped(volume.name, entry.name, str(exc), volume.partition)
    if sample.frames == 0:
        return Skipped(volume.name, entry.name, "zero-length sample", volume.partition)

    twin = written_audio.get(hashlib.sha256(sample.pcm).digest())
    if twin is not None:
        twin_name, twin_has_smpl = twin
        # Same audio is not the same file. On 314 of these pairs the AIFF
        # carries a root key and a loop the WAV has nowhere to put, so
        # dropping it for having identical audio would drop the metadata with
        # it -- and where both carry it they agree exactly, checked on 173
        # pairs against the publisher's own smpl chunk (ADR-0024).
        if twin_has_smpl or (sample.pitch is None and not sample.loops):
            return Skipped(
                volume.name,
                entry.name,
                f"same audio as {twin_name}, already written",
                volume.partition,
                duplicate=True,
            )

    stem, _ = os.path.splitext(os.path.basename(entry.name))
    path = unique_path(out_dir, safe_name(stem))
    write_wav(
        path,
        sample.pcm,
        rate=sample.rate,
        channels=sample.channels,
        sample_width=sample.width,
        midi_note=sample.pitch,
        cents=sample.cents,
        loops=_wav_loops(sample),
        name=sample.name,
    )
    return Extracted(
        volume=volume.name,
        name=entry.name,
        path=path,
        rate=sample.rate,
        frames=sample.frames,
        pitch=sample.pitch if sample.pitch is not None else 0,
        partition=volume.partition,
        channels=sample.channels,
    )


def volume_dir(out_root: str, volume: Volume) -> str:
    """Where one volume's WAVs go.

    A volume from a partitioned filesystem is written under its partition,
    because the name alone does not identify it: nearly every partition of an
    AKAI disc has a ``VOLUME 001``, and writing two of them into one directory
    puts two libraries' audio side by side with ``unique_path`` suffixes and
    nothing to say which is which (ADR-0007, ADR-0023).
    """
    if volume.partition:
        return os.path.join(out_root, f"partition-{volume.partition}", safe_name(volume.name))
    return os.path.join(out_root, safe_name(volume.name))


def extract_disc(
    image: SectorImage,
    backend: Backend,
    origin: int,
    out_root: str,
    join_stereo: bool = True,
    keep_originals: bool = False,
) -> Iterator[Extracted | Skipped | Joined | Kept]:
    """Write every sample on the disc, one directory per volume."""
    for volume in backend.volumes(image, origin):
        out_dir = volume_dir(out_root, volume)
        yield from extract_volume(
            image, backend, origin, volume, out_dir, join_stereo, keep_originals
        )
