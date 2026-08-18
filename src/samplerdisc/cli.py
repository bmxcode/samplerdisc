"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc import __version__
from samplerdisc.audiocd import detect as detect_audio_cd
from samplerdisc.audiocd import extract_tracks
from samplerdisc.batch import convert_tree, find_images, write_manifest
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.export import export_iso
from samplerdisc.extract import Extracted, Joined, Kept, extract_disc
from samplerdisc.fs import base as _fs_registry  # noqa: F401  (registers backends)
from samplerdisc.fs.probe import find_origin


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def cmd_list(args: argparse.Namespace) -> int:
    with open_image(args.image) as image:
        origin = find_origin(image)
        if origin is None:
            print("no recognised filesystem -- try `samplerdisc export-iso`", file=sys.stderr)
            return 1
        volumes = 0
        kinds: Counter[str] = Counter()
        for volume in origin.backend.volumes(image, origin.offset):
            volumes += 1
            print(f"{volume.name}  (block {volume.start_block}, {len(volume.files)} files)")
            for entry in volume.files:
                kinds[entry.kind] += 1
                if not args.volumes_only:
                    print(f"    {entry.name:<14} {entry.kind:<8} {entry.size:>9} bytes")
        # Kinds are the backend's vocabulary, not ours: AKAI says sample and
        # program, ISO 9660 says wav and aiff.
        breakdown = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        print(f"\n{volumes} volumes" + (f", {breakdown}" if breakdown else ""))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    sheet = detect_audio_cd(args.image)
    if sheet is not None:
        count = 0
        for track in extract_tracks(args.image, sheet, args.out):
            count += 1
            if args.verbose:
                print(f"  {track.number:3}  {track.seconds:6.1f}s  {track.title}")
        print(f"wrote {count} audio tracks to {args.out}")
        return 0

    with open_image(args.image) as image:
        origin = find_origin(image)
        if origin is None:
            print("no recognised filesystem -- try `samplerdisc export-iso`", file=sys.stderr)
            return 1
        written = 0
        joined = 0
        kept = 0
        skipped = 0
        results = extract_disc(
            image,
            origin.backend,
            origin.offset,
            args.out,
            join_stereo=not args.no_stereo,
            keep_originals=args.keep_originals,
        )
        for result in results:
            if isinstance(result, Extracted):
                written += 1
                if args.verbose:
                    seconds = result.frames / result.rate if result.rate else 0
                    print(f"  {result.volume}/{result.name}  {seconds:.2f}s @ {result.rate} Hz")
            elif isinstance(result, Joined):
                joined += 1
                if args.verbose:
                    print(f"  {result.volume}/stereo/{result.name}  joined")
            elif isinstance(result, Kept):
                kept += 1
                if args.verbose:
                    print(f"  {result.volume}/original/{result.name}  kept ({result.kind})")
            else:
                skipped += 1
                print(f"  skipped {result.volume}/{result.name}: {result.reason}", file=sys.stderr)
    print(f"wrote {written} WAV files to {args.out}")
    if joined:
        print(f"joined {joined} stereo pairs (mono originals kept)")
    if kept:
        print(f"kept {kept} original AKAI files")
    if skipped:
        # A disc that yields most of its samples is a good outcome; say so
        # plainly rather than burying it.
        print(f"skipped {skipped} damaged or unreadable entries")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    images = find_images(args.directory)
    if not images:
        print(f"no disc images found under {args.directory}", file=sys.stderr)
        return 1
    print(f"found {len(images)} images")
    reports = []
    for report in convert_tree(
        args.directory,
        args.out,
        join_stereo=not args.no_stereo,
        keep_originals=args.keep_originals,
    ):
        reports.append(report)
        label = os.path.basename(report.source)
        if report.error:
            print(f"  FAILED  {label}: {report.error}")
        else:
            extra = f", {report.stereo_pairs} stereo" if report.stereo_pairs else ""
            extra += f", {report.originals} originals" if report.originals else ""
            if report.audio_tracks:
                extra = f", {report.audio_tracks} audio tracks"
            body = f"{report.samples} samples" if report.samples else ""
            print(f"  ok      {label}  [{report.container}] {body}{extra}".replace("] ,", "]"))

    converted = sum(1 for r in reports if r.ok)
    samples = sum(r.samples for r in reports)
    tracks = sum(r.audio_tracks for r in reports)
    summary = f"\nconverted {converted}/{len(reports)} discs, {samples} samples"
    if tracks:
        summary += f", {tracks} audio tracks"
    print(summary)
    if args.manifest:
        write_manifest(args.manifest, reports)
        print(f"manifest written to {args.manifest}")
    return 0 if converted else 1


def cmd_info(args: argparse.Namespace) -> int:
    sheet = detect_audio_cd(args.image)
    if sheet is not None:
        total = sum(1 for _ in sheet.tracks)
        print("container   audio-cd (Red Book)")
        print(f"tracks      {total}")
        print("filesystem  none -- the sectors are the audio")
        return 0

    with open_image(args.image) as image:
        origin = find_origin(image)
        print(f"container   {sniff(args.image)}")
        print(f"size        {image.size} bytes ({_human(image.size)})")
        print(f"sectors     {image.sectors}")
        blocks = getattr(image, "blocks", None)
        if blocks is not None:
            # A wrong payload offset inverts these. See docs/formats/mdx.md.
            print(
                f"mdx blocks  {len(blocks)} x {image.block_size} "
                f"({image.compressed_blocks} compressed, {image.stored_blocks} stored)"
            )
            if image.trimmed:
                print(f"trimmed     {image.trimmed} bytes past the last whole sector")
        if origin is None:
            print("filesystem  none recognised -- try `samplerdisc export-iso`")
        else:
            print(f"filesystem  {origin.backend.name} at offset {origin.offset}")
    return 0


def cmd_export_iso(args: argparse.Namespace) -> int:
    # Progress uses \r to overwrite one line, which only makes sense on a
    # terminal. Redirected, it would emit a line per chunk into the output.
    show_progress = not args.quiet and sys.stderr.isatty()

    def progress(done: int, total: int) -> None:
        pct = 100.0 * done / total if total else 100.0
        print(f"\r  {pct:5.1f}%  {_human(done)} / {_human(total)}", end="", file=sys.stderr)

    with open_image(args.image) as image:
        written = export_iso(image, args.out, progress=progress if show_progress else None)
    if show_progress:
        print(file=sys.stderr)
    print(f"wrote {args.out} ({written} bytes, {written // 2048} sectors)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samplerdisc",
        description="Convert vintage sampler CD-ROM images to uncompressed WAV.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    info = sub.add_parser("info", help="identify the container and locate the filesystem")
    info.add_argument("image")
    info.set_defaults(func=cmd_info)

    listing = sub.add_parser("list", help="list volumes and files without extracting")
    listing.add_argument("image")
    listing.add_argument("-v", "--volumes-only", action="store_true", help="volumes, not files")
    listing.set_defaults(func=cmd_list)

    extract = sub.add_parser("extract", help="write every sample out as WAV")
    extract.add_argument("image")
    extract.add_argument("out")
    extract.add_argument("-v", "--verbose", action="store_true", help="name each file written")
    extract.add_argument(
        "--no-stereo", action="store_true", help="do not rejoin -L/-R pairs into stereo"
    )
    extract.add_argument(
        "--keep-originals",
        action="store_true",
        help="also write the raw AKAI sample and program files, exactly as stored",
    )
    extract.set_defaults(func=cmd_extract)

    batch = sub.add_parser("batch", help="convert every disc image under a directory")
    batch.add_argument("directory")
    batch.add_argument("out")
    batch.add_argument("--manifest", help="write a JSON report of the run")
    batch.add_argument("--no-stereo", action="store_true", help="do not rejoin -L/-R pairs")
    batch.add_argument(
        "--keep-originals",
        action="store_true",
        help="also write the raw AKAI sample and program files, exactly as stored",
    )
    batch.set_defaults(func=cmd_batch)

    export = sub.add_parser("export-iso", help="unwrap the container to a flat ISO")
    export.add_argument("image")
    export.add_argument("out")
    export.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    export.set_defaults(func=cmd_export_iso)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"samplerdisc: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
