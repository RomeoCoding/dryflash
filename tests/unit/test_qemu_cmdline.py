from pathlib import Path

from esp32_sim_mcp.qemu_cmd import QemuOptions, build_qemu_cmdline
from esp32_sim_mcp.targets import get_target


def _opts(**kw):
    base = dict(target=get_target("esp32"), flash=Path("/s/flash.bin"), efuse=Path("/s/efuse.bin"),
                run_dir=Path("/s"), gdb_port=4242)
    base.update(kw)
    return QemuOptions(**base)


def _pairs(cmd):
    return list(zip(cmd, cmd[1:]))


def test_always_starts_paused_with_qmp_uart_and_gdb():
    cmd = build_qemu_cmdline(_opts())
    assert cmd[0] == "qemu-system-xtensa"
    assert "-S" in cmd
    assert ("-qmp", "unix:/s/qmp.sock,server=on,wait=off") in _pairs(cmd)
    assert ("-chardev", "socket,id=uart0,path=/s/uart0.sock,server=on,wait=off") in _pairs(cmd)
    assert ("-serial", "chardev:uart0") in _pairs(cmd)
    assert ("-gdb", "tcp:127.0.0.1:4242") in _pairs(cmd)
    assert ("-drive", "file=/s/flash.bin,if=mtd,format=raw") in _pairs(cmd)
    assert ("-machine", "esp32") in _pairs(cmd)
    assert "-nographic" in cmd
    assert ("-monitor", "none") in _pairs(cmd)


def test_efuse_and_strap_mode_follow_idf_py():
    cmd = build_qemu_cmdline(_opts())
    assert ("-drive", "file=/s/efuse.bin,if=none,format=raw,id=efuse") in _pairs(cmd)
    assert ("-global", "driver=nvram.esp32.efuse,property=drive,value=efuse") in _pairs(cmd)
    assert ("-m", "4M") in _pairs(cmd)


def test_deterministic_uses_icount_without_sleep():
    cmd = build_qemu_cmdline(_opts(deterministic=True))
    assert ("-icount", "shift=3,sleep=off") in _pairs(cmd)
    cmd = build_qemu_cmdline(_opts(deterministic=True, icount_shift=2))
    assert ("-icount", "shift=2,sleep=off") in _pairs(cmd)


def test_non_deterministic_esp32_has_no_icount_but_riscv_keeps_idf_default():
    assert "-icount" not in build_qemu_cmdline(_opts())
    cmd = build_qemu_cmdline(_opts(target=get_target("esp32c3")))
    assert ("-icount", "3") in _pairs(cmd)
    assert ("-machine", "esp32c3") in _pairs(cmd)


def test_reboot_policy():
    assert "-no-reboot" in build_qemu_cmdline(_opts())
    assert "-no-reboot" not in build_qemu_cmdline(_opts(reboot=True))


def test_watchdogs_can_be_disabled_like_idf_py():
    assert not any("wdt_disable" in a for a in build_qemu_cmdline(_opts()))
    cmd = build_qemu_cmdline(_opts(watchdogs=False))
    assert ("-global", "driver=timer.esp32.timg,property=wdt_disable,value=true") in _pairs(cmd)


def test_extra_devices_and_args_are_appended():
    cmd = build_qemu_cmdline(_opts(extra_args=["-device", "tmp105,bus=i2c-bus.0,address=0x49"]))
    assert cmd[-2:] == ["-device", "tmp105,bus=i2c-bus.0,address=0x49"]
