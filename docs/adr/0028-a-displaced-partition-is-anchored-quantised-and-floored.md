# ADR-0028 · A displaced AKAI partition is searched for from its declared position, in the container's unit, and never inside one already read

**Status:** accepted · 2026-08-22 · *amends [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md): "a declared position with no header is skipped, never searched for" becomes "searched for backwards, under three constraints". What ADR-0023 refused was a free signature scan, and it was right to; the evidence that changed is below.*

## Context

Eight of the 44 AKAI images are **short of the disc they were made from**. The container is faithful to the file — every MDX block decodes, every one emits exactly the bytes it should — and the file is not a complete copy of the disc: whole 32 KB blocks are missing, so everything after a gap sits that much nearer the front. [ADR-0022](0022-a-volume-is-explained-by-the-allocation-map.md) found it from inside a volume directory, [ADR-0023](0023-partitions-come-from-the-table-the-disc-declares.md) measured it across the collection, and [issue #25](https://github.com/bmxcode/samplerdisc/issues/25) records what it costs: **109 of the 384 declared partitions have no header where the table puts them**, and on these eight the header is not absent, it is displaced.

ADR-0023 declined to go and find them, on three grounds, each of which it stated as sufficient:

- **the signature is a sawtooth and audio reproduces it** — 374 blocks of `Global Trance Mission 2`'s free space matched, and 153 of `ProSamples vol.14`;
- **filtering the matches by whether they yield files lost real partitions**, 94 volumes down to 72 on `Advanced Media Trax 3`;
- **the gain came almost entirely from short images**, where the audio is displaced with nothing reporting it — 7 723 of the recovered files being on `Kickin' Lunatic Beats 2 CD1`, the disc whose partition 1 already extracted nine samples that were not their own.

The third is answered, and by a different deliverable: [ADR-0027](0027-a-payload-must-be-the-file-its-entry-placed.md) made every AKAI sample prove it is the file its directory entry placed, by four fields the payload repeats. Displaced audio is no longer something that ships silently; it is refused and named. So the question ADR-0023 could not ask is now askable — *does the recovered audio verify?* — and the answer is measured below.

The first two are answered by the search being **anchored, size-matched and floored** rather than being a scan. That is a claim, and this record has to show it.

### What the header-shaped blocks in free space actually are

**ADR-0023's first ground was right about the danger and wrong about its cause, and the truth is worse.** Those 374 blocks are not audio that happens to reproduce a rising sawtooth. Digested, `ProSamples vol.14`'s 153 matches are **one 8 KB block repeated 148 times**, byte for byte, plus its five real partition headers. `Global Trance Mission 2`'s 374 are three distinct blocks repeated 288, 58 and 19 times, plus its partitions and one singleton. Audio does not repeat 8192 bytes exactly 148 times.

They are **partition headers**, complete ones. `vol.14`'s carries the pristine formatted volume directory — `VOLUME 001` … `VOLUME 100`, type 0, start block 0 — and `Global Trance Mission 2`'s names real volumes: `R+R KIT 1`, `REGGAE KIT 1`, `RAP    KIT 1`. Every one sits in a block the partition's own allocation map calls free. Whether they are filler the mastering wrote or headers from an earlier state of the disk is not established and does not matter here: **they pass every test the header offers**, including the two size fields, including a volume directory that parses. A scan cannot tell them from a real header on the bytes, at all, and there is no stricter byte test that would.

That is why the constraints below are about *where a header may be found* and not about *what a header looks like*.

### What the constrained search recovers

Searching backward from each declared position in the container's own storage unit, requiring `partition_header()` to restate the size the table gave **that** partition, and stopping at the end of the partition already accepted:

| Disc | Recovered | Volumes | Files | Samples | Passing ADR-0027 |
|---|---:|---:|---:|---:|---:|
| `AMG - Kickin' Lunatic Beats 2 CD1` | 7 | 121 | 7 723 | 7 308 | 7 293 |
| `AMG - Kickin' Lunatic Beats 2 CD2` | 7 | 100 | 6 203 | 5 912 | 5 912 |
| `AKAI.S3000.Sound.Library.6` | 7 | 84 | 1 054 | 955 | 955 |
| `Back In Time Records - Elektra Vox` | 5 | 33 | 661 | 463 | 463 |
| `Audio Factory - Classical Wild Takes` | 4 | 18 | 189 | 80 | 80 |
| `AKAI.S3000.Sound.Library.5` | 3 | 34 | 473 | 400 | 377 |
| `AKAI.S3000.Sound.Library.7` | 3 | 20 | 660 | 546 | 546 |
| `AMG - Global Trance Mission 2` | 3 | 22 | 217 | 144 | 139 |
| **Total** | **39** | **432** | **17 180** | **15 808** | **15 765 (99.7 %)** |

**The 99.7 % is the finding this rests on, and it is not a coincidence of the search.** The gaps are whole blocks missing from the image, so everything past one shifts by a constant: inside a recovered partition the directory and its audio moved *together* and stay consistent with each other. Displacement only breaks payload-versus-directory agreement where a gap falls **inside** a partition read at its declared position — which is exactly ADR-0027's 61 mismatches, all of them a run to the end of one volume just past a gap.

Three things corroborate the recovery and none of them is the search:

- **The displacements reproduce the table in [the format doc](../formats/akai-fs.md)**, measured a deliverable ago by a different method and for a different purpose.
- **`Kickin' CD1` yields 7 723 files**, which is precisely the number ADR-0023's rejected signature scan measured for that disc independently.
- **No recovered partition repeats another's header block**, on any of the eight — which is what separates a partition from the stale copies above.

## Decision

**A declared partition with no header at its declared position is searched for backwards, in the unit the container stores the disc in, for a header restating the size the table gave that partition — and never below the end of the partition already accepted.**

Five parts.

**Backwards from the declared position, and anchored to it.** A short image has *lost* bytes; nothing has moved away from the front. The search starts where the table puts partition *k* and walks back, so what it finds is partition *k* or nothing. **That is what settles the index**, which is otherwise unanswerable: sizes repeat — eight of `Loop Soup`'s nine are 7680 blocks — so a header restating size N does not say which N it is, and a free scan that found 72 headers could name only five of them. Here the index is the table's and the search never has to choose. The output path `out/partition-N/` is therefore the table's N, on a displaced partition exactly as on a present one, and there is no case where it cannot be known.

**In the unit the container states.** `SectorImage.granularity` is new: cooked bytes per unit this container stores the disc in — the thing an incomplete image is missing whole numbers of. Flat containers hold the sectors literally and report one sector; `MdxImage` reports its measured block size scaled to the cooked stride, 32 768 on all eight of these and 30 720 on a subchannel image. The filesystem asks and does not name it: a `32768` in `fs/akai.py` would be the container's business asserted by the layer that cannot know it, and an AKAI check in `container/` would be the same leak the other way ([ADR-0003](0003-brand-neutral-pluggable-backends.md)). A container that reports nothing usable gets no search rather than a default step chosen in `fs/`.

**Confirmed by the size the table gave that partition.** The same confirmation a declared position gets — the constant field, the size echo at `0xC6`, the tail at `0xC8` — plus the block count this index was given. Placement by one structure, confirmation by another, which is the shape [ADR-0020](0020-read-e-iv-through-its-sample-directory.md), [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md) and ADR-0023 already use.

**Never below the end of the partition already accepted.** This is the safety argument and it does all of the rejecting. It is a **bound on the search**, not a filter on its results: nothing below the floor is examined, so an overlap cannot arise and cannot need resolving. Two consequences fall out of it rather than being added. Partition 1 can never move, on any disc, because its declared position is 0 and its window is empty — which is what protects every count pinned since #22. And accepted partitions never overlap in either direction: a recovered partition ends *before* its declared end, so it cannot reach into a later one either.

**A displaced partition says so, and says it where a listing shows it.** `Partition.displaced` and `Volume.displaced` carry the byte distance; `list` prints it under the partition heading and in the layout line — *"11 partitions declared, 8 present in this image (7 of them displaced — this image is short of the disc it was made from)"* — and `batch` records that line per disc in the manifest. Not on the `File` or on an `Extracted`: the provenance is a property of the partition, constant across the 7 723 files of one, and a per-file flag would repeat it 7 723 times to say one thing.

## Alternatives rejected

**Keep ADR-0023's rule and leave the fifteen thousand files unread.** The conservative position, and it was the right one for exactly as long as a recovered payload could not be checked. ADR-0027 is what changed: 99.7 % of the 15 808 recovered samples prove they are the files their entries placed, against a structure the search knows nothing about, and the 0.3 % that do not are refused and named like any other. Refusing readable audio that verifies, on the strength of a rule whose stated reason has been answered, is not conservatism.

**Scan the image for the header signature**, ADR-0023's own framing of what recovery would mean. Rejected, and more firmly than ADR-0023 could: the free blocks of these discs hold *complete partition headers*, 148 identical copies on one disc, so the scan's false positives are not weak matches to be filtered — they are indistinguishable from the real thing by construction. It also cannot name what it finds: 67 of 72 first-pass hits restated a size several partitions of the disc share.

**Filter a scan's matches by whether the partition yields files.** ADR-0023 measured this and it *lost* real partitions — 94 volumes down to 72 on `Advanced Media Trax 3`. Rejected again, on the same measurement, and worth restating because it is the tempting repair: a partition that legitimately holds nothing is not a false positive, and a test that cannot tell those apart trades a wrong answer for a missing one. `Advanced Media Trax 3` is pinned in `tests/test_discs.py` at 9 partitions, 94 volumes, 2 938 files, **nothing displaced**, precisely so a future search that touches it fails.

**Search in AKAI blocks — a unit the filesystem can state on its own.** No container API, one layer touched instead of two, and *measured identical on this collection*: at 32 768, 8 192 and 2 048 bytes the search recovers the same 39 partitions on the same eight discs, with the same displacements. Rejected on what it claims rather than on what it produced. A step of 8 192 examines four positions for every one a lost container block could have put a header at, and three of the four are places the fault cannot reach; looseness that the data does not currently punish is still looseness, and it is what ADR-0023 refused. The measurement is the reason to be relaxed about the choice, not a reason to make the weaker one.

**Read an overlapping recovery, truncated at the clash.** 24 of the 70 refusals are a header that is really there and really is that partition's, sitting inside a partition already being read — `Kickin' CD2`'s partition 2, four AKAI blocks inside partition 1, is the clean specimen. Truncating would yield most of the partition. Rejected because the clash is not a boundary dispute to be split: it means the image holds one run of bytes that two partitions' bookkeeping both describe, and the audio can only belong to one of them. Reading both would put the same blocks under two names — the failure `Protozoa` taught in [ADR-0021](0021-a-bank-owns-the-run-its-header-declares.md), and the one thing worse than not reading a partition.

**Move the *present* partition instead, on the grounds that the displaced one is where the disc really says.** The most interesting alternative, because on a clash the present partition's declared extent is provably wrong: its last blocks are not in the image, which is why its neighbour's header sits inside them. Rejected on the gate this deliverable is judged by. The 275 partitions read today are the collection's entire established baseline — 2 154 volumes and 68 997 files, pinned per disc — and re-placing any of them to gain a neighbour would move counts that four deliverables have verified, in exchange for a partition whose extent still could not be read whole. What is actually true is that a partition preceding a gap is *shorter in the image than it declares*, and this project has no field that states that. Saying so in the layout line is the honest half; acting on it is not.

**Refuse every disc that has any overlapping recovery.** All-or-nothing per disc, which would be simple to explain. Rejected on the data: `Kickin' CD2`'s partition 2 clashes and its partitions 3 to 9 do not, and refusing them costs 6 203 files to punish a fault they do not share. The rule is per partition because the damage is.

**Recover `Alpha Dance I` by relaxing the floor by the size of one container block.** Its single missing partition is displaced by four AKAI blocks — the same gap as `Kickin' CD2` — and one byte of tolerance would take it. Rejected as a threshold with one specimen behind it, and the argument does not stop there: an overlap is an overlap at any size, and the reason to refuse a 4-block clash is the reason to refuse a 60-block one. `Alpha Dance I` recovers nothing, and the record says so plainly rather than tuning until it does.

**Search forward as well as backward.** Symmetry, and it costs nothing to write. Rejected because it is not symmetric: a rip that lost blocks makes an image *short*, and there is no mechanism on the shelf that inserts them. Every one of the 39 displacements is backwards, as are all 70 refusals. A forward search would double the candidate positions in exchange for a fault nothing has produced.

**Report the provenance per file, on `Extracted` and in the manifest's skip list.** The strongest signal for a user grepping a run. Rejected for repeating one fact 7 723 times: displacement is a property of the partition, `Volume.displaced` is where a consumer can already see it, and the manifest carries the backend's layout line per disc, which says it once and says it for the discs that wrote nothing too.

**Fix issue [#35](https://github.com/bmxcode/samplerdisc/issues/35) here — the run of blocks lost *inside* a partition.** The mechanism found here explains it exactly, and that is now measured rather than supposed: **103 of the 104 refused payloads across the collection are found intact, carrying their entry's own name, a whole number of container blocks earlier** — one block back on `Alpha Dance II`'s 21 and `Library.1`'s 3, 134 on `Library.3`'s one, one to four on the rest. The single exception is `Loop Soup`'s known directory record that lands mid-sample. Rejected as a different decision, not a bigger version of this one: a partition has a *declared position* to anchor a search to, and a file has only a chain the allocation map states. Placing a file's audio somewhere the map does not put it is the search [ADR-0022](0022-a-volume-is-explained-by-the-allocation-map.md) and ADR-0023 both refused, and it would need its own answer to "which file is this?" — which is a name comparison, on payloads whose name does not decode on 54 of 60.

## Consequences

**Good, and the headline.** The 44 AKAI discs go from 275 partitions to **314**, from 2 154 volumes to **2 586**, and from 68 997 files to **86 177**. 15 765 samples that were unreadable are now written, all of them on the eight images the collection had written off. The collection goes from 89 156 samples to **104 921**.

**Good.** The audio verifies against a structure the search does not consult. 15 765 of the 15 808 recovered samples carry a payload header whose id, valid flag and name agree with the directory entry that placed them — 99.7 %, against 99.85 % over all 72 298 AKAI samples — and every accepted payload's word count agrees with its entry's declared size. `Kickin' CD2`, `Library.6`, `Library.7`, `Elektra Vox` and `Classical Wild Takes` recover **6 203, 1 054, 660, 661 and 189 files with not one refusal between them**.

**Good.** The eight images now *say* they are short, in `list` and in the manifest, per partition and per disc. Before this they said "11 partitions declared, 1 present" and the other ten were an absence with no explanation attached.

**Bad, and stated plainly.** 70 declared partitions stay unread and 31 of them are not absent — a header is there, inside a partition already being read. `Best Service - Alpha Dance I` gains nothing at all: its one displaced partition clashes, and this deliverable's answer for that disc is no answer. 10 more have no header at any position the search may look at, and 29 land exactly on a partition already read.

**Bad.** Extraction on the eight discs writes about 15 800 files that were not there before, under `out/partition-N/` paths that did not exist. Anyone who extracted them should do it again, and anyone who diffed a previous run will see additions on those eight and nowhere else.

**Bad.** `list` and `batch` are slower on a disc with missing partitions, because the search walks from a declared position back to the last accepted one and that window can be most of an image. Measured over the whole collection the walk goes from 26 to 45 seconds and a full `batch` from 48 to 72; on a disc with nothing missing the cost is zero, since the search never runs.

**Watch for.** A disc where a *present* partition's header is a stale copy. The floor makes the first partition of a run authoritative over everything after it, so a stale header accepted at a declared position would push the real one below the floor and cost every partition behind it. Nothing on the shelf does this — the 275 present partitions were verified before this deliverable and none moved — but the failure would present as partitions quietly not recovering rather than as an error.

**Watch for.** ADR-0023's statement that a partition header must never be scanned for, which stands and is now better argued. The line to hold is that a position must be *placed* by a structure the disc states — here the table, with the loss the container declares subtracted from it — and never chosen because the bytes there look right. The free blocks of these discs are full of bytes that look exactly right.

**Watch for.** `granularity` growing meanings. It is what an incomplete image is missing whole numbers of, and nothing else: not a read size, not an alignment, not a hint about compression. The temptation will be to use it as a chunk size somewhere in `container/`, and then to change it for a reason that has nothing to do with damage.
