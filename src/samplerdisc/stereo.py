"""Rejoin the split mono files AKAI samplers used for stereo.

There is no stereo sample type on these machines: a stereo sound is two mono
files whose names end -L and -R, paired by the sampler at load time. Nothing in
the filesystem records the pairing, so this is a name heuristic -- which is why
the joined file is written *alongside* the mono originals and never instead of
them (ADR-0007).
"""

from __future__ import annotations

import re
import sys
from array import array
from dataclasses import dataclass

#: Trailing -L / -R, optionally with padding around it. AKAI names are fixed
#: width, so the side marker is often followed by spaces.
_SIDE = re.compile(r"^(?P<base>.*?)\s*-\s*(?P<side>[LR])\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Pair:
    base: str
    left: str
    right: str


def split_side(name: str) -> tuple[str, str] | None:
    """Return (base, 'L'|'R') if ``name`` looks like one half of a pair."""
    match = _SIDE.match(name)
    if not match:
        return None
    base = match.group("base").strip()
    if not base:
        return None
    return base, match.group("side").upper()


def find_pairs(names: list[str]) -> list[Pair]:
    """Match -L names to -R names, preserving the order the left ones arrived in.

    A base with two lefts and no right, or three files, is not a pair. Being
    conservative costs the user a manual join; being loose silently welds two
    unrelated sounds together.
    """
    lefts: dict[str, list[str]] = {}
    rights: dict[str, list[str]] = {}
    order: list[str] = []
    for name in names:
        parsed = split_side(name)
        if parsed is None:
            continue
        base, side = parsed
        bucket = lefts if side == "L" else rights
        if base not in lefts and base not in rights:
            order.append(base)
        bucket.setdefault(base, []).append(name)

    pairs = []
    for base in order:
        left = lefts.get(base, [])
        right = rights.get(base, [])
        if len(left) == 1 and len(right) == 1:
            pairs.append(Pair(base=base, left=left[0], right=right[0]))
    return pairs


def interleave(left: bytes, right: bytes) -> bytes:
    """Interleave two 16-bit mono PCM buffers into one stereo buffer.

    Lengths can differ on damaged rips. The shorter side is padded with silence
    rather than the longer one truncated -- losing the tail of a sound is worse
    than a little silence in one channel, and truncation is unrecoverable.

    Uses ``array`` slice assignment rather than a per-frame loop: these samples
    run to hundreds of thousands of frames and the obvious loop is far slower.
    """
    left_samples = array("h")
    right_samples = array("h")
    left_samples.frombytes(left[: len(left) - len(left) % 2])
    right_samples.frombytes(right[: len(right) - len(right) % 2])
    if sys.byteorder == "big":
        # AKAI PCM is little-endian; array() is native.
        left_samples.byteswap()
        right_samples.byteswap()

    frames = max(len(left_samples), len(right_samples))
    left_samples.extend([0] * (frames - len(left_samples)))
    right_samples.extend([0] * (frames - len(right_samples)))

    out = array("h", bytes(4 * frames))
    out[0::2] = left_samples
    out[1::2] = right_samples
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()
