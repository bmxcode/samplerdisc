# ADR-0008 · No disc images or extracted audio in the repository, ever

**Status:** accepted · 2026-08-18

## Context

Development happens against three commercial sample libraries totalling 1.6 GB, sitting in the working directory. The repository is public. Git history is exposed retroactively — a commit removed later is still in the history, and still there when someone clones.

The pull toward committing media is constant and reasonable-sounding. Regression tests want a real disc. A 200 KB slice of a real image would make the MDX block-chain test far more convincing than a synthetic one. It is small, it is a fragment, nobody would mind.

It is still copyrighted audio from a commercial product, and it is still permanent.

## Decision

No disc image, image fragment, or extracted audio is ever committed. `.gitignore` covers every image and audio extension — `*.mdx *.nrg *.iso *.img *.bin *.cue *.mds *.mdf *.cdr *.tao *.wav *.aif *.aiff` — and `out/` and `discs/`, from the first commit, before there was anything to ignore.

Test fixtures are **synthetic and constructed in code**: a handful of DEFLATE blocks assembled by the test, a partition header written field by field. Tests that need a real disc read `SAMPLERDISC_TEST_DISCS` and skip when it is unset.

## Alternatives rejected

**Commit a small fragment as a fixture.** Genuinely better tests — the real thing exercises the real edge cases, including the ones nobody thought to synthesise. Rejected: a fragment of a commercial library is still a fragment of a commercial library, size is not a defence, and this is the single commit that cannot be taken back. Synthetic fixtures cover the mechanics, and the constants in [docs/formats/](../formats/) carry what the real discs proved.

**Keep the repo private until it is clean.** Just defers the same commit, and history is exposed retroactively when it flips. The rule has to hold from the first commit or it does not hold.

**Git LFS or a separate media repo.** Same copyright problem with more machinery.

## Consequences

**Good.** The repo can be published at any moment with no audit. CI needs no fixtures and stays fast. Contributors run the full suite with their own discs.

**Bad.** CI cannot verify the constants in `docs/formats/`; only a developer with the discs can. The disc-backed tests are the ones most likely to rot unnoticed.

**Mitigated by** naming the reference discs and their exact sizes in [docs/formats/README.md](../formats/README.md), so anyone with the same images can confirm they have the same bytes.

**Watch for.** `git add -A` in a working directory that holds the discs. `.gitignore` is what makes that safe, which is why it was the first file written.
