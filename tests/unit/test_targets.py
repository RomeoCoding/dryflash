import pytest

from esp32_sim_mcp.targets import TARGETS, get_target, UnknownTargetError


def test_esp32_is_the_only_sensor_target():
    assert [t.name for t in TARGETS.values() if t.sensors] == ["esp32"]


def test_esp32_tools():
    t = get_target("esp32")
    assert t.qemu == "qemu-system-xtensa"
    assert t.machine == "esp32"
    assert t.gdb == "xtensa-esp32-elf-gdb"
    assert t.addr2line == "xtensa-esp32-elf-addr2line"
    assert t.arch == "xtensa"


def test_esp32c3_is_riscv():
    t = get_target("esp32c3")
    assert t.qemu == "qemu-system-riscv32"
    assert t.gdb == "riscv32-esp-elf-gdb"
    assert t.arch == "riscv32"


def test_unknown_target_lists_supported():
    with pytest.raises(UnknownTargetError, match="esp32c3"):
        get_target("esp8266")
