# Pull request to espressif/qemu (esp-develop): prepared, not submitted

The owner submits this under their own name. Nothing here has been pushed or opened.

## Status (re-checked 2026-10-01)

| check | result |
|---|---|
| base | `esp-develop` head `febae182e1` (2026-04-29), 5 commits past `esp-develop-9.2.2-20260417`; the 5 are ESP32-C6/RISC-V work and touch none of the files below. Still the newest tag. |
| applies | `0005` and `0006` apply with plain `git am` on the head, **without** 0001–0004 (no fuzz, no 3-way merge). |
| checkpatch | `scripts/checkpatch.pl origin/esp-develop..esp32-icount-determinism`: 0 errors, 0 warnings on both commits. |
| builds | `configure --target-list=xtensa-softmmu`, `ninja qemu-system-xtensa`: OK. |
| effect | measured on the head, unpatched vs patched, see **Testing** below. |

### Recommendation: send 0005 now, hold 0006

- **0005** (esp32 machine, `hw/xtensa/esp32.c`) has a clean, reproducible A/B on current
  `esp-develop`: without it, dual-core runs at `-icount shift=5` produce 3 different UART logs in
  30 runs; with it, 30/30 are identical. 0005 alone accounts for the whole effect.
- **0006** changes generic QEMU code (`accel/tcg/icount-common.c`, `system/runstate.c`). Its effect
  was seen in this project with the sim-clock device (patch 0003, not part of the PR), which
  requests a VM stop from a timer callback. I have no standalone reproducer on stock esp-develop,
  so a reviewer has nothing to run. Two options: send it with the PR and say so plainly, or hold it
  until there is a reproducer (a qtest that requests a stop from a timer while the vCPUs idle).
  Because it is core QEMU code, Espressif may also ask for it to go to qemu-devel first.

The commands below cover both: a single-patch PR (0005) and, optionally, both patches.

### Numbers that are not backed by a committed log

The commit messages say "APP CPU cycle counts 277 cycles apart" (0005) and "8.87 ms" (0006). Both
come from the original investigation (`-d int` trace diffs, the sim-clock stop test), but no log
of either is in the repo. The earlier draft of this text also claimed "8 runs gave 2 distinct logs
at shift=3"; no log backs that either, and today's measurement does **not** reproduce a shift=3
divergence on `timer_det` (20/20 identical unpatched). That claim is dropped. Before submitting,
the owner may want to reword the two commit-message numbers as "for example" or remove them.

## Testing (for the PR body)

`experiments/upstream/ab_determinism.sh`, app `experiments/m1/timer_det` (esp_timer at 1 kHz plus a
busy task pinned to each core), ESP-IDF v6.1, `-icount shift=N,sleep=off -seed 1`. Each UART log is
cut at the app's `TIMER_DET_DONE` line and hashed. All three binaries are built from the same
`esp-develop` head; they differ only in the patches applied.

| binary | shift=3 | shift=5 |
|---|---|---|
| esp-develop head, unpatched | 10/10 identical | **3 distinct logs in 30 runs** (17 / 12 / 1) |
| + 0005 only | 20/20 identical | **20/20 identical** |
| + 0005 + 0006 | 10/10 identical | **30/30 identical** (same hash as 0005-only) |

N is small (10–30 runs per cell) and the divergence depends on host load, so the unpatched
shift=5 split is evidence of the race, not a rate. The patched hashes are identical across
separate batches.

## Commands for the owner

On Linux, macOS or WSL (on plain Windows, clone with `-c core.autocrlf=false` so `git am` sees the
patches byte for byte):

```sh
# 1. fork https://github.com/espressif/qemu on GitHub (button), then:
git clone -c core.autocrlf=false --branch esp-develop https://github.com/RomeoCoding/qemu.git
cd qemu
git remote add upstream https://github.com/espressif/qemu.git
git fetch upstream esp-develop
git checkout -b esp32-appcpu-reset-determinism upstream/esp-develop

# 2a. recommended: 0005 only
git am /path/to/dryflash/qemu-patches/0005-hw-xtensa-esp32-reset-the-APP-CPU-synchronously.patch
# 2b. or both
# git am /path/to/dryflash/qemu-patches/0005-*.patch /path/to/dryflash/qemu-patches/0006-*.patch

./scripts/checkpatch.pl upstream/esp-develop..HEAD      # expect 0 errors, 0 warnings
git push -u origin esp32-appcpu-reset-determinism

# 3. open the PR (or use the GitHub web UI), body = the section below
gh pr create --repo espressif/qemu --base esp-develop \
  --head RomeoCoding:esp32-appcpu-reset-determinism \
  --title "hw/xtensa/esp32: reset the APP CPU synchronously (deterministic dual-core runs under -icount)" \
  --body-file pr-body.md
```

## PR body (copy into pr-body.md)

> **hw/xtensa/esp32: reset the APP CPU synchronously**
>
> With `-icount shift=N,sleep=off`, two runs of the same esp32 image should behave identically.
> On dual-core images they do not: releasing the APP CPU from reset (`DPORT_APPCPU_RESET`, or a
> timer-group watchdog CPU reset) goes through `qemu_system_reset_request()`, which the main loop
> services at a host-dependent moment. The APP CPU may already be running by then, so it executes
> a varying number of instructions before its reset, and the guest diverges.
>
> This patch queues the APP CPU reset on that vCPU with `async_run_on_cpu()`, so it takes effect
> before the vCPU executes further, without the main loop. PRO CPU resets are unchanged.
>
> **Testing.** A small ESP-IDF v6.1 app (esp_timer at 1 kHz, one busy task pinned to each core)
> run repeatedly with `-icount shift=N,sleep=off -seed 1`; the UART log up to a marker line is
> hashed. All binaries are built from the same esp-develop head (`febae182e1`).
>
> | binary | shift=3 | shift=5 |
> |---|---|---|
> | unpatched | 10/10 identical | 3 distinct logs in 30 runs |
> | patched | 20/20 identical | 20/20 identical |
>
> checkpatch: 0 errors, 0 warnings. The test app and script are at
> https://github.com/RomeoCoding/dryflash (`experiments/m1/timer_det`,
> `experiments/upstream/ab_determinism.sh`), where this change keeps an emulator-based test
> harness reproducible.

If 0006 goes in too, add this paragraph and say plainly that it has no standalone reproducer:

> **icount: do not warp the clock while a VM stop is pending.** `icount_start_warp_timer()` warps
> `QEMU_CLOCK_VIRTUAL` when the VM is running and all vCPUs are idle. Between a stop request from a
> vCPU or device and the main loop handling it, the run state is still RUNNING while the vCPUs are
> halted for the stop, so the clock can jump to the next timer deadline instead of stopping where
> requested. The patch adds `qemu_vmstop_pending()` (non-consuming) and skips the warp while a stop
> or debug request is pending. We hit this with a device that requests a stop from a
> `QEMU_CLOCK_VIRTUAL` timer; we do not yet have a reproducer that runs on stock esp-develop.

## Later candidates from M5 (not yet prepared as PRs)

See docs/M5_REPORT.md, "Patches ready to propose upstream". In short: 0011 (SPI command phase),
0013 + 0018 (SPI completion IRQ and the interrupt matrix keeping source levels), 0009 (GPIO
registers), and the bus part of 0016. 0012 duplicates espressif/qemu PR #144 and must not be sent.
None of them has been rebased onto esp-develop head or A/B-tested there yet.
