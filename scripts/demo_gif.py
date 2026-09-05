#!/usr/bin/env python3
"""Regenerate the README demo: build a synthetic AKAI disc, run the tool against
it, and render the session to ``docs/demo.gif``.

Nothing here comes off a real disc (ADR-0008). The disc is built from the same
synthetic fixtures the tests use, the commands are the real CLI run in-process,
and their output is captured verbatim -- only the *timing* (the typing effect
and the pauses) is synthesised, exactly what a live recording's timing would be.

The recording is written as an asciicast v2 ``.cast`` and rendered to GIF with
``agg`` (https://docs.asciinema.org/manual/agg/, ``brew install agg``). If agg
is not installed, the ``.cast`` is still written and the command to render it is
printed.

    uv run --with-editable . python scripts/demo_gif.py
"""

from __future__ import annotations

import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tests import fixtures  # noqa: E402

from samplerdisc.cli import main  # noqa: E402

DISC = "Demo AKAI CD.nrg"
COLS, ROWS = 82, 30

# Typing and pacing, in seconds. A demo that types too fast reads as a dump; too
# slow and nobody waits for it.
KEYSTROKE = 0.045
AFTER_ENTER = 0.35
AFTER_OUTPUT = 1.1
PROMPT = "\x1b[32m$\x1b[0m "  # a green $, the one bit of colour


def build_disc(directory: pathlib.Path) -> pathlib.Path:
    """A small AKAI disc of invented samples, wrapped in an NRG container."""

    def sample(name: str, **kw: object) -> bytes:
        return fixtures.akai_sample(name, **kw)

    volumes = [
        (
            "SYNTH BASS",
            [
                ("PIANO C3", sample("PIANO C3", rate=44100, words=96, pitch=60, loop=(8, 88))),
                ("BASS PICK", sample("BASS PICK", rate=44100, words=80, pitch=48)),
            ],
        ),
        (
            "DRUM KIT 1",
            [
                ("KICK 1", sample("KICK 1", rate=44100, words=64, pitch=36)),
                ("SNARE 1", sample("SNARE 1", rate=44100, words=72, pitch=38)),
                ("HIHAT CL", sample("HIHAT CL", rate=22050, words=48, pitch=42)),
            ],
        ),
    ]
    volumes = [(n, [(fn, 0x73, len(p), p) for fn, p in files]) for n, files in volumes]
    disc = fixtures.akai_disc([fixtures.akai_partition(volumes, blocks_total=64)])
    path = directory / DISC
    path.write_bytes(fixtures.make_nrg(disc))
    return path


def run(argv: list[str]) -> str:
    """The real CLI, in-process, with its stdout captured verbatim."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    if code != 0:
        raise SystemExit(f"{' '.join(argv)} exited {code}")
    return buffer.getvalue()


def wav_tree(out: pathlib.Path) -> str:
    return "\n".join(str(p.relative_to(out.parent)) for p in sorted(out.rglob("*.wav"))) + "\n"


class Cast:
    """An asciicast v2 writer with a keystroke-by-keystroke typing effect."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.events: list[tuple[float, str, str]] = []
        self.t = 0.0

    def emit(self, text: str, dt: float = 0.0) -> None:
        self.t += dt
        self.events.append((round(self.t, 3), "o", text))

    def command(self, shown: str) -> None:
        self.emit(PROMPT)
        for ch in shown:
            self.emit(ch, KEYSTROKE)
        self.emit("\r\n", KEYSTROKE)

    def output(self, text: str) -> None:
        self.emit(text.replace("\n", "\r\n"), AFTER_ENTER)
        self.t += AFTER_OUTPUT

    def write(self, path: pathlib.Path) -> None:
        # No wall-clock timestamp: it does not affect rendering and its only
        # effect would be to churn the file on every regeneration.
        header = {
            "version": 2,
            "width": self.cols,
            "height": self.rows,
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/zsh"},
        }
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(header) + "\n")
            for stamp, kind, data in self.events:
                handle.write(json.dumps([stamp, kind, data]) + "\n")
            # A last breath so the final frame is not cut off.
            handle.write(json.dumps([round(self.t + 2.0, 3), "o", ""]) + "\n")


def main_() -> None:
    docs = REPO / "docs"
    cast_path = docs / "demo.cast"
    gif_path = docs / "demo.gif"

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        build_disc(work)
        # Run from the disc's directory so the recording shows a bare filename.
        cwd = pathlib.Path.cwd()
        try:
            import os

            os.chdir(work)
            info = run(["info", DISC])
            listing = run(["list", DISC])
            extract = run(["extract", DISC, "out"])
            tree = wav_tree(work / "out")
        finally:
            os.chdir(cwd)

    cast = Cast(COLS, ROWS)
    cast.command(f'samplerdisc info "{DISC}"')
    cast.output(info)
    cast.command(f'samplerdisc list "{DISC}"')
    cast.output(listing)
    cast.command(f'samplerdisc extract "{DISC}" out')
    cast.output(extract)
    cast.command("find out -name '*.wav' | sort")
    cast.output(tree)
    cast.write(cast_path)
    print(f"wrote {cast_path}")

    agg = shutil.which("agg")
    if not agg:
        print("agg not found (brew install agg); to render the GIF yourself:")
        print(f"  agg --theme asciinema --font-size 20 {cast_path} {gif_path}")
        return
    subprocess.run(
        [
            agg,
            "--theme",
            "asciinema",
            "--font-size",
            "20",
            "--speed",
            "1.0",
            str(cast_path),
            str(gif_path),
        ],
        check=True,
    )
    print(f"wrote {gif_path} ({gif_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main_()
