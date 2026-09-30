import sys
from pathlib import Path

import pytest

from dryflash.gdbmi import Debugger, GdbError

FAKE = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_gdb.py")]


@pytest.fixture
async def dbg():
    d = await Debugger.start(FAKE, elf=Path("/w/app.elf"), port=1234)
    yield d
    await d.close()


@pytest.mark.anyio
async def test_attach_leaves_target_stopped(dbg):
    assert dbg.state == "stopped"
    assert dbg.last_stop["frame"]["func"] == "app_main"


@pytest.mark.anyio
async def test_break_and_continue_hits(dbg):
    bp = await dbg.break_insert("app_main")
    assert bp == {"number": 1, "address": "0x400d5a18", "function": "app_main", "file": "main/app.c", "line": 10}
    stop = await dbg.continue_(timeout=5)
    assert stop["stopped"] is True
    assert stop["reason"] == "breakpoint-hit"
    assert stop["frame"] == {"function": "app_main", "file": "main/app.c", "line": 10, "address": "0x400d5a18"}


@pytest.mark.anyio
async def test_continue_timeout_interrupts(dbg):
    stop = await dbg.continue_(timeout=0.3)
    assert stop["stopped"] is True
    assert stop["reason"] == "timeout"
    assert dbg.state == "stopped"


@pytest.mark.anyio
async def test_bad_breakpoint_raises(dbg):
    with pytest.raises(GdbError, match="not defined"):
        await dbg.break_insert("nosuchfn")


@pytest.mark.anyio
async def test_step_reports_new_line(dbg):
    stop = await dbg.step("over")
    assert stop["reason"] == "end-stepping-range"
    assert stop["frame"]["line"] == 11
    with pytest.raises(ValueError):
        await dbg.step("sideways")


@pytest.mark.anyio
async def test_backtrace(dbg):
    frames = await dbg.backtrace()
    assert [f["function"] for f in frames] == ["app_main", "main_task"]
    assert frames[0] == {"level": 0, "address": "0x400d5a18", "function": "app_main", "file": "main/app.c",
                         "line": 10}


@pytest.mark.anyio
async def test_registers_named_and_filtered(dbg):
    regs = await dbg.registers()
    assert regs == {"pc": "0x400d5a18", "ar0": "0x800d5a33", "ar1": "0x3ffb45f0", "sar": "0x4"}
    assert await dbg.registers(["pc", "sar"]) == {"pc": "0x400d5a18", "sar": "0x4"}


@pytest.mark.anyio
async def test_read_memory_and_eval(dbg):
    assert await dbg.read_memory(0x3FFB0000, 4) == bytes.fromhex("deadbeef")
    assert await dbg.evaluate("x") == "42"
    with pytest.raises(GdbError, match="No symbol"):
        await dbg.evaluate("bad")
