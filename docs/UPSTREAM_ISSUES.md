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
   ESP32 device model uses only `QEMU_CLOCK_VIRTUAL`. **Root cause confirmed 2026-10-01: item 5.**
   On the esp-develop head (`febae182e1`), the unpatched build gave 3 distinct logs in 30 runs at
   shift=5, while 0005 alone gave 20/20 identical, the same hash as 0005+0006
   (`experiments/upstream/ab_determinism.sh`, docs/upstream-pr.md). The shift≤3 workaround is
   no longer needed with the patched QEMU.
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
5. **Dual-core esp32 boots were not reproducible under `-icount`.** Releasing the APP CPU from
   reset went through `qemu_system_reset_request()`, which the main loop services at a
   host-dependent moment while the APP CPU may already be running. Two runs of the same image
   showed APP CPU cycle counts 277 cycles apart (found by diffing `-d int` traces). *Patched* by
   `qemu-patches/0005-*` (the reset is queued on the APP CPU with `async_run_on_cpu()`). This is
   also the cause of item 2 (shift=5), confirmed by an A/B on esp-develop head.
6. **QEMU core: the icount warp advances the clock while a VM stop is pending.** Between a stop
   request and the main loop handling it, the run state is still RUNNING and the vCPUs look idle,
   so `icount_start_warp_timer()` jumped the clock to the next timer deadline (8.87 ms).
   *Patched* by `qemu-patches/0006-*`. It affects any device- or debugger-requested stop, not
   only this project.
7. **QEMU core (not a bug, a constraint): `vm_stop()` from a `QEMU_CLOCK_VIRTUAL` timer callback
   deadlocks**, because `pause_all_vcpus()` waits for the running timer list to finish. The
   sim-clock requests the stop with `qemu_system_vmstop_request()` instead.
8. **The esp32 RNG peripheral returns host entropy** (`qemu_guest_getrandom`); runs are only
   reproducible with `-seed`. Expected QEMU behaviour, but easy to miss.
