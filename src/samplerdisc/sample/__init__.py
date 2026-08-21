"""Sampler-native sample formats.

One module per on-disc sample format, each exposing a ``parse`` that returns
something with ``name``, ``rate``, ``frames`` and ``pcm``. What varies is how
much the format knows about the sound: AKAI carries root key, tuning and loops
in a header ahead of the audio; E-mu carries a rate and nothing else; Roland
keeps its parameters in a different region of the disc entirely, so its
filesystem layer hands them over on the ``File``.

None of them alter a sample value. A sampler payload becomes a WAV data chunk
unchanged; AIFF alone is re-ordered, because its samples are big-endian and a
WAV's are little-endian, and reversing the bytes within a value is not the same
as changing it (ADR-0011, ADR-0024).
"""

from __future__ import annotations


class NotASample(ValueError):
    """A payload that cannot be used as audio.

    Each format raises its own subclass, so a caller can catch this one thing
    rather than a tuple that grows by one every time a backend is added.
    """
