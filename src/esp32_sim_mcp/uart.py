"""UART capture: a ring buffer addressed by absolute byte offsets ("cursors").

MCP has no server push, so clients poll with a cursor; offsets keep counting past the ring's
capacity, and a read from an offset that has already been overwritten reports how many bytes
were dropped instead of failing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReadResult:
    data: bytes
    next_cursor: int
    dropped: int


@dataclass
class Match:
    start_offset: int
    end_offset: int
    _m: re.Match

    def group(self, *args):
        return self._m.group(*args)

    def groups(self):
        return self._m.groups()


class UartBuffer:
    def __init__(self, capacity: int = 4 * 1024 * 1024):
        self.capacity = capacity
        self._buf = bytearray()
        self.start = 0  # absolute offset of _buf[0]

    @property
    def total(self) -> int:
        return self.start + len(self._buf)

    def append(self, data: bytes) -> None:
        self._buf += data
        excess = len(self._buf) - self.capacity
        if excess > 0:
            del self._buf[:excess]
            self.start += excess

    def _clamp(self, offset: int) -> int:
        return min(max(offset, self.start), self.total)

    def read(self, cursor: int, max_bytes: int) -> ReadResult:
        dropped = max(0, self.start - cursor)
        begin = self._clamp(cursor)
        end = min(begin + max(0, max_bytes), self.total)
        return ReadResult(bytes(self._buf[begin - self.start:end - self.start]), end, dropped)

    def slice(self, begin: int, end: int) -> bytes:
        b, e = self._clamp(begin), self._clamp(end)
        return bytes(self._buf[b - self.start:e - self.start])

    def tail(self, n: int) -> bytes:
        return self.slice(self.total - n, self.total)

    def last_line_end(self) -> int:
        """Absolute offset just past the last newline (== start if there is none)."""
        return self.start + self._buf.rfind(b"\n") + 1

    def search(self, pattern: re.Pattern[bytes], cursor: int, end: int | None = None) -> Match | None:
        begin = self._clamp(cursor)
        stop = self._clamp(self.total if end is None else end)
        if stop < begin:
            return None
        m = pattern.search(self._buf, begin - self.start, stop - self.start)
        if m is None:
            return None
        return Match(m.start() + self.start, m.end() + self.start, m)
