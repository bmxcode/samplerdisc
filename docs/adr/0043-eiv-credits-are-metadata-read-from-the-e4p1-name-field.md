# ADR-0043 · E-IV credits are metadata, read from the `E4P1` name field alone

**Status:** accepted · 2026-09-05 · relates to [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md), [ADR-0032](0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md)

## Context

[ADR-0032](0032-read-the-eiv-form-e4b0-bank-and-its-embedded-samples.md) reads the audio of 162 of the 170 E-IV `FORM/E4B0` banks. The remaining eight carry a `FORM` with `TOC1`, `E4Ma` and `E4P1` chunks and **no `E3S1` sample chunk**, and are noted `the bank holds presets or text and no samples; listed only`. That note is accurate about audio, but these banks are not empty of information: they carry human-readable **disc provenance** — author, house, contact, thanks — one line per `E4P1` preset's 16-byte name field. Four are named `Credits` (Producer Series Vol. 3, 4, 5 and 8-CD2) and four are byte-identical `E-mu Systems 96` contact cards on `eiv-studio`. [Issue #53](https://github.com/bmxcode/samplerdisc/issues/53), spun off from #44/PR #52.

The `E4P1` chunk is the same structure that holds the key ranges, envelopes and root key on every *sample* bank — the preset [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md) deliberately leaves to [ConvertWithMoss](https://github.com/git-moss/ConvertWithMoss). So reading anything from an `E4P1` needs a line drawn, or it becomes the thin end of preset parsing. And the output is text, not audio, so it cannot ride in a WAV — it is a new kind of output for this project.

Verified against the discs (`docs/formats/emu3.md`, "A `FORM` with no `E3S1` chunk"): the narrow definition — *a `FORM/E4B0` bank with no `E3S1` chunk and at least one `E4P1` chunk* — catches **exactly eight banks, 89 lines**, and nothing that carries audio. The name field sits at chunk-body `+2`, 16 bytes, exactly where a sample record's name sits, so the existing `decode_name`/`is_plausible_name` read it verbatim.

## Decision

**Read the `E4P1` name field — the 16 bytes at chunk-body `+2` — and only from a `FORM/E4B0` bank that carries no `E3S1` sample chunk. Write the lines to a per-disc `Credits.txt` sidecar at the extract root, under a dedicated `--metadata` flag.**

Three boundaries make this metadata rather than preset parsing, and each is load-bearing:

- **Only the name field.** The 284-byte voice blocks, the 22-byte zone entries, the key ranges, root key, pan and envelopes are never read. A label is not the instrument definition.
- **Only a sample-free text bank.** An `E4P1` inside a bank that carries audio is a real preset and is left untouched. The `Credits` and `E-mu Systems 96` banks are the whole population, identified structurally (no `E3S1` chunk), not by matching their names.
- **Text, not a sampler format.** The output is a plain `Credits.txt`, byte-identical sections collapsed, headed by the bank name. It is the same "carry what the disc knows" bargain [ADR-0025](0025-the-loop-is-decoded-the-root-key-is-not.md) made for loops, one field narrower — not an instrument, and not a WAV chunk, because it is not about a sample.

This does not reopen [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md): its watch-for — "an SFZ exporter because the key ranges are right there" — is exactly what the first boundary forbids. The credits are a disc's byline, and freeing them from the hardware is the same goal as freeing its samples.

## Alternatives rejected

**Read the `TOC1` chunk's concatenation instead.** `TOC1` holds the multimap name and a run of the same lines joined together. Rejected: the per-`E4P1` name field is the clean, per-line source, self-delimited at 16 bytes; `TOC1` is a redundant concatenation with no line breaks, and parsing it back into lines is guesswork the `E4P1` fields make unnecessary.

**Dump every disc's TOC and preset names as a provenance file.** The broad reading of #53. Rejected as scope creep and the thin end this ADR exists to prevent: it would read `E4P1` names from all ~900 *sample* banks' presets on `eiv-studio` alone, which is preset parsing wearing a metadata hat. The narrow cut — the named text banks, identified by having no sample chunk — is the safe line.

**Fold the sidecar into `--keep-originals`.** Smaller CLI surface, and the "content a WAV can't hold" rationale is shared. Rejected: `--keep-originals` means *byte-for-byte original files* — the `.exs`, `.krz`, AKAI program — and a derived text digest is a different thing. Keeping the flags distinct keeps each one's meaning exact.

**Always write `Credits.txt` when a disc has text banks.** The credits are lossless, tiny and genuinely useful, so an always-on emit is defensible. Rejected to stay conservative and match #53's opt-in framing: a new output kind is opt-in until asked for, and the flag costs a user one word.

**Carry the credits in a WAV `LIST`/`INFO` chunk.** The project already writes RIFF metadata chunks. Rejected: there is no WAV to attach them to — the bank has no audio — and the provenance is a disc-level fact, not a per-sample one.

## Consequences

**Good.** Eight banks across five discs, 89 lines, become a readable `Credits.txt`: who sampled the disc, who programmed it, and how to reach the publisher. It is on the disc, it is lost when the disc is, and it costs a text file a user asks for.

**Good, and asserted.** The change is additive to the audio path by construction — `volumes()` reads the `E4P1` names only where a FORM bank already yielded no samples, and the sidecar is written after the volume loop. The disc-backed suite pins the audio counts, loops, stereo and per-payload digests as before, and they are unchanged; `test_emu3_credits_text_banks_carry_disc_provenance` pins the eight-bank corpus, and a synthetic test holds the line that a sample bank's `E4P1` presets are not read.

**Bad.** The line is drawn by discipline, not by the format: nothing stops a later change from reading one more `E4P1` field "while it is right there", which is the preset parsing this ADR refuses. The watch-for is the same as [ADR-0011](0011-the-deliverable-is-daw-ready-wav.md)'s, at one more remove.

**Watch for.** A disc that writes provenance in a bank that also carries audio, or in a chunk other than `E4P1` — this reader would miss it, silently, because it only looks at sample-free banks' `E4P1` names. None in the collection does. And `--metadata` reads only E-mu E-IV today; another backend with disc-level text would surface it through the same `Volume.credits` channel, not a second flag.
