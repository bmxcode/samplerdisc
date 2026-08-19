# ADR-0017 · The stereo side marker is a character class, not a hyphen

**Status:** accepted · 2026-08-20

## Context

None of these samplers has a stereo sample type. A stereo sound is two mono files whose names end in a side letter, paired by the sampler at load time, and `stereo.py` rebuilds that pairing from the names — writing the joined file *alongside* the mono originals, never instead of them, because the pairing is a heuristic ([ADR-0007](0007-emit-mono-and-stereo.md)).

AKAI spells the separator with a hyphen: `MOVIN 105 -L`. **Roland S-7xx spells it with byte `0x7F`**: `STR:Vn1 Pizz55\x7fL`. The pattern in `stereo.py` required a literal hyphen, so no Roland pair was ever recognised — 2 130 names across the five reference discs carry that marker, and on `northstar` it is 1 110 of 1 284 samples. Most of that disc came out mono-only.

`stereo.py` is brand-neutral core. [ADR-0003](0003-brand-neutral-pluggable-backends.md) confines sampler knowledge to `fs/` and `sample/`, and its "watch for" is precisely a manufacturer's constant drifting into shared code. So this is a small change in exactly the place that decision is defensive about, and widening the pattern quietly would be the wrong way to make it.

## Decision

**The side separator is a character class — `[-\x7f]` — not a hyphen**, and it stays in brand-neutral core.

The distinction that permits this: what lives in `stereo.py` is the *convention* — a base name, a separator, a side letter — of which the hyphen and `0x7F` are two observed spellings. That is not format knowledge in the sense ADR-0003 guards. There is nothing here that must be verified against a disc to be read correctly, nothing that changes how a byte is interpreted, and a third manufacturer's spelling widens the class rather than adding a backend hook. The reasoning is stated in the module docstring so it travels with the code.

The separator stays **required**. `KICKL` and `KICKR` are not a pair.

## Alternatives rejected

**Put the pairing behind a backend hook, so each `fs/` module declares its own side marker.** Strictly correct about where brand knowledge belongs, and it scales to a sampler that pairs by something other than a suffix. Rejected as machinery ahead of need: it puts channel logic in three places to express one convention with two spellings, and every backend would return the same answer but one. If a manufacturer ever pairs by something structural rather than by name, that is when the hook earns itself.

**Normalise Roland names to the AKAI spelling during the directory walk.** One line in `fs/roland_s7xx.py`, and `stereo.py` never learns about Roland. Rejected because it lies about the disc: the name in a listing, a manifest and a `--keep-originals` filename would no longer be the name on the disc, and this project's whole claim is that it reports what is there.

**Make the separator optional.** Would catch any sampler that just appends `L`/`R`. Rejected outright — it is the loose-heuristic failure ADR-0007 keeps the mono originals against, and the discs supply the counter-example: `amg-now` has `FX :Headache-R\x7fN`, whose base already ends in `-R`. A pattern that let anything follow the side letter would read that as the right half of `FX :Headache` and weld it to an unrelated sound.

## Consequences

**Good.** 1 341 stereo pairs across the five Roland discs, where there were none: 555 on `northstar`, 297 on `l-cdx-01`, 295 on `amg-now`, 170 on `lcdp05`, 24 on `edirol-brass`.

**Good.** The change is one character class. The lazy base, the padding tolerance, the empty-base guard and the refusal to pair anything ambiguous are untouched, and every pre-existing test passes unchanged.

**Good, and unplanned.** `l-cdx-01` carries `SNR:Aargh Sn1 -L` and `-R` — *Roland* names using AKAI's spelling. They pair. That is direct evidence the separator is a class rather than a per-brand constant, from a disc that had no reason to provide it.

**Bad, accepted.** Cross-spelling pairing is possible in principle: an `A-L` and an `A\x7fR` on one disc both reduce to base `A` and would join. It occurs on none of the five discs, and requiring both halves to use the same separator would add state to `find_pairs` for a case with no observed instance. Recorded so it is a known gap rather than an oversight.

**Watch for.** A third spelling arriving with a manufacturer whose names also *contain* the new character, as Roland's do. `0x7F` appears mid-name on these discs and is only a separator when a side letter and nothing else follows it; that anchoring is what makes the class safe to widen, and it is the property to preserve.
