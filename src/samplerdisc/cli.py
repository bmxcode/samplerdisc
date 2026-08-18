"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from samplerdisc import __version__
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.export import export_iso
from samplerdisc.fs.probe import find_origin


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def cmd_info(args: argparse.Namespace) -> int:
    with open_image(args.image) as image:
        origin = find_origin(image)
        print(f"container   {sniff(args.image)}")
        print(f"size        {image.size} bytes ({_human(image.size)})")
        print(f"sectors     {image.sectors}")
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
