"""Rejoin the split mono files samplers used for stereo.

There is no stereo sample type on these machines: a stereo sound is two mono
files whose names end in a side marker, L and R, paired by the sampler at load
time. Nothing in the filesystem records the pairing, so this is a name
heuristic -- which is why the joined file is written *alongside* the mono
originals and never instead of them (ADR-0007).

Two manufacturers spell the separator differently. AKAI uses a hyphen --
``MOVIN 105 -L`` -- and Roland S-7xx uses byte ``0x7F`` -- ``STR:Vn1
Pizz55\\x7fL``. What lives here is the *convention*, a base name followed by a
separator and a side letter, of which those are two observed spellings; that is
why this stays in brand-neutral core rather than moving into ``fs/``. Neither
character is a Roland or an AKAI constant in the sense ADR-0003 guards -- there
is no format knowledge here, nothing that must be verified against a disc to be
read correctly, and a third manufacturer's spelling widens the class rather
than adding a backend hook.
"""

from __future__ import annotations

import re
import sys
from array import array
from dataclasses import dataclass
from typing import Generic, TypeVar

#: What each name carries alongside it -- the parsed sample, to ``extract`` --
#: threaded through the heuristic untouched so a matched pair hands back the
#: object itself rather than a name to look up again. Keeping it opaque is what
#: lets this stay in brand-neutral core: the pairing knows names, nothing more.
T = TypeVar("T")

#: A trailing side letter behind a separator, optionally with padding around
#: it. Both name forms are fixed width and space-padded, so the side marker is
#: often followed by spaces. The separator is a class of two: ``-`` as AKAI
#: writes it, and ``0x7F`` as Roland S-7xx does -- the latter appears 2130
#: times across the reference discs and is documented under "Names" in
#: docs/formats/roland-s7xx.md. It is deliberately *not* optional: ``KICKL``
#: and ``KICKR`` are not a pair, and a separator-free reading is exactly the
#: loose heuristic ADR-0007 keeps the mono originals against.
_SIDE = re.compile(r"^(?P<base>.*?)\s*[-\x7f]\s*(?P<side>[LR])\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Pair(Generic[T]):
    base: str
    #: The payloads the two halves arrived carrying, not their names: a matched
    #: pair hands back the samples themselves, so ``extract`` never looks one up
    #: by a name that a second entry may share (issue #11).
    left: T
    right: T


@dataclass(frozen=True)
class Ambiguous:
    """A base whose halves could not be paired without a guess.

    Two files marked ``-L`` and one marked ``-R`` is not a pair. Before this was
    reported it was silently dropped, and a duplicate name upstream could defeat
    the drop and weld two unrelated sounds together (issue #11). Reported, it
    becomes a ``Skipped`` -- the same way ``extract`` handles every other
    ambiguity it will not resolve on its own.
    """

    base: str
    reason: str


@dataclass(frozen=True)
class Pairing(Generic[T]):
    """The two outcomes of pairing: the clean matches, and the refusals."""

    pairs: list[Pair[T]]
    ambiguous: list[Ambiguous]


def split_side(name: str) -> tuple[str, str] | None:
    """Return (base, 'L'|'R') if ``name`` looks like one half of a pair."""
    match = _SIDE.match(name)
    if not match:
        return None
    base = match.group("base").strip()
    if not base:
        return None
    return base, match.group("side").upper()


def find_pairs(items: list[tuple[str, T]]) -> Pairing[T]:
    """Match -L names to -R names, preserving the order the left ones arrived in.

    Each item is ``(name, payload)``; only the name drives the match, so this
    stays a pure name heuristic, and the payload rides along so a matched pair
    hands back the two objects rather than names to resolve again.

    A base with exactly one left and one right pairs. Both sides present in any
    other count -- two lefts and a right, three files -- is *ambiguous* and
    reported rather than resolved: being conservative costs the user a manual
    join, and being loose silently welds two unrelated sounds together, which
    without the mono originals is unrecoverable (ADR-0007). A lone half with no
    opposite is neither -- it stays an unpaired mono sample, as it always has.
    """
    lefts: dict[str, list[T]] = {}
    rights: dict[str, list[T]] = {}
    order: list[str] = []
    for name, payload in items:
        parsed = split_side(name)
        if parsed is None:
            continue
        base, side = parsed
        bucket = lefts if side == "L" else rights
        if base not in lefts and base not in rights:
            order.append(base)
        bucket.setdefault(base, []).append(payload)

    pairs: list[Pair[T]] = []
    ambiguous: list[Ambiguous] = []
    for base in order:
        left = lefts.get(base, [])
        right = rights.get(base, [])
        if len(left) == 1 and len(right) == 1:
            pairs.append(Pair(base=base, left=left[0], right=right[0]))
        elif left and right:
            ambiguous.append(
                Ambiguous(
                    base=base,
                    reason=(
                        f"{len(left)} files marked -L and {len(right)} marked -R; "
                        "refusing to guess the pair"
                    ),
                )
            )
    return Pairing(pairs=pairs, ambiguous=ambiguous)


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
