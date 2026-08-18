# Contributing to samplerdisc

Thanks for helping preserve these sounds. This project reads vintage sampler CD-ROM images and writes their samples out as uncompressed WAV. Before you change anything, read [docs/README.md](docs/README.md) — it is the reading order for the project — and the format doc under [docs/formats/](docs/formats/) for whatever layer you are touching.

## The shape of the project

A disc image is three independent problems stacked, and keeping them independent is the whole design. A **container** (`.mdx`, `.nrg`, `.bin`, `.iso`) wraps sectors and knows nothing about music. A **filesystem** (AKAI, ISO 9660, …) sits inside those sectors. A **sample format** sits inside a file. Solve each layer once and the combinations come free. See [docs/architecture.md](docs/architecture.md) and the [ADRs](docs/adr/) for the decisions already made — don't relitigate them; if one looks wrong, say so in an issue rather than quietly working around it.

## Ground rules

- **Never commit disc images or extracted audio.** These are commercial sample libraries and this repo is public. `.gitignore` and CI both enforce this ([ADR-0008](docs/adr/0008-no-media-in-the-repo.md)); real discs are reached through the `SAMPLERDISC_TEST_DISCS` environment variable and those tests skip when it is unset. Test fixtures are synthetic and built in code.
- **`container/` may not know what a sampler is.** No brand constants there; brand knowledge lives in `fs/` and `sample/` ([ADR-0003](docs/adr/0003-brand-neutral-pluggable-backends.md)).
- **Format knowledge lives in `docs/formats/`, with a constant verified against a real disc.** A magic number in the source with no doc reference is a bug, even when it works.
- **Detect by signature, not by extension** ([ADR-0004](docs/adr/0004-detect-by-signature.md)), and **never assume the filesystem starts at byte 0** ([ADR-0005](docs/adr/0005-probe-for-the-filesystem-origin.md)).
- **Damaged input degrades, never crashes.** Skip the bad entry, log why, keep going. A disc that yields 400 of 420 samples is a good outcome; a traceback is not.
- **Write each markdown paragraph as a single line.** No hard wrapping at a column — it makes one-word edits reflow the whole paragraph and hides the real change in the diff.

## Setup

System Python is often older than this project needs. Always go through [uv](https://docs.astral.sh/uv/) (`requires-python >= 3.11`), never bare `python3`.

```bash
uv sync --all-extras --dev
```

## Verify before you push

CI runs all four of these, and the last one matters on its own — a passing test suite and a working installed entrypoint are not the same thing.

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv tool install --editable . && samplerdisc --version
```

## Workflow

- One deliverable per branch (`d1-containers`, `d2-akai-fs`), one GitHub issue per deliverable — the issue is the spec.
- Branch off `main`; don't push to `main` directly.
- Open a pull request with `Closes #<issue>` in the body.
- Keep the PR green: CI must pass before merge.

## Reporting a disc that won't read

Open an issue with the container type (`.mdx`, `.nrg`, `.bin`, …), where the image came from, the exact command you ran, and the full output. If a specific volume or sample fails, name it. Never attach the disc image or any extracted audio — a description of the failure is what we need, not the library.
