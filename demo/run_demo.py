"""Scripted end-to-end MCP session for a screen recording: build, run, crash, decode, fix, sensor test.

Every step is a real MCP tool call over stdio to the server; the "fix" steps apply the benchmark's
reference patches, standing in for the edit an agent would make.

  docker run --rm -it -v <repo>:/opt/dryflash dryflash-sensors \
      python /opt/dryflash/demo/run_demo.py            # writes demo/transcript.md
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

REPO = Path(__file__).resolve().parents[1]
WORK = Path("/tmp/dryflash-demo")
LOG: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    LOG.append(text)


def pause(seconds: float = 1.0) -> None:
    if os.environ.get("DEMO_FAST") != "1":
        time.sleep(seconds)


async def call(c: Client, name: str, show: list[str] | None = None, **args):
    say(f"\n**agent → `{name}`** `{json.dumps(args)}`")
    t0 = time.monotonic()
    r = await c.call_tool(name, args)
    body = r.structured_content if r.structured_content is not None else {"text": r.content[0].text}
    picked = {k: body[k] for k in (show or []) if k in body} if show else body
    say(f"```json\n{json.dumps(picked, indent=2)[:1500]}\n```  ({time.monotonic() - t0:.1f}s)")
    pause()
    if r.is_error:
        raise SystemExit(f"{name} failed: {body}")
    return body


def fix(app: str) -> None:
    subprocess.run(["patch", "-p1", "-d", str(WORK / app), "-i", str(REPO / "bench" / app / "reference.patch")],
                   check=True, capture_output=True)
    diff = [line for line in (REPO / "bench" / app / "reference.patch").read_text().splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    say("\n*agent edits the source:*\n```diff\n" + "\n".join(diff) + "\n```")
    pause(2)


async def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    for app in ("null_config", "adc_byte_order"):
        shutil.copytree(REPO / "bench" / app / "app", WORK / app)
        shutil.copytree(REPO / "bench" / app / "hidden", WORK / app / "test")
    server = StdioServerParameters(command=sys.executable, args=["-m", "dryflash"], env=dict(os.environ))
    async with Client(server) as c:
        tools = (await c.list_tools()).tools
        say(f"# dryflash demo\n\nConnected over stdio: {len(tools)} tools.")

        say("\n## 1. A crash, decoded\n\nA config shell reboots when an operator types `set name` with no value.")
        cfg = str(WORK / "null_config")
        await call(c, "project_build", show=["ok", "duration_s", "sizes"], project_dir=cfg)
        s = await call(c, "emu_start", show=["session_id", "state", "target"], project_dir=cfg)
        sid = s["session_id"]
        await call(c, "uart_expect", show=["matched", "match"], session_id=sid, pattern="config shell ready",
                   timeout_s=60)
        await call(c, "uart_write", session_id=sid, text="set name")
        await call(c, "uart_expect", show=["matched", "reason"], session_id=sid, pattern="name=", timeout_s=10)
        await call(c, "decode_panic", show=["kind", "exception", "cause", "backtrace"], session_id=sid)
        await call(c, "emu_stop", show=["state"], session_id=sid)
        fix("null_config")
        await call(c, "test_run", show=["passed", "steps", "duration_s"], project_dir=cfg,
                   scenario_file="test/scenario.yaml")

        say("\n## 2. A sensor bug no crash dump can show\n\nA voltmeter reads an ADS1115 ADC over I2C. "
            "The test injects 1.234 V on AIN0, then 2.5 V at t = 3 s of virtual time.")
        adc = str(WORK / "adc_byte_order")
        await call(c, "test_run", show=["passed", "failed_step", "reason"], project_dir=adc,
                   scenario_file="test/scenario.yaml")
        fix("adc_byte_order")
        await call(c, "test_run", show=["passed", "steps", "duration_s"], project_dir=adc,
                   scenario_file="test/scenario.yaml")
        say("\nBoth bugs were found and fixed without a board: the crash from its decoded backtrace, "
            "the sensor bug from injected, deterministic ADC data.")
    out = REPO / "demo" / "transcript.md"
    out.write_text("\n".join(LOG) + "\n")
    print(f"\ntranscript written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
