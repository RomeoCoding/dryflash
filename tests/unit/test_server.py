import pytest
from mcp.client import Client

from dryflash.server import create_server

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "project_build", "emu_start", "emu_stop", "emu_status", "emu_reset", "emu_run_for", "emu_pause",
    "emu_continue", "uart_read", "uart_write", "uart_expect", "gdb_break", "gdb_continue", "gdb_step",
    "gdb_backtrace", "gdb_registers", "gdb_read_memory", "gdb_eval", "decode_panic", "test_run",
    "sensor_set", "sensor_stream",
}


async def test_all_tools_are_listed_with_model_oriented_descriptions():
    async with Client(create_server()) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert EXPECTED_TOOLS <= set(tools)
    for name, t in tools.items():
        assert t.description and len(t.description) > 60, name


async def test_emu_start_documents_every_sensor_model():
    # A benchmark agent read only this description, took the generic model for a register-less stub
    # and gave up on emulating a NAU7802. Every model and the generic model's fields must be here.
    async with Client(create_server()) as c:
        desc = next(t for t in (await c.list_tools()).tools if t.name == "emu_start").description
    for word in ("adxl345", "ads1115", "generic", "registers", "channels", "stride", "read_only", "read_set",
                 "int24_be", "scale", "bias"):
        assert word in desc, word


async def test_uart_expect_documents_the_halted_answer():
    async with Client(create_server()) as c:
        desc = next(t for t in (await c.list_tools()).tools if t.name == "uart_expect").description
    assert "halted" in desc and "gdb_continue" in desc


async def test_unknown_session_is_a_readable_tool_error():
    async with Client(create_server()) as c:
        r = await c.call_tool("uart_read", {"session_id": "s99"})
    assert r.is_error
    text = r.content[0].text
    assert "no session 's99'" in text and "emu_start" in text


async def test_emu_status_lists_no_sessions():
    async with Client(create_server()) as c:
        r = await c.call_tool("emu_status", {})
    assert not r.is_error
    assert r.structured_content == {"sessions": []}


async def test_decode_panic_on_text_without_elf():
    text = ("Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.\n\n"
            "Core  0 register dump:\nPC      : 0x400d5a1b  PS      : 0x00060830\n"
            "EXCVADDR: 0x00000000  LBEG    : 0x400014fd\n\n\nBacktrace: 0x400d5a18:0x3ffb45f0\n")
    async with Client(create_server()) as c:
        r = await c.call_tool("decode_panic", {"text": text})
    assert not r.is_error
    out = r.structured_content
    assert out["kind"] == "guru_meditation" and "NULL pointer" in out["cause"]
    assert any("not symbolized" in n for n in out["notes"])


async def test_bad_target_is_reported():
    async with Client(create_server()) as c:
        r = await c.call_tool("project_build", {"project_dir": "/nonexistent", "target": "esp8266"})
    assert r.is_error and "esp8266" in r.content[0].text
