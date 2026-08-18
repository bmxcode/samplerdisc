"""Pluggable sampler filesystem backends."""

# Importing a backend registers it. See fs/base.py.
# AKAI first: it is the more specific probe, and a hybrid disc can
# satisfy both.
from samplerdisc.fs import akai as _akai  # noqa: F401
from samplerdisc.fs import iso9660 as _iso9660  # noqa: F401
