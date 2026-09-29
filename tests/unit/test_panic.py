from pathlib import Path

import pytest

from esp32_sim_mcp.panic import decode_panic_text, find_panic_start, Frame

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return (FIX / name).read_text()


def fake_symbolizer(table):
    def sym(addrs):
        return [table.get(a, Frame(a, "??", None, None)) for a in addrs]
    return sym


def test_load_prohibited_null_deref():
    sym = fake_symbolizer({0x400d5a18: Frame(0x400d5a18, "read_sensor", "main/app.c", 17),
                           0x400d5a30: Frame(0x400d5a30, "app_main", "main/app.c", 30)})
    r = decode_panic_text(fx("panic_loadprohibited.txt"), symbolize=sym)
    assert r.kind == "guru_meditation"
    assert r.exception == "LoadProhibited"
    assert r.core == 0
    assert r.registers["PC"] == 0x400d5a1b
    assert r.registers["EXCVADDR"] == 0x4
    assert [f.pc for f in r.backtrace][:2] == [0x400d5a18, 0x400d5a30]
    assert r.backtrace[0].function == "read_sensor" and r.backtrace[0].line == 17
    assert "NULL pointer" in r.cause and "read_sensor" in r.cause and "main/app.c:17" in r.cause
    assert not r.backtrace_corrupted


def test_stack_overflow_names_task_and_flags_corruption():
    r = decode_panic_text(fx("panic_stack_overflow.txt"))
    assert r.kind == "stack_overflow"
    assert r.task == "recurse"
    assert "stack overflow" in r.cause.lower() and "recurse" in r.cause
    assert r.backtrace_corrupted
    assert len(r.backtrace) == 6


def test_assert_extracts_expression_and_location():
    r = decode_panic_text(fx("panic_assert.txt"))
    assert r.kind == "assert"
    assert r.assertion == {"function": "ring_push", "file": "ring.c", "line": 42,
                           "expression": "r->count <= RING_CAP"}
    assert "r->count <= RING_CAP" in r.cause and "ring.c:42" in r.cause


def test_abort_symbolizes_caller_pc():
    sym = fake_symbolizer({0x400d7c4f: Frame(0x400d7c4f, "parse_packet", "main/proto.c", 88)})
    r = decode_panic_text(fx("panic_abort.txt"), symbolize=sym)
    assert r.kind == "abort"
    assert r.registers["PC"] == 0x400d7c4f
    assert "parse_packet" in r.cause


def test_task_watchdog_lists_starved_and_running_tasks():
    r = decode_panic_text(fx("panic_task_wdt.txt"))
    assert r.kind == "task_wdt"
    assert r.wdt_starved == ["IDLE0 (CPU 0)"]
    assert r.wdt_running == {"CPU 0": "spinner", "CPU 1": "IDLE1"}
    assert "spinner" in r.cause and "IDLE0" in r.cause


def test_interrupt_watchdog():
    r = decode_panic_text(fx("panic_int_wdt.txt"))
    assert r.kind == "int_wdt"
    assert r.core == 1
    assert "interrupt watchdog" in r.cause.lower()


def test_stack_canary_is_reported_as_stack_overflow():
    r = decode_panic_text(fx("panic_canary.txt"))
    assert r.kind == "stack_overflow"
    assert r.task == "worker"


def test_riscv_store_fault_uses_mepc_and_ra():
    sym = fake_symbolizer({0x42005a5c: Frame(0x42005a5c, "write_reg", "main/x.c", 5),
                           0x42005a4e: Frame(0x42005a4e, "app_main", "main/x.c", 9)})
    r = decode_panic_text(fx("panic_riscv_store.txt"), symbolize=sym)
    assert r.exception == "Store access fault"
    assert r.registers["MEPC"] == 0x42005a5c and r.registers["MTVAL"] == 0
    assert [f.function for f in r.backtrace] == ["write_reg", "app_main"]
    assert "NULL pointer" in r.cause
    assert any("RISC-V" in n for n in r.notes)


def test_no_panic():
    r = decode_panic_text("I (10) boot: all good\n")
    assert r.kind == "none" and r.backtrace == []


def test_find_panic_start_picks_the_last_panic():
    text = fx("panic_abort.txt") + "rst:0xc\n" + fx("panic_loadprohibited.txt")
    start = find_panic_start(text)
    assert text[start:].startswith("Guru Meditation Error")


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("panic_*.txt")))
def test_every_fixture_yields_a_one_line_cause(name):
    r = decode_panic_text(fx(name))
    assert r.kind != "none"
    assert r.cause and "\n" not in r.cause


# Captured from crashlab (tests/firmware/crashlab) running in QEMU with ESP-IDF v6.1; CRLF kept.
REAL = {
    "real_null.txt": ("guru_meditation", "LoadProhibited"),
    "real_div0.txt": ("guru_meditation", "IntegerDivideByZero"),
    "real_abort.txt": ("abort", None),
    "real_assert.txt": ("assert", None),
    "real_wdt.txt": ("task_wdt", None),
}


@pytest.mark.parametrize("name", list(REAL))
def test_real_captures(name):
    kind, exc = REAL[name]
    r = decode_panic_text((FIX / name).read_bytes().decode())
    assert r.kind == kind
    assert r.exception == exc
    assert r.backtrace, r
    if kind == "guru_meditation":
        assert "PC" in r.registers and "EXCVADDR" in r.registers
    if name == "real_null.txt":
        assert r.registers["EXCVADDR"] == 0 and "NULL pointer" in r.cause
