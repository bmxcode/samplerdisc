"""Convert vintage sampler CD-ROM images to uncompressed WAV."""

from importlib.metadata import PackageNotFoundError, version

# One source of truth: the packaged version in pyproject.toml, read back from
# the installed distribution's metadata. A hardcoded literal here drifts the
# moment the package version bumps — 0.5.1 shipped reporting 0.5.0 that way.
try:
    __version__ = version("samplerdisc")
except PackageNotFoundError:  # a source tree with no installed distribution
    __version__ = "0.0.0+unknown"
