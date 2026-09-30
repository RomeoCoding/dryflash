import asyncio
import json

import pytest

from dryflash.qmp import QmpClient, QmpError


class FakeQmp:
    """Minimal QMP server: greeting, capabilities negotiation, a few commands, async events."""

    def __init__(self):
        self.received = []
        self.status = "prelaunch"

    async def handle(self, reader, writer):
        greeting = {"QMP": {"version": {"qemu": {"major": 9, "minor": 2, "micro": 2}}, "capabilities": []}}
        writer.write(json.dumps(greeting).encode() + b"\r\n")
        await writer.drain()
        while line := await reader.readline():
            msg = json.loads(line)
            self.received.append(msg)
            cmd, mid = msg["execute"], msg.get("id")
            if cmd == "qmp_capabilities":
                resp = {"return": {}}
            elif cmd == "query-status":
                resp = {"return": {"status": self.status, "running": self.status == "running"}}
            elif cmd == "cont":
                self.status = "running"
                writer.write(json.dumps({"event": "RESUME", "timestamp": {}}).encode() + b"\r\n")
                resp = {"return": {}}
            elif cmd == "stop":
                self.status = "paused"
                resp = {"return": {}}
                writer.write(json.dumps({"event": "STOP", "timestamp": {}}).encode() + b"\r\n")
            else:
                resp = {"error": {"class": "CommandNotFound", "desc": f"The command {cmd} has not been found"}}
            if mid is not None:
                resp["id"] = mid
            writer.write(json.dumps(resp).encode() + b"\r\n")
            await writer.drain()


@pytest.fixture
async def fake(tmp_path):
    f = FakeQmp()
    path = tmp_path / "qmp.sock"
    server = await asyncio.start_unix_server(f.handle, path=str(path))
    yield f, path
    server.close()


@pytest.mark.anyio
async def test_connect_negotiates_and_executes(fake):
    f, path = fake
    q = await QmpClient.connect(path, timeout=2)
    try:
        assert q.version == "9.2.2"
        assert f.received[0]["execute"] == "qmp_capabilities"
        st = await q.execute("query-status")
        assert st["status"] == "prelaunch"
        await q.execute("cont")
        ev = await q.wait_event("RESUME", timeout=2, since=0)
        assert ev["event"] == "RESUME"
        assert (await q.execute("query-status"))["running"] is True
    finally:
        await q.close()


@pytest.mark.anyio
async def test_error_raises(fake):
    _, path = fake
    q = await QmpClient.connect(path, timeout=2)
    try:
        with pytest.raises(QmpError, match="CommandNotFound"):
            await q.execute("bogus")
    finally:
        await q.close()


@pytest.mark.anyio
async def test_connect_waits_for_socket_to_appear(tmp_path):
    f = FakeQmp()
    path = tmp_path / "late.sock"

    async def start_late():
        await asyncio.sleep(0.3)
        return await asyncio.start_unix_server(f.handle, path=str(path))

    task = asyncio.create_task(start_late())
    q = await QmpClient.connect(path, timeout=3)
    await q.close()
    (await task).close()


@pytest.mark.anyio
async def test_connect_times_out(tmp_path):
    with pytest.raises(TimeoutError):
        await QmpClient.connect(tmp_path / "never.sock", timeout=0.3)


@pytest.mark.anyio
async def test_wait_event_sees_events_that_arrived_earlier(fake):
    _, path = fake
    q = await QmpClient.connect(path, timeout=2)
    try:
        await q.execute("stop")
        await asyncio.sleep(0.05)
        ev = await q.wait_event("STOP", timeout=1, since=0)
        assert ev["event"] == "STOP"
    finally:
        await q.close()
