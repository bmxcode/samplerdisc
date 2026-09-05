"""Loose sample banks in an ordinary directory, converted to WAV.

Some E-mu libraries ship not as a disc image but as loose files in the clear:
an Emulator X / Proteus X bank is a ``.exb`` definition beside a ``SamplePool/``
of ``.ebl`` sample files. There is no disc, no container and no on-disc
filesystem to read -- the operating system's own filesystem already presents
the bytes and the tree -- so this is a *source*, not a container or a
``Backend`` (ADR-0042). It runs the same verified ``emu_ebl`` decoder the
on-disc path does, through ``extract.ebl_to_wav``.

The ``.exb`` holds the preset key ranges and zone mappings; like the on-disc
``.exb`` and the E-IV presets it is left to ConvertWithMoss and is not read
here (ADR-0011). Only the ``.ebl`` sample files are converted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from samplerdisc.extract import Extracted, Skipped, ebl_to_wav, safe_name

if TYPE_CHECKING:
    from collections.abc import Iterator


def find_bank_dirs(root: str) -> list[Path]:
    """Every directory under ``root`` that directly holds ``.ebl`` files.

    Returned in stable sorted order. A render/oracle tree or a stray folder
    with no ``.ebl`` is not a bank and is passed over: the presence of the
    sample files is the whole test, so ``.exb``-only or FLAC-only folders never
    qualify.
    """
    found: list[Path] = []
    for directory, _dirs, files in os.walk(root):
        if any(name.lower().endswith(".ebl") for name in files):
            found.append(Path(directory))
    return sorted(found)


def bank_name(bank_dir: Path) -> str:
    """The library name for a bank directory.

    An E-mu bank keeps its samples in a child ``SamplePool/``, so the name that
    means something is the parent (``Proteus 1``), not the pool. A directory
    that holds the ``.ebl`` files directly is named for itself.
    """
    if bank_dir.name.lower() == "samplepool":
        return bank_dir.parent.name
    return bank_dir.name


def extract_bank(bank_dir: Path, out_dir: str, volume: str) -> Iterator[Extracted | Skipped]:
    """Convert every ``.ebl`` in one bank directory to a WAV in ``out_dir``.

    Files are walked in sorted order for a stable run. Each is decoded by the
    shared ``ebl_to_wav``, which names the output from the sample's own header
    and refuses a bad payload with a reason rather than raising -- one damaged
    ``.ebl`` never ends the bank. Unlike the AKAI path there is no stereo
    ``-L``/``-R`` pairing and no de-duplication: an ``.ebl`` has no on-disc
    twin (as on the disc EBL path).
    """
    for path in sorted(bank_dir.glob("*.ebl")):
        try:
            payload = path.read_bytes()
        except OSError as exc:  # pragma: no cover - filesystem-level failure
            yield Skipped(volume, path.name, f"unreadable: {exc}")
            continue
        yield ebl_to_wav(payload, path.name, volume, out_dir)


def extract_banks(root: str, out_root: str) -> Iterator[Extracted | Skipped]:
    """Convert every loose bank found under ``root``.

    Each bank's WAVs land under ``out_root/<bank name>/`` so several banks share
    an output tree without colliding.
    """
    for bank_dir in find_bank_dirs(root):
        name = bank_name(bank_dir)
        out_dir = os.path.join(out_root, safe_name(name))
        yield from extract_bank(bank_dir, out_dir, name)
