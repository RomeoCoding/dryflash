"""The MCP server: tools for building, running, debugging and testing ESP32 firmware in QEMU."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .build import BUILD_ROOT, build_dir_for, build_project
from .gdbmi import GdbError
from .panic import decode_panic_text, make_addr2line_symbolizer
from .qmp import QmpError
from .scenario import ScenarioError
from .sensors.link import LinkError
from .sensors.models import SensorSpecError
from .sensors.waveform import WaveformError
from .session import SessionConfig, SessionError, SessionManager, SessionNotFound
from .testrun import resolve_scenario, run_test
from .targets import UnknownTargetError, get_target

log = logging.getLogger("dryflash")

INSTRUCTIONS = """\
Build ESP-IDF firmware, run it in Espressif's QEMU (no board needed), and drive it like a developer:
serial console, GDB, crash decoding and (esp32 with the sensors image) injected I2C sensor data.

Typical loop: project_build -> emu_start -> uart_expect / uart_read -> (on a crash) decode_panic ->
edit code -> project_build -> emu_reset or emu_stop + emu_start. For debugging start with
wait_for_gdb=true, then gdb_break, gdb_continue, gdb_backtrace. For a repeatable pass/fail check use
test_run with a scenario YAML. Always emu_stop sessions you no longer need.
Paths are inside the container; the host project is normally mounted at /work.
Targets: esp32 (full support incl. sensors), esp32c3 and esp32s3 (no sensors). No Wi-Fi/BLE/ADC/I2S.
"""

_EXPECTED = (SessionError, SessionNotFound, ScenarioError, GdbError, QmpError, UnknownTargetError,
             SensorSpecError, WaveformError, LinkError,
             ValueError, FileNotFoundError, TimeoutError, asyncio.TimeoutError)


def _tool_errors(fn):
    """Report anticipated failures to the model as tool errors with their message."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except _EXPECTED as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e
    return wrapper


def _path(p: str) -> Path:
    path = Path(p)
    return (path if path.is_absolute() else Path.cwd() / path).resolve()


def create_server(manager: SessionManager | None = None) -> MCPServer:
    mgr = manager or SessionManager()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield {}
        finally:
            # Client disconnected (stdin closed) or the server is shutting down: no orphaned QEMUs.
            await mgr.stop_all()

    app = MCPServer("dryflash", version=__version__, instructions=INSTRUCTIONS, lifespan=lifespan)

    def tool(fn):
        app.tool()(_tool_errors(fn))
        return fn

    # ------------------------------------------------------------------ build
    @tool
    async def project_build(project_dir: str = ".", target: str = "esp32", clean: bool = False) -> dict[str, Any]:
        """Build an ESP-IDF project with idf.py (incremental; clean=true for a full rebuild).

        Returns ok, compiler/linker errors parsed to {severity, file, line, column, message} (errors
        first, paths relative to project_dir), binary sizes (app size, app partition free %, IRAM/DRAM
        use), build duration, and on failure the tail of the build log.
        Call it after every source edit, before emu_start or test_run. If ok is false, fix the listed
        errors and build again. Builds are out of tree, so the project folder stays clean.
        """
        res = await build_project(_path(project_dir), target, clean=clean)
        return res.to_dict()

    # ------------------------------------------------------------------ emulator lifecycle
    @tool
    async def emu_start(project_dir: str | None = None, image: str | None = None, elf: str | None = None,
                        target: str = "esp32", deterministic: bool = False, wait_for_gdb: bool = False,
                        sensors: list[dict[str, Any]] | None = None, reboot: bool = False,
                        watchdogs: bool = True, icount_shift: int = 3,
                        qemu_args: list[str] | None = None) -> dict[str, Any]:
        """Start an emulator session running the firmware and return its session_id.

        Give project_dir (uses its last project_build; builds first if it was never built) or image
        (a merged 4 MB flash .bin, plus elf for symbols). deterministic=true runs QEMU with
        -icount shift=N,sleep=off so runs are repeatable byte for byte (about 1.6x slower).
        wait_for_gdb=true keeps the CPU halted at reset so you can set breakpoints first (then
        gdb_break + gdb_continue). By default a guest reset (panic, watchdog, esp_restart) ends the
        session and keeps the crash at the end of the UART log; reboot=true boot-loops like a board.
        sensors (esp32, sensors image only) declares injected I2C sensors, e.g.
        [{"model": "adxl345", "name": "accel", "address": 83, "waveform": {...}}]; see sensor_set.
        Next: uart_expect for a boot message, or uart_read with cursor 0.
        """
        t = get_target(target)
        built = False
        if project_dir is not None:
            proj = _path(project_dir)
            bdir = build_dir_for(proj, target)
            flash = bdir / "flash_qemu.bin"
            elf_path = None
            if not flash.exists():
                res = await build_project(proj, target)
                if not res.ok:
                    raise ToolError("the project does not build; call project_build to see the errors")
                built = True
            desc = bdir / "project_description.json"
            if desc.exists():
                elf_path = bdir / json.loads(desc.read_text())["app_elf"]
        elif image is not None:
            proj, flash = None, _path(image)
            elf_path = _path(elf) if elf else None
        else:
            raise ToolError("give project_dir or image")
        if sensors and not t.sensors:
            raise ToolError(f"sensors are supported only on esp32, not {target}")
        s = await mgr.start(SessionConfig(
            target=target, flash_image=flash, elf=elf_path, project_dir=proj, deterministic=deterministic,
            icount_shift=icount_shift, wait_for_gdb=wait_for_gdb, reboot=reboot, watchdogs=watchdogs,
            extra_args=list(qemu_args or []), sensors=list(sensors or [])))
        return {**s.status(), "built_first": built,
                "next": "gdb_break then gdb_continue" if wait_for_gdb else "uart_expect or uart_read(cursor=0)"}

    @tool
    async def emu_stop(session_id: str) -> dict[str, Any]:
        """Stop a session: kills QEMU and GDB and deletes its temporary files. Returns the final status.

        Call when done with a session (sessions also stop when the MCP client disconnects).
        """
        s = mgr.get(session_id)
        final = s.status()
        tail = s.uart.tail(600).decode(errors="replace")
        await mgr.stop(session_id)
        return {**final, "state": "stopped", "uart_tail": tail}

    @tool
    async def emu_status(session_id: str | None = None) -> dict[str, Any]:
        """Status of one session (state, target, UART byte count, GDB, exit reason) or of all sessions.

        state is running, paused, debug-halted (stopped in GDB) or exited (QEMU ended; UART still
        readable). If exited after a crash, call decode_panic.
        """
        if session_id is None:
            return {"sessions": [s.status() for s in mgr.list()]}
        return mgr.get(session_id).status()

    @tool
    async def emu_reset(session_id: str) -> dict[str, Any]:
        """Power-cycle the emulated board: restart QEMU with the same flash (NVS persists).

        Works on running, paused or exited sessions (e.g. after a crash). UART cursors stay valid;
        use the returned uart_cursor_at_reset to read only the new boot. GDB is detached (breakpoints
        are lost). To run new code, project_build first, then emu_stop + emu_start.
        """
        s = mgr.get(session_id)
        return {**(await s.reset()), **s.status()}

    @tool
    async def emu_run_for(session_id: str, virtual_ms: int) -> dict[str, Any]:
        """Let the CPU run for virtual_ms of emulated time, then pause it.

        Exact (to the nanosecond of virtual time) in deterministic sessions on the sensors image;
        otherwise an approximation from wall time, reported as exact=false. Next: uart_read, then
        emu_continue to keep running.
        """
        if virtual_ms <= 0:
            raise ToolError("virtual_ms must be positive")
        s = mgr.get(session_id)
        return {**(await s.run_for(virtual_ms)), **s.status()}

    @tool
    async def emu_pause(session_id: str) -> dict[str, Any]:
        """Pause the emulated CPUs (virtual time stops). Resume with emu_continue."""
        s = mgr.get(session_id)
        await s.pause()
        return s.status()

    @tool
    async def emu_continue(session_id: str) -> dict[str, Any]:
        """Resume a paused session (or a GDB-halted one without waiting for a stop; use gdb_continue to wait)."""
        s = mgr.get(session_id)
        await s.resume()
        return s.status()

    # ------------------------------------------------------------------ UART
    @tool
    async def uart_read(session_id: str, cursor: int = 0, max_bytes: int = 8192) -> dict[str, Any]:
        """Read UART0 output from a byte cursor. Returns text, the next cursor, and at_end.

        MCP has no push, so keep the returned cursor and pass it next time to get only new output.
        cursor=0 reads from the start (boot log). dropped_bytes>0 means old output was discarded.
        """
        return mgr.get(session_id).uart_read(cursor, max(1, min(max_bytes, 65536)))

    @tool
    async def uart_write(session_id: str, text: str, newline: bool = True) -> dict[str, Any]:
        """Send text to the firmware's UART0 RX (stdin), with a trailing \\n unless newline=false.

        Then call uart_expect to wait for the reply.
        """
        s = mgr.get(session_id)
        data = (text + ("\n" if newline else "")).encode()
        cursor = s.uart.total
        await s.uart_write(data)
        return {"bytes_written": len(data), "uart_cursor_before_write": cursor}

    @tool
    async def uart_expect(session_id: str, pattern: str, timeout_s: float = 10.0,
                          cursor: int | None = None, complete_lines: bool = True) -> dict[str, Any]:
        """Wait until UART output matches a Python regex; return the match, groups and context.

        Searches from cursor (default: all retained output), so pass the cursor from a previous
        call to only match new output. By default only complete lines are searched, so
        'value=(\\d+)' never matches a half-received line; set complete_lines=false to match a
        prompt that has no trailing newline. On timeout returns matched=false with the last
        output; if the session exited, the reason says so (then decode_panic).
        """
        re.compile(pattern)
        return await mgr.get(session_id).uart_expect(pattern, timeout=min(timeout_s, 600), cursor=cursor,
                                                     complete_lines=complete_lines)

    # ------------------------------------------------------------------ debugger
    async def _dbg(session_id: str):
        return await mgr.get(session_id).debugger()

    def _with_uart(s, result: dict) -> dict[str, Any]:
        result["uart_tail"] = s.uart.tail(300).decode(errors="replace")
        return result

    @tool
    async def gdb_break(session_id: str, location: str, condition: str | None = None,
                        temporary: bool = False) -> dict[str, Any]:
        """Set a breakpoint at a function, file:line, or *0xADDRESS. Returns its resolved address/line.

        Attaches GDB on first use (the CPU halts while attaching and then resumes its previous
        state). Next: gdb_continue to run until it is hit.
        """
        d = await _dbg(session_id)
        return {"breakpoint": await d.break_insert(location, temporary=temporary, condition=condition),
                "target_state": d.state}

    @tool
    async def gdb_continue(session_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
        """Run until a breakpoint, crash or other stop, or until timeout_s (then the CPU is interrupted).

        Returns stop reason (breakpoint-hit, signal-received, timeout, ...), the frame
        {function, file, line} and the last UART output. Next: gdb_backtrace, gdb_eval, gdb_step.
        """
        s = mgr.get(session_id)
        d = await s.debugger()
        stop = await (d.wait_stop(timeout_s) if d.state == "running" else d.continue_(timeout_s))
        return _with_uart(s, stop)

    @tool
    async def gdb_step(session_id: str, kind: str = "over") -> dict[str, Any]:
        """Step the halted CPU: kind = over (next line), into, out (finish function) or instruction.

        Returns the new frame. The target must be halted (after gdb_continue stopped).
        """
        s = mgr.get(session_id)
        return _with_uart(s, await (await s.debugger()).step(kind))

    @tool
    async def gdb_backtrace(session_id: str, max_frames: int = 32) -> dict[str, Any]:
        """Call stack of the halted CPU: [{level, function, file, line, address}], innermost first."""
        return {"frames": await (await _dbg(session_id)).backtrace(max_frames)}

    @tool
    async def gdb_registers(session_id: str, names: list[str] | None = None) -> dict[str, Any]:
        """CPU registers of the halted core as hex strings; names filters (e.g. ["pc", "a1"] or ["pc", "sp", "ra"])."""
        return {"registers": await (await _dbg(session_id)).registers(names)}

    @tool
    async def gdb_read_memory(session_id: str, address: str, length: int = 64) -> dict[str, Any]:
        """Read up to 4096 bytes of target memory at address (hex like 0x3ffb0000, or a C expression such as &my_buf).

        Returns hex and an ASCII rendering.
        """
        if not 0 < length <= 4096:
            raise ToolError("length must be 1..4096")
        d = await _dbg(session_id)
        if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", address.strip()):
            addr = int(address, 0)
        else:
            value = await d.evaluate(f"(unsigned long)({address})")
            addr = int(value.split()[0], 0)
        data = await d.read_memory(addr, length)
        return {"address": f"0x{addr:08x}", "length": len(data), "hex": data.hex(),
                "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data)}

    @tool
    async def gdb_eval(session_id: str, expression: str) -> dict[str, Any]:
        """Evaluate a C expression in the current frame of the halted CPU (variables, struct fields, casts, calls to pure functions)."""
        return {"expression": expression, "value": await (await _dbg(session_id)).evaluate(expression)}

    # ------------------------------------------------------------------ crash decoding
    @tool
    async def decode_panic(session_id: str | None = None, text: str | None = None,
                           project_dir: str | None = None, target: str = "esp32",
                           elf: str | None = None) -> dict[str, Any]:
        """Decode an ESP-IDF crash (Guru Meditation, abort, assert, stack overflow, watchdog).

        With session_id, uses that session's UART output and ELF; or pass the crash text plus
        project_dir (its last build's ELF is used) or elf. Returns kind, exception, register dump,
        the backtrace symbolized to function/file/line, and a one-line probable cause. The last crash
        in the text is decoded. Next: fix the code at the first frame in your own sources.
        """
        elf_path: Path | None = _path(elf) if elf else None
        src_root: Path | None = _path(project_dir) if project_dir else None
        t = get_target(target)
        if session_id is not None:
            s = mgr.get(session_id)
            text = s.uart.tail(65536).decode(errors="replace")
            elf_path = elf_path or s.config.elf
            src_root = src_root or s.config.project_dir
            t = s.target
        if text is None:
            raise ToolError("give session_id or text")
        if elf_path is None and src_root is not None:
            bdir = build_dir_for(src_root, t.name)
            desc = bdir / "project_description.json"
            if desc.exists():
                elf_path = bdir / json.loads(desc.read_text())["app_elf"]
        sym = make_addr2line_symbolizer(t.addr2line, elf_path, src_root) if elf_path and elf_path.exists() else None
        report = decode_panic_text(text, symbolize=sym)
        out = report.to_dict()
        if sym is None and report.kind != "none":
            out["notes"].append("no ELF available, so addresses are not symbolized")
        return out

    # ------------------------------------------------------------------ scenario tests
    @tool
    async def test_run(project_dir: str, scenario_file: str, build: bool = True) -> dict[str, Any]:
        """Build the project, run it in a fresh session per the scenario YAML, and report pass/fail.

        The scenario (schema in the README) sets the target, emulator options, sensors, fail_on
        patterns and steps (expect / expect_not / write / run_for_ms / sensor_set / sensor_stream).
        Returns passed, the failing step and reason, per-step results, the UART transcript, and a
        decoded crash if one happened. The session is always stopped afterwards. Use it to confirm a
        fix; it is also what CI and the benchmark run.
        """
        proj = _path(project_dir)
        return await run_test(mgr, proj, resolve_scenario(proj, scenario_file), build=build)

    # ------------------------------------------------------------------ sensors (sensors image)
    def _hub(session_id: str):
        s = mgr.get(session_id)
        if s.sensors is None or not s.sensors.models:
            raise ToolError("this session has no injected sensors: declare them in emu_start(sensors=[...]) "
                            "(esp32 on the dryflash-sensors image)")
        return s.sensors

    @tool
    async def sensor_set(session_id: str, sensor: str, values: dict[str, Any],
                         at_ms: float | None = None) -> dict[str, Any]:
        """Change what an injected sensor reports, from virtual time at_ms (default: now) onwards.

        values maps channel -> number or waveform spec: adxl345 channels x/y/z in g, ads1115 ain0..ain3
        in volts, generic sensors their declared channels. Channels not given keep their waveform.
        E.g. {"z": 1.0} or {"x": {"type": "sine", "freq_hz": 50, "amplitude": 0.2}}.
        For byte-identical deterministic runs give an explicit at_ms (or call this while paused,
        e.g. after emu_run_for), because "now" on a running board depends on host timing.
        Next: uart_expect for the firmware's reaction.
        """
        return await _hub(session_id).set(sensor, values=values, at_ms=at_ms)

    @tool
    async def sensor_stream(session_id: str, sensor: str, waveform: dict[str, Any],
                            at_ms: float | None = None) -> dict[str, Any]:
        """Feed a sensor a time-varying source from at_ms (default: now): per-channel waveform specs.

        Sources: {"type": "csv", "path": "rec.csv", "column": "x", "loop": true} (recorded samples,
        path relative to the project), sine / noise / step / rotation (imbalance 1x line:
        {"type": "rotation", "rpm": 1800, "amplitude": 0.3, "harmonics": [[2, 0.1]]}) or a list to
        sum several. Samples are resampled onto the sensor's rate_hz grid in virtual time.
        """
        return await _hub(session_id).stream(sensor, waveform=waveform, at_ms=at_ms)

    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("DRYFLASH_LOG", "WARNING"),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    create_server().run("stdio")
