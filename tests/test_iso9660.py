"""ISO 9660 backend, for discs whose payload is already audio."""

from __future__ import annotations

import pytest

from samplerdisc.container.flat import FlatImage
from samplerdisc.extract import Extracted, extract_disc
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
