"""Execute a Scenario against a running Session and produce a pass/fail report."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .scenario import Scenario, Step

_POLL_S = 0.25  # how often a waiting step re-checks fail_on patterns and session liveness


class _Fail(Exception):
    pass


async def run_scenario(session: Any, scenario: Scenario, transcript_bytes: int = 16000) -> dict:
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    deadline = loop.time() + scenario.timeout_s
    fail_rx = [re.compile(p.encode()) for p in scenario.fail_on]
    cursor = 0
    steps: list[dict] = []
    failed_step, reason = None, None

    def check_fail_on() -> None:
        for rx in fail_rx:
            m = session.uart.search(rx, 0)
            if m is not None:
                raise _Fail(f"fail_on pattern {rx.pattern.decode()!r} matched: "
                            f"{session.uart.slice(m.start_offset, m.start_offset + 160).decode(errors='replace').splitlines()[0]}")

    def remaining(limit: float) -> float:
        left = deadline - loop.time()
        if left <= 0:
            raise _Fail(f"scenario timeout ({scenario.timeout_s}s) reached")
        return min(limit, left)

    for i, step in enumerate(scenario.steps):
        s0 = time.monotonic()
        rec: dict[str, Any] = {"index": i, "action": step.action, "name": step.name}
        try:
            check_fail_on()
            cursor = await _run_step(session, step, cursor, rec, check_fail_on, remaining)
            rec["passed"] = True
        except _Fail as e:
            rec["passed"], rec["error"] = False, str(e)
            failed_step, reason = i, str(e)
        rec["elapsed_s"] = round(time.monotonic() - s0, 2)
        steps.append(rec)
        if failed_step is not None:
            break

    return {
        "scenario": scenario.name,
        "passed": failed_step is None,
        "failed_step": failed_step,
        "reason": reason,
        "steps": steps,
        "duration_s": round(time.monotonic() - t0, 2),
        "transcript": session.uart.tail(transcript_bytes).decode(errors="replace"),
    }


async def _run_step(session, step: Step, cursor: int, rec: dict, check_fail_on, remaining) -> int:
    loop = asyncio.get_running_loop()
    action = step.action
    if action == "expect":
        rec["pattern"] = step.expect
        end = loop.time() + step.timeout_s
        while True:
            r = await session.uart_expect(step.expect, timeout=remaining(min(_POLL_S, end - loop.time())),
                                          cursor=cursor)
            if r["matched"]:
                break
            check_fail_on()
            if not session.alive:
                raise _Fail(f"session {session.state} ({session.exit_reason}) before {step.expect!r} appeared")
            if loop.time() >= end:
                raise _Fail(f"timeout after {step.timeout_s}s waiting for {step.expect!r}")
        rec["match"], rec["groups"] = r["match"], r.get("groups", [])
        if step.value_range is not None:
            lo, hi = step.value_range
            try:
                value = float(r["groups"][0])
            except (TypeError, ValueError, IndexError):
                raise _Fail(f"capture group 1 of {step.expect!r} is not a number: {r.get('groups')}") from None
            rec["value"] = value
            if not lo <= value <= hi:
                raise _Fail(f"value {value:g} from {r['match']!r} is outside [{lo:g}, {hi:g}]")
        return r["cursor"]
    if action == "expect_not":
        rec["pattern"] = step.expect_not
        rx = re.compile(step.expect_not.encode())
        end = loop.time() + step.within_s
        while loop.time() < end:
            m = session.uart.search(rx, cursor)
            if m is not None:
                raise _Fail(f"forbidden pattern {step.expect_not!r} appeared: {m.group(0).decode(errors='replace')!r}")
            check_fail_on()
            await asyncio.sleep(remaining(min(0.05, max(0.0, end - loop.time()))))
        if (m := session.uart.search(rx, cursor)) is not None:
            raise _Fail(f"forbidden pattern {step.expect_not!r} appeared: {m.group(0).decode(errors='replace')!r}")
        return cursor
    if action == "write":
        await session.uart_write(step.write.encode())
        return cursor
    if action == "run_for_ms":
        rec["result"] = await session.run_for(step.run_for_ms)
        await session.resume()
        return cursor
    if action in ("sensor_set", "sensor_stream"):
        if session.sensors is None or not session.sensors.models:
            raise _Fail(f"{action} needs sensors declared in the scenario's 'sensors' list")
        spec = getattr(step, action)
        rec["result"] = await (session.sensors.set(**spec) if action == "sensor_set"
                               else session.sensors.stream(**spec))
        return cursor
    raise _Fail(f"unsupported action {action}")
