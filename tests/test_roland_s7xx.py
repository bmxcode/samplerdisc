"""Roland ``S770 MR25A`` filesystem tests against synthetic images (ADR-0008).

Every fixture below is built in code from the backend's own constants. Nothing
here came off a disc, and nothing here may: the reference libraries are
commercial and this repository is public.

Each test is pinned to a failure this format can actually produce. Where the
comment says a real disc would not have caught something, that is the point of
the test -- most of these traps are invisible on the discs that exist, and only
show up as a sample quietly reporting its neighbour's audio.
"""

from __future__ import annotations

import struct

from samplerdisc.container.flat import FlatImage
from samplerdisc.fs.probe import find_origin
from samplerdisc.fs.roland_s7xx import (
    BLOCK,
    CHAIN_END,
    CLASS_PARTIAL,
    CLASS_PATCH,
    CLASS_PERFORMANCE,
    CLASS_SAMPLE,
    CLASS_VOLUME,
    CLUSTER,
    CLUSTER_BLOCKS,
    DATA_BLOCK,
    DIR_BLOCK,
    ENTRY_LEN,
    FAT_BLOCK,
    FIRST_DATA_CLUSTER,
    MAGIC,
    OFF_MAGIC,
    OFF_PARAM_SUSTAIN_START,
    PARAM_LEN,
    SAMPLE_PARAM_BLOCK,
    SAMPLE_RATE,
    RolandS7xxBackend,
    max_cluster,
)
from tests import fixtures

BACKEND = RolandS7xxBackend()

#: A small disc in the shape of a real one: a few samples, mixed loop modes,
#: mixed terminators, one name carrying the 0x7F stereo side marker.
FOUR_SAMPLES = [
    fixtures.roland_sample("STR:Vln Mt1 G_4", (2, 3), key=67, loop=(1000, 5000)),
    fixtures.roland_sample("BRS:1Fr.Horn A#3", (4,), key=58, loop_mode=0),
    fixtures.roland_sample("GTR:Gm Walk*\x7fL", (5, 6, 7), key=36, terminator=0xFFFA),
    fixtures.roland_sample("KIK:JJ Ambo K1 ^", (8,), key=60, terminator=0xFFFE, loop_mode=16),
]


def image_of(tmp_path, data: bytes, name: str = "roland.iso") -> FlatImage:
    path = tmp_path / name
    path.write_bytes(data)
    return FlatImage(path)


def files_of(image, offset: int = 0):
    """The one volume's files. This backend yields exactly one (ADR-0016)."""
    volumes = list(BACKEND.volumes(image, offset))
    assert len(volumes) == 1
    return volumes[0].files


def audio_of(chain, seed: int = 11) -> bytes:
    """What the fixture wrote into those clusters, in that order."""
    return b"".join(fixtures.roland_cluster(c, seed) for c in chain)


# --- the constants the format doc claims ---------------------------------


def test_the_block_map_is_the_one_the_docs_state():
    """CLAUDE.md's rule: the tests and the docs must state the same numbers.

    A constant that only lives in the source drifts from the doc silently, and
    on this format the doc is where the nine-disc evidence for each figure is
    written down. So they are asserted here rather than trusted.
    """
    assert (MAGIC, OFF_MAGIC) == (b"S770 MR25A", 4)
    assert BLOCK == 512
    assert (CLUSTER_BLOCKS, CLUSTER) == (18, 9216)
    assert FAT_BLOCK == 1028
    assert FIRST_DATA_CLUSTER == 2
    assert DIR_BLOCK == {
        CLASS_VOLUME: 1284,
        CLASS_PERFORMANCE: 1292,
        CLASS_PATCH: 1324,
        CLASS_PARTIAL: 1388,
        CLASS_SAMPLE: 1644,
    }
    assert SAMPLE_PARAM_BLOCK == 4780
    assert DATA_BLOCK == 5548
    assert (ENTRY_LEN, PARAM_LEN) == (32, 48)
    assert SAMPLE_RATE == 44100


def test_the_two_arithmetic_closures_hold():
    """The block map is a finding, not an arrangement that happens to fit.

    8 192 directory entries of 32 bytes is *exactly* the 512 blocks from the
    sample directory to the next region, and 8 192 parameter records of 48
    bytes is *exactly* the 768 blocks from the parameter area to the sample
    data. The data area begins where the parameter area ends.
    """
    assert 8192 * ENTRY_LEN == 512 * BLOCK
    assert DIR_BLOCK[CLASS_SAMPLE] + 512 == 2156  # volume/performance/patch parameters
    assert 8192 * PARAM_LEN == 768 * BLOCK
    assert SAMPLE_PARAM_BLOCK + 768 == DATA_BLOCK


def test_the_terminator_floor_is_fff6_and_not_fff0():
    """Load-bearing in both directions.

    Too high and a marker reads as a cluster. Too low and a cluster reads as a
    marker: the largest partition seen declares 1 184 980 blocks, which is
    65 525 clusters -- 0xFFF5 -- and l-cdx-01's last sample really does sit at
    the top of it. A 0xFFF0 floor drops that sample with nothing reported.
    """
    assert CHAIN_END == 0xFFF6
    assert max_cluster(1_184_980) == 65_525 == CHAIN_END - 1
    assert max_cluster(1_184_980) > 0xFFF0  # so a 0xFFF0 floor is inside the range
    # And it tightens on a small disc rather than trusting one constant.
    assert max_cluster(DATA_BLOCK + 10 * CLUSTER_BLOCKS) == FIRST_DATA_CLUSTER + 9


# --- probe ----------------------------------------------------------------


def test_probe_accepts_a_synthetic_disc(tmp_path):
    assert BACKEND.probe(image_of(tmp_path, fixtures.roland_s7xx_disc(FOUR_SAMPLES)), 0)


def test_probe_ignores_the_free_text_version_field(tmp_path):
    """A probe keyed on "SYS-772" drops the entire L-CDX series, silently.

    The field at 0x20 reads "S-760 System Disk    Ver.2.23Y" on L-CDX-02, and
    the format underneath is identical at every level -- directory, parameter
    record and FAT chain all agree. Probe on the magic and nothing else.
    """
    data = fixtures.roland_s7xx_disc(FOUR_SAMPLES, version_text="S-760 System Disk    Ver.2.23Y")
    image = image_of(tmp_path, data, "s760.iso")
    assert BACKEND.probe(image, 0)
    assert [f.name for f in files_of(image)] == [s["name"] for s in FOUR_SAMPLES]


def test_probe_rejects_a_plausible_header_with_a_zeroed_sample_directory(tmp_path):
    """ADR-0012, and it names this backend in its "watch for".

    A ten-byte magic is a far stronger signature than AKAI's volume table, but
    a magic plus a pointer is still only structure. The pointer has to be
    followed and the thing it points at confirmed, or the disc is claimed and
    then walks out empty -- which reads as an empty disc, not as a bug.
    """
    data = fixtures.roland_s7xx_disc(FOUR_SAMPLES, zero_sample_directory=True)
    image = image_of(tmp_path, data, "hollow.iso")
    assert data[OFF_MAGIC : OFF_MAGIC + len(MAGIC)] == MAGIC  # the header is intact
    assert not BACKEND.probe(image, 0)


def test_probe_rejects_zeros_and_noise(tmp_path):
    assert not BACKEND.probe(image_of(tmp_path, b"\x00" * 65536, "z.iso"), 0)
    assert not BACKEND.probe(image_of(tmp_path, fixtures.incompressible_block(7) * 2, "n.iso"), 0)


def test_find_origin_does_not_claim_the_magic_buried_in_audio(tmp_path):
    """Ten bytes of magic can occur inside sample data, and a disc is full of it.

    ``find_origin`` tries every 2048-byte sector, so any sector of PCM that
    happens to start "\\0\\0\\0\\0S770 MR25A" would be claimed by a probe that
    stopped at the signature. To make that a real test rather than a lucky one,
    an entire *valid* header block is spliced into the middle of the audio
    here: the magic is right, the five counts are in range and the partition
    size closes. What is not there is the sample directory 1 644 blocks further
    on, which is audio -- so the pointer has to be followed and the thing it
    points at confirmed (ADR-0012).
    """
    header = fixtures.roland_s7xx_disc(FOUR_SAMPLES)[:BLOCK]
    pcm = bytearray(fixtures.mono_sample_block() * 32)
    at = 20 * 2048
    pcm[at : at + BLOCK] = header
    image = image_of(tmp_path, bytes(pcm), "audio.iso")
    assert image.read(at + OFF_MAGIC, len(MAGIC)) == MAGIC
    assert not BACKEND.probe(image, at)
    assert find_origin(image, candidates=[BACKEND]) is None


def test_origin_resolves_behind_a_150_sector_nrg_pregap(tmp_path):
    """ADR-0005, asserted per backend rather than assumed to carry over.

    A Nero image puts 150 sectors of zeroed pregap in front of the filesystem.
    The container knows where its *track* starts and strips that, so the origin
    inside the cooked stream is 0 -- but only because the probe asked instead of
    assuming, and getting it wrong here reads as an empty disc.
    """
    from samplerdisc.container.nrg import NrgImage

    path = tmp_path / "disc.nrg"
    path.write_bytes(fixtures.make_nrg(fixtures.roland_s7xx_disc(FOUR_SAMPLES)))
    with NrgImage(path) as image:
        origin = find_origin(image)
        assert origin is not None
        assert origin.backend.name == "roland_s7xx"
        assert origin.offset == 0
        assert len(files_of(image, origin.offset)) == len(FOUR_SAMPLES)


def test_origin_resolves_when_the_pregap_is_inside_the_cooked_stream(tmp_path):
    """The other half of ADR-0005: a container that hands over the pregap.

    Here the 150 zeroed sectors really are in the stream -- a hybrid disc, or a
    raw rip -- and the resolved origin must be the byte the header sits on, not
    zero.
    """
    pregap = b"\x00" * (150 * 2048)
    image = image_of(tmp_path, pregap + fixtures.roland_s7xx_disc(FOUR_SAMPLES), "gap.iso")
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "roland_s7xx"
    assert origin.offset == 150 * 2048
    assert [f.name for f in files_of(image, origin.offset)] == [s["name"] for s in FOUR_SAMPLES]


# --- the happy path -------------------------------------------------------


def test_a_disc_lists_its_samples_with_their_parameters(tmp_path):
    """Names, rate, root key, and the audio byte for byte.

    The payload check is the one that matters: it is not enough that a sample
    comes out the right length, because the failure this format offers is a
    sample of exactly the right length made of the wrong clusters.
    """
    image = image_of(tmp_path, fixtures.roland_s7xx_disc(FOUR_SAMPLES))
    files = files_of(image)
    assert [f.name for f in files] == [
        "STR:Vln Mt1 G_4",
        "BRS:1Fr.Horn A#3",
        "GTR:Gm Walk*\x7fL",
        "KIK:JJ Ambo K1 ^",
    ]
    assert [f.get("key") for f in files] == [67, 58, 36, 60]
    assert {f.get("rate") for f in files} == {SAMPLE_RATE}
    assert [f.get("clusters") for f in files] == [2, 1, 3, 1]
    assert [f.size for f in files] == [2 * CLUSTER, CLUSTER, 3 * CLUSTER, CLUSTER]
    for entry, spec in zip(files, FOUR_SAMPLES, strict=True):
        assert BACKEND.read_file(image, 0, entry) == audio_of(spec["chain"])


def test_the_one_volume_is_named_from_the_id_label(tmp_path):
    """The hierarchy is located, not walked (ADR-0016).

    Samples live in one flat global directory; the volume/performance/patch/
    partial chain above them groups them, and two of its four record formats
    are undecoded. One verified volume beats thirteen guessed ones -- and its
    name comes from the header's "ID<n>:" label at 0x100.
    """
    data = fixtures.roland_s7xx_disc(FOUR_SAMPLES, label="ID2:Solo Strngs ")
    volumes = list(BACKEND.volumes(image_of(tmp_path, data), 0))
    assert [v.name for v in volumes] == ["ID2:Solo Strngs"]


def test_the_stereo_side_marker_survives_into_the_name(tmp_path):
    """0x7F is a character in this charset, not a control code to strip.

    It is Roland's spelling of AKAI's "-L"/"-R" and covers 1 110 of NorthStar's
    1 284 samples, so a name decoder that drops it destroys the only thing that
    pairs the two halves of a stereo sound (ADR-0017). Joining them is another
    workstream; keeping the byte is this one's business.
    """
    image = image_of(tmp_path, fixtures.roland_s7xx_disc(FOUR_SAMPLES))
    names = [f.name for f in files_of(image)]
    assert "GTR:Gm Walk*\x7fL" in names


# --- the allocation table -------------------------------------------------


def test_a_fragmented_chain_is_followed_through_the_table(tmp_path):
    """The most important test in this file.

    All 6 392 chains on all five reference discs are contiguous -- every FAT
    entry is its own index plus one. A reader that assumed contiguity would
    therefore pass on every disc anyone has, and fail on the first one that
    does not, by splicing a neighbour's audio onto a sample and reporting no
    problem at all. This is the same coincidence that held on E-mu's simple
    discs and broke on 41 of 46 banks on eiiix-2.
    """
    fragmented = fixtures.roland_sample("PAD:Fragmented  ", (2, 9, 5, 3))
    neighbour = fixtures.roland_sample("PAD:Neighbour   ", (4, 8))
    image = image_of(tmp_path, fixtures.roland_s7xx_disc([fragmented, neighbour]), "frag.iso")
    files = files_of(image)

    payload = BACKEND.read_file(image, 0, files[0])
    assert payload == audio_of((2, 9, 5, 3))
    # The contiguous read is the same length and entirely wrong, which is the
    # whole problem: nothing about the result looks like an error.
    assert len(audio_of((2, 3, 4, 5))) == len(payload)
    assert payload != audio_of((2, 3, 4, 5))
    # And cluster 4 belongs to the neighbour, which is still intact.
    assert BACKEND.read_file(image, 0, files[1]) == audio_of((4, 8))


def test_every_terminator_seen_on_a_real_disc_ends_a_chain(tmp_path):
    """0xFFF8 and 0xFFFA occur locally and 0xFFFE was seen remotely.

    Testing for 0xFFF8 alone runs a chain off the end of its own file and into
    the next one. Each sample here declares one more cluster than its chain
    holds, so the walk only stops if the marker is recognised.
    """
    specs = [
        fixtures.roland_sample("END:fff8       ", (2, 3), clusters=3, terminator=0xFFF8),
        fixtures.roland_sample("END:fffa       ", (4, 5), clusters=3, terminator=0xFFFA),
        fixtures.roland_sample("END:fffe       ", (6, 7), clusters=3, terminator=0xFFFE),
    ]
    image = image_of(tmp_path, fixtures.roland_s7xx_disc(specs), "ends.iso")
    for entry, spec in zip(files_of(image), specs, strict=True):
        assert BACKEND.read_file(image, 0, entry) == audio_of(spec["chain"])


def test_a_chain_longer_than_its_declared_count_is_bounded(tmp_path):
    """The count is a bound, not a hint.

    A damaged or over-long chain must not swallow the clusters after it. This
    sample's chain links four clusters while its directory entry declares two,
    and the walk has to stop at two -- otherwise the extra clusters arrive as
    part of this sample's audio and the file is simply longer than it should
    be, with nothing to notice.
    """
    over = fixtures.roland_sample("OVR:Runs long   ", (2, 3, 4, 5), clusters=2)
    after = fixtures.roland_sample("OVR:Next sample ", (6,))
    image = image_of(tmp_path, fixtures.roland_s7xx_disc([over, after]), "over.iso")
    files = files_of(image)
    payload = BACKEND.read_file(image, 0, files[0])
    assert payload == audio_of((2, 3))
    assert len(payload) == 2 * CLUSTER
    assert audio_of((4,)) not in payload
    assert BACKEND.read_file(image, 0, files[1]) == audio_of((6,))


# --- the directory --------------------------------------------------------


def test_only_the_declared_count_of_entries_is_read(tmp_path):
    """The header's count is the authority; there is no terminator.

    That removes the whole directory-overrun failure class -- the one that
    protozoa's 0x42 filler produced on EMU3, where walking past the last bank
    yielded entries that decoded perfectly plausibly. Here the filler entries
    below are entirely valid samples, so a reader that scans for an end picks
    up six extra sounds that are not on the disc.
    """
    data = fixtures.roland_s7xx_disc(FOUR_SAMPLES, filler=6)
    files = files_of(image_of(tmp_path, data, "filler.iso"))
    assert len(files) == len(FOUR_SAMPLES)
    assert not [f for f in files if f.name.startswith("FIL:")]

    # The filler really is there and really would decode: this test is only
    # meaningful if a scanning reader would have found something.
    base = DIR_BLOCK[CLASS_SAMPLE] * BLOCK + len(FOUR_SAMPLES) * ENTRY_LEN
    assert data[base : base + 4] == b"FIL:"
    assert data[base + 16] == CLASS_SAMPLE


def test_the_directory_name_wins_over_a_stale_parameter_name(tmp_path):
    """The two records are joined by index and only by index.

    NorthStar carries 7 samples the directory has since renamed -- it reads
    "PLK:F7MuteChr*" where the parameter record still reads "PLK:F7MuteChor".
    Validating the pairing on name equality drops exactly those 7, silently,
    and using the parameter record's name reports a name the disc does not
    show.
    """
    stale = fixtures.roland_sample(
        "PLK:F7MuteChr*", (2,), param_name="PLK:F7MuteChor", key=72, loop=(100, 4000)
    )
    image = image_of(tmp_path, fixtures.roland_s7xx_disc([stale]), "stale.iso")
    entry = files_of(image)[0]
    assert entry.name == "PLK:F7MuteChr*"
    # Still fully read: the parameters came from the record whose name differs.
    assert entry.get("key") == 72
    assert entry.get("loop_end") == 4000
    assert BACKEND.read_file(image, 0, entry) == audio_of((2,))


# --- the parameter record -------------------------------------------------


def test_a_declared_end_past_the_allocation_is_clamped(tmp_path):
    """Six entries across the reference discs declare more than they own.

    Edirol's "BRS:Cpm Tpt G_3A" claims 203 415 frames against 28 clusters, and
    l-cdx-01 has a ":  :" divider entry claiming 13 822 636 frames in a single
    cluster. Reading the declared length walks straight into the next sample
    and reports its audio as this one's -- a longer file, not an error. Clamp
    to what is allocated, keep the sample, do not crash.
    """
    greedy = fixtures.roland_sample("DIV::  :        ", (2,), frames=13_822_636)
    after = fixtures.roland_sample("DIV:Next        ", (3,))
    image = image_of(tmp_path, fixtures.roland_s7xx_disc([greedy, after]), "greedy.iso")
    files = files_of(image)
    assert files[0].get("declared_frames") == 13_822_636
    assert files[0].size == CLUSTER
    payload = BACKEND.read_file(image, 0, files[0])
    assert payload == audio_of((2,))
    assert BACKEND.parse_sample(files[0], payload).frames == CLUSTER // 2
    assert BACKEND.read_file(image, 0, files[1]) == audio_of((3,))


def test_addresses_are_24_8_fixed_point(tmp_path):
    """The low byte is a fractional frame, not part of the address.

    Reading one as a plain u32 gives a frame count 256 times too large, which
    on a big image still lands inside the disc and so does not look wrong. The
    fraction is zero everywhere except the sustain loop start, where 220 real
    records carry one -- which is what a sub-sample loop tuning looks like, and
    is the tell that confirms the reading.
    """
    spec = fixtures.roland_sample("FIX:Tuned loop  ", (2, 3), loop=(1000, 5000))
    spec["loop_start_fraction"] = 128
    data = fixtures.roland_s7xx_disc([spec], sample_count=1)
    raw_at = SAMPLE_PARAM_BLOCK * BLOCK + OFF_PARAM_SUSTAIN_START
    assert struct.unpack_from("<I", data, raw_at)[0] == (1000 << 8) | 128

    entry = files_of(image_of(tmp_path, data, "fixed.iso"))[0]
    assert entry.get("loop_start") == 1000
    assert entry.get("loop_end") == 5000


def test_a_loop_is_emitted_only_when_the_mode_byte_is_non_zero(tmp_path):
    """And mode 0 does *not* mean the addresses are junk.

    Mode-0 samples carry loop points that splice as cleanly as mode-1 ones
    (80.6% against 86.5%): the points are crafted whether or not the sampler is
    told to play them, so the byte gates playback and nothing else. Both
    entries below carry the same addresses; only one loops.
    """
    looped = fixtures.roland_sample("LP :mode 1      ", (2,), loop_mode=1, loop=(500, 4000))
    parked = fixtures.roland_sample("LP :mode 0      ", (3,), loop_mode=0, loop=(500, 4000))
    image = image_of(tmp_path, fixtures.roland_s7xx_disc([looped, parked]), "loops.iso")
    files = files_of(image)

    first = BACKEND.parse_sample(files[0], BACKEND.read_file(image, 0, files[0]))
    assert [(loop.start, loop.end) for loop in first.loops] == [(500, 4000)]

    second = BACKEND.parse_sample(files[1], BACKEND.read_file(image, 0, files[1]))
    assert second.loops == ()
    # The addresses survived the walk; nothing was inferred from the zero.
    assert (files[1].get("loop_start"), files[1].get("loop_end")) == (500, 4000)


def test_an_unknown_loop_mode_still_loops(tmp_path):
    """The enum is open and must not be gated on.

    Four discs say {0, 1, 2, 4} and l-cdx-01 -- the S-760 -- says 16. A parser
    that rejected an unknown value would have dropped 144 of that disc's
    samples on the strength of a set four discs happened to agree on. What the
    non-zero values distinguish is not established, so every one becomes a
    plain forward loop.
    """
    specs = [
        fixtures.roland_sample(f"LP :mode {mode:<7}", (cluster,), loop_mode=mode, loop=(64, 2048))
        for cluster, mode in enumerate((1, 2, 4, 16, 99), start=2)
    ]
    image = image_of(tmp_path, fixtures.roland_s7xx_disc(specs), "modes.iso")
    for entry in files_of(image):
        sample = BACKEND.parse_sample(entry, BACKEND.read_file(image, 0, entry))
        assert [(loop.start, loop.end) for loop in sample.loops] == [(64, 2048)], entry.name
