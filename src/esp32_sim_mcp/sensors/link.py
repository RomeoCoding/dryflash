"""Line-protocol clients for the QEMU i2c-sim-sensor and sim-clock chardevs (see qemu-patches/)."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Callable


class LinkError(RuntimeError):
    pass


class _LineLink:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader, self._writer = reader, writer
        self._seq = itertools.count(1)
        self._waiters: dict[str, asyncio.Future] = {}
        self.errors: list[str] = []
        self._task = asyncio.create_task(self._read_loop())

    @classmethod
    async def connect(cls, path: Path, timeout: float = 10.0, **kw):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(str(path))
                return cls(reader, writer, **kw)
            except (FileNotFoundError, ConnectionRefusedError):
                if loop.time() >= deadline:
                    raise LinkError(f"chardev socket {path} did not accept connections within {timeout}s")
                await asyncio.sleep(0.05)

    async def _read_loop(self) -> None:
        try:
            while line := await self._reader.readline():
                f = line.decode(errors="replace").split()
                if f:
                    self._dispatch(f)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            for fut in self._waiters.values():
                if not fut.done():
                    fut.set_exception(LinkError("chardev link closed (QEMU exited?)"))

    def _dispatch(self, f: list[str]) -> None:
        if f[0] == "E":
            self.errors.append(" ".join(f[1:]))
            del self.errors[:-50]

    def _resolve(self, seq: str, value: int) -> None:
        fut = self._waiters.pop(seq, None)
        if fut is not None and not fut.done():
            fut.set_result(value)

    async def send(self, lines: list[str]) -> None:
        if lines:
            self._writer.write(("\n".join(lines) + "\n").encode())
            await self._writer.drain()

    async def _request(self, fmt: str, timeout: float = 30.0) -> int:
        seq = str(next(self._seq))
        fut = asyncio.get_running_loop().create_future()
        self._waiters[seq] = fut
        await self.send([fmt.format(seq=seq)])
        return await asyncio.wait_for(fut, timeout)

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass
        self._task.cancel()


class SensorLink(_LineLink):
    def __init__(self, reader, writer, on_guest_write: Callable[[int, bytes], None] | None = None):
        self._on_guest_write = on_guest_write
        super().__init__(reader, writer)

    def _dispatch(self, f):
        if f[0] == "A" and len(f) == 3:
            self._resolve(f[1], int(f[2]))
        elif f[0] == "G" and len(f) == 4 and self._on_guest_write:
            self._on_guest_write(int(f[2]), bytes.fromhex(f[3]))
        else:
            super()._dispatch(f)

    async def sync(self) -> int:
        """Round trip: returns once QEMU has processed every earlier line; value is virtual ns."""
        return await self._request("S {seq}")


class ClockLink(_LineLink):
    def __init__(self, reader, writer, on_stopped: Callable[[int], None] | None = None):
        self._on_stopped = on_stopped
        super().__init__(reader, writer)

    def _dispatch(self, f):
        if f[0] == "T" and len(f) == 3:
            self._resolve(f[1], int(f[2]))
        elif f[0] == "X" and len(f) == 2 and self._on_stopped:
            self._on_stopped(int(f[1]))
        else:
            super()._dispatch(f)

    async def now(self) -> int:
        return await self._request("N {seq}")

    async def stop_at(self, virtual_ns: int) -> int:
        return await self._request("S {seq} " + str(int(virtual_ns)))

    async def cancel(self) -> int:
        return await self._request("C {seq}")
