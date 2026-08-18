<!-- One deliverable per branch, one issue per deliverable. The issue is the spec. -->

Closes #

## What this changes



## Which layer

<!-- Keep the layers independent. Tick what this touches. -->

- [ ] `container/` — sectors in, flat 2048-byte sectors out (no sampler knowledge)
- [ ] `fs/` — a sampler filesystem
- [ ] `sample/` — a sample format
- [ ] `docs/` only

## Checklist

- [ ] No disc images or extracted audio added (CI enforces this; see [ADR-0008](docs/adr/0008-no-media-in-the-repo.md))
- [ ] New format constants are documented in `docs/formats/` and asserted in a test
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run pytest -q` passes
- [ ] `uv tool install --editable . && samplerdisc --version` works
