"""Flat images: the cooked sectors are already the file. ``.iso``, ``.img``."""

from __future__ import annotations

from samplerdisc.container.base import _FileBacked


class FlatImage(_FileBacked):
    kind = "flat"

    @property
    def size(self) -> int:
        return self._end - self._start

    def read(self, offset: int, length: int) -> bytes:
        return self._raw(offset, length)
