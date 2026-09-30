import asyncio

import pytest

from dryflash.sensors.hub import sample_lines
from dryflash.sensors.link import ClockLink, SensorLink
from dryflash.sensors.models import make_model

pytestmark = pytest.mark.anyio


class FakeDevice:
    """Speaks the i2c-sim-sensor and sim-clock line protocols like the QEMU devices do."""

    def __init__(self, now=0):
        self.lines = []
        self.now = now
        self.writer = None

    async def handle(self, reader, writer):
        self.writer = writer
        while line := await reader.readline():
            text = line.decode().strip()
            self.lines.append(text)
            f = text.split()
            if f[0] == "S" and len(f) == 2:
                writer.write(f"A {f[1]} {self.now}\n".encode())
            elif f[0] == "N":
                writer.write(f"T {f[1]} {self.now}\n".encode())
            elif f[0] == "S" and len(f) == 3:
                writer.write(f"T {f[1]} {self.now}\n".encode())
            elif f[0] == "C":
                writer.write(f"T {f[1]} {self.now}\n".encode())
            await writer.drain()

    async def push(self, text):
        self.writer.write(text.encode())
        await self.writer.drain()


async def serve(tmp_path, name, dev):
    path = tmp_path / name
    server = await asyncio.start_unix_server(dev.handle, path=str(path))
    return server, path


async def test_sensor_link_sync_waits_for_ack(tmp_path):
    dev = FakeDevice(now=1234)
    server, path = await serve(tmp_path, "s.sock", dev)
    link = await SensorLink.connect(path, timeout=2)
    try:
        await link.send(["W 0 -1 0 e5", "W 100 8 50 0001"])
        now = await link.sync()
        assert now == 1234
        assert dev.lines[:2] == ["W 0 -1 0 e5", "W 100 8 50 0001"]
        assert dev.lines[2].startswith("S ")
    finally:
        await link.close()
        server.close()


async def test_sensor_link_reports_guest_writes_and_errors(tmp_path):
    dev = FakeDevice()
    server, path = await serve(tmp_path, "s.sock", dev)
    seen = []
    link = await SensorLink.connect(path, timeout=2, on_guest_write=lambda off, data: seen.append((off, data)))
    try:
        await link.sync()
        await dev.push("G 500 49 0b\nE bad W command\n")
        await link.sync()
        assert seen == [(49, b"\x0b")]
        assert link.errors == ["bad W command"]
    finally:
        await link.close()
        server.close()


async def test_clock_link_now_stop_and_stopped_event(tmp_path):
    dev = FakeDevice(now=5_000)
    server, path = await serve(tmp_path, "c.sock", dev)
    stops = []
    link = await ClockLink.connect(path, timeout=2, on_stopped=stops.append)
    try:
        assert await link.now() == 5_000
        await link.stop_at(9_000)
        assert dev.lines[-1].split()[0] == "S" and dev.lines[-1].split()[2] == "9000"
        await dev.push("X 9000\n")
        await asyncio.sleep(0.05)
        assert stops == [9000]
        await link.cancel()
        assert dev.lines[-1].startswith("C ")
    finally:
        await link.close()
        server.close()


def test_sample_lines_cover_half_open_window_on_the_rate_grid():
    m = make_model({"model": "adxl345", "name": "a", "rate_hz": 1000, "waveform": {"z": 1.0}})
    lines = sample_lines(m, 0, 3_000_000)          # [0, 3 ms) at 1 kHz: t = 0, 1, 2 ms
    times = sorted({int(line.split()[1]) for line in lines})
    assert times == [0, 1_000_000, 2_000_000]
    assert len(lines) == 3 * 8                     # 8 banks per sample
    assert lines[0] == "W 0 0 50 000000000001"     # bank 0 (10-bit +-2g): z = 1 g = 256 = 0x0100 LE
    later = sample_lines(m, 3_000_000, 4_000_000)
    assert {int(line.split()[1]) for line in later} == {3_000_000}


def test_sample_lines_non_integer_period_has_no_drift():
    m = make_model({"model": "ads1115", "name": "a", "rate_hz": 3, "waveform": {"ain0": 1.0}})
    times = sorted({int(line.split()[1]) for line in sample_lines(m, 0, 1_000_000_000)})
    assert times == [0, 333_333_333, 666_666_667]
