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

The following were found in M5 step 0 (2026-10-03); the evidence is in
`experiments/m5_spike/README.md`, and the patches are pending (M5b).

9. **`esp32_spi_txrx_buffer()` tests the data byte instead of the loop index**
   (`if (byte < tx_bytes)` / `if (byte < rx_bytes)`). Any received byte whose transmitted
   counterpart is ≥ the rx length is dropped, and the guest reads its own tx data back. An
   Adafruit_MAX31855 read (0xFF filler) returns `ff ff ff ff`. **Already reported and fixed upstream
   in espressif/qemu PR #144** (QEMU-282, open since 2026-02-28, also covering esp32c3/s3); our fix
   will credit it.
10. **Phantom command phase on user SPI transactions** (not found upstream). `SPI_CMD_USR` sends a
    command phase if `SPI_USER.USR_COMMAND` is set **or** `SPI_USER2.COMMAND_BITLEN` is non-zero.
    The TRM (v5.8, §20.3 and `SPI_USER2_REG`) says a phase is enabled only by its control bit,
    and the bit length "is only valid when SPI_USR_COMMAND is set to 1". ESP-IDF's "no command"
    (`usr_command=0`, bitlen field 15) therefore clocks 2 extra bytes, and Arduino (reset bitlen 4)
    1 extra byte, so every read is shifted. Fix tested in the spike; flash/NVS on SPI1 unaffected.
11. **The SPI controllers never raise their interrupt.** The IRQ is created and routed to the
    interrupt matrix, but `qemu_set_irq` is never called, and `SPI_SLAVE` always reads
    `TRANS_DONE | TRANS_INTEN`. ESP-IDF's interrupt-driven `spi_device_transmit()` blocks forever;
    the polling API works.
12. **SPI DMA is not modelled, and fails silently.** `DMA_CONF`/`DMA_IN_LINK` writes are ignored,
    and the transfer completes with `ESP_OK` while the DMA buffer is never written. Firmware must
    use `SPI_DMA_DISABLED`.
13. **SPI2/SPI3 can't take command-line devices** (same cause as item 1: `periph_bus`, all buses
    named `spi`). An SSI device with an unconnected CS input is always selected and never sees a
    frame start.
14. **The GPIO model only implements `GPIO_STRAP`.** `OUT`, `ENABLE`, `IN`, W1TS/W1TC and pin
    interrupts read 0 or are dropped. A pull-up input reads 0, so an active-low button reads
    "pressed" forever.

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
