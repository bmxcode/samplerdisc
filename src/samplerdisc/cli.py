"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import samplerdisc.fs  # noqa: F401  (importing registers the backends)
from samplerdisc import __version__
from samplerdisc.audiocd import detect as detect_audio_cd
from samplerdisc.audiocd import extract_tracks, looks_like_cd_audio, write_whole_disc
from samplerdisc.batch import convert_tree, find_images, write_manifest
from samplerdisc.container.detect import open_image, sniff
from samplerdisc.export import export_iso
from samplerdisc.extract import Credited, Extracted, Joined, Kept, extract_disc
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
        # How the disc is laid out, where the backend has something to say --
        # for AKAI, how many partitions the disk declares against how many this
        # image holds, which is how a short rip stops being a silent absence.
        describe = getattr(origin.backend, "layout", None)
        described = describe(image, origin.offset) if describe is not None else ""
        if described:
            print(described)
        volumes = 0
        partitions = 0
        kinds: Counter[str] = Counter()
        current = 0
        for volume in origin.backend.volumes(image, origin.offset):
            volumes += 1
            if volume.partition and volume.partition != current:
                current = volume.partition
                partitions += 1
                # Where the partition was not where the disc's table put it,
                # say so here rather than only in the summary line: these
                # volumes read perfectly and are still evidence that the image
                # is short of the disc (ADR-0028).
                short = (
                    f"  ({volume.displaced} bytes before its declared position "
                    f"-- this image is short of the disc)"
                    if volume.displaced
                    else ""
                )
                print(f"\npartition {volume.partition}{short}")
            # Volumes sit under their partition where there is one, because
            # their names repeat across partitions (ADR-0023).
            indent = "  " if volume.partition else ""
            note = f" -- {volume.note}" if volume.note else ""
            print(
                f"{indent}{volume.name}  (block {volume.start_block}, "
                f"{len(volume.files)} files){note}"
            )
            for entry in volume.files:
                kinds[entry.kind] += 1
                if not args.volumes_only:
                    print(f"{indent}    {entry.name:<14} {entry.kind:<8} {entry.size:>9} bytes")
        # Kinds are the backend's vocabulary, not ours: AKAI says sample and
        # program, ISO 9660 says wav and aiff.
        breakdown = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        across = f" across {partitions} partitions" if partitions > 1 else ""
        print(f"\n{volumes} volumes{across}" + (f", {breakdown}" if breakdown else ""))
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
        if origin is None and getattr(args, "assume_audio_cd", False):
            # The user has asserted this is audio; confirm rather than obey, so
            # a mistyped filename does not produce half a gigabyte of noise.
            if not looks_like_cd_audio(image):
                print(
                    "--assume-audio-cd: this stream does not look like 16-bit stereo PCM",
                    file=sys.stderr,
                )
                return 1
            os.makedirs(args.out, exist_ok=True)
            stem = os.path.splitext(os.path.basename(args.image))[0]
            out_path = os.path.join(args.out, f"{stem}.wav")
            frames = write_whole_disc(image, out_path)
            print(f"wrote {out_path} ({frames / 44100:.1f}s, no track boundaries without a cue)")
            return 0
        if origin is None:
            print("no recognised filesystem -- try `samplerdisc export-iso`", file=sys.stderr)
            return 1
        written = 0
        stereo = 0
        joined = 0
        kept = 0
        skipped = 0
        duplicates = 0
        mismatches = 0
        credited: Credited | None = None
        results = extract_disc(
            image,
            origin.backend,
            origin.offset,
            args.out,
            join_stereo=not args.no_stereo,
            keep_originals=args.keep_originals,
            metadata=args.metadata,
        )
        for result in results:
            if isinstance(result, Credited):
                credited = result
                if args.verbose:
                    print(f"  {result.path}  {result.lines} credit lines from {result.banks} banks")
            elif isinstance(result, Extracted):
                written += 1
                if result.channels > 1:
                    stereo += 1
                if args.verbose:
                    seconds = result.frames / result.rate if result.rate else 0
                    channels = "stereo" if result.channels > 1 else "mono"
                    print(
                        f"  {result.volume}/{result.name}  "
                        f"{seconds:.2f}s @ {result.rate} Hz {channels}"
                    )
            elif isinstance(result, Joined):
                joined += 1
                if args.verbose:
                    print(f"  {result.volume}/stereo/{result.name}  joined")
            elif isinstance(result, Kept):
                kept += 1
                if args.verbose:
                    print(f"  {result.volume}/original/{result.name}  kept ({result.kind})")
            else:
                if result.duplicate:
                    duplicates += 1
                elif result.mismatch:
                    mismatches += 1
                else:
                    skipped += 1
                print(f"  skipped {result.volume}/{result.name}: {result.reason}", file=sys.stderr)
    print(f"wrote {written} WAV files to {args.out}")
    if stereo:
        # Stereo on the disc, not joined here: the record declared two
        # channels and no filename was consulted (ADR-0026).
        print(f"{stereo} of them were stereo samples")
    if joined:
        print(f"joined {joined} stereo pairs (mono originals kept)")
    if kept:
        # Not "AKAI files": an ISO 9660 disc keeps EXS24 and HALion
        # instruments through the same path.
        print(f"kept {kept} original files")
    if duplicates:
        # Not damage, and saying so matters: a disc that lists 423 skips reads
        # as a bad rip when every one of them is a sound already written.
        print(f"skipped {duplicates} duplicates of audio already written")
    if mismatches:
        # The loudest line on a short image, and the one ADR-0012's argument
        # applies to: a payload that is not the file the directory placed is
        # not "damage" in the sense the next line means, and lumping the two
        # together is how nine wrong samples went unremarked on for a release.
        print(f"skipped {mismatches} payloads that are not the file the directory placed")
    if skipped:
        # A disc that yields most of its samples is a good outcome; say so
        # plainly rather than burying it.
        print(f"skipped {skipped} damaged or unreadable entries")
    if credited is not None:
        # The disc's own provenance, read from its text banks (ADR-0043).
        print(
            f"wrote {credited.lines} credit lines from {credited.banks} "
            f"text banks to {credited.path}"
        )
    return 0


def cmd_extract_banks(args: argparse.Namespace) -> int:
    from samplerdisc.banks import extract_banks

    if not os.path.isdir(args.directory):
        print(f"not a directory: {args.directory}", file=sys.stderr)
        return 1
    written = 0
    stereo = 0
    skipped = 0
    for result in extract_banks(args.directory, args.out):
        if isinstance(result, Extracted):
            written += 1
            if result.channels > 1:
                stereo += 1
            if args.verbose:
                seconds = result.frames / result.rate if result.rate else 0
                channels = "stereo" if result.channels > 1 else "mono"
                print(
                    f"  {result.volume}/{result.name}  {seconds:.2f}s @ {result.rate} Hz {channels}"
                )
        else:
            skipped += 1
            print(f"  skipped {result.volume}/{result.name}: {result.reason}", file=sys.stderr)
    if not written and not skipped:
        print(f"no .ebl sample banks found under {args.directory}", file=sys.stderr)
        return 1
    print(f"wrote {written} WAV files to {args.out}")
    if stereo:
        print(f"{stereo} of them were stereo samples")
    if skipped:
        print(f"skipped {skipped} damaged or unreadable entries")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from samplerdisc.banks import find_bank_dirs

    images = find_images(args.directory)
    bank_dirs = find_bank_dirs(args.directory)
    if not images and not bank_dirs:
        print(f"no disc images or sample banks found under {args.directory}", file=sys.stderr)
        return 1
    found = [f"{len(images)} images"] if images else []
    if bank_dirs:
        found.append(f"{len(bank_dirs)} loose banks")
    print("found " + " and ".join(found))
    reports = []
    for report in convert_tree(
        args.directory,
        args.out,
        join_stereo=not args.no_stereo,
        keep_originals=args.keep_originals,
        metadata=args.metadata,
    ):
        reports.append(report)
        # A loose bank's source path ends in the meaningless ``SamplePool``; its
        # library name is the volume the report carries.
        if report.container == "loose-ebl" and report.volumes:
            label = report.volumes[0]["name"]
        else:
            label = os.path.basename(report.source)
        if report.error:
            print(f"  FAILED  {label}: {report.error}")
        else:
            extra = f", {report.stereo_pairs} joined" if report.stereo_pairs else ""
            if report.stereo_samples:
                extra += f", {report.stereo_samples} stereo"
            extra += f", {report.originals} originals" if report.originals else ""
            if report.audio_tracks:
                extra = f", {report.audio_tracks} audio tracks"
            body = f"{report.samples} samples" if report.samples else ""
            print(f"  ok      {label}  [{report.container}] {body}{extra}".replace("] ,", "]"))

    converted = sum(1 for r in reports if r.ok)
    samples = sum(r.samples for r in reports)
    tracks = sum(r.audio_tracks for r in reports)
    credit_lines = sum(r.credit_lines for r in reports)
    summary = f"\nconverted {converted}/{len(reports)} discs, {samples} samples"
    if tracks:
        summary += f", {tracks} audio tracks"
    if credit_lines:
        summary += f", {credit_lines} credit lines"
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
            if image.stored_only:
                # Not a defect on its own: PCM does not deflate, so an image of
                # an audio CD is legitimately all stored. Say which reading
                # applies rather than leaving a bare zero to be misread.
                measured = "measured" if image.block_size_measured else "assumed"
                print(f"            fully stored (uncompressed image, block size {measured})")
            if image.trimmed:
                print(f"trimmed     {image.trimmed} bytes past the last whole sector")
        if origin is not None:
            print(f"filesystem  {origin.backend.name} at offset {origin.offset}")
            return 0

        print("filesystem  none recognised -- try `samplerdisc export-iso`")
        if looks_like_cd_audio(image):
            print("content     consistent with Red Book audio (16-bit 44.1 kHz stereo)")
            print("            no cue sheet means no track boundaries; extract the whole")
            print("            stream with `samplerdisc extract --assume-audio-cd`")
        elif blocks is not None and image.stored_only and not image.block_size_measured:
            # The one case the container cannot resolve alone: every block fell
            # through to stored AND the size was never read off the image. Say
            # so plainly instead of presenting a decode we cannot vouch for.
            print("            every block was stored and the block size could not be")
            print("            measured -- if another container of this disc reads, the")
            print("            two should agree byte for byte. See docs/formats/mdx.md")
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
        "--no-stereo", action="store_true", help="do not rejoin L/R pairs into stereo"
    )
    extract.add_argument(
        "--keep-originals",
        action="store_true",
        help="also write the raw AKAI sample and program files, exactly as stored",
    )
    extract.add_argument(
        "--metadata",
        action="store_true",
        help="also write a Credits.txt of the disc's provenance from its E-IV text banks",
    )
    extract.add_argument(
        "--assume-audio-cd",
        action="store_true",
        help="disc has no filesystem and holds CD audio: write the whole stream as one WAV",
    )
    extract.set_defaults(func=cmd_extract)

    banks = sub.add_parser(
        "extract-banks",
        help="convert loose E-mu .ebl sample banks in a directory (no disc image)",
    )
    banks.add_argument("directory")
    banks.add_argument("out")
    banks.add_argument("-v", "--verbose", action="store_true", help="name each file written")
    banks.set_defaults(func=cmd_extract_banks)

    batch = sub.add_parser("batch", help="convert every disc image under a directory")
    batch.add_argument("directory")
    batch.add_argument("out")
    batch.add_argument("--manifest", help="write a JSON report of the run")
    batch.add_argument("--no-stereo", action="store_true", help="do not rejoin L/R pairs")
    batch.add_argument(
        "--keep-originals",
        action="store_true",
        help="also write the raw AKAI sample and program files, exactly as stored",
    )
    batch.add_argument(
        "--metadata",
        action="store_true",
        help="also write a Credits.txt of each disc's provenance from its E-IV text banks",
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
