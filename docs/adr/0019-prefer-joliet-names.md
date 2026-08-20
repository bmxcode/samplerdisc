# ADR-0019: Prefer Joliet names over the ISO 9660 short names

**Status:** accepted

## Context

`Digital Sound Factory - E-MU Vintage Pro.bin` lists 1 062 files under 1 002 distinct paths. Sixty-one of them, all different sizes, come back as `VINTAG~0.EXB/SAMPLE~0/VINTA~1000.E`.

The parsing was faithful: those are the names on the disc. MagicISO v5.2 caps a short name at twelve characters in total and lets the `~N` counter eat the extension, so every index from 1000 upward masters as the same twelve bytes. **8.3 mangling is not injective**, and this disc depends on that being someone else's problem.

The disc also carries a Joliet supplementary descriptor — UCS-2, `%/E` — whose root describes the same extents under `Vintage Pro.exb/SamplePool/Vintage ProSL001.ebl` and so on, all 1 062 distinct. So does `BSBSSD2.bin`, the only other ISO 9660 disc in the collection. Neither carries Rock Ridge. The information was there the whole time; we were reading the wrong descriptor.

Nothing is currently lost, because `.EBL` has no converter and the disc extracts zero files. The moment `.EBL` support lands, sixty-one samples arrive wearing one name.

## Decision

**Where a disc carries a Joliet supplementary descriptor, walk its tree. Otherwise walk the primary.** One name space per volume, chosen at the root, never merged.

Where there is no Joliet, report the primary names exactly as the disc stores them, collisions and all. Uniqueness of *output paths* is extraction's job — `unique_path` already guarantees it — and inventing a unique name in the directory listing would put a path in front of the user that is not on the disc.

## Rejected

**Keep reading the primary tree and de-duplicate the names.** Fixes the file count and nothing else. `VINTA~1000.E_37` is not a name, and the real one — with its case, its spaces and its extension — was on the disc the whole time. It also leaves the volume label wrong.

**Merge the two trees, primary for structure and Joliet for names.** They describe identical extents, so there is nothing to gain and a second failure mode to invent: a disc where the two disagree would be reconciled by rules nobody has ever tested.

**Read Rock Ridge as well.** Neither disc has it — every directory record on both ends at its name, with no system-use bytes at all. Support for a thing no available disc exercises is support that is wrong the first time it matters. If a disc turns up with Rock Ridge and no Joliet, that is when to write it.

**Take names from the payload instead.** An `.EBL` carries its own 16-character name at file offset 34, which is the better *display* name — but only 1 057 of Vintage Pro's 1 061 are distinct, so it cannot be the path. It is also per-format knowledge, and `fs/iso9660.py` may not know what an `.EBL` is ([ADR-0003](0003-brand-neutral-pluggable-backends.md)).

## Consequences

Names on both ISO 9660 discs change: correct case (`Samples/` not `SAMPLES/`, `.nki` not `.NKI`) and, on Vintage Pro, correct names at all. `BSBSSD2` extracts byte-for-byte identically to before — its short names were already unique and already carried the same stems — so the change is visible in listings and inert in output there.

The volume label comes from the chosen descriptor and stops at the first NUL. Vintage Pro is now `VintagePro`; it was `VintagePro 57`, which read two stray bytes of its volume set identifier past the terminator.

`docs/formats/iso9660.md` records the layout and the measured numbers.
