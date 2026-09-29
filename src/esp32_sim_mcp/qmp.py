"""Small asyncio QMP (QEMU Machine Protocol) client over a Unix socket."""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any


class QmpError(RuntimeError):
    pass


class QmpClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, greeting: dict):
        self._reader, self._writer = reader, writer
        v = greeting["QMP"]["version"]["qemu"]
        self.version = f"{v['major']}.{v['minor']}.{v['micro']}"
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self.events: list[dict] = []
        self._event_cond = asyncio.Condition()
        self.closed = asyncio.Event()
        self._task = asyncio.create_task(self._read_loop())

    @classmethod
    async def connect(cls, path: Path, timeout: float = 10.0) -> "QmpClient":
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if loop.time() >= deadline:
                    raise TimeoutError(f"QMP socket {path} did not accept connections within {timeout}s")
                await asyncio.sleep(0.05)
        greeting = json.loads(await asyncio.wait_for(reader.readline(), timeout))
        client = cls(reader, writer, greeting)
        await client.execute("qmp_capabilities")
        return client

    async def _read_loop(self) -> None:
        try:
            while line := await self._reader.readline():
                msg = json.loads(line)
                if "event" in msg:
                    async with self._event_cond:
                        self.events.append(msg)
                        self._event_cond.notify_all()
                elif (fut := self._pending.pop(msg.get("id"), None)) is not None and not fut.done():
                    fut.set_result(msg)
        except (ConnectionError, json.JSONDecodeError):
            pass
        finally:
            self.closed.set()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(QmpError("QMP connection closed (QEMU exited?)"))
            async with self._event_cond:
                self._event_cond.notify_all()

    async def execute(self, command: str, timeout: float = 30.0, **arguments: Any) -> Any:
        if self.closed.is_set():
            raise QmpError("QMP connection closed (QEMU exited?)")
        mid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        msg: dict[str, Any] = {"execute": command, "id": mid}
        if arguments:
            msg["arguments"] = arguments
        self._writer.write(json.dumps(msg).encode() + b"\n")
        await self._writer.drain()
        resp = await asyncio.wait_for(fut, timeout)
        if "error" in resp:
            raise QmpError(f"{command}: {resp['error'].get('class')}: {resp['error'].get('desc')}")
        return resp.get("return")

    async def wait_event(self, name: str, timeout: float, since: int | None = None) -> dict:
        """Wait for event `name` at index >= since (default: only events that arrive from now on)."""
        start = len(self.events) if since is None else since

        def find():
            return next((e for e in self.events[start:] if e["event"] == name), None)

        async with self._event_cond:
            await asyncio.wait_for(
                self._event_cond.wait_for(lambda: find() is not None or self.closed.is_set()), timeout)
        ev = find()
        if ev is None:
            raise QmpError(f"QMP closed while waiting for {name}")
        return ev

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass
        self._task.cancel()
