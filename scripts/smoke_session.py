"""Scripted MCP client session against the real server over stdio.

Steps: list tools, build examples/hello_world, start it halted, break at app_main, continue to
the breakpoint, backtrace, resume, uart_expect the greeting, stop. (The greeting is printed by
app_main itself, so the breakpoint has to be placed before the greeting is awaited.)

Inside the image (default):   python scripts/smoke_session.py
From the host via Docker:     python scripts/smoke_session.py --docker dryflash
Exit code 0 on success; a transcript of every call is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

EXPECTED_TOOLS = {"project_build", "emu_start", "uart_expect", "gdb_break", "gdb_continue",
                  "gdb_backtrace", "emu_stop", "decode_panic", "test_run"}


def server_params(args) -> StdioServerParameters:
    if args.docker:
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        return StdioServerParameters(command="docker", args=[
            "run", "-i", "--rm", "-v", f"{repo}:/work", args.docker])
    return StdioServerParameters(command=sys.executable, args=["-m", "dryflash"],
                                 env={**os.environ}, cwd=args.workdir)


async def call(c: Client, name: str, **arguments):
    t0 = time.monotonic()
    r = await c.call_tool(name, arguments)
    dt = time.monotonic() - t0
    body = r.structured_content if r.structured_content is not None else r.content[0].text
    shown = json.dumps(body, indent=None)[:400] if not isinstance(body, str) else body[:400]
    print(f"-> {name}({json.dumps(arguments)}) [{dt:.1f}s]{' ERROR' if r.is_error else ''}\n   {shown}")
    if r.is_error:
        raise SystemExit(f"{name} failed")
    return body


async def main(args) -> None:
    project = "examples/hello_world"
    async with Client(server_params(args)) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        print(f"-> list_tools: {len(tools)} tools")
        missing = EXPECTED_TOOLS - tools
        assert not missing, f"missing tools: {missing}"

        b = await call(c, "project_build", project_dir=project, target="esp32")
        assert b["ok"], b
        s = await call(c, "emu_start", project_dir=project, target="esp32", wait_for_gdb=True)
        sid = s["session_id"]
        try:
            bp = await call(c, "gdb_break", session_id=sid, location="app_main")
            assert bp["breakpoint"]["function"] == "app_main"
            stop = await call(c, "gdb_continue", session_id=sid, timeout_s=60)
            assert stop["reason"] == "breakpoint-hit" and stop["frame"]["function"] == "app_main", stop
            bt = await call(c, "gdb_backtrace", session_id=sid)
            funcs = [f["function"] for f in bt["frames"]]
            assert funcs[0] == "app_main" and "main_task" in funcs, funcs
            await call(c, "emu_continue", session_id=sid)
            m = await call(c, "uart_expect", session_id=sid, pattern=r"Hello from dryflash!", timeout_s=90)
            assert m["matched"], m
        finally:
            await call(c, "emu_stop", session_id=sid)
        st = await call(c, "emu_status")
        assert st["sessions"] == []
    print("SMOKE SESSION PASSED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docker", metavar="IMAGE", help="run the server with docker run -i --rm IMAGE")
    ap.add_argument("--workdir", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    asyncio.run(main(ap.parse_args()))
