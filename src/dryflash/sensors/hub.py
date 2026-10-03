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

from ..qmp import QmpError
from .display import read_text, text_art, write_png
from .gpio import GpioBank, GpioSpecError, check_pad, window_stats
from .link import ClockLink, GpioLink, LinkError, SensorLink
from .models import SensorModel, SensorSpecError, Ssd1306, make_model

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
    def __init__(self, session: Any, models: list[SensorModel], gpio: GpioBank | None = None):
        self.session = session
        self.models = models
        self.gpio = gpio
        self.links: list[SensorLink] = []
        self.clock: ClockLink | None = None
        self.gpio_link: GpioLink | None = None
        self.horizon = 0
        self.user_target: int | None = None
        self.user_paused = False
        self._user_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stop_tasks: set[asyncio.Task] = set()
        self.refills = 0
        self._closing = False
        self.stop_error: str | None = None

    @property
    def slicing(self) -> bool:
        """Run in virtual-time slices (pause at each horizon) when there is anything to feed in."""
        return bool(self.models) or bool(self.gpio and self.gpio.declared)

    # ----- QEMU wiring ---------------------------------------------------------------------------
    def _sock(self, name: str) -> Path:
        return Path(self.session.run_dir) / f"{name}.sock"

    def qemu_args(self) -> list[str]:
        args = ["-chardev", f"socket,id=simclk,path={self._sock('simclk')},server=on,wait=off",
                "-device", "sim-clock,chardev=simclk"]
        if self.gpio is not None:
            args += ["-chardev", f"socket,id=simgpio,path={self._sock('simgpio')},server=on,wait=off",
                     "-device", "sim-gpio,chardev=simgpio"]
        for i, m in enumerate(self.models):
            if m.interface == "spi":
                dev = "ssi-sim-sensor"
                props = [f"bus={m.bus}", f"cs={m.cs}", f"chardev=sens{i}"]
                if m.cs_gpio is not None:
                    props.append(f"cs-gpio={m.cs_gpio}")
            else:
                dev = "i2c-sim-sensor"
                props = [f"bus=i2c-bus.{m.bus}", f"address=0x{m.address:02x}", f"chardev=sens{i}"]
            props += [f"{k}={_qemu_opt(v)}" for k, v in m.device_props().items()]
            args += ["-chardev", f"socket,id=sens{i},path={self._sock(f'sens{i}')},server=on,wait=off",
                     "-device", dev + "," + ",".join(props)]
        return args

    async def connect(self) -> None:
        """Connect to the freshly started (still halted) QEMU and preload the first slices."""
        self._closing = False
        self.stop_error = None
        self.clock = await ClockLink.connect(self._sock("simclk"), on_stopped=self._on_stopped)
        self.links = [await SensorLink.connect(self._sock(f"sens{i}"), on_guest_write=m.on_guest_write,
                                               on_stream=m.on_stream)
                      for i, m in enumerate(self.models)]
        if self.gpio is not None:
            self.gpio.traces.clear()  # a restarted QEMU starts with every pad low
            self.gpio_link = await GpioLink.connect(self._sock("simgpio"), on_change=self.gpio.on_change)
            await self.gpio_link.send([GpioLink.level_line(*e) for e in self.gpio.initial_lines()])
        self.horizon = 0
        if self.slicing:
            for m, link in zip(self.models, self.links):
                await link.send(_initial_lines(m) + sample_lines(m, 0, PREFILL_NS))
            await self._flush_gpio()
            await self._sync_all()
            self.horizon = PREFILL_NS

    async def _sync_all(self) -> None:
        links = self.links + ([self.gpio_link] if self.gpio_link is not None else [])
        await asyncio.gather(*(link.sync() for link in links))

    async def _flush_gpio(self) -> None:
        if self.gpio is not None and self.gpio_link is not None:
            await self.gpio_link.send([GpioLink.level_line(*e) for e in self.gpio.take_pending()])

    # ----- virtual-time control --------------------------------------------------------------------
    async def arm(self) -> None:
        if self.clock is None:
            return
        targets = [t for t in (self.user_target, self.horizon if self.slicing else None) if t is not None]
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
        if self._closing:
            return  # a final stop event racing the session's shutdown
        t = asyncio.create_task(self._handle_stop(ns))
        self._stop_tasks.add(t)
        t.add_done_callback(self._stop_tasks.discard)

    async def _handle_stop(self, ns: int) -> None:
        try:
            await self._handle_stop_locked(ns)
        except (ConnectionError, LinkError, QmpError) as e:
            # QEMU going away mid-refill is expected while the session stops; anything else is
            # recorded (and wakes a waiting emu_run_for) instead of dying as an orphaned task.
            if self._closing or not self.session.alive:
                return
            self.stop_error = f"{type(e).__name__}: {e}"
            self._user_event.set()

    async def _handle_stop_locked(self, ns: int) -> None:
        async with self._lock:
            if self.slicing and ns >= self.horizon:
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
        await self._flush_gpio()
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
        while not self._user_event.is_set() or self.stop_error:
            if self.stop_error:
                raise RuntimeError(f"virtual-time control failed: {self.stop_error}")
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

    # ----- GPIO ------------------------------------------------------------------------------------
    def _require_gpio(self) -> GpioBank:
        if self.gpio is None or self.gpio_link is None:
            raise SensorSpecError("GPIO injection needs the dryflash-sensors image (patched QEMU with sim-gpio)")
        return self.gpio

    async def gpio_events(self, events: list[tuple[float | None, Any, int]]) -> dict:
        """Apply pad levels [(at_ms or None for now, pin, level)] from outside the chip."""
        gpio = self._require_gpio()
        async with self._lock:
            now = await self.now()
            planned = []
            for at_ms, pin, level in events:
                pad = check_pad(pin)
                t = round(at_ms * 1e6) if at_ms is not None else now
                planned.append((max(t, now), pad, 1 if level else 0))
            running = self.session.state == "running"
            # Deterministic only if QEMU is touched while the VM is stopped: either it is paused now,
            # or every event lies beyond the horizon and goes out with the next slice.
            if not running:
                mode = "sent while paused"
                await self.gpio_link.send([GpioLink.level_line(*e) for e in planned])
                await self.gpio_link.sync()
            elif self.slicing and all(t >= self.horizon for t, _, _ in planned):
                mode = "queued for the next slice"
                for e in planned:
                    gpio.schedule(*e)
            else:
                mode = "sent while running"
                await self.gpio_link.send([GpioLink.level_line(*e) for e in planned])
                await self.gpio_link.sync()
        return {"events": [{"pin": p, "level": lv, "at_ms": t / 1e6} for t, p, lv in planned],
                "deterministic": mode != "sent while running", "delivery": mode,
                **({"note": "the board was running and the time was not beyond the next slice; declare the "
                            "pin in gpio at emu_start and give at_ms ahead of the current time (or pause "
                            "first) for reproducible timing"} if mode == "sent while running" else {})}

    async def gpio_pulse(self, pin: Any, width_ms: float, at_ms: float | None = None,
                         level: int | None = None) -> dict:
        gpio = self._require_gpio()
        pad = check_pad(pin)
        if width_ms <= 0:
            raise GpioSpecError("width_ms must be positive")
        active = (1 - gpio.default_of(pad)) if level is None else (1 if level else 0)
        start = at_ms if at_ms is not None else (await self.now()) / 1e6
        return await self.gpio_events([(start, pad, active), (start + width_ms, pad, 1 - active)])

    async def gpio_read(self, pin: Any) -> dict:
        gpio = self._require_gpio()
        pad = check_pad(pin)
        await self.gpio_link.sync()
        now = await self.now()
        return {"pin": pad, "level": gpio.level(pad, now), "virtual_ms": now / 1e6,
                "declared_default": gpio.defaults.get(pad)}

    async def gpio_trace(self, pin: Any, cursor: int = 0, max_edges: int = 200) -> dict:
        gpio = self._require_gpio()
        pad = check_pad(pin)
        await self.gpio_link.sync()
        out = gpio.trace(pad, cursor, max_edges)
        out["virtual_ms_now"] = (await self.now()) / 1e6
        return out

    async def gpio_window(self, pin: Any, window_ms: float) -> dict:
        """Run exactly window_ms of virtual time (then stay paused) and summarise the pad over it."""
        gpio = self._require_gpio()
        pad = check_pad(pin)
        delta = round(window_ms * 1e6)
        end = await self.run_until_offset(delta)
        start = end - delta  # the window starts where run_until_offset read the clock
        await self.gpio_link.sync()
        edges = gpio.edges(pad, start, end)
        stats = window_stats(edges, start, end)
        stats.update(pin=pad, level_at_end=gpio.level(pad, end))
        return stats

    # ----- displays --------------------------------------------------------------------------------
    async def display_snapshot(self, sensor: str, png_path: Path | None = None) -> dict:
        m = self.model(sensor)
        if not isinstance(m, Ssd1306):
            raise SensorSpecError(f"sensor {sensor!r} is a {m.model}, not a display (ssd1306)")
        await self.links[self.models.index(m)].sync()  # every write transfer so far has been decoded
        img = m.display.image()
        out = m.display.describe()
        out.update(text_art(img))
        out["text"] = read_text(img)
        out["virtual_ms"] = (await self.now()) / 1e6
        out["last_write_ms"] = m.last_write_ns / 1e6 if m.last_write_ns is not None else None
        if png_path is not None:
            write_png(img, png_path)
            out["png"] = str(png_path)
        return out

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
        self._closing = True
        tasks = list(self._stop_tasks)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for link in self.links:
            await link.close()
        if self.gpio_link is not None:
            await self.gpio_link.close()
        if self.clock is not None:
            await self.clock.close()
        self.links, self.clock, self.gpio_link = [], None, None


async def attach_sensors(session: Any, specs: list[dict], gpio_specs: list[dict] | None = None) -> list[str]:
    """Create the session's SensorHub if its QEMU has the sim devices; return extra QEMU args."""
    caps = await qemu_devices(session.target.qemu)
    if (specs or gpio_specs) and not session.target.sensors:
        raise SensorSpecError(f"sensors and GPIO injection are supported only on esp32, not {session.target.name}")
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
    i2c = [(m.bus, m.address) for m in models if m.interface == "i2c"]
    if len(set(i2c)) != len(i2c):
        raise SensorSpecError("two I2C sensors share a bus and address")
    spi = [(m.bus, m.cs) for m in models if m.interface == "spi"]
    if len(set(spi)) != len(spi):
        raise SensorSpecError("two SPI sensors share a bus and cs line; give each its own cs (0-2), "
                              "also when chip select comes from cs_gpio")
    if spi and "ssi-sim-sensor" not in caps:
        raise SensorSpecError("this QEMU has no ssi-sim-sensor device: SPI sensors need a newer "
                              "dryflash-sensors image")
    gpio = None
    if "sim-gpio" in caps:
        gpio = GpioBank(gpio_specs)
        for m in models:
            if m.interface == "spi" and m.cs_gpio is not None:
                gpio.add_default(m.cs_gpio, 1, f"sensor {m.name} (cs_gpio)")  # CS idles high
    elif gpio_specs or any(m.interface == "spi" and m.cs_gpio is not None for m in models):
        raise SensorSpecError("this QEMU has no sim-gpio device: GPIO injection and cs_gpio need a "
                              "newer dryflash-sensors image")
    hub = SensorHub(session, models, gpio)
    session.sensors = hub
    session.vclock = hub
    return hub.qemu_args()
