# Decision records

One record per decision where a real alternative was rejected. An ADR is about *why*, and it is immutable once accepted — superseded, never edited.

If you find yourself writing an ADR with no rejected alternative, you are writing documentation. Put it in [../formats/](../formats/) or [../architecture.md](../architecture.md) instead.

| # | Decision | Rejected |
|---|---|---|
| [0001](0001-pure-python-stdlib-only.md) | Pure Python, stdlib only | Vendoring akaiutil; depending on libmirage |
| [0002](0002-mit-license.md) | MIT | GPL-3.0; Apache-2.0 |
| [0003](0003-brand-neutral-pluggable-backends.md) | Brand-neutral name, pluggable `fs/` backends | `unakai`, AKAI-only |
| [0004](0004-detect-by-signature.md) | Detect containers by signature | Extension dispatch with a `--format` override |
| [0005](0005-probe-for-the-filesystem-origin.md) | Probe for the filesystem origin | Assuming byte 0; scanning for AKAI specifically |
| [0006](0006-mdx-blocks-classified-by-decode-attempt.md) | MDX blocks classified by decode attempt + consumed-length guard | Hunting for a block index; inflate-and-catch alone |
| [0007](0007-emit-mono-and-stereo.md) | Emit mono originals *and* joined stereo | Stereo-only; mono-only |
| [0008](0008-no-media-in-the-repo.md) | No disc images or audio in the repo, ever | A small committed fixture slice; private-until-clean |
| [0009](0009-export-iso-escape-hatch.md) | `export-iso` as an escape hatch | Failing on unrecognised filesystems; auto-running akaiutil |
