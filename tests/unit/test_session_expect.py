"""uart_expect on a halted target answers quickly and says why, instead of waiting out the timeout.

QEMU-free: a Session is constructed without starting it, and its UART buffer is fed directly.
"""

import asyncio
import time
from pathlib import Path

import pytest

from dryflash.session import Session, SessionConfig

pytestmark = pytest.mark.anyio


class FakeGdb:
    def __init__(self, state, frame=None):
        self.state = state
        self.last_stop = {"reason": "breakpoint-hit", "frame": frame} if frame else {}
        self.source_root = None


def make_session(state="running", gdb=None):
    s = Session("t1", SessionConfig(target="esp32", flash_image=Path("unused.bin")), 0)
    s.state = state
    s.gdb = gdb
    return s


async def feed(s, data: bytes, after: float):
    await asyncio.sleep(after)
    async with s._uart_cond:
        s.uart.append(data)
        s._uart_cond.notify_all()


async def test_debugger_halted_target_reports_where_it_stopped():
    s = make_session(gdb=FakeGdb("stopped", {"func": "app_main", "file": "main/main.c", "line": "15"}))
    t0 = time.monotonic()
    r = await s.uart_expect(r"Hello", timeout=20)
    assert time.monotonic() - t0 < 3
    assert r["matched"] is False
    assert r["reason"].startswith("halted")
    assert "app_main" in r["reason"] and "main/main.c:15" in r["reason"]
    assert "gdb_continue" in r["reason"] and "emu_continue" in r["reason"]


async def test_paused_session_says_paused():
    s = make_session(state="paused")
    t0 = time.monotonic()
    r = await s.uart_expect(r"Hello", timeout=20)
    assert time.monotonic() - t0 < 3
    assert r["matched"] is False and "paused" in r["reason"] and "emu_continue" in r["reason"]


async def test_output_already_received_still_matches_while_halted():
    s = make_session(gdb=FakeGdb("stopped", {"func": "app_main"}))
    s.uart.append(b"Hello from dryflash!\n")
    r = await s.uart_expect(r"Hello", timeout=5)
    assert r["matched"] is True


async def test_running_target_waits_for_output_as_before():
    s = make_session()
    asyncio.get_running_loop().create_task(feed(s, b"Hello\n", 1.2))
    r = await s.uart_expect(r"Hello", timeout=5)
    assert r["matched"] is True


async def test_briefly_halted_target_that_resumes_is_not_reported():
    # A resume racing with uart_expect (halted for less than the grace period) must not fail.
    g = FakeGdb("stopped", {"func": "app_main"})
    s = make_session(gdb=g)

    async def resume_then_print():
        await asyncio.sleep(0.2)
        g.state = "running"
        await feed(s, b"Hello\n", 0.8)

    asyncio.get_running_loop().create_task(resume_then_print())
    r = await s.uart_expect(r"Hello", timeout=5)
    assert r["matched"] is True
