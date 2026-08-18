# ADR-0014 · One backend per on-disc format, named after the format

**Status:** accepted · 2026-08-19

## Context

[ADR-0003](0003-brand-neutral-pluggable-backends.md) put sampler knowledge behind a `Backend` interface with "one module per sampler". That phrasing was written when there was one implementation, and the second and third do not fit it.

The archives sort E-mu discs into three generations — EIIIX, ESI/Formula 4000, E-IV — and sell them as different product lines. All five reference discs write `EMU3` at byte 0, share a header whose `0x08 + 0x0C == 0x10` relation closes exactly, and walk the same folder and bank directories with one parser. Three modules would have been three copies.

Roland goes the other way. `Roland LCD1` opens `* ROLAND S-550 *`; the other four Roland discs open `S770 MR25A` at byte 4. They share no magic, no addressing scheme and no directory record — 512-byte units both, and nothing else. One module would be two parsers behind one `probe()` answering for two unrelated magics, which is the loose probe [ADR-0005](0005-probe-for-the-filesystem-origin.md) warns about and [ADR-0012](0012-a-probe-must-confirm-a-file.md) had to fix once already.

So the unit that matters is neither the manufacturer nor the model. It is the format written on the disc.

## Decision

**One backend per on-disc format, named after the format.**

```
fs/emu3.py          EMU3              -- EIIIX, ESI/Formula 4000 and E-IV
fs/roland_s7xx.py   S770 MR25A        -- S-770, S-750, S-760
fs/roland_s550.py   * ROLAND S-550 *  -- S-550, S-330, S-50, W-30
```

The name comes from what the disc says about itself, not from the badge on the sampler. `emu3` is the string in the header; it is also what stopped the module being split three ways to match a marketing taxonomy.

Where one format spans generations that differ *below* the directory, that is handled inside the module rather than by splitting it — see [ADR-0015](0015-locate-banks-by-signature.md).

## Alternatives rejected

**One backend per manufacturer.** Matches how a user thinks about their collection, and how the README is organised. Rejected: it forces S-550 and S-7xx into a module sharing nothing but the word "Roland", and forces one probe to recognise two unrelated magics. The cost lands exactly where this project has already been bitten.

**One backend per marketing generation.** What the archive's own directory structure suggests, and it would have looked diligent. Rejected because the bytes say otherwise: it splits `EMU3` three ways for discs that are byte-compatible at every level the directory reaches. The archive's labels are not evidence — the same collection files an AKAI disc under *Roland S-770,S-750*.

**One backend per sampler model.** Most precise-sounding. Rejected as unimplementable: S-1000 and S-3000 already share `fs/akai.py` and differ only in a high bit, and nothing on an EIIIX disc says which of six machines wrote it.

## Consequences

**Good.** Adding a manufacturer stays "a module plus a `register()` call", and adding a *generation* usually costs nothing at all — the E-IV discs were readable by the `EMU3` module before anyone looked at one.

**Good.** The naming is falsifiable. `emu3` is a string you can find in a hex dump; "the E-mu backend" is a claim about the world that the discs turned out not to support.

**Bad.** The module names are less obvious to a user, who has an *E-IV* disc and must work out that `emu3` reads it. Mitigated in the README and in `samplerdisc info`, which names the backend that claimed the disc.

**Watch for.** A backend growing a second parser behind one `probe()`. That is the signal the format actually split and the module should have, and it is easier to see early than after both parsers have grown tests. The reverse signal — two modules whose probes differ only in a version byte — means they were one format all along.
