# ADR-0042: A loose `.ebl` bank is converted as a source, reversing the refusal to serve bare bank folders

**Status:** accepted

## Context

The `.EBL` decoder is now verified beyond doubt. ADR-0033 shipped it against a disc's render, ADR-0041 added the stereo interleave, and both were checked byte-for-byte against the publisher's own renders across four banks. What the decoder eats is a single file's bytes -- `emu_ebl.parse(payload)` -- and where those bytes come from has never mattered to it.

Where they come from mattered to the *project*, twice, on purpose. [ADR-0033](0033-ebl-is-converted-on-a-disc-and-verified-by-a-render.md) rejected "converting bare `.exb` folders", and [ADR-0041](0041-stereo-ebl-is-interleaved-and-verified-by-the-render.md) rejected "open a loose-`.exb` bank mode", both on the same ground: *"Serving bare bank folders is the source-6 trap ADR-0033 part 4 refused ... the container layer stays the reason this tool exists."* Those refusals were correct in their context. The loose banks in play then were mattetti's renders and the `emuexbsoundbanks` archive -- **validation inputs**, reached only to check the on-disc decoder against a render. Building a whole ingest mode to reach a test fixture is backwards; a render already served the doubt, and the tool's identity is the container layer (compressed `.mdx`, `.nrg`, raw `.bin`) that neither ConvertWithMoss nor akaiutil opens.

The premise has now changed in the one way that matters. archive.org's `e-mu-sample-sets` ships **Proteus 1/2/3** as loose `.exb` + `SamplePool/*.ebl` **in the clear** -- 686 banks a user actually holds and wants as WAV, with no disc image anywhere and no installer to unpack (contrast `e-mu-sound-central-esc`, whose "Emulator X ISO" entries are InstallShield CDs with the payload sealed in `Setup/data2.cab` -- *that* is still the source-6 trap, and this is not it). The files are right there, byte-identical to what a `SamplePool` on a disc would hold, and the verified decoder reads them already. The only thing between them and a WAV is the tool's insistence that input arrive wrapped in a container it can strip.

## Decision

**Convert a loose `.ebl` bank through a dedicated source that runs the existing `emu_ebl` decoder unchanged. A directory of sample files in the clear is a *source*, not a container or a filesystem.**

- **Loose files are not forced through the container→filesystem→sample stack.** For a disc that stack earns its place: a container strips compression and sector geometry, a filesystem finds the files. For a directory of `.ebl` the operating system's own filesystem has already done both -- there is no compression, no sectors, no on-disc directory to parse. A new `banks` module walks the tree for `*.ebl`, reads each file's bytes, and hands them to `extract.ebl_to_wav`, the same decode-and-write path the ISO 9660 backend now calls. No synthetic `SectorImage`, no `Backend` (see Rejected).
- **The output mirrors the disc path.** Each sample is named from its own 64-byte header (`EP4MKIIL A0`), not the meaningless `Proteus 1SL001.ebl` filename, and grouped under its bank name -- the parent of `SamplePool`, not the pool. Mono and stereo both convert on the verified rules; the loop rides the `smpl` chunk.
- **Only `.ebl` sample files are read. The `.exb` is left alone**, exactly as the on-disc `.exb` and the E-IV/EXS24 presets are: it holds the keygroups and zones, which are ConvertWithMoss's job, not ours (ADR-0011). Ignoring it needs no special case -- the walk matches `.ebl` and nothing else.
- **A dedicated CLI verb, `extract-banks <dir> <out>`, not an overload of `extract`.** `extract`/`info`/`list` speak of a container and a filesystem and print sector geometry; a loose bank has none of that, so overloading their `image` argument would make them describe a disc that is not there. `batch` also discovers loose-bank trees, so a mixed or bank-only directory converts in one pass and lands in the manifest (`container: loose-ebl`, `filesystem: none`).
- **Verification is the decoder's, plus a real-tree smoke test.** The bytes are proven by the same render oracles ADR-0033/0041 wired in; nothing about reading a file off disk instead of out of a sector changes them. A gated `tests/test_discs.py` case (`SAMPLERDISC_LOOSE_EBL`) runs the whole Proteus tree and asserts every bank is discovered, converted to a WAV that exists, and none refused. Synthetic `tests/test_banks.py` covers discovery, grouping, the `.exb` being ignored, and a corrupt `.ebl` degrading to a skip.

## Rejected

**Keep refusing, because the container is the reason this tool exists.** This was ADR-0033 part 4 and ADR-0041's third rejection, and it was right when the loose banks were test fixtures. It is wrong now for content the user holds: declining to convert files the verified decoder already reads, purely because they did not arrive inside a container, serves no one and leaves 686 banks unread. The container layer is still what is *genuinely ours* -- loose banks add breadth on a format already shipped, they do not turn the project into a format hub (SF2/SFZ/Kontakt stay out, ADR-0011). The identity claim survives; the blanket refusal does not.

**Model the directory as a `Backend` over a synthetic `SectorImage`.** This would honour the three-layer shape literally -- a "container" that serves file bytes, a "filesystem" that lists the directory. But the layers would carry nothing: no compression to undo, no geometry, no on-disc structure to read. It is architecture cosplay -- ceremony that makes the code look like the disc path without doing any of the disc path's work -- and it would put brand-neutral machinery (`container/`) in the business of walking an OS directory, which is not its job (ADR-0003). A source that calls the decoder directly is smaller and honest about what is happening.

**Overload `extract` to accept a directory.** Detecting a directory and branching inside `extract` keeps one verb, but `info` and `list` would still have to answer for a disc that is not there, and the `image` positional documented as a disc image would sometimes mean a folder. A named verb says what it does.

## Consequences

**Good.** The 686 Proteus banks convert -- 685 mono and one genuinely-stereo `Snare w/Verb 28K`, zero refused -- and any future library shipped as loose `.ebl` in the clear converts with no new code.

**Good.** The container's separation from the sample layer paid off exactly as ADR-0003 intended: the decoder moved to a second, container-less source without a line of change, because it never knew where its bytes came from.

**Neutral.** The disc EBL path is unchanged; `_convert_ebl` now reads its bytes off the disc and calls the shared `ebl_to_wav`, the same function the loose source calls.

**Watch for.** The one Proteus stereo file has **no render to check its interleave against** -- Proteus 1 is not among mattetti's rendered banks. It is classified stereo by the `V12` channel byte, the signal ADR-0041 verified against 636 stereo files on four other banks, and interleaved by that ADR's end-anchored rule; but this specific file's interleave rests on the rule, not on its own oracle. That is borrowed evidence of the kind ADR-0025 names elsewhere, and it is recorded here rather than hidden: a Proteus render, should one surface, would settle it.
