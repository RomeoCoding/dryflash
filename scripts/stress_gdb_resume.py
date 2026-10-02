"""Stress the GDB-continue -> uart_expect path that once timed out under host load (item 4).

Repeats the smoke test's debugger sequence against SessionManager directly:
  emu_start(wait_for_gdb) -> break app_main -> gdb continue -> emu_continue -> uart_expect "Hello"
and records how long each step took and, on failure, the GDB and session state.

  python scripts/stress_gdb_resume.py --runs 10 --parallel 3 [--expect-timeout 30]
(inside the dryflash image, with the build cache volume mounted).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dryflash.build import build_dir_for, build_project  # noqa: E402
from dryflash.session import SessionConfig, SessionManager  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1] / "examples" / "hello_world"


async def one(mgr: SessionManager, worker: int, run: int, expect_timeout: float) -> dict:
    bdir = build_dir_for(PROJECT, "esp32")
    elf = bdir / json.loads((bdir / "project_description.json").read_text())["app_elf"]
    rec: dict = {"worker": worker, "run": run, "steps": {}}
    t = time.monotonic()

    def lap(name):
        nonlocal t
        now = time.monotonic(); rec["steps"][name] = round(now - t, 2); t = now

    s = await mgr.start(SessionConfig(target="esp32", flash_image=bdir / "flash_qemu.bin", elf=elf,
                                      project_dir=PROJECT, wait_for_gdb=True))
    try:
        lap("start")
        d = await s.debugger(); lap("attach")
        await d.break_insert("app_main"); lap("break")
        stop = await d.continue_(60); lap("gdb_continue")
        rec["stop_reason"] = stop.get("reason")
        rec["gdb_state_before_resume"] = d.state
        await s.resume(); lap("emu_continue")
        rec["gdb_state_after_resume"] = d.state
        m = await s.uart_expect(r"Hello from dryflash!", timeout=expect_timeout); lap("uart_expect")
        rec["ok"] = bool(m["matched"])
        if not m["matched"]:
            rec["reason"] = m.get("reason")
            rec["gdb_state_at_failure"] = d.state
            rec["gdb_last_stop"] = d.last_stop
            rec["gdb_console_tail"] = d.console[-15:]
            rec["session"] = s.status()
            rec["uart_tail"] = s.uart.tail(600).decode(errors="replace")
    except Exception as e:  # report, keep going
        rec["ok"] = False; rec["error"] = f"{type(e).__name__}: {e}"
        rec["gdb_console_tail"] = (s.gdb.console[-15:] if s.gdb else None)
    finally:
        await mgr.stop(s.id)
    return rec


async def main(a) -> int:
    res = await build_project(PROJECT, "esp32")
    if not res.ok:
        print("build failed"); return 2
    mgr = SessionManager()
    results = []

    async def worker(w):
        for r in range(a.runs):
            rec = await one(mgr, w, r, a.expect_timeout)
            results.append(rec)
            print(json.dumps({k: rec[k] for k in ("worker", "run", "ok", "steps") if k in rec}), flush=True)
            if not rec.get("ok"):
                print("FAILURE DETAIL", json.dumps(rec, indent=1, default=str), flush=True)

    await asyncio.gather(*(worker(w) for w in range(a.parallel)))
    await mgr.stop_all()
    bad = [r for r in results if not r.get("ok")]
    worst = max(r["steps"].get("uart_expect", 0) for r in results)
    print(f"{len(results) - len(bad)}/{len(results)} ok; slowest uart_expect {worst:.2f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--expect-timeout", type=float, default=30.0)
    sys.exit(asyncio.run(main(ap.parse_args())))
