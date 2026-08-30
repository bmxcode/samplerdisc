# ADR-0033: E-mu `.EBL` is converted when a disc carries it, and one disc is enough because a render checks it

**Status:** accepted

## Context

`Digital Sound Factory - E-MU Vintage Pro.bin` reads cleanly all the way down -- `rawcd` container, `iso9660` filesystem, a volume of 1 062 files -- and then extracted **nothing**. The files are `.EBL`: E-mu Emulator X sample banks, an ordinary file format inside an ordinary ISO 9660 disc, which no `sample/` backend read. It is the disc the README counts among the ones that do not convert.

`.EBL` is the third layer of the design and nothing more: a sample format inside a file (ADR-0003). It is not the `EMU3` filesystem (D12) -- that is a hardware sampler's own on-disc layout; this is written by E-mu's Windows software sampler and sits inside a normal filesystem. So it lands in one new module, `sample/emu_ebl.py`, wired into the ISO 9660 path exactly as `sample/aiff.py` is, and the deliverable is DAW-ready WAV and nothing else (ADR-0011).

Two things stood in the way of just building it.

**The evidence is one disc.** This project's rule is a constant verified against a real disc, and its instinct is more than one specimen before a format's shape is committed. There is exactly one EBL *disc*, and the search for a second is exhausted: the archive item that looked like a source of them turned out to be InstallShield installer CDs with the banks locked inside `Setup/data2.cab` -- no `.EBL` in the clear -- plus a byte-identical duplicate of the disc already in hand. The loose-bank sources (a 5.5 GB archive of `.exb`, and mattetti's input folder) are not discs.

**Serving loose banks is a trap.** Point the tool at a folder of bare `.exb`/`.ebl` and it becomes a general format converter with the container layer contributing nothing -- the precise scope creep [ADR-0010](0010-build-the-instrument-layer-ourselves.md) names. Emulator X banks already live on a PC and a working X-3 install exports them; the rescue argument that justifies this project is weak for them.

## Decision

**Convert `.EBL` when a disc carries it, through the normal `list`/`extract`/`batch` path. Ship the mono case, which one disc plus a render establishes completely. Refuse stereo with a reason. Do not build a bare-bank converter.**

Four parts.

**1. One disc is enough here, because a render supplies what a second disc would.** The reason to want two specimens is to prove a decoder *understood* the bytes rather than copying a shape that happens to work once ([ADR-0024](0024-the-aiff-twin-is-converted-and-deduplicated.md) makes this argument for AIFF). What proves understanding is not a second disc but an independent statement of the right answer. We have one: mattetti's [e-mu-soundbanks](https://github.com/mattetti/e-mu-soundbanks) rendered the entire Vintage Pro bank to FLAC, and every one of the disc's 1 007 uniquely-named samples decodes to that render's rate and PCM **byte for byte** (the 4 that do not are names the disc uses twice, which no render can disambiguate). The format is independently corroborated at ~42 000 files across two implementations besides. This is the [ADR-0024](0024-the-aiff-twin-is-converted-and-deduplicated.md) oracle, one step removed: a render of the same disc rather than a twin on it. See [formats/emu-ebl.md](../formats/emu-ebl.md).

**2. The record is read, not assumed.** The rate varies wildly -- 282 distinct values on one bank, 44 100 among only 27 of 1 061 files -- so it is read from the data-description block. The audio offset is computed by walking the variable-width header, not hardcoded, and the mono length is the `V4 − V3 + 2` the header states, which is what the render agrees with. A hardcoded rate or offset would be a magic number the disc contradicts.

**3. Stereo is refused, not guessed.** The format stores stereo non-interleaved (`LLLL…RRRR`), and stereo `.EBL` exist in other banks. But every file on the one disc in hand is mono, and no stereo `.EBL` is available paired with a render to check an interleave against. Converting one by an unverified rule would write audio that opens, plays as noise, and reports nothing wrong. So a stereo record is skipped with a reason (ADR-0026: the record declares the channel count), and its support waits for a specimen with an oracle. On this disc that costs nothing -- zero files.

**4. On a disc only.** No mode that points at a loose `.exb`/`.ebl` folder. Bare banks are pointed at [ebl-reading](https://github.com/misaim/ebl-reading), the way instruments are pointed at ConvertWithMoss (ADR-0009, ADR-0010). The container layer stays the reason this tool exists.

## Rejected

**Wait for a second EBL disc before committing.** None is findable, and it is not what the doubt actually needs: a second disc would show the format is stable, and the render shows the decoder is *right*, which is the stronger fact and the one a lone specimen was said to lack. Deferring would leave 1 061 samples unread to satisfy a rule whose purpose a render already serves. This is the same call ADR-0024 made in rejecting "wait for a second publisher's discs."

**Convert bare `.exb`/`.ebl` folders too.** The real fork, and the source-6 trap: it makes the container layer dead weight and turns the tool into a format hub (ADR-0010). Rejected so it is not relitigated the next time someone has a folder of banks.

**Ship the stereo interleave anyway, faithful to the reference implementation.** The reference works across 42 000 files, so the layout is known. But *our* output would be checked by nothing -- no stereo-in / known-good-out pair exists -- and an L/R swap is invisible until someone listens. Skipping with a reason is honest; shipping an unverified conversion is the failure this project guards against everywhere else.

**Hardcode the audio offset at `0x128`.** It is correct for all 1 061 Vintage Pro files, and it is a magic number the format contradicts: another bank starts its audio at `0x124`. The header is variable-width and declares where the audio is, so it is walked. A constant that holds on one disc and silently corrupts the next is exactly what the "verified against a real disc" rule exists to prevent.

## Consequences

**Good.** Vintage Pro goes from 0 WAV to 1 061, each named from the sample's own header (`EP4MKIIL A0`) under its bank folder rather than from the meaningless ISO sequence, with loop points carried where the file has them. `sample/emu_ebl.py` is the whole change; the ISO 9660 backend already found the files.

**Good.** The mono decoder is pinned to the render in `tests/test_discs.py` -- the second thing in this project, after AIFF, checked against an independent answer rather than against the bytes it came from.

**Bad, accepted.** Stereo `.EBL` on some future disc will be skipped, not converted, until a specimen and an oracle exist. The gap is named in [formats/emu-ebl.md](../formats/emu-ebl.md) and in [#57](https://github.com/bmxcode/samplerdisc/issues/57), with the render outputs already located, so picking it up is verification and interleaving, not rediscovery.

**Watch for.** A request to point `extract` at a loose bank folder. That is decision part 4 being reversed, and the container layer becoming optional is the signal.
