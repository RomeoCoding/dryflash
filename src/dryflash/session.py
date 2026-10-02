"""Emulator sessions: one QEMU process with its QMP, UART and (optional) GDB connections."""

from __future__ import annotations

import asyncio
import itertools
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gdbmi import Debugger, _frame
from .procutil import PortAllocator, die_with_parent
from .qemu_cmd import DEFAULT_ICOUNT_SHIFT, QemuOptions, build_qemu_cmdline
from .qmp import QmpClient
from .sensors.hub import attach_sensors
from .targets import get_target
from .uart import UartBuffer

RUN_ROOT = Path(os.environ.get("DRYFLASH_RUN_ROOT", tempfile.gettempdir())) / "dryflash" / "runs"
EFUSE_CACHE = Path(tempfile.gettempdir()) / "dryflash" / "efuse"

# Wall-clock seconds per virtual second measured in M1 (docs/M1_REPORT.md, question 4); used only
# when the emulator cannot stop at an exact virtual time.
_WALL_PER_VIRTUAL = {3: 1.6, 2: 2.9}
_HALT_GRACE_S = 1.0  # how long uart_expect tolerates a halted CPU before reporting it


class SessionError(RuntimeError):
    pass


@dataclass
class SessionConfig:
    target: str
    flash_image: Path
    elf: Path | None = None
    project_dir: Path | None = None
    deterministic: bool = False
    icount_shift: int = DEFAULT_ICOUNT_SHIFT
    wait_for_gdb: bool = False
    reboot: bool = False
    watchdogs: bool = True
    extra_args: list[str] = field(default_factory=list)
    sensors: list[dict[str, Any]] = field(default_factory=list)


async def _default_efuse(target: str) -> Path | None:
    """Default eFuse image for the target, taken from idf.py's own table (chip revision etc.)."""
    EFUSE_CACHE.mkdir(parents=True, exist_ok=True)
    out = EFUSE_CACHE / f"{target}.bin"
    if out.exists():
        return out
    idf = os.environ.get("IDF_PATH")
    py = Path(os.environ.get("IDF_PYTHON_ENV_PATH", "")) / "bin" / "python"
    if not idf or not py.exists():
        return None
    tmp = out.with_suffix(f".{os.getpid()}.tmp")
    code = (f"import sys; sys.path.insert(0, {str(Path(idf) / 'tools')!r}); "
            f"from idf_py_actions.qemu_ext import QEMU_TARGETS; "
            f"open({str(tmp)!r}, 'wb').write(QEMU_TARGETS[{target!r}].default_efuse)")
    proc = await asyncio.create_subprocess_exec(str(py), "-c", code, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL)
    if await proc.wait() != 0 or not tmp.exists():
        return None
    tmp.replace(out)
    return out


class Session:
    def __init__(self, sid: str, config: SessionConfig, gdb_port: int):
        self.id = sid
        self.config = config
        self.target = get_target(config.target)
        self.gdb_port = gdb_port
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        self.run_dir = Path(tempfile.mkdtemp(prefix=f"{sid}-", dir=RUN_ROOT))
        self.uart = UartBuffer()
        self._uart_cond = asyncio.Condition()
        self._uart_writer: asyncio.StreamWriter | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.qmp: QmpClient | None = None
        self.gdb: Debugger | None = None
        # SensorHub: sensor injection and exact virtual-time stops; only with the patched QEMU.
        self.sensors: Any = None
        self.vclock: Any = None
        self.state = "starting"
        self.exit_code: int | None = None
        self.exit_reason: str | None = None
        self.started_at = time.monotonic()
        self.stderr = UartBuffer(capacity=64 * 1024)
        self.cmdline: list[str] = []
        self._tasks: list[asyncio.Task] = []
        self._exited = asyncio.Event()
        self._extra_args: list[str] = []
        self.resets = 0

    # ----- lifecycle -------------------------------------------------------------------------
    async def start(self, extra_args: list[str] | None = None) -> None:
        cfg = self.config
        if not cfg.flash_image.is_file():
            raise SessionError(f"flash image {cfg.flash_image} not found; run project_build first")
        # QEMU writes to the flash image (NVS, OTA); keep the build artefact pristine.
        shutil.copyfile(cfg.flash_image, self.run_dir / "flash.bin")
        efuse = await _default_efuse(self.target.name)
        if efuse is not None:
            shutil.copyfile(efuse, self.run_dir / "efuse.bin")
        self._extra_args = list(extra_args or [])
        await self._launch()

    async def _launch(self) -> None:
        cfg = self.config
        efuse = self.run_dir / "efuse.bin"
        opts = QemuOptions(target=self.target, flash=self.run_dir / "flash.bin",
                           efuse=efuse if efuse.exists() else None, run_dir=self.run_dir,
                           gdb_port=self.gdb_port, deterministic=cfg.deterministic,
                           icount_shift=cfg.icount_shift, reboot=cfg.reboot, watchdogs=cfg.watchdogs,
                           extra_args=self._extra_args + list(cfg.extra_args))
        self.cmdline = build_qemu_cmdline(opts)
        # Sockets left by a previous QEMU (emu_reset) must not be mistaken for the new ones.
        for sock in self.run_dir.glob("*.sock"):
            sock.unlink(missing_ok=True)
        self._exited = asyncio.Event()
        self.exit_code = self.exit_reason = None
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmdline, cwd=self.run_dir, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, preexec_fn=die_with_parent)
        self._tasks.append(asyncio.create_task(self._pump_stderr()))
        self._tasks.append(asyncio.create_task(self._watch_exit(self.proc, self._exited)))
        try:
            self.qmp = await self._race_exit(QmpClient.connect(opts.qmp_socket, timeout=15))
            reader, self._uart_writer = await self._race_exit(self._connect_uart(opts.uart_socket))
            self._tasks.append(asyncio.create_task(self._pump_uart(reader)))
        except BaseException:
            await self.stop()
            raise
        self.state = "paused"

    async def _race_exit(self, coro):
        task = asyncio.ensure_future(coro)
        exited = asyncio.ensure_future(self._exited.wait())
        done, _ = await asyncio.wait({task, exited}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            exited.cancel()
            return task.result()
        task.cancel()
        raise SessionError(f"QEMU exited during start-up (code {self.exit_code}): "
                           f"{self.stderr.tail(2000).decode(errors='replace').strip()}")

    async def _connect_uart(self, path: Path):
        for _ in range(200):
            try:
                return await asyncio.open_unix_connection(str(path))
            except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError):
                await asyncio.sleep(0.05)
        raise SessionError(f"UART socket {path} never appeared")

    async def _pump_uart(self, reader: asyncio.StreamReader) -> None:
        while data := await reader.read(65536):
            async with self._uart_cond:
                self.uart.append(data)
                self._uart_cond.notify_all()

    async def _pump_stderr(self) -> None:
        assert self.proc and self.proc.stdout
        while data := await self.proc.stdout.read(4096):
            self.stderr.append(data)

    async def _watch_exit(self, proc: asyncio.subprocess.Process, exited: asyncio.Event) -> None:
        code = await proc.wait()
        if self.state not in ("stopped", "restarting"):
            self.exit_code = code
            self.state = "exited"
            text = self.uart.tail(8000).decode(errors="replace")
            self.exit_reason = ("guest reset (panic, watchdog or esp_restart; sessions run with -no-reboot)"
                                if code == 0 else f"QEMU exited with code {code}")
            if "Rebooting..." in text:
                self.exit_reason = "guest reset after a crash (see decode_panic)"
        exited.set()
        async with self._uart_cond:
            self._uart_cond.notify_all()

    async def wait_exit(self, timeout: float) -> None:
        await asyncio.wait_for(self._exited.wait(), timeout)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None and self.state not in ("exited", "stopped")

    def _require_alive(self) -> None:
        if not self.alive:
            raise SessionError(f"session {self.id} is {self.state}"
                               + (f": {self.exit_reason}" if self.exit_reason else "")
                               + ". UART output is still readable; call emu_stop to release it.")

    async def _terminate_process(self) -> None:
        if self.gdb is not None:
            try:
                await asyncio.wait_for(self.gdb.close(), 5)
            except Exception:
                pass
            self.gdb = None
        if self.qmp is not None and self.proc is not None and self.proc.returncode is None:
            try:
                await self.qmp.execute("quit", timeout=3)
            except Exception:
                pass
        if self.proc is not None and self.proc.returncode is None:
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self.qmp is not None:
            await self.qmp.close()
            self.qmp = None
        if self._uart_writer is not None:
            self._uart_writer.close()
            self._uart_writer = None
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def stop(self) -> None:
        prev, self.state = self.state, "stopped"
        if self.sensors is not None:
            try:
                await self.sensors.close()
            except Exception:
                pass
        await self._terminate_process()
        shutil.rmtree(self.run_dir, ignore_errors=True)
        if prev == "exited":
            self.state = "exited"

    # ----- run control -----------------------------------------------------------------------
    async def resume(self) -> None:
        self._require_alive()
        if self.sensors is not None:
            await self.sensors.before_resume()
        if self.gdb is not None:
            if self.gdb.state == "stopped":
                await self.gdb.command("-exec-continue")
        else:
            assert self.qmp
            await self.qmp.execute("cont")
        self.state = "running"

    async def pause(self) -> None:
        self._require_alive()
        if self.sensors is not None:
            self.sensors.on_user_pause()
        if self.gdb is not None:
            await self.gdb.interrupt()
        else:
            assert self.qmp
            await self.qmp.execute("stop")
        self.state = "paused"

    async def reset(self) -> dict:
        """Power-cycle the board: restart QEMU with the same flash file (NVS contents persist).

        QMP system_reset is not used: on the esp32 machine it is followed by a TG0 watchdog reset
        from the ROM (docs/UPSTREAM_ISSUES.md), which -no-reboot turns into a shutdown.
        """
        if self.state == "stopped":
            raise SessionError(f"session {self.id} is stopped")
        resume = self.state != "paused"  # an exited or running board comes back running
        cursor = self.uart.total
        self.state = "restarting"
        if self.sensors is not None:
            await self.sensors.before_restart()
        await self._terminate_process()
        await self._launch()
        if self.sensors is not None:
            await self.sensors.connect()
        self.resets += 1
        if resume and not self.config.wait_for_gdb:
            await self.resume()
        return {"uart_cursor_at_reset": cursor, "state": self.state}

    async def run_for(self, virtual_ms: int) -> dict:
        """Run for virtual_ms of emulated time, then pause."""
        self._require_alive()
        if self.vclock is not None:
            t_ns = await self.vclock.run_until_offset(virtual_ms * 1_000_000)
            self.state = "paused"
            return {"virtual_ms": virtual_ms, "exact": True, "virtual_time_ns": t_ns}
        if self.config.deterministic:
            ratio = _WALL_PER_VIRTUAL.get(self.config.icount_shift, 1.6)
        else:
            ratio = 1.0
        if self.state != "running":
            await self.resume()
        await asyncio.sleep(virtual_ms / 1000 * ratio)
        if self.alive:
            await self.pause()
        return {"virtual_ms": virtual_ms, "exact": False,
                "note": "stock QEMU cannot stop at an exact virtual time; this ran for an estimated "
                        f"{virtual_ms * ratio:.0f} ms of wall time. The sensors image stops exactly."}

    # ----- UART ------------------------------------------------------------------------------
    def uart_read(self, cursor: int, max_bytes: int) -> dict:
        r = self.uart.read(cursor, max_bytes)
        return {"text": r.data.decode(errors="replace"), "cursor": r.next_cursor, "dropped_bytes": r.dropped,
                "at_end": r.next_cursor >= self.uart.total, "session_state": self.state}

    async def uart_write(self, data: bytes) -> None:
        self._require_alive()
        assert self._uart_writer
        self._uart_writer.write(data)
        await self._uart_writer.drain()

    async def uart_expect(self, pattern: str, timeout: float, cursor: int | None = None,
                          context_bytes: int = 400, complete_lines: bool = True) -> dict:
        """complete_lines: only match text up to the last newline received, so a pattern such as
        'value=(\\d+)' cannot match a line that is still arriving ("value=1" of "value=12")."""
        rx = re.compile(pattern.encode())
        start = self.uart.start if cursor is None else cursor
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        halted_since: float | None = None
        async with self._uart_cond:
            while True:
                m = self.uart.search(rx, start, self.uart.last_line_end() if complete_lines else None)
                if m is None and complete_lines and self._exited.is_set():
                    m = self.uart.search(rx, start)  # the final unterminated line counts once QEMU is gone
                if m is not None:
                    return {
                        "matched": True,
                        "match": m.group(0).decode(errors="replace"),
                        "groups": [g.decode(errors="replace") if g is not None else None for g in m.groups()],
                        "cursor": m.end_offset,
                        "context_before": self.uart.slice(m.start_offset - context_bytes,
                                                          m.start_offset).decode(errors="replace"),
                        "context_after": self.uart.slice(m.end_offset,
                                                         m.end_offset + 200).decode(errors="replace"),
                    }
                now = loop.time()
                remaining = deadline - now
                # A halted CPU prints nothing, so waiting out the timeout only hides why. The grace
                # period lets a resume that races with this call (emu_continue just before) win.
                halt = self.halt_reason()
                halted_since = (halted_since or now) if halt else None
                halted_too_long = halt is not None and now - halted_since >= _HALT_GRACE_S
                if remaining <= 0 or self._exited.is_set() or halted_too_long:
                    if self._exited.is_set():
                        reason = f"session {self.state}: {self.exit_reason}"
                    elif halted_too_long:
                        reason = halt
                    else:
                        reason = "timeout"
                    return {
                        "matched": False,
                        "reason": reason,
                        "cursor": self.uart.total,
                        "tail": self.uart.slice(max(start, self.uart.total - 1500),
                                                self.uart.total).decode(errors="replace"),
                    }
                try:
                    # wake up periodically even without output, to notice a halt
                    await asyncio.wait_for(self._uart_cond.wait(), min(remaining, 0.25))
                except asyncio.TimeoutError:
                    pass

    def halt_reason(self) -> str | None:
        """Why the CPU cannot produce output right now (paused or stopped in the debugger), or None."""
        if self._exited.is_set():
            return None
        if self.gdb is not None and self.gdb.state == "stopped":
            stop = self.gdb.last_stop or {}
            f = _frame(stop.get("frame"), getattr(self.gdb, "source_root", None)) or {}
            where = ""
            if f.get("function"):
                where = f" in {f['function']}"
                if f.get("file") and f.get("line"):
                    where += f" ({f['file']}:{f['line']})"
            why = stop.get("reason") or "stopped"
            return (f"halted: the CPU is stopped in the debugger ({why}{where}), so no UART output can "
                    "arrive; resume it with gdb_continue or emu_continue, then call uart_expect again")
        if self.state == "paused":
            return ("halted: the session is paused, so no UART output can arrive; resume it with "
                    "emu_continue, then call uart_expect again")
        return None

    # ----- debugger --------------------------------------------------------------------------
    async def debugger(self) -> Debugger:
        """Attach GDB on first use. Attaching halts the CPU; the previous run state is restored."""
        if self.gdb is not None and self.gdb.state != "exited":
            return self.gdb
        self._require_alive()
        if self.config.elf is None or not self.config.elf.is_file():
            raise SessionError("this session has no ELF file, so there are no symbols to debug with")
        was_running = self.state == "running"
        self.gdb = await Debugger.start([self.target.gdb], elf=self.config.elf, port=self.gdb_port,
                                        source_root=self.config.project_dir)
        if was_running:
            await self.gdb.command("-exec-continue")
        return self.gdb

    def status(self) -> dict:
        st = self.state
        if self.gdb is not None and self.alive:
            st = "running" if self.gdb.state == "running" else "debug-halted"
        return {
            "session_id": self.id,
            "state": st,
            "target": self.target.name,
            "deterministic": self.config.deterministic,
            "uptime_s": round(time.monotonic() - self.started_at, 1),
            "uart_bytes": self.uart.total,
            "gdb_attached": self.gdb is not None,
            "gdb_port": self.gdb_port,
            "resets": self.resets,
            "exit_code": self.exit_code,
            "exit_reason": self.exit_reason,
            "sensors": self.sensors.describe() if self.sensors is not None else [],
            "virtual_time_control": self.sensors is not None,
            "exact_run_for": self.vclock is not None,
            "elf": str(self.config.elf) if self.config.elf else None,
        }


class SessionNotFound(KeyError):
    def __str__(self):
        return self.args[0]


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._ids = itertools.count(1)
        self._ports = PortAllocator()

    async def start(self, config: SessionConfig) -> Session:
        port = self._ports.allocate()
        s = Session(f"s{next(self._ids)}", config, port)
        self._sessions[s.id] = s
        try:
            # Adds the sim-clock (and any declared sensors) when this QEMU has the patched devices.
            extra = await attach_sensors(s, config.sensors)
            await s.start(extra)
            if s.sensors is not None:
                await s.sensors.connect()
            if not config.wait_for_gdb:
                await s.resume()
        except BaseException:
            self._sessions.pop(s.id, None)
            self._ports.release(port)
            await s.stop()
            raise
        return s

    def get(self, sid: str) -> Session:
        try:
            return self._sessions[sid]
        except KeyError:
            active = ", ".join(self._sessions) or "none"
            raise SessionNotFound(f"no session {sid!r} (active sessions: {active}); start one with emu_start")

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    async def stop(self, sid: str) -> None:
        s = self.get(sid)
        self._sessions.pop(sid, None)
        self._ports.release(s.gdb_port)
        await s.stop()

    async def stop_all(self) -> None:
        await asyncio.gather(*(self.stop(sid) for sid in list(self._sessions)), return_exceptions=True)
