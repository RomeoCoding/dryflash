"""The panic decoder against genuine ESP-IDF v6.1 crash output produced in QEMU."""

from pathlib import Path

import pytest

from dryflash.panic import decode_panic_text, make_addr2line_symbolizer
from dryflash.session import SessionConfig, SessionManager

from .conftest import CRASHLAB

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

CASES = {
    # command: (expected kind, expected exception or None, function expected in the backtrace)
    "null": ("guru_meditation", "LoadProhibited", "read_sensor_value"),
    "div0": ("guru_meditation", "IntegerDivideByZero", "divide"),
    "abort": ("abort", None, "app_main"),
    "assert": ("assert", None, "app_main"),
    "overflow": ("stack_overflow", None, None),
}


@pytest.mark.parametrize("command", list(CASES))
async def test_real_crash_is_decoded(command, crashlab_build):
    kind, exc, func = CASES[command]
    mgr = SessionManager()
    try:
        s = await mgr.start(SessionConfig("esp32", Path(crashlab_build.flash_image), Path(crashlab_build.elf),
                                          project_dir=CRASHLAB))
        assert (await s.uart_expect("crashlab ready", timeout=30))["matched"]
        await s.uart_write(command.encode() + b"\n")
        await s.wait_exit(timeout=60)
        text = s.uart.tail(20000).decode(errors="replace")
        r = decode_panic_text(text, make_addr2line_symbolizer("xtensa-esp32-elf-addr2line",
                                                              Path(crashlab_build.elf), CRASHLAB))
        assert r.kind == kind, (r.to_dict(), text[-3000:])
        if exc:
            assert r.exception == exc
        if func:
            assert func in [f.function for f in r.backtrace], r.to_dict()
        if command == "null":
            assert "NULL pointer" in r.cause and "read_sensor_value" in r.cause
            assert r.backtrace[0].file == "main/crashlab.c"
        if command == "overflow":
            assert r.task == "recurse"
        if command == "assert":
            assert r.assertion["expression"] == "strlen(line) == 0"
    finally:
        await mgr.stop_all()


async def test_task_watchdog_is_reported(crashlab_build):
    mgr = SessionManager()
    try:
        s = await mgr.start(SessionConfig("esp32", Path(crashlab_build.flash_image), Path(crashlab_build.elf),
                                          project_dir=CRASHLAB))
        assert (await s.uart_expect("crashlab ready", timeout=30))["matched"]
        await s.uart_write(b"wdt\n")
        m = await s.uart_expect(r"task_wdt: Print CPU \d \(current core\) backtrace[\s\S]*?Backtrace:[^\n]*\n",
                                timeout=60)
        assert m["matched"], m
        r = decode_panic_text(s.uart.tail(20000).decode(errors="replace"))
        assert r.kind == "task_wdt"
        assert any("IDLE0" in t for t in r.wdt_starved)
        assert r.wdt_running.get("CPU 0") == "spinner"
    finally:
        await mgr.stop_all()
