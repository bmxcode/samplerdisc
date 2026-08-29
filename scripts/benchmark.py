#!/usr/bin/env python3
"""Regenerate the README "Tested against" benchmark against a disc collection.

The benchmark is a real batch run: every disc the collection holds is converted
to a scratch directory, the reports are tallied, and the WAVs written are
scanned for silence and sample-rate spread. Nothing is committed -- the scratch
output is deleted at the end -- so the numbers describe whatever collection
``SAMPLERDISC_TEST_DISCS`` (or the first argument) points at.

    uv run python scripts/benchmark.py [COLLECTION_ROOT]

It prints a human summary and, below it, the Markdown tables ready to paste into
README.md's "Tested against" section. The collection is re-anchored by running
this and pasting the result: as discs are downloaded and filed under
``<state>/<source-slug>/``, the source breakdown and container counts follow
without editing the script. Source names and URLs are read from each
``incoming/<source-slug>/_details.md`` when present, so a new source documents
itself.

Run it from a release branch when cutting a version, the way 0.3.0 did.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import samplerdisc.fs  # noqa: F401  (registers the backends)
from samplerdisc.batch import convert_tree

#: A readable label per backend name, in the order the table lists them.
FS_LABEL = {
    "akai": "AKAI",
    "emu3": "E-mu `EMU3`",
    "iso9660": "ISO 9660",
    "roland_s7xx": "Roland `S770 MR25A`",
    "none (Red Book audio)": "Audio CD",
}
FS_ORDER = ["akai", "emu3", "iso9660", "roland_s7xx", "none (Red Book audio)"]

#: A readable label per container kind reported by the manifest.
CONTAINER_LABEL = {
    "flat": "flat `.iso`/`.bin`",
    "mdx": "compressed `.mdx`",
    "rawcd": "raw CD image",
    "nrg": "`.nrg`",
    "mdsmdf": "`.mds`/`.mdf` pair",
    "audio-cd": "audio CD",
}


def _source_slug(path: str) -> str:
    """The collection the disc was filed under -- ``<state>/<slug>/disc``."""
    return Path(path).parent.name


def _source_url(root: Path, slug: str) -> str | None:
    """The source URL from ``incoming/<slug>/_details.md``, if recorded."""
    details = root / "incoming" / slug / "_details.md"
    if not details.is_file():
        return None
    for line in details.read_text(encoding="utf-8", errors="replace").splitlines():
        if "url" in line.lower() and "http" in line:
            return "http" + line.split("http", 1)[1].split()[0].strip()
    return None


def _wav_stats(root: Path) -> tuple[int, int, Counter, Counter]:
    """(files, silent, silent-by-top-dir, rate histogram) over the output WAVs."""
    files = silent = 0
    silent_by_dir: Counter = Counter()
    rates: Counter = Counter()
    for path in root.rglob("*.wav"):
        raw = path.read_bytes()
        files += 1
        pos, rate, data = 12, None, None
        while pos + 8 <= len(raw):
            tag = raw[pos : pos + 4]
            size = struct.unpack_from("<I", raw, pos + 4)[0]
            if tag == b"fmt ":
                rate = struct.unpack_from("<I", raw, pos + 12)[0]
            elif tag == b"data":
                data = raw[pos + 8 : pos + 8 + size]
            pos += 8 + size + (size & 1)
        if rate is not None:
            rates[rate] += 1
        if data is not None and len(data) and not any(data):
            silent += 1
            silent_by_dir[path.relative_to(root).parts[0]] += 1
    return files, silent, silent_by_dir, rates


#: The sampler filesystems whose decoded PCM is a run of the disc's own bytes.
#: ISO 9660 is left out on purpose: an AIFF is byte-swapped to little endian on
#: the way to a WAV, so its PCM is *not* the disc's bytes, and its correctness is
#: the AIFF/WAV twin check instead (ADR-0024).
_SAMPLER_FS = {"akai", "emu3", "roland_s7xx"}


def _byte_identity(reports) -> tuple[int, int, int]:
    """Verify every sampler-filesystem sample against the disc's own bytes.

    The decoded audio is a run of the payload: a mono record's PCM is the tail
    of the payload (AKAI keeps a 150/192-byte header in front of it; the others
    keep none), and a stereo record's two channel blocks are the payload once
    the written interleave is undone. A payload ``parse_sample`` refuses -- not
    the file its entry placed, or tail damage -- is one the writer refuses too,
    so it is skipped, exactly as it is never written. This is the
    whole-collection form of what ``tests/test_discs.py`` pins per disc.

    Returns ``(discs, matched, payloads)``.
    """
    from array import array

    from samplerdisc.container.detect import open_image
    from samplerdisc.fs.probe import find_origin

    discs = matched = payloads = 0
    for source in {r.source for r in reports if r.filesystem in _SAMPLER_FS and not r.error}:
        discs += 1
        clean = True
        with open_image(source) as image:
            origin = find_origin(image)
            if origin is None:
                continue
            for volume in origin.backend.volumes(image, origin.offset):
                for entry in volume.samples():
                    payload = origin.backend.read_file(image, origin.offset, entry)
                    try:
                        sample = origin.backend.parse_sample(entry, payload)
                    except Exception:
                        continue
                    payloads += 1
                    if getattr(sample, "channels", 1) == 2:
                        half = len(payload) // 2
                        frames = array("h")
                        frames.frombytes(sample.pcm)
                        blocks = (frames[0::2].tobytes(), frames[1::2].tobytes())
                        if blocks != (payload[:half], payload[half:]):
                            clean = False
                    elif not bytes(payload).endswith(bytes(sample.pcm)):
                        clean = False
        matched += clean
    return discs, matched, payloads


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SAMPLERDISC_TEST_DISCS", ""))
    if not root.is_dir():
        print("set SAMPLERDISC_TEST_DISCS or pass a collection root", file=sys.stderr)
        return 2

    out = Path(tempfile.mkdtemp(prefix="samplerdisc-bench-"))
    try:
        started = time.monotonic()
        reports = list(convert_tree(str(root), str(out)))
        elapsed = time.monotonic() - started
        files, silent, silent_by_dir, rates = _wav_stats(out)
    finally:
        for path in sorted(out.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        out.rmdir()

    def ok(r):
        return r.error is None and (r.samples > 0 or r.audio_tracks > 0)

    converted = sum(1 for r in reports if ok(r))
    samples = sum(r.samples for r in reports)
    stereo_pairs = sum(r.stereo_pairs for r in reports)
    stereo_samples = sum(r.stereo_samples for r in reports)
    tracks = sum(r.audio_tracks for r in reports)
    duplicates = sum(r.duplicates for r in reports)
    mismatches = sum(r.mismatches for r in reports)
    damage = sum(len(r.skipped) for r in reports) - duplicates - mismatches

    containers = Counter(r.container for r in reports)
    sources: dict[str, Counter] = defaultdict(Counter)
    for r in reports:
        sources[_source_slug(r.source)]["images"] += 1
        sources[_source_slug(r.source)]["converted"] += ok(r)

    fs: dict[str, Counter] = defaultdict(Counter)
    fs_discs: Counter = Counter()
    for r in reports:
        key = r.filesystem or "unclaimed"
        fs_discs[key] += 1
        fs[key]["samples"] += r.samples
        fs[key]["stereo_pairs"] += r.stereo_pairs
        fs[key]["stereo_samples"] += r.stereo_samples
        # The "Skipped" column is damage plus not-placed, not the ISO dedup.
        fs[key]["skipped"] += len(r.skipped) - r.duplicates
        fs[key]["audio_tracks"] += r.audio_tracks

    id_discs, id_matched, id_payloads = _byte_identity(reports)

    print(f"collection: {root}")
    print(f"images {len(reports)}  converted {converted}  time {elapsed:.0f} s\n")
    print(f"samples {samples}  stereo pairs {stereo_pairs}  record-stereo {stereo_samples}")
    print(f"tracks {tracks}  duplicates {duplicates}  not-placed {mismatches}  damage {damage}")
    print(f"byte-identity: {id_matched}/{id_discs} sampler discs, {id_payloads} payloads")
    print(
        f"WAV written {files}  silent {silent}  "
        f"rates {len(rates)} distinct {min(rates)}-{max(rates)} Hz"
    )
    print(f"silent by disc: {dict(silent_by_dir)}\n")

    print("--- container mix ---")
    for kind, n in containers.most_common():
        print(f"  {n:3}  {CONTAINER_LABEL.get(kind, kind)}")
    print("\n--- by source ---")
    for slug in sorted(sources):
        url = _source_url(root, slug)
        print(f"  {sources[slug]['images']:3} images  {slug}  {url or ''}")

    print("\n=== README: top table ===")
    print("| | |\n|---|---|")
    print(f"| Discs converted | {converted} of {len(reports)} |")
    print(f"| Samples | {samples:,} |".replace(",", " "))
    print(f"| Stereo pairs rejoined | {stereo_pairs:,} |".replace(",", " "))
    print(f"| Audio CD tracks | {tracks} |")
    print(f"| Duplicate audio suppressed | {duplicates:,} |".replace(",", " "))
    print(f"| Entries not the file their entry placed | {mismatches} |")
    print(f"| Entries skipped (damage) | {damage} |")
    print(f"| Time | {elapsed:.0f} s |")

    print("\n=== README: by filesystem ===")
    print("| | Discs | Samples | Stereo pairs | Skipped |\n|---|---:|---:|---:|---:|")
    for key in FS_ORDER:
        if key not in fs:
            continue
        c = fs[key]
        pairs = f"{c['stereo_pairs']:,}" if c["stereo_pairs"] else "—"
        label = FS_LABEL.get(key, key)
        line = f"| {label} | {fs_discs[key]} | {c['samples']:,} | {pairs} | {c['skipped'] or 0} |"
        print(line.replace(",", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
