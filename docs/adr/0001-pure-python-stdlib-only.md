# ADR-0001 · Pure Python, standard library only

**Status:** accepted · 2026-08-18

## Context

The mature open-source reader for AKAI sampler filesystems is [akaiutil](https://sourceforge.net/projects/akaiutil/) — C, maintained since 2008, covering far more variants than this project will for a long time: S900 compressed samples, floppy geometries, the optional DD partition, tar import/export. Not using it means re-implementing work someone has already done well.

But akaiutil reads neither compressed `.mdx` nor `.nrg`, which is the majority of what the archives actually hold, so it cannot be the whole answer regardless.

## Decision

Implement in Python against the standard library alone. `zlib` decodes MDX blocks, `wave` writes output, `struct` parses headers, `argparse` runs the CLI. No third-party runtime dependencies.

## Alternatives rejected

**Vendor akaiutil and drive it from a Python wrapper.** This is what [vintage-samplerCD-extractor](https://github.com/umikado/vintage-samplerCD-extractor) does, and it inherits a filesystem reader that is correct across many more discs than ours. Rejected on the install story and the seam. It needs a C toolchain at install time, which turns `uv tool install` into a build; it needs a license review before vendoring; and the container work — the genuinely novel part — still has to be written in Python and materialised to a temp ISO before akaiutil can see it. That leaves a project that is half ours, half vendored, with the boundary running straight through the interesting layer.

**Depend on `libmirage`/CDEmu for containers.** Handles MDS and NRG properly and is well tested. Rejected: a GObject-based C library is a heavy and platform-awkward dependency for a tool whose entire job is reading bytes out of a file, and it does not read compressed `.mdx` either — the one thing that most needed writing.

## Consequences

**Good.** `uv tool install samplerdisc` and it works, on any platform, with no compiler. The whole codebase is inspectable by the people most likely to want to extend it. Adding a manufacturer is a Python module.

**Bad.** We own correctness for every format variant, and akaiutil has a fifteen-year head start on the odd ones. A disc that uses an AKAI variant we do not parse gets nothing from us.

**Mitigated by** [ADR-0009](0009-export-iso-escape-hatch.md): `export-iso` unwraps the container and hands the result to akaiutil, so the coverage gap costs a step rather than the disc. akaiutil also stays the oracle we diff against in testing.
