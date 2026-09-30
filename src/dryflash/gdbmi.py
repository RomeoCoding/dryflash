"""Asynchronous GDB/MI client: one GDB process attached to one QEMU gdbstub.

pygdbmi supplies the MI record parser; process I/O is plain asyncio so a long "continue" can be
interrupted from another coroutine without threads.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any

from pygdbmi.gdbmiparser import parse_response


class GdbError(RuntimeError):
    pass


_STEP_CMDS = {
    "over": "-exec-next",
    "into": "-exec-step",
    "out": "-exec-finish",
    "instruction": "-exec-next-instruction",
}


def _frame(raw: dict | None, source_root: Path | None = None) -> dict | None:
    if not raw:
        return None
    file = raw.get("fullname") or raw.get("file")
    if file and source_root is not None:
        try:
            file = Path(file).resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            pass
    if file and source_root is None:
        file = raw.get("file") or file
    return {
        "function": raw.get("func"),
        "file": file,
        "line": int(raw["line"]) if raw.get("line") else None,
        "address": raw.get("addr"),
    }


class Debugger:
    def __init__(self, proc: asyncio.subprocess.Process, source_root: Path | None):
        self._proc = proc
        self.source_root = source_root
        self._tokens = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._cond = asyncio.Condition()
        self._stop_seq = 0
        self.state = "unknown"
        self.last_stop: dict | None = None
        self.console: list[str] = []
        self._reg_names: list[str] | None = None
        self._reader = asyncio.create_task(self._read_loop())

    @classmethod
    async def start(cls, gdb_cmd: list[str], elf: Path, port: int, source_root: Path | None = None,
                    timeout: float = 30.0) -> "Debugger":
        proc = await asyncio.create_subprocess_exec(
            *gdb_cmd, "--interpreter=mi3", "-nx", "-q",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        d = cls(proc, source_root)
        try:
            for c in ("-gdb-set mi-async on", "-gdb-set pagination off", "-gdb-set confirm off",
                      "-gdb-set remotetimeout 20", f"-file-exec-and-symbols {elf}"):
                await d.command(c, timeout=timeout)
            seq = d._stop_seq
            await d.command(f"-target-select remote 127.0.0.1:{port}", timeout=timeout)
            # QEMU's gdbstub halts the machine when a debugger attaches.
            await d._wait_stop_after(seq, timeout=5, required=False)
            d.state = "stopped"
        except BaseException:
            await d.close()
            raise
        return d

    async def _read_loop(self) -> None:
        assert self._proc.stdout
        while line := await self._proc.stdout.readline():
            rec = parse_response(line.decode(errors="replace").rstrip("\r\n"))
            kind = rec.get("type")
            if kind == "result":
                fut = self._pending.pop(rec.get("token"), None)
                if fut is not None and not fut.done():
                    fut.set_result(rec)
            elif kind == "notify":
                async with self._cond:
                    if rec["message"] == "running":
                        self.state = "running"
                    elif rec["message"] == "stopped":
                        self.state = "stopped"
                        self.last_stop = rec.get("payload") or {}
                        self._stop_seq += 1
                    self._cond.notify_all()
            elif kind in ("console", "target", "log") and rec.get("payload"):
                self.console.append(str(rec["payload"]))
                del self.console[:-200]
        async with self._cond:
            self.state = "exited"
            self._cond.notify_all()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(GdbError("GDB exited"))

    async def command(self, cmd: str, timeout: float = 10.0) -> dict:
        if self._proc.returncode is not None or self.state == "exited":
            raise GdbError("GDB is not running")
        tok = next(self._tokens)
        fut = asyncio.get_running_loop().create_future()
        self._pending[tok] = fut
        assert self._proc.stdin
        self._proc.stdin.write(f"{tok}{cmd}\n".encode())
        await self._proc.stdin.drain()
        try:
            rec = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(tok, None)
            raise GdbError(f"GDB did not answer {cmd!r} within {timeout}s") from None
        if rec["message"] == "error":
            raise GdbError((rec.get("payload") or {}).get("msg", "unknown GDB error"))
        return rec.get("payload") or {}

    async def _wait_stop_after(self, seq: int, timeout: float, required: bool = True) -> bool:
        try:
            async with self._cond:
                await asyncio.wait_for(
                    self._cond.wait_for(lambda: self._stop_seq > seq or self.state == "exited"), timeout)
        except asyncio.TimeoutError:
            if required:
                raise
            return False
        return self._stop_seq > seq

    def _stop_summary(self, reason_override: str | None = None) -> dict:
        p = self.last_stop or {}
        return {
            "stopped": self.state == "stopped",
            "reason": reason_override or p.get("reason") or ("exited" if self.state == "exited" else "stopped"),
            "signal": p.get("signal-name"),
            "breakpoint": int(p["bkptno"]) if p.get("bkptno") else None,
            "thread": p.get("thread-id"),
            "frame": _frame(p.get("frame"), self.source_root),
        }

    async def break_insert(self, location: str, temporary: bool = False, condition: str | None = None) -> dict:
        opts = (" -t" if temporary else "") + (f' -c "{condition}"' if condition else "")
        bkpt = (await self.command(f"-break-insert{opts} {location}"))["bkpt"]
        f = _frame(bkpt, self.source_root) or {}
        return {"number": int(bkpt["number"]), "address": bkpt.get("addr"), "function": f.get("function"),
                "file": f.get("file"), "line": f.get("line")}

    async def continue_(self, timeout: float) -> dict:
        seq = self._stop_seq
        await self.command("-exec-continue")
        if await self._wait_stop_after(seq, timeout, required=False):
            return self._stop_summary()
        return await self.interrupt(reason="timeout")

    async def wait_stop(self, timeout: float) -> dict:
        """If the target is running, wait for it to stop (interrupting it on timeout)."""
        if self.state != "running":
            return self._stop_summary()
        if await self._wait_stop_after(self._stop_seq, timeout, required=False):
            return self._stop_summary()
        return await self.interrupt(reason="timeout")

    async def interrupt(self, reason: str = "interrupted") -> dict:
        if self.state != "running":
            return self._stop_summary()
        seq = self._stop_seq
        await self.command("-exec-interrupt")
        await self._wait_stop_after(seq, timeout=10)
        return self._stop_summary(reason_override=reason)

    async def step(self, kind: str = "over", timeout: float = 30.0) -> dict:
        if kind not in _STEP_CMDS:
            raise ValueError(f"step kind must be one of {sorted(_STEP_CMDS)}")
        seq = self._stop_seq
        await self.command(_STEP_CMDS[kind])
        if await self._wait_stop_after(seq, timeout, required=False):
            return self._stop_summary()
        return await self.interrupt(reason="timeout")

    async def backtrace(self, max_frames: int = 32) -> list[dict]:
        stack = (await self.command(f"-stack-list-frames 0 {max_frames - 1}"))["stack"]
        out = []
        for entry in stack:
            raw = entry.get("frame", entry) if isinstance(entry, dict) else entry
            f = _frame(raw, self.source_root) or {}
            out.append({"level": int(raw.get("level", len(out))), "address": f.get("address"),
                        "function": f.get("function"), "file": f.get("file"), "line": f.get("line")})
        return out

    async def registers(self, names: list[str] | None = None) -> dict[str, str]:
        if self._reg_names is None:
            self._reg_names = (await self.command("-data-list-register-names"))["register-names"]
        wanted = None
        if names:
            wanted = {n.lower() for n in names}
            unknown = wanted - {n.lower() for n in self._reg_names if n}
            if unknown:
                raise GdbError(f"unknown register(s): {', '.join(sorted(unknown))}")
        vals = (await self.command("-data-list-register-values --skip-unavailable x"))["register-values"]
        out = {}
        for v in vals:
            name = self._reg_names[int(v["number"])]
            if name and (wanted is None or name.lower() in wanted):
                out[name] = v["value"]
        return out

    async def read_memory(self, address: int, length: int) -> bytes:
        mem = (await self.command(f"-data-read-memory-bytes 0x{address:x} {length}"))["memory"]
        return b"".join(bytes.fromhex(block["contents"]) for block in mem)

    async def evaluate(self, expression: str) -> str:
        escaped = expression.replace("\\", "\\\\").replace('"', '\\"')
        return (await self.command(f'-data-evaluate-expression "{escaped}"'))["value"]

    async def close(self) -> None:
        if self._proc.returncode is None:
            try:
                if self.state == "running":
                    await self.interrupt()
                await self.command("-target-detach", timeout=3)
            except (GdbError, asyncio.TimeoutError, ConnectionError, OSError):
                pass
            try:
                self._proc.stdin.write(b"-gdb-exit\n")  # type: ignore[union-attr]
                await asyncio.wait_for(self._proc.wait(), 3)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                self._proc.kill()
                await self._proc.wait()
        self._reader.cancel()

    def info(self) -> dict[str, Any]:
        return {"state": self.state, "last_stop": self._stop_summary() if self.last_stop is not None else None}
