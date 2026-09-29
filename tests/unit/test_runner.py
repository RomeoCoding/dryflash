import asyncio
import re

import pytest

from esp32_sim_mcp.runner import run_scenario
from esp32_sim_mcp.scenario import parse_scenario
from esp32_sim_mcp.uart import UartBuffer

pytestmark = pytest.mark.anyio


class FakeSession:
    """Just enough of Session for the runner: a UART buffer fed by a script of (delay, bytes)."""

    def __init__(self, script, exit_after=None):
        self.uart = UartBuffer()
        self.written = []
        self.run_for_calls = []
        self.alive = True
        self.state = "running"
        self.exit_reason = None
        self._cond = asyncio.Condition()
        self._task = asyncio.create_task(self._feed(script, exit_after))
        self.sensors = None

    async def _feed(self, script, exit_after):
        for delay, data in script:
            await asyncio.sleep(delay)
            async with self._cond:
                self.uart.append(data)
                self._cond.notify_all()
        if exit_after is not None:
            await asyncio.sleep(exit_after)
            self.alive, self.state, self.exit_reason = False, "exited", "guest reset"

    async def uart_expect(self, pattern, timeout, cursor=None, context_bytes=400):
        rx = re.compile(pattern.encode())
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            m = self.uart.search(rx, cursor or 0)
            if m:
                return {"matched": True, "match": m.group(0).decode(), "cursor": m.end_offset,
                        "groups": [g.decode() if g is not None else None for g in m.groups()]}
            if loop.time() >= end:
                return {"matched": False, "reason": "timeout", "cursor": self.uart.total, "tail": ""}
            await asyncio.sleep(0.01)

    async def uart_write(self, data):
        self.written.append(data)
        async with self._cond:
            self.uart.append(b"got " + data)

    async def run_for(self, virtual_ms):
        self.run_for_calls.append(virtual_ms)
        return {"virtual_ms": virtual_ms, "exact": False}

    async def resume(self):
        pass


def scen(text):
    return parse_scenario(text)


async def test_ordered_expectations_pass():
    s = FakeSession([(0.01, b"boot\n"), (0.05, b"value=1\n"), (0.05, b"value=2\n")])
    r = await run_scenario(s, scen("""
name: t
steps:
  - expect: "value=1"
  - expect: "value=(\\\\d)"
    value_range: [2, 2]
"""))
    assert r["passed"], r
    assert [st["passed"] for st in r["steps"]] == [True, True]
    assert r["steps"][1]["groups"] == ["2"]


async def test_expect_timeout_fails_with_step_index():
    s = FakeSession([(0.01, b"boot\n")])
    r = await run_scenario(s, scen("name: t\nsteps:\n  - {expect: never, timeout_s: 0.3}\n"))
    assert not r["passed"]
    assert r["failed_step"] == 0 and "timeout" in r["reason"]


async def test_value_range_failure():
    s = FakeSession([(0.01, b"rms=0.50\n")])
    r = await run_scenario(s, scen("name: t\nsteps:\n  - {expect: 'rms=([0-9.]+)', value_range: [0.69, 0.72]}\n"))
    assert not r["passed"] and "0.5" in r["reason"] and "[0.69, 0.72]" in r["reason"]


async def test_fail_on_aborts_a_waiting_expect_early():
    s = FakeSession([(0.05, b"Guru Meditation Error: Core  0 panic'ed (LoadProhibited).\n")])
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    r = await run_scenario(s, scen("name: t\nsteps:\n  - {expect: never, timeout_s: 10}\n"))
    assert not r["passed"]
    assert "Guru Meditation" in r["reason"]
    assert loop.time() - t0 < 3


async def test_expect_not_window():
    s = FakeSession([(0.05, b"ok\n"), (0.1, b"overflow!\n")])
    r = await run_scenario(s, scen("name: t\nfail_on: []\nsteps:\n  - {expect_not: overflow, within_s: 0.5}\n"))
    assert not r["passed"] and "overflow" in r["reason"]
    s2 = FakeSession([(0.05, b"ok\n")])
    r2 = await run_scenario(s2, scen("name: t\nfail_on: []\nsteps:\n  - {expect_not: overflow, within_s: 0.2}\n"))
    assert r2["passed"]


async def test_write_and_run_for():
    s = FakeSession([(0.01, b"ready\n")])
    r = await run_scenario(s, scen("""
name: t
steps:
  - expect: ready
  - write: "ping\\n"
  - expect: "got ping"
  - run_for_ms: 50
"""))
    assert r["passed"], r
    assert s.written == [b"ping\n"] and s.run_for_calls == [50]


async def test_session_exit_fails_pending_expect():
    s = FakeSession([(0.01, b"boot\n")], exit_after=0.1)
    r = await run_scenario(s, scen("name: t\nfail_on: []\nsteps:\n  - {expect: never, timeout_s: 5}\n"))
    assert not r["passed"] and "exited" in r["reason"]


async def test_overall_timeout():
    s = FakeSession([(0.01, b"boot\n")])
    r = await run_scenario(s, scen("name: t\ntimeout_s: 0.3\nsteps:\n  - {expect: never, timeout_s: 10}\n"))
    assert not r["passed"] and "scenario timeout" in r["reason"]


async def test_transcript_included():
    s = FakeSession([(0.01, b"hello\n")])
    r = await run_scenario(s, scen("name: t\nsteps:\n  - expect: hello\n"))
    assert "hello" in r["transcript"]
