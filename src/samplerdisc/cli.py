"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc import __version__
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.export import export_iso
from samplerdisc.extract import Extracted, Joined, extract_disc
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
        samples = 0
        programs = 0
        for volume in origin.backend.volumes(image, origin.offset):
            volumes += 1
            print(f"{volume.name}  (block {volume.start_block}, {len(volume.files)} files)")
            for entry in volume.files:
                if entry.kind == "sample":
                    samples += 1
                elif entry.kind == "program":
                    programs += 1
                if not args.volumes_only:
                    print(f"    {entry.name:<14} {entry.kind:<8} {entry.size:>9} bytes")
        print(f"\n{volumes} volumes, {samples} samples, {programs} programs")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    with open_image(args.image) as image:
        origin = find_origin(image)
        if origin is None:
            print("no recognised filesystem -- try `samplerdisc export-iso`", file=sys.stderr)
            return 1
        written = 0
        joined = 0
        skipped = 0
        results = extract_disc(
            image, origin.backend, origin.offset, args.out, join_stereo=not args.no_stereo
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
            else:
                skipped += 1
                print(f"  skipped {result.volume}/{result.name}: {result.reason}", file=sys.stderr)
    print(f"wrote {written} WAV files to {args.out}")
    if joined:
        print(f"joined {joined} stereo pairs (mono originals kept)")
    if skipped:
        # A disc that yields most of its samples is a good outcome; say so
        # plainly rather than burying it.
        print(f"skipped {skipped} damaged or unreadable entries")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with open_image(args.image) as image:
        origin = find_origin(image)
        print(f"container   {sniff(args.image)}")
        print(f"size        {image.size} bytes ({_human(image.size)})")
        print(f"sectors     {image.sectors}")
        blocks = getattr(image, "blocks", None)
        if blocks is not None:
            # A wrong payload offset inverts these. See docs/formats/mdx.md.
            print(
                f"mdx blocks  {len(blocks)} "
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
    extract.set_defaults(func=cmd_extract)

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
