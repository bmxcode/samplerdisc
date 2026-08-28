"""ISO 9660 backend, for discs whose payload is already audio."""

from __future__ import annotations

import pytest

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, extract_disc
from samplerdisc.fs import iso9660
from samplerdisc.fs.akai import AkaiBackend
from samplerdisc.fs.iso9660 import Iso9660Backend
from samplerdisc.fs.probe import find_origin
from tests import fixtures

BACKEND = Iso9660Backend()


@pytest.fixture
def payload(tmp_path) -> bytes:
    return fixtures.tiny_wav(tmp_path)


def iso_image(tmp_path, files, name="d.iso", **kwargs) -> FlatImage:
    path = tmp_path / name
    path.write_bytes(fixtures.make_iso9660(files, **kwargs))
    return FlatImage(path)


def test_probe_finds_the_primary_volume_descriptor(tmp_path, payload):
    assert BACKEND.probe(iso_image(tmp_path, {"A.WAV": payload}), 0)


def test_probe_rejects_an_akai_partition(tmp_path):
    """The two backends must not shadow each other."""
    path = tmp_path / "akai.iso"
    sample = fixtures.akai_sample("KICK")
    path.write_bytes(fixtures.akai_partition([("VOL 1", [("KICK", 0x73, len(sample), sample)])]))
    image = FlatImage(path)
    assert not BACKEND.probe(image, 0)
    assert AkaiBackend().probe(image, 0)


def test_akai_probe_rejects_an_iso9660_disc(tmp_path, payload):
    assert not AkaiBackend().probe(iso_image(tmp_path, {"A.WAV": payload}), 0)


def test_lists_files_with_the_volume_label(tmp_path, payload):
    image = iso_image(tmp_path, {"KICK.WAV": payload, "SNARE.WAV": payload}, label="KONTAKT LIB")
    volumes = list(BACKEND.volumes(image, 0))
    assert len(volumes) == 1
    assert volumes[0].name == "KONTAKT LIB"
    assert [f.name for f in volumes[0].files] == ["KICK.WAV", "SNARE.WAV"]


def test_version_suffix_is_stripped_from_names(tmp_path, payload):
    """ISO 9660 appends ';1'; nobody wants that in a filename."""
    image = iso_image(tmp_path, {"KICK.WAV": payload})
    assert next(iter(BACKEND.volumes(image, 0))).files[0].name == "KICK.WAV"


def test_audio_files_are_classified(tmp_path, payload):
    image = iso_image(tmp_path, {"A.WAV": payload, "B.AIFF": payload, "C.TXT": b"notes"})
    kinds = {f.name: f.kind for f in next(iter(BACKEND.volumes(image, 0))).files}
    assert kinds == {"A.WAV": "wav", "B.AIFF": "aiff", "C.TXT": "file"}


def test_read_file_returns_the_payload(tmp_path, payload):
    image = iso_image(tmp_path, {"KICK.WAV": payload})
    entry = next(iter(BACKEND.volumes(image, 0))).files[0]
    assert BACKEND.read_file(image, 0, entry) == payload


def test_extraction_copies_audio_verbatim(tmp_path, payload):
    """Already-audio files are copied, not decoded -- there is nothing to decode."""
    image = iso_image(tmp_path, {"KICK.WAV": payload, "NOTES.TXT": b"ignore me"})
    out = tmp_path / "out"
    results = list(extract_disc(image, BACKEND, 0, str(out)))
    assert sum(isinstance(r, Extracted) for r in results) == 1
    written = out / "SAMPLE CD" / "KICK.wav"
    assert written.read_bytes() == payload


def test_origin_probe_selects_iso9660_for_an_iso_disc(tmp_path, payload):
    image = iso_image(tmp_path, {"A.WAV": payload})
    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "iso9660"


def test_origin_resolves_when_the_pregap_is_inside_the_cooked_stream(tmp_path, payload):
    """ADR-0005 for the hybrid case it names, asserted rather than assumed.

    The container hands over a cooked stream with the 150 zeroed sectors still
    in it -- a hybrid disc with an ISO track ahead of the real filesystem, or a
    raw rip -- so the origin probe, not an assumption of byte 0, must resolve to
    the byte the primary volume descriptor sits on. Getting it wrong reads as an
    empty disc, not an error.

    This also pins the assumption that directory-record LBAs are relative to the
    resolved origin: the backend reads ``origin + extent * SECTOR_SIZE``, and the
    fixture's extents count from its own byte 0, so they land only if the origin
    is threaded through. The read-back is the assertion that matters -- an
    extent-vs-origin bug can list every file and still read pregap zeros, which
    is exactly how the EMU3 bug in PR #49 hid behind a listing that looked whole.
    """
    pregap = b"\x00" * (150 * 2048)
    body = fixtures.make_iso9660({"KICK.WAV": payload, "SNARE.WAV": payload}, label="HYBRID LIB")
    path = tmp_path / "gap.iso"
    path.write_bytes(pregap + body)
    image = FlatImage(path)

    origin = find_origin(image)
    assert origin is not None
    assert origin.backend.name == "iso9660"
    assert origin.offset == 150 * 2048

    volume = next(iter(origin.backend.volumes(image, origin.offset)))
    assert volume.name == "HYBRID LIB"
    assert [f.name for f in volume.files] == ["KICK.WAV", "SNARE.WAV"]
    for entry in volume.files:
        assert BACKEND.read_file(image, origin.offset, entry) == payload


# Vintage Pro's SamplePool holds 1 061 files under 1 001 short names: MagicISO
# caps the 8.3 name at twelve characters total and lets the "~1000" counter eat
# the extension, so every index from 1000 up masters as VINTA~1000.E. Three
# files reproduce the shape; the sizes differ so an overwrite cannot hide.
_COLLIDING = {
    "Vintage ProSL1000.wav": b"first" * 40,
    "Vintage ProSL1001.wav": b"second" * 50,
    "Vintage ProSL1002.wav": b"third" * 80,
}
_SHORT = dict.fromkeys(_COLLIDING, "VINTA~1000.W")

#: The same collision with the extension left intact, so the entries still
#: classify as audio and reach the copy path. On Vintage Pro the runaway
#: counter eats the extension too, which is a second way to lose a file --
#: worth keeping the two apart in a test.
_SHORT_KEEPING_THE_SUFFIX = dict.fromkeys(_COLLIDING, "VINT~10.WAV")


def test_the_primary_tree_reports_colliding_short_names_faithfully(tmp_path):
    """Without Joliet there is nothing better to report -- so report the truth.

    Inventing a unique name here would put a path in the listing that is not on
    the disc. Uniqueness is extraction's problem, not the directory's.
    """
    image = iso_image(tmp_path, _COLLIDING, short_names=_SHORT)
    files = next(iter(BACKEND.volumes(image, 0))).files
    assert [f.name for f in files] == ["VINTA~1000.W"] * 3
    assert len({f.size for f in files}) == 3
    # The runaway counter ate the extension, so nothing here even looks like
    # audio any more -- another thing Joliet gets right and the short name does not.
    assert {f.kind for f in files} == {"file"}


def test_joliet_names_are_preferred_over_the_short_names(tmp_path):
    image = iso_image(tmp_path, _COLLIDING, short_names=_SHORT, joliet=True)
    files = next(iter(BACKEND.volumes(image, 0))).files
    assert [f.name for f in files] == list(_COLLIDING)
    assert len({f.name for f in files}) == len(_COLLIDING)


def test_joliet_hides_no_file_the_primary_tree_lists(tmp_path):
    """Joliet is a second set of names, not a second set of files.

    Sizes rather than extents: the two images are not byte-identical, because a
    Joliet disc carries a second root directory and everything after it shifts.
    """
    plain = iso_image(tmp_path, _COLLIDING, short_names=_SHORT, name="a.iso")
    wide = iso_image(tmp_path, _COLLIDING, short_names=_SHORT, name="b.iso", joliet=True)
    sizes = [f.size for f in next(iter(BACKEND.volumes(plain, 0))).files]
    assert [f.size for f in next(iter(BACKEND.volumes(wide, 0))).files] == sizes


def test_joliet_payloads_still_read_back(tmp_path):
    image = iso_image(tmp_path, _COLLIDING, short_names=_SHORT, joliet=True)
    volume = next(iter(BACKEND.volumes(image, 0)))
    for entry in volume.files:
        assert BACKEND.read_file(image, 0, entry) == _COLLIDING[entry.name]


def test_colliding_names_extract_to_one_file_each(tmp_path):
    """The guarantee that matters: as many files out as the disc holds.

    Read through the primary tree on purpose -- this is the case where the
    filesystem hands extraction three entries with one name, and no payload may
    be lost to it.
    """
    image = iso_image(tmp_path, _COLLIDING, short_names=_SHORT_KEEPING_THE_SUFFIX)
    out = tmp_path / "out"
    results = list(extract_disc(image, BACKEND, 0, str(out)))
    written = sorted((out / "SAMPLE CD").iterdir())
    assert len(written) == 3
    assert sum(isinstance(r, Extracted) for r in results) == 3
    assert {p.read_bytes() for p in written} == set(_COLLIDING.values())


def test_joliet_extraction_names_the_files_from_the_long_names(tmp_path):
    image = iso_image(tmp_path, _COLLIDING, short_names=_SHORT, joliet=True)
    out = tmp_path / "out"
    list(extract_disc(image, BACKEND, 0, str(out)))
    names = sorted(p.name for p in (out / "SAMPLE CD").iterdir())
    assert names == ["Vintage ProSL1000.wav", "Vintage ProSL1001.wav", "Vintage ProSL1002.wav"]


def test_a_nul_terminated_volume_label_stops_at_the_nul(tmp_path, payload):
    """MagicISO leaves buffer content after the NUL; it is not part of the name.

    Vintage Pro's primary label reads 'VintagePro\\x0057', the trailing 57 a
    fragment of its volume set identifier. Reading past the NUL invented a
    volume named "VintagePro 57" that is nowhere on the disc.
    """
    image = iso_image(tmp_path, {"A.WAV": payload}, label="VintagePro\x0057")
    assert next(iter(BACKEND.volumes(image, 0))).name == "VintagePro"


def test_the_joliet_label_is_decoded_as_ucs2(tmp_path, payload):
    image = iso_image(
        tmp_path, {"A.wav": payload}, label="SHOUTY", joliet=True, joliet_label="Vintage Pro"
    )
    assert next(iter(BACKEND.volumes(image, 0))).name == "Vintage Pro"


def test_a_supplementary_descriptor_that_is_not_joliet_is_ignored(tmp_path, payload):
    """Only the UCS-2 escape sequences mean Joliet. Anything else is not ours."""
    path = tmp_path / "svd.iso"
    raw = bytearray(fixtures.make_iso9660({"A.wav": payload}, joliet=True, label="PRIMARY"))
    svd = 17 * 2048
    raw[svd + 88 : svd + 91] = b"XXX"
    path.write_bytes(bytes(raw))
    volume = next(iter(BACKEND.volumes(FlatImage(path), 0)))
    assert volume.name == "PRIMARY"
    assert [f.name for f in volume.files] == ["A.WAV"]


def test_joliet_carries_characters_the_short_names_cannot(tmp_path, payload):
    """UCS-2 is the point: the primary tree has no way to spell these."""
    image = iso_image(tmp_path, {"Café Ørchestra.wav": payload}, joliet=True)
    assert [f.name for f in next(iter(BACKEND.volumes(image, 0))).files] == ["Café Ørchestra.wav"]


def test_the_documented_descriptor_layout_is_what_the_backend_reads():
    """The table in docs/formats/iso9660.md, so the doc and the code cannot drift."""
    assert (iso9660.MAGIC, iso9660.PVD_MAGIC_OFFSET, iso9660.PVD_SECTOR) == (b"CD001", 1, 16)
    assert (iso9660.TYPE_PRIMARY, iso9660.TYPE_SUPPLEMENTARY, iso9660.TYPE_TERMINATOR) == (
        1,
        2,
        255,
    )
    assert iso9660.ESCAPE_OFFSET == 88
    assert iso9660.JOLIET_ESCAPES == (b"%/@", b"%/C", b"%/E")
    assert (iso9660.ROOT_RECORD_OFFSET, iso9660.ROOT_RECORD_SIZE) == (156, 34)


def test_an_apple_resource_fork_is_not_listed_as_a_file(tmp_path):
    """Bit 2 of the record flags marks a second record wearing the data
    file's name and pointing somewhere else -- Apple's resource fork.

    Listing it gives the file two identical paths and extracts a few KB of
    fork metadata under an audio extension: a WAV that opens, plays as noise
    and reports nothing wrong. Real discs are full of them -- 1 388 of
    ProSamples vol. 43's 4 189 records, 359 of vol. 52's, 115 of vol. 40's,
    and on every one of them the duplicate count equals the flagged count
    exactly.
    """
    files = {"Kick 01.wav": b"K" * 4096, "Snare 02.wav": b"S" * 4096}
    image = iso_image(tmp_path, files, "forks.iso", joliet=True, associated=("Kick 01.wav",))
    volume = next(iter(BACKEND.volumes(image, 0)))
    names = [f.name for f in volume.files]

    assert names == sorted(set(names)), "a resource fork was listed under the data file's name"
    assert names == ["Kick 01.wav", "Snare 02.wav"]
    # The one that survived is the audio, not the 4-byte fork.
    kick = next(f for f in volume.files if f.name == "Kick 01.wav")
    assert kick.size == 4096


def test_a_damaged_joliet_tree_falls_back_to_the_primary(tmp_path):
    """Preferring Joliet is a decision about names (ADR-0019). It must not
    become a decision about whether the disc reads at all.

    These are rips and tail damage is normal, so a supplementary descriptor
    can point at nothing while the primary tree beside it is perfectly good.
    Committing to Joliet and walking out empty is the ADR-0012 signature --
    a claimed disc with no files and no explanation.
    """
    files = {"Kick 01.wav": b"K" * 4096, "Snare 02.wav": b"S" * 4096}
    healthy = next(iter(BACKEND.volumes(iso_image(tmp_path, files, "ok.iso", joliet=True), 0)))
    assert [f.name for f in healthy.files] == ["Kick 01.wav", "Snare 02.wav"]

    broken = next(
        iter(
            BACKEND.volumes(
                iso_image(tmp_path, files, "broken.iso", joliet=True, break_joliet_root=True), 0
            )
        )
    )
    # Every file still found, under the primary tree's names rather than none.
    assert len(broken.files) == 2
    assert [f.name for f in broken.files] == ["KICK 01.WAV", "SNARE 02.WAV"]


def test_the_fallback_does_not_fire_on_a_healthy_disc(tmp_path):
    """The guard above must not quietly become "walk whichever tree is bigger".

    A Joliet tree that legitimately yields files is used even when the primary
    would also have worked -- otherwise the preference this whole change exists
    for would depend on which tree happened to be larger.
    """
    files = {"Kick 01.wav": b"K" * 4096}
    image = iso_image(
        tmp_path, files, "healthy.iso", joliet=True, short_names={"Kick 01.wav": "KICK~001.WAV"}
    )
    volume = next(iter(BACKEND.volumes(image, 0)))
    assert [f.name for f in volume.files] == ["Kick 01.wav"]


def test_instrument_definitions_are_classified_as_programs(tmp_path, payload):
    """EXS24 and HALion files are to one of these discs what a program is to an
    AKAI one: the key ranges and envelopes, which the WAVs cannot carry."""
    image = iso_image(
        tmp_path,
        {"P.EXS": b"exs", "H.FXP": b"fxp", "B.FXB": b"fxb", "A.WAV": payload, "R.TXT": b"read me"},
    )
    kinds = {f.name: f.kind for f in next(iter(BACKEND.volumes(image, 0))).files}
    assert kinds == {
        "P.EXS": "program",
        "H.FXP": "program",
        "B.FXB": "program",
        "A.WAV": "wav",
        "R.TXT": "file",
    }


def test_an_original_keeps_the_extension_the_disc_gave_it(tmp_path, payload):
    """Unlike a sampler filesystem, this one has real filenames. Falling back
    to the default suffix writes every kept .exs out as .bin -- the bytes
    survive and nothing will open them."""
    image = iso_image(tmp_path, {"P.EXS": b"exs", "A.WAV": payload})
    files = {f.name: f for f in next(iter(BACKEND.volumes(image, 0))).files}
    assert BACKEND.original_suffix(files["P.EXS"]) == ".exs"


def test_an_original_with_no_extension_falls_back_to_the_default(tmp_path, payload):
    image = iso_image(tmp_path, {"README": b"notes", "A.WAV": payload})
    entry = next(f for f in next(iter(BACKEND.volumes(image, 0))).files if f.name == "README")
    assert BACKEND.original_suffix(entry) == ".bin"
