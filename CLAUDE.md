# samplerdisc — working notes

Reads vintage sampler CD-ROM images and writes their samples out as uncompressed WAV. [README.md](README.md) has the problem and the idea; [docs/architecture.md](docs/architecture.md) has the shape.

## Read before changing anything

- [docs/README.md](docs/README.md) — reading order for a new session. Start there, not here.
- [docs/formats/](docs/formats/) — **what the bytes mean.** This is the expensive knowledge in the project and it is invisible in the source once written. Read the doc for the format you are touching before you touch it.
- [docs/adr/](docs/adr/) — every decision already made, each with the alternative rejected. **Don't relitigate them.** If one looks wrong, say so — don't quietly work around it.

## The idea

A disc image is three independent problems stacked, and keeping them independent is the whole design.

**A container** wraps sectors — `.mdx`, `.nrg`, `.bin`, `.iso`. It knows about compression, sector geometry and pregaps, and nothing whatsoever about music. **A filesystem** sits inside those sectors — AKAI, ISO 9660, one day E-mu and Roland. **A sample format** sits inside a file. Every manufacturer mixes and matches: an AKAI library ships as `.mdx` on one site and `.nrg` on another, and an E-mu disc arrives in the same containers as an AKAI one. Solve each layer once and the combinations come free.

## Rules

**Never commit disc images or extracted audio.** These are commercial sample libraries, this repo is public, and git history is exposed retroactively — one such commit is permanent and surfaces the day someone looks. `.gitignore` covers every image and audio extension from the first commit, because a rule that depends on discipline at the moment of commit is the rule that fails. Test fixtures are synthetic and built in code; real discs are reached through `SAMPLERDISC_TEST_DISCS` and those tests skip when it is unset. ([ADR-0008](docs/adr/0008-no-media-in-the-repo.md))

**Format knowledge lives in `docs/formats/`, with a constant verified against a real disc.** A magic number in the source with no doc reference is a bug, even when it works. The tests assert the same constants the docs claim, so the two cannot drift apart quietly.

**`container/` may not know what a sampler is.** No AKAI constant, no sample-header check, no brand name. Brand knowledge lives in `fs/` and `sample/`. This separation is the reason a second manufacturer is one new module and nothing else. ([ADR-0003](docs/adr/0003-brand-neutral-pluggable-backends.md))

**Never assume the filesystem starts at byte 0.** A Nero image of an AKAI disc puts 150 sectors of zeroed pregap in front of it. Ask the container where its track starts, then probe for the filesystem — never assume. This one cost real debugging time and reads as an empty disc when you get it wrong, not as an error. ([ADR-0005](docs/adr/0005-probe-for-the-filesystem-origin.md))

**Detect by signature, not by extension.** These files come off archive.org and personal FTPs with whatever name someone typed. ([ADR-0004](docs/adr/0004-detect-by-signature.md))

**Damaged input degrades, never crashes.** Many of these rips have tail damage or a truncated last block. Skip the entry, log why, keep going — a disc that yields 400 of 420 samples is a good outcome and a traceback is not.

**Write each markdown paragraph as a single line.** No hard wrapping at a column. Hard-wrapped prose makes a one-word edit reflow the paragraph, so the diff hides the actual change inside a block of noise.

## Where this sits

**The deliverable is WAV that works anywhere** ([ADR-0011](docs/adr/0011-the-deliverable-is-daw-ready-wav.md)). The point is to free these sounds from the hardware they were trapped in — not to move them into a different sampler's format. No SFZ, no MPC keygroups, no DecentSampler. Loop points and root key go into the WAV's own standard `smpl` chunk, which any DAW may read and any may ignore.

[ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss) is the tool for anyone who does want a playable multisample instrument, and it is better at that than we will ever be. Point people at it; `export-iso` feeds it. The layer that is genuinely ours is the container: compressed `.mdx`, `.nrg` and raw `.bin` are what neither it nor akaiutil opens.

## Working

One deliverable per branch (`d1-containers`, `d2-akai-fs`), one GitHub issue per deliverable — the issue is the spec. PR body says `Closes #<issue>`. Don't push to `main`.

## Verify

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv tool install --editable . && samplerdisc --version
```

CI runs all four. The last one matters on its own: a passing test suite and a working installed entrypoint are not the same thing, and that gap is where a broken `bin` hides.

System Python here is 3.9; the project needs ≥3.11. Always go through `uv`, never bare `python3`.

## Layout

```
src/samplerdisc/
  container/   sectors in, flat 2048-byte sectors out — no sampler knowledge
  fs/          one module per sampler filesystem, behind a common Backend
  sample/      one module per sampler sample format
  wav.py stereo.py cli.py
tests/         synthetic fixtures; real-disc tests are opt-in and skip by default
docs/formats/  what the bytes mean
docs/adr/      one record per contested decision
```
