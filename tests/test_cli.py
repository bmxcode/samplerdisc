from samplerdisc import __version__
from samplerdisc.cli import build_parser


def test_version_matches_package():
    assert __version__ == "0.1.0"


def test_parser_exposes_version_flag():
    parser = build_parser()
    assert any(a.dest == "version" for a in parser._actions)
