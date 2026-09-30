"""Per-session sensor injection and virtual-time control on top of the patched QEMU.

Determinism: sensor samples are sent ahead of the guest up to a "horizon" in virtual time, and the
sim-clock device pauses the VM exactly at the horizon. While paused the hub sends the next slice,
waits until every sensor device has acknowledged it (so the data is queued inside QEMU), moves the
horizon and resumes. The guest therefore never reaches a virtual time whose data is still in
flight, however slow the host is. User requests to stop at a virtual time (emu_run_for) share the
same stop mechanism.
"""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
from typing import Any

from .link import ClockLink, SensorLink
from .models import SensorModel, SensorSpecError, make_model

CHUNK_NS = int(os.environ.get("DRYFLASH_CHUNK_NS", 100_000_000))  # refill slice (virtual ns)
PREFILL_NS = int(os.environ.get("DRYFLASH_PREFILL_NS", 2 * CHUNK_NS))

_caps_cache: dict[str, set[str]] = {}


async def qemu_devices(qemu: str) -> set[str]:
    """Device types a QEMU binary knows (cached): tells the stock and sensors images apart."""
    if qemu not in _caps_cache:
        proc = await asyncio.create_subprocess_exec(
            qemu, "-machine", "none", "-device", "help", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        names = set()
        for line in out.decode(errors="replace").splitlines():
            line = line.strip()
            if line.startswith('name "'):
                names.add(line.split('"')[1])
        _caps_cache[qemu] = names
    return _caps_cache[qemu]


def sample_lines(model: SensorModel, start_ns: int, end_ns: int) -> list[str]:
    """W commands for every sample of `model` with start_ns <= t < end_ns on its rate grid."""
    period = 1e9 / model.rate_hz
    k = max(0, math.floor(start_ns / period) - 1)
    lines = []
    while True:
        t = round(k * period)
        k += 1
        if t < start_ns:
            continue
        if t >= end_ns:
            break
        for bank, off, data in model.encode(model.values_at(t)):
            lines.append(f"W {t} {bank} {off} {data.hex()}")
    return lines


def _initial_lines(model: SensorModel) -> list[str]:
    lines = []
    for bank, off, data in model.initial_writes():
        for i in range(0, len(data), 32):
            lines.append(f"W 0 {bank} {off + i} {data[i:i + 32].hex()}")
    return lines


def _qemu_opt(v: str) -> str:
    return str(v).replace(",", ",,")  # commas inside a -device property value are doubled


class SensorHub:
    def __init__(self, session: Any, models: list[SensorModel]):
        self.session = session
        self.models = models
        self.links: list[SensorLink] = []
        self.clock: ClockLink | None = None
        self.horizon = 0
        self.user_target: int | None = None
        self.user_paused = False
        self._user_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stop_tasks: set[asyncio.Task] = set()
        self.refills = 0

    # ----- QEMU wiring ---------------------------------------------------------------------------
    def _sock(self, name: str) -> Path:
        return Path(self.session.run_dir) / f"{name}.sock"

    def qemu_args(self) -> list[str]:
        args = ["-chardev", f"socket,id=simclk,path={self._sock('simclk')},server=on,wait=off",
                "-device", "sim-clock,chardev=simclk"]
        for i, m in enumerate(self.models):
            props = [f"bus=i2c-bus.{m.bus}", f"address=0x{m.address:02x}", f"chardev=sens{i}"]
            props += [f"{k}={_qemu_opt(v)}" for k, v in m.device_props().items()]
            args += ["-chardev", f"socket,id=sens{i},path={self._sock(f'sens{i}')},server=on,wait=off",
                     "-device", "i2c-sim-sensor," + ",".join(props)]
        return args

    async def connect(self) -> None:
        """Connect to the freshly started (still halted) QEMU and preload the first slices."""
        self.clock = await ClockLink.connect(self._sock("simclk"), on_stopped=self._on_stopped)
        self.links = [await SensorLink.connect(self._sock(f"sens{i}"), on_guest_write=m.on_guest_write)
                      for i, m in enumerate(self.models)]
        self.horizon = 0
        if self.models:
            for m, link in zip(self.models, self.links):
                await link.send(_initial_lines(m) + sample_lines(m, 0, PREFILL_NS))
            await self._sync_all()
            self.horizon = PREFILL_NS

    async def _sync_all(self) -> None:
        await asyncio.gather(*(link.sync() for link in self.links))

    # ----- virtual-time control --------------------------------------------------------------------
    async def arm(self) -> None:
        if self.clock is None:
            return
        targets = [t for t in (self.user_target, self.horizon if self.models else None) if t is not None]
        if targets:
            await self.clock.stop_at(min(targets))
        else:
            await self.clock.cancel()

    async def before_resume(self) -> None:
        self.user_paused = False
        await self.arm()

    def on_user_pause(self) -> None:
        self.user_paused = True

    def _on_stopped(self, ns: int) -> None:
        t = asyncio.create_task(self._handle_stop(ns))
        self._stop_tasks.add(t)
        t.add_done_callback(self._stop_tasks.discard)

    async def _handle_stop(self, ns: int) -> None:
        async with self._lock:
            if self.models and ns >= self.horizon:
                await self._refill(ns + CHUNK_NS)
            if self.user_target is not None and ns >= self.user_target:
                self.user_target = None
                self.session.state = "paused"
                self._user_event.set()
                return
            if self.user_paused or not self.session.alive:
                return
            await self.arm()
            await self.session.qmp.execute("cont")

    async def _refill(self, until_ns: int) -> None:
        start, end = self.horizon, max(until_ns, self.horizon + CHUNK_NS)
        for m, link in zip(self.models, self.links):
            await link.send(sample_lines(m, start, end))
        await self._sync_all()
        self.horizon = end
        self.refills += 1

    async def now(self) -> int:
        assert self.clock is not None
        return await self.clock.now()

    async def run_until_offset(self, delta_ns: int, timeout: float = 600.0) -> int:
        """Run until the virtual clock has advanced by delta_ns, then leave the VM paused."""
        now = await self.now()
        self.user_target = now + delta_ns
        self._user_event.clear()
        self.user_paused = False
        await self.arm()
        status = await self.session.qmp.execute("query-status")
        if not status.get("running"):
            await self.session.qmp.execute("cont")
        self.session.state = "running"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self._user_event.is_set():
            if not self.session.alive:
                raise RuntimeError(f"session ended before reaching the target time: {self.session.exit_reason}")
            if loop.time() > deadline:
                raise TimeoutError(f"virtual time target not reached within {timeout}s of wall time")
            try:
                await asyncio.wait_for(self._user_event.wait(), 0.5)
            except asyncio.TimeoutError:
                pass
        return now + delta_ns

    # ----- sensor changes --------------------------------------------------------------------------
    def model(self, name: str) -> SensorModel:
        for m in self.models:
            if m.name == name:
                return m
        raise SensorSpecError(f"no sensor named {name!r}; declared: {', '.join(m.name for m in self.models) or 'none'}")

    async def set(self, sensor: str, values: dict[str, Any] | None = None, at_ms: float | None = None,
                  waveform: dict[str, Any] | None = None) -> dict:
        """Drive channels of `sensor` with new values/waveforms from virtual time at_ms (default: now)."""
        m = self.model(sensor)
        spec = dict(values or {})
        spec.update(waveform or {})
        if not spec:
            raise SensorSpecError("give values (channel -> number or waveform) to apply")
        from_ns = round(at_ms * 1e6) if at_ms is not None else await self.now()
        async with self._lock:
            m.schedule(from_ns, spec)
            resent = 0
            if from_ns < self.horizon:
                # Samples already queued inside QEMU for [from_ns, horizon) are superseded: equal
                # timestamps apply in arrival order, so re-sent samples win.
                lines = sample_lines(m, from_ns, self.horizon)
                await self.links[self.models.index(m)].send(lines)
                await self.links[self.models.index(m)].sync()
                resent = len(lines)
        return {"sensor": sensor, "applies_from_ms": from_ns / 1e6, "channels": sorted(spec),
                "resent_updates": resent}

    async def stream(self, sensor: str, waveform: dict[str, Any], at_ms: float | None = None) -> dict:
        return await self.set(sensor, waveform=waveform, at_ms=at_ms)

    def describe(self) -> list[dict]:
        out = []
        for m, link in zip(self.models, self.links or [None] * len(self.models)):
            d = m.describe()
            if link is not None and link.errors:
                d["device_errors"] = link.errors[-5:]
            out.append(d)
        return out

    # ----- lifecycle -------------------------------------------------------------------------------
    async def before_restart(self) -> None:
        await self.close()
        self.user_target = None
        self.horizon = 0

    async def on_reset(self) -> None:
        pass

    async def close(self) -> None:
        for t in list(self._stop_tasks):
            t.cancel()
        for link in self.links:
            await link.close()
        if self.clock is not None:
            await self.clock.close()
        self.links, self.clock = [], None


async def attach_sensors(session: Any, specs: list[dict]) -> list[str]:
    """Create the session's SensorHub if its QEMU has the sim devices; return extra QEMU args."""
    caps = await qemu_devices(session.target.qemu)
    if specs and not session.target.sensors:
        raise SensorSpecError(f"sensors are supported only on esp32, not {session.target.name}")
    if specs and "i2c-sim-sensor" not in caps:
        raise SensorSpecError("this QEMU has no i2c-sim-sensor device: sensor injection needs the "
                              "dryflash-sensors image (docker/qemu-sensors.Dockerfile)")
    if "sim-clock" not in caps:
        return []
    base = Path(session.config.project_dir) if session.config.project_dir else None
    models = [make_model(s, base) for s in specs]
    names = [m.name for m in models]
    if len(set(names)) != len(names):
        raise SensorSpecError(f"sensor names must be unique: {names}")
    addrs = [(m.bus, m.address) for m in models]
    if len(set(addrs)) != len(addrs):
        raise SensorSpecError("two sensors share a bus and address")
    hub = SensorHub(session, models)
    session.sensors = hub
    session.vclock = hub
    return hub.qemu_args()
