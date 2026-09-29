import asyncio
from pathlib import Path

import pytest

from esp32_sim_mcp.session import SessionConfig, SessionManager

from .conftest import CRASHLAB, HELLO

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def cfg(build, project, **kw):
    return SessionConfig(target=build.target, flash_image=Path(build.flash_image), elf=Path(build.elf),
                         project_dir=project, **kw)


@pytest.fixture
async def mgr():
    m = SessionManager()
    yield m
    await m.stop_all()


async def test_hello_world_boots_and_stops_cleanly(mgr, hello_build):
    s = await mgr.start(cfg(hello_build, HELLO))
    r = await s.uart_expect(r"Hello from esp32-sim-mcp!", timeout=30)
    assert r["matched"], r
    assert s.status()["state"] == "running"
    run_dir, pid = s.run_dir, s.proc.pid
    await mgr.stop(s.id)
    assert not run_dir.exists()
    with pytest.raises(ProcessLookupError):
        import os
        os.kill(pid, 0)
    assert mgr.list() == []


async def test_guest_reset_ends_session_with_no_reboot(mgr, crashlab_build):
    s = await mgr.start(cfg(crashlab_build, CRASHLAB))
    assert (await s.uart_expect("crashlab ready", timeout=30))["matched"]
    await s.uart_write(b"abort\n")
    await s.wait_exit(timeout=30)
    st = s.status()
    assert st["state"] == "exited"
    assert "abort() was called" in s.uart.tail(4000).decode(errors="replace")


async def test_uart_write_round_trip_and_cursor(mgr, crashlab_build):
    s = await mgr.start(cfg(crashlab_build, CRASHLAB))
    r = await s.uart_expect("crashlab ready", timeout=30)
    await s.uart_write(b"echo hello there\n")
    r2 = await s.uart_expect(r"echo: ([^\r\n]*)\r?\n", timeout=10, cursor=r["cursor"])
    assert r2["groups"] == ["hello there"]
    chunk = s.uart_read(r["cursor"], 1000)
    assert "echo: hello there" in chunk["text"]


async def test_expect_timeout_reports_tail(mgr, hello_build):
    s = await mgr.start(cfg(hello_build, HELLO))
    r = await s.uart_expect("this never appears", timeout=2)
    assert not r["matched"] and r["reason"] == "timeout"
    assert "Hello from esp32-sim-mcp!" in r["tail"]


async def test_deterministic_runs_are_byte_identical(mgr, hello_build):
    logs = []
    for _ in range(2):
        s = await mgr.start(cfg(hello_build, HELLO, deterministic=True))
        assert (await s.uart_expect("done", timeout=60))["matched"]
        logs.append(s.uart.slice(0, s.uart.search(__import__("re").compile(rb"done"), 0).end_offset))
        await mgr.stop(s.id)
    assert logs[0] == logs[1]
    assert b"tick 5" in logs[0]


async def test_parallel_sessions_do_not_collide(mgr, hello_build):
    sessions = await asyncio.gather(*[mgr.start(cfg(hello_build, HELLO)) for _ in range(3)])
    assert len({s.gdb_port for s in sessions}) == 3
    assert len({s.run_dir for s in sessions}) == 3
    results = await asyncio.gather(*[s.uart_expect("tick 3", timeout=60) for s in sessions])
    assert all(r["matched"] for r in results)


async def test_gdb_break_at_app_main_and_backtrace(mgr, hello_build):
    s = await mgr.start(cfg(hello_build, HELLO, wait_for_gdb=True))
    assert s.status()["state"] == "paused"
    dbg = await s.debugger()
    bp = await dbg.break_insert("app_main")
    assert bp["function"] == "app_main" and bp["file"].endswith("hello_world.c")
    stop = await dbg.continue_(timeout=60)
    assert stop["reason"] == "breakpoint-hit", stop
    assert stop["frame"]["function"] == "app_main"
    frames = await dbg.backtrace()
    assert frames[0]["function"] == "app_main"
    assert any(f["function"] == "main_task" for f in frames)
    regs = await dbg.registers(["pc"])
    assert int(regs["pc"], 16) == int(bp["address"], 16)
    assert await dbg.evaluate("counter") == "0"
    stop = await dbg.step("over")
    assert stop["frame"]["function"] == "app_main"


async def test_pause_continue_and_reset(mgr, hello_build):
    s = await mgr.start(cfg(hello_build, HELLO))
    assert (await s.uart_expect("tick 1", timeout=30))["matched"]
    await s.pause()
    assert s.status()["state"] == "paused"
    await s.resume()
    assert s.status()["state"] == "running"
    before = s.uart.total
    await s.reset()
    r = await s.uart_expect("Hello from esp32-sim-mcp!", timeout=30, cursor=before)
    assert r["matched"]


async def test_run_for_advances_and_pauses(mgr, hello_build):
    s = await mgr.start(cfg(hello_build, HELLO, deterministic=True, wait_for_gdb=False))
    r = await s.run_for(virtual_ms=200)
    assert s.status()["state"] == "paused"
    assert r["virtual_ms"] == 200
    assert "exact" in r
