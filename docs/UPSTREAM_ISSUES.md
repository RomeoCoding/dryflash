# Upstream issues noticed

Things outside this project that look wrong or surprising. None are patched here except where
noted; the workaround is listed instead.

## espressif/qemu (esp-develop-9.2.2-20260417)

1. **I2C devices can't be created from the command line on the esp32 machine.** The
   controllers are realized on the SoC-private `esp32-periph-bus`, which `qbus_find()` can't
   reach, and both buses are named `i2c`. The source acknowledges it in a comment in
   `esp32_machine_init_i2c()`. *Patched* by `qemu-patches/0001-*`; a candidate for an
   upstream PR.
2. **`-icount shift=5,sleep=off` isn't deterministic on the esp32 machine.** Across 10 runs
   of the same image there were 2 distinct UART logs, differing by 1 ms in one boot-log
   timestamp (`experiments/m1/logs/q4b_n10.log`). shift=1 to 3 were deterministic, and every
   ESP32 device model uses only `QEMU_CLOCK_VIRTUAL`. Not root-caused. Workaround: use shift≤3.
3. **`esp32_i2c.c` runs a whole command list in zero virtual time** and never raises
   ARBITRATION or TIME_OUT. It's fine for master-side sensor reads, but it hides timing bugs.
   Not patched.

## QEMU core (inherited)

1. **`tmp105` ignores `temperature=` given on `-device`**: `tmp105_reset()` zeroes it after the
   properties are applied. Workaround: `qom-set` after reset, before `cont`.
4. **QMP `system_reset` on the esp32 machine is followed by a guest TG0 watchdog reset**
   (`rst:0x7 (TG0WDT_SYS_RESET)` right after `rst:0x1 (POWERON_RESET)`). With `-no-reboot`
   this second, guest-initiated reset shuts QEMU down. Timer-group watchdog state seems to
   survive the host reset. Workaround: `emu_reset` restarts the QEMU process.
