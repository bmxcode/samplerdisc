"""Pluggable sampler filesystem backends."""

# Importing a backend registers it. See fs/base.py.
# AKAI first: it is the more specific probe, and a hybrid disc can
# satisfy both.
from samplerdisc.fs import akai as _akai  # noqa: F401
from samplerdisc.fs import emu3 as _emu3  # noqa: F401
from samplerdisc.fs import iso9660 as _iso9660  # noqa: F401
from samplerdisc.fs import kurzweil as _kurzweil  # noqa: F401
from samplerdisc.fs import roland_s7xx as _roland_s7xx  # noqa: F401

# HFS last, for the same reason AKAI is first: a hybrid disc satisfies more than
# one probe. A Mac/PC ProSamples disc carries an Apple Partition Map (which the
# HFS probe matches) over the ISO 9660 filesystem that is its intended, verified
# reading -- so HFS must only claim a disc no established backend recognises,
# which is what a pure SampleCell cartridge is.
from samplerdisc.fs import hfs as _hfs  # noqa: F401  # isort: skip
