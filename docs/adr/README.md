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
| [0010](0010-build-the-instrument-layer-ourselves.md) | ~~Build the instrument layer ourselves~~ *superseded by 0011* | Handing off to ConvertWithMoss; containers-only scope |
| [0011](0011-the-deliverable-is-daw-ready-wav.md) | The deliverable is DAW-ready WAV, not a sampler format | Building SFZ/MPC export; plain WAV with no metadata |
| [0012](0012-a-probe-must-confirm-a-file.md) | A probe must confirm a file, not a plausible directory | A stricter header heuristic; scoring candidate offsets |
| [0013](0013-cueless-audio-is-reported-not-guessed.md) | Cue-less audio is reported; extracted only on request | Silent refusal; automatic whole-disc WAV; splitting on silence |
| [0014](0014-one-backend-per-on-disc-format.md) | One backend per on-disc format, named after the format | One per manufacturer; per marketing generation; per model |
| [0015](0015-locate-banks-by-signature.md) | ~~Locate E-mu banks by signature; list what cannot be read~~ *superseded by 0020* | Hunting for the allocation unit; guessing the E-IV interior |
| [0016](0016-the-s7xx-hierarchy-is-located-not-walked.md) | The S-7xx object hierarchy is located, not walked | Walking volume→…→sample to group; grouping by name prefix |
| [0017](0017-the-stereo-side-marker-is-a-character-class.md) | The stereo side marker is a character class | A per-backend hook; renaming Roland to AKAI's spelling; an optional separator |
| [0018](0018-the-s7xx-sample-rate-is-measured.md) | The S-7xx rate is 44 100 by measurement, not by a field | Refusing to extract; a `--rate` override; per-sample pitch inference |
| [0019](0019-prefer-joliet-names.md) | Prefer Joliet names over the ISO 9660 short names | De-duplicating the short names; merging the two trees; Rock Ridge; naming from the payload |
| [0020](0020-read-e-iv-through-its-sample-directory.md) | Read E-IV through its `E3S1` sample directory | Waiting for a fourth disc; arithmetic on `start`; a signature walk; an `EMU4` backend; ~~a stereo channel count~~ *overturned by 0025* |
| [0021](0021-a-bank-owns-the-run-its-header-declares.md) | An EIII/ESI bank owns the record run its own header declares | Bounding by the directory's `length`; deduplicating headers by address; dropping repeated names; listing the `4k` banks with a note; a looser header match |
| [0022](0022-a-volume-is-explained-by-the-allocation-map.md) | An AKAI volume's emptiness is explained by the partition's allocation map | Rejecting type 0; requiring the directory to parse; using the map as an allocation flag; recovering the displaced directories; calling the damage in the note |
| [0023](0023-partitions-come-from-the-table-the-disc-declares.md) | An AKAI disc's partitions come from the table it declares | Tiling at multiples of the first size; chaining each header's own size; locating headers by signature; walking partitions in the probe; rewriting block numbers as disc-relative; nesting extraction only where a disc has several |
| [0024](0024-the-aiff-twin-is-converted-and-deduplicated.md) | Convert AIFF, and drop the twin only when it says nothing new | Writing both trees; never converting; deduplicating by name; preferring the AIFF; merging its metadata into the copied WAV; calling the byte swap a conversion |
| [0025](0025-the-loop-is-decoded-the-root-key-is-not.md) | The E-mu loop is decoded from the record; the root key is not there to decode | Deriving the root key from the sample name; no `smpl` chunk without a root key; clamping the loop end as AKAI and Roland do; emitting the second channel's loop as well; trusting the declared extent over the record length |
| [0026](0026-the-record-declares-the-channel-count.md) | The E-mu record declares the channel count, and its own extents confirm it | Splitting on the channel count alone; writing the mono halves alongside; filing it under `stereo/`; deciding stereo from the audio; taking high-correlation one-channel records as stereo; splitting at `end_L`; writing two mono files |
