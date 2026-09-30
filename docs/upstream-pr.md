# Draft: pull request to espressif/qemu (esp-develop)

Not submitted. This is prepared text for the owner to use. The two determinism fixes stand on their
own; the sensor devices (0002–0004) and the CLI I2C attach (0001) can follow as a separate PR once
these are in.

**Title:** Make esp32 dual-core runs reproducible under -icount

**Patches:** `qemu-patches/0005-hw-xtensa-esp32-reset-the-APP-CPU-synchronously.patch`,
`qemu-patches/0006-icount-do-not-warp-the-clock-while-a-VM-stop-is-pend.patch` (on
`esp-develop-9.2.2-20260417`; checkpatch: 0 errors, 0 warnings).

## Summary

With `-icount shift=N,sleep=off`, two runs of the same esp32 image should produce identical guest
behaviour. They do not, for two independent reasons.

1. **APP CPU reset timing (esp32 machine).** Releasing the APP CPU from reset
   (`DPORT_APPCPU_RESET`, or a timer-group watchdog CPU reset) calls
   `qemu_system_reset_request()`, which the main loop services at a host-dependent moment. The APP
   CPU may already be running by then, so it executes a varying number of instructions before its
   reset. Two runs of one image showed APP CPU cycle counts 277 cycles apart in `-d int` traces, and
   UART logs that differed in a boot timestamp. The patch queues the reset on the APP CPU with
   `async_run_on_cpu()`, so it takes effect before that vCPU executes further, without the main loop.
   PRO CPU resets are unchanged.

2. **icount warp during a pending stop (core).** `icount_start_warp_timer()` warps
   `QEMU_CLOCK_VIRTUAL` when the VM is running and all vCPUs are idle. Between a stop request and
   the main loop handling it, the run state is still RUNNING while the vCPUs are halted for the
   stop, so the clock jumped to the next deadline (8.87 ms in our case) instead of stopping where
   requested. The patch adds `qemu_vmstop_pending()` (non-consuming) and skips the warp while a stop
   or debug request is pending. This affects any device- or debugger-initiated stop, not only esp32.

## Testing

- Before: 8 runs of a dual-core ESP-IDF v6.1 application with `-icount shift=3,sleep=off -seed 1`
  gave 2 distinct UART logs. After patch 1: 8/8 byte-identical.
- Before patch 2, a device-requested stop at virtual time T left the clock at T + 8.87 ms. After it,
  stops land exactly at T (checked at 300 ms and 550 ms).
- Used by an ESP-IDF test harness that runs these checks in CI (`tests/integration/test_sensors.py`
  in the originating project).

Signed-off-by: Romeo Mattar <romeomat.work@gmail.com> (on each patch)
