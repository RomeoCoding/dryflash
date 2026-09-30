"""End-to-end through the MCP tool layer (in-process client), plus the stdio smoke script."""

import subprocess
import sys

import pytest
from mcp.client import Client

from dryflash.server import create_server

from .conftest import CRASHLAB, HELLO, REPO

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def call(c, name, **args):
    r = await c.call_tool(name, args)
    assert not r.is_error, r.content[0].text
    return r.structured_content


async def test_test_run_passes_on_hello_world():
    async with Client(create_server()) as c:
        r = await call(c, "test_run", project_dir=str(HELLO), scenario_file="test.yaml")
    assert r["passed"], r
    assert [s["passed"] for s in r["steps"]] == [True] * 4
    assert r["steps"][1]["value"] == 1


async def test_test_run_fails_and_decodes_a_real_crash():
    async with Client(create_server()) as c:
        r = await call(c, "test_run", project_dir=str(CRASHLAB), scenario_file="scenarios/null_crash.yaml")
    assert not r["passed"]
    assert r["failed_step"] == 2
    assert "Guru Meditation" in r["reason"]
    assert r["panic"]["exception"] == "LoadProhibited"
    assert r["panic"]["backtrace"][0]["function"] == "read_sensor_value"


async def test_test_run_uart_write_scenario():
    async with Client(create_server()) as c:
        r = await call(c, "test_run", project_dir=str(CRASHLAB), scenario_file="scenarios/echo.yaml")
    assert r["passed"], r


async def test_build_errors_are_parsed(tmp_path):
    proj = tmp_path / "broken"
    (proj / "main").mkdir(parents=True)
    (proj / "CMakeLists.txt").write_text((HELLO / "CMakeLists.txt").read_text())
    (proj / "main" / "CMakeLists.txt").write_text('idf_component_register(SRCS "app.c")\n')
    (proj / "main" / "app.c").write_text("void app_main(void)\n{\n    undeclared_thing = 1;\n}\n")
    async with Client(create_server()) as c:
        r = await call(c, "project_build", project_dir=str(proj))
    assert r["ok"] is False
    e = r["diagnostics"][0]
    assert (e["severity"], e["file"], e["line"]) == ("error", "main/app.c", 3)
    assert "undeclared_thing" in e["message"]


@pytest.mark.parametrize("target", ["esp32c3", "esp32s3"])
async def test_other_targets_build_run_and_debug(target):
    async with Client(create_server()) as c:
        b = await call(c, "project_build", project_dir=str(HELLO), target=target)
        assert b["ok"], b
        s = await call(c, "emu_start", project_dir=str(HELLO), target=target, wait_for_gdb=True)
        sid = s["session_id"]
        try:
            await call(c, "gdb_break", session_id=sid, location="app_main")
            stop = await call(c, "gdb_continue", session_id=sid, timeout_s=60)
            assert stop["frame"]["function"] == "app_main", stop
            await call(c, "emu_continue", session_id=sid)
            m = await call(c, "uart_expect", session_id=sid, pattern="tick 2", timeout_s=60)
            assert m["matched"], m
        finally:
            await call(c, "emu_stop", session_id=sid)


def test_smoke_session_script():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "smoke_session.py")], cwd=REPO,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "SMOKE SESSION PASSED" in r.stdout
