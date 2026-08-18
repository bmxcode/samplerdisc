"""Pluggable sampler filesystem backends."""

# Importing a backend registers it. See fs/base.py.
from samplerdisc.fs import akai as _akai  # noqa: F401
