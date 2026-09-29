# Session Summary
Last updated: 2026-09-29 (late, +03:00). Stopped mid-M3: usage limit reached.

## What was just done
M3 in progress (not committed yet). The sensor stack works end to end: the vibration_monitor RMS
scenario passes, two deterministic runs are byte-identical, and emu_run_for stops exactly
(300,000,000 / 550,000,000 ns). 5 of 6 sensor integration tests pass on the dev QEMU build.

## State of M3
- Python (done, unit-tested; 117 unit tests green): src/esp32_sim_mcp/sensors/{waveform,models,link,hub}.py,
  sensor_set/sensor_stream tools, uart_expect complete_lines (default true), -seed 1 in deterministic mode.
- QEMU staged sources, as whole files, in qemu-src/ (gitignored working area):
  hw/sensor/i2c_sim_sensor.c, hw/misc/sim_clock.c, hw/xtensa/esp32.c (0001+0005),
  system/runstate.c + include/sysemu/runstate.h + accel/tcg/icount-common.c (new patch 0006:
  no icount warp while a vmstop is pending), msgs/000N.txt (commit messages), apply-dev.sh.
- qemu-patches/: 0001-0005 generated, BUT 0003 (sim_clock) is STALE (it lacks the cpu_pause +
  vmstop_request fix) and 0006 is NOT generated yet. Rebuild the series from qemu-src/: new script
  = fresh git workspace with pristine files (from the release tarball), git am 0001, then commit the
  staged files with msgs/0002..0006 (0002 sensor+Kconfig/meson glue, 0003 sim_clock+glue,
  0004 xtensa imply, 0005 esp32.c, 0006 core files), then format-patch. The old scratchpad script
  mkpatches.sh is obsolete. Write msgs/0006.txt. Run checkpatch.pl (0 errors).
- Dev loop: docker volume qemu-dev (/dev-src/qemu, configured build); apply-dev.sh copies the staged
  files and runs ninja; scripts/dev-test-qemu.sh runs pytest with the dev binary swapped into
  esp32-sim-mcp:test-sensors. The images must be rebuilt after the patches are regenerated.

## Remaining failure
tests/integration/test_sensors.py::test_reset_reconnects_sensors. Debug with scratch/reset.py
(non-deterministic session + adxl345). A synchronous vm_stop deadlock was fixed just before the
stop; recheck whether it still fails, then investigate hub.before_restart/connect over emu_reset.

## Findings to record (not yet in DECISIONS.md / UPSTREAM_ISSUES.md)
- The esp32 APP CPU reset went through qemu_system_reset_request (async), so dual-core boots
  were non-deterministic under icount; fixed by patch 0005 (async_run_on_cpu). This is likely also
  the cause of M1's shift=5 result.
- The icount warp advanced the clock while a stop was pending (8.87 ms overshoot); fixed by 0006.
- vm_stop cannot be called from a QEMU_CLOCK_VIRTUAL timer callback (deadlock); use vmstop_request.
- The ESP32 RNG reads host entropy; deterministic mode passes -seed 1.
- The UART regex partial-match trap led to complete_lines=true by default.
- Design: SensorHub prefills samples to a horizon, sim-clock stops exactly there, refill+sync, cont.
  Banked chips get writes for every bank, so there's no reaction to guest writes (which would be
  host-timing dependent). ADS1115 defaults to 0x49 (tmp105 at 0x48).

## Next steps
1. Fix the reset test; regenerate patches 0002-0006; rebuild the sensors image; run all suites.
2. Update DECISIONS.md / UPSTREAM_ISSUES.md; commit M3.
3. M4: bench/ (10 apps + hidden scenarios + reference.patch, 3 needing sensors), harness with
   `claude -p` (smoke 2x2 only), CI workflow, README (full), demo/ transcript.
