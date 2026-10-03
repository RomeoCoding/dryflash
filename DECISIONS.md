# Decisions

One entry per non-obvious call: the decision, the alternative, and why.

## M1

- **Stock QEMU from the IDF image for the base image; patched QEMU only in the second image.**
  Alternative: always build QEMU. Why: the v6.1 image already ships the pinned
  esp_develop_9.2.2_20260417 build, and the base image stays GPL-patch-free and quick to build.
- **Patch 0001 moves the esp32 I2C controllers to sysbus-default and uses auto bus names
  (`i2c-bus.0/1`).** Alternatives: a machine property listing I2C devices, or creating devices
  from machine init. Why: it is the conventional QEMU arrangement (aspeed and others do the same),
  it's the smallest diff, it keeps `-device ...,bus=` working for any I2C slave, and the reset
  side effect can't be observed (see M1_REPORT question 2).
- **Keep the hard-wired tmp105 at 0x48; ADS1115 examples use 0x49.** Alternative: remove it or
  gate it behind a machine property. Why: removing it changes behaviour for existing users, and
  a property would add patch surface for little gain.
- **Deterministic mode = `-icount shift=3,sleep=off`.** Alternatives: shift=2 (closer to
  240 MHz, 1.8× slower in wall time), shift=5 (fast but measured non-deterministic). Why: it is
  the fastest setting that was byte-identical in 10/10 runs.
- **The QEMU build fetches meson subprojects (keycodemapdb, dtc wraps) with git at the
  revisions pinned in the tarball.** Alternative: vendor them. Why: Espressif's source tarball
  ships `.wrap` files, not the subprojects. The revisions are pinned by commit, so the build
  stays reproducible.
- **The patched QEMU build drops SDL** (Espressif's flags otherwise). Why: the server is
  headless, and this saves image size and build dependencies.
- **Treated the owner's `/goal` ("work until the prompt is complete") as the go past the M1
  checkpoint.** Alternative: stop and wait. Why: the owner set the goal after writing the prompt
  and then said "continue". The M1 report was still written and committed first.

## M2

- **MCP Python SDK 2.2.0 (`MCPServer`), not 1.x (`FastMCP`).** Why: it is the current release, and
  the brief asked for the official SDK without naming a version. v2 renamed FastMCP to MCPServer and
  reports only `ToolError` messages to the client, so the server maps its domain errors
  (session, GDB, QMP, scenario, target) to `ToolError` in one decorator.
- **Tools beyond the brief's list: `emu_pause` and `emu_continue` as separate tools**, instead of
  one tool with a flag. Why: each is one obvious verb for the model; `emu_run_for` covers stepping
  in virtual time.
- **Sessions always start QEMU with `-S`**, and resume after the UART socket is connected (or not
  at all with `wait_for_gdb`). Why: a chardev socket in `wait=off` mode drops output while no
  client is connected, and without `-S` the start of the boot log would be lost.
- **`-no-reboot` by default.** Alternative: boot-loop like hardware (`reboot=true` is available).
  Why: a crash then ends the session with the report at the end of the log, instead of scrolling
  away in a reboot loop, and QEMU stops burning CPU.
- **`emu_reset` restarts the QEMU process (power cycle) instead of QMP `system_reset`.** Why: on
  the esp32 machine `system_reset` is followed by a TG0 watchdog reset from the ROM (see
  UPSTREAM_ISSUES). With `-no-reboot` that ends the session, and without it the reset isn't
  clean. A process restart is a true power-on and stays deterministic. The flash file (and so
  NVS) is kept.
- **Unix sockets for QMP and UART, TCP only for the gdbstub**, with ports from an in-process
  allocator that never hands out a port a live session holds. Why: Unix sockets can't collide,
  and each container has its own network namespace, so allocation only has to be unique within
  one server.
- **Out-of-tree builds in container-local `/tmp/esp32-sim-mcp/builds/<project>-<hash>-<target>`,
  with `-DSDKCONFIG` there too.** Why: the user's project stays clean (no root-owned `build/` on
  Linux hosts), and bind mounts are slow for builds. The trade-off is that a fresh container
  starts with a cold build (45 to 110 s on the dev laptop; 3 s incremental).
- **GDB attaches lazily on the first `gdb_*` call and restores the previous run state.** Why:
  sessions that never debug pay nothing, and `gdb_break` on a running board doesn't leave it
  halted by surprise.
- **Default eFuse image generated from `idf_py_actions.qemu_ext.QEMU_TARGETS`**, i.e. IDF's own
  table, cached per target. Why: the same chip revision `idf.py qemu` uses, without copying
  Espressif's data.
- **`emu_run_for` on stock QEMU is approximate** (wall-time estimate from the M1 ratio, reported
  as `exact: false`). Why: stock QEMU has no way to stop at a virtual time (`replay-break` needs
  record/replay mode). The sensors image adds exact stops (M3).
- **RISC-V panics are symbolized from MEPC and RA only.** Why: IDF prints no backtrace for RISC-V
  chips, and the full unwind needs GDB on the stack dump; `gdb_backtrace` on a live session
  covers it.
- **The smoke session breaks at `app_main` before waiting for the greeting.** Why: `app_main`
  prints the greeting, so a breakpoint set after it can never be hit.

## M3

- **One generic C device (`i2c-sim-sensor`, 549 lines) plus a tiny `sim-clock` device (201
  lines), not per-chip C models.** Why: the brief puts sensor semantics in Python. Four generic
  mechanisms cover the ADXL345 and ADS1115 without chip code: register stride, one bank selector,
  read-set bits and read-only ranges.
- **Banked chips get one write per bank for every sample**, instead of the host reacting to the
  firmware's configuration writes. Why: a host reaction arrives at a host-dependent time, which
  would break determinism. The cost is volume (ADS1115: 64 writes per sample), which the line
  protocol handles comfortably at the default rates (ADXL345 400 Hz, ADS1115 250 Hz).
- **Determinism by slicing, not by bulk preload:** the host sends samples up to a horizon, and
  `sim-clock` pauses the VM exactly there. The host then sends the next 100 ms, waits for a sync
  acknowledgement from every sensor, and resumes. Alternatives: preload a whole run (memory
  grows with run length, and mid-run changes aren't possible), or stream while running (any
  host-driven `timer_mod` on a running VM kicks the round-robin vCPU loop at a host-dependent
  moment). The same stop mechanism makes `emu_run_for` exact.
- **Line-oriented ASCII protocol on the chardevs.** Alternative: a binary framing. Why: it is
  debuggable with `socat`, reviewable in C, and fast enough (parsing is not the bottleneck).
- **`sensor_set` takes an optional `at_ms`.** Why: "now" on a running VM depends on host timing.
  Changes at an explicit virtual time (or while paused) are reproducible. A change that lands
  inside already-queued data re-sends those samples; equal timestamps apply in arrival order,
  so the re-sent ones win.
- **`uart_expect` matches complete lines by default.** Why: output streams in chunks, and
  `rms_x=([0-9.]+)` matched a half-received `0.` in the first demo run. An agent would hit the
  same trap with any `value=(\d+)` pattern.
- **Two QEMU fixes outside the device itself (patches 0005, 0006) were needed for determinism.**
  Why: see UPSTREAM_ISSUES 5 and 6. Both are small, justified in their commit messages, and pass
  checkpatch; the alternative (documenting "almost deterministic") would have failed the
  byte-identical requirement.
- **Deterministic mode also passes `-seed 1`.** Why: the esp32 RNG peripheral reads
  `qemu_guest_getrandom`, which is host entropy otherwise.
- **Sensor waveforms restart at virtual time 0 after `emu_reset`.** Why: the reset restarts QEMU,
  and its virtual clock starts again from 0; the waveform timeline stays the same.

## M4

- **Facts from the brief corrected:** atomicdog/renode-mcp lists 13 tools, not 12, and shows no
  "inactive" marker (it has a single commit). The Veecle article (2026-08-13) could not be
  re-verified, so it is not cited. The ESP-IDF Tools MCP ships inside `idf.py` from IDF 6.0
  (set_target, build, flash, clean). Wokwi's MCP mode is confirmed as experimental, cloud-based
  and token-gated.
- **Hidden tests live next to each app (`bench/<app>/hidden/`), and the harness copies only
  `app/` and `TASK.md` into the agent's workspace.** Alternative: a separate private repo. Why:
  everything stays reproducible from one checkout, and the agent still never sees them.
- **Baseline = file tools plus a `./build.sh` that compiles in Docker, no general shell.** Why: it
  is the "compile and reason" workflow the MCP server is meant to improve on. A general shell
  would let the baseline agent run QEMU by hand, which turns the comparison into a test of
  improvisation.
- **Harness defaults to `claude-sonnet-5`** (`--model` to change). Why: it is the cost-sensitive
  choice for a 20-run benchmark; the owner decides whether to spend more.
- **Agent runs inherit the operator's user-level CLAUDE.md.** `--setting-sources project` and
  `--disable-slash-commands` strip user settings and skills, but not user memory, and `--bare`
  needs an API key instead of the owner's login. `--claude-config-dir` allows a clean run; the
  smoke run did not use it, and bench/README says so.
- **The demo reuses two benchmark apps** (`null_config` for the crash, `adc_byte_order` for the
  sensor bug) instead of a demo-only firmware. Why: the story (crash → decode → fix, then a
  sensor test failing → fix → passing) uses code that is already verified.
- **`bench/verify.py` wipes the build directory and copies with fresh mtimes.** It found a real
  hazard: ninja trusts mtimes, and `copytree` preserves them, so a reused path silently tested a
  stale (already fixed) binary. The harness's per-task baseline build volume is removed for the
  same reason.

## Release prep

- **Renamed to `dryflash`** (the owner's choice after M1): Python package `dryflash`, CLI
  `dryflash`, images `dryflash` and `dryflash-sensors`, MCP server name `dryflash`, env vars
  `DRYFLASH_*`, QEMU pkgversion suffix `+dryflash`. Checked 2026-09-30: no PyPI package
  (`dryflash`, `dryflash-mcp`), no GitHub repository, no Glama, mcp.so or PulseMCP entry. The
  folder keeps its working name, as the brief asked; earlier entries in this file use the old
  name.

## Post-release: harder benchmark tasks

- **Five new tasks, named after the product rather than the bug** (`humidity_logger`,
  `scale_display`, `vibration_telemetry`, `pressure_alarm`, `tank_gauge`). Why: the harness names
  each workspace `<task>-<config>`, so names like `adc_byte_order` hand the agent the answer.
  The first ten keep their names so that the smoke run stays comparable; bench/README.md says so.
- **The CSV recording lives in `app/data/`, so the agent sees it.** Why: CSV paths resolve
  against the project directory (the agent's workspace), and a customer attaching a field log is
  realistic. The hidden test replays the same file; its limits come from the tank geometry,
  computed independently of the firmware.
- **The crash task relies on .bss layout** (`s_cal` directly after `s_frame`). Checked with
  `nm`: the variables are adjacent in link order (telemetry.c before calib.c in SRCS). A
  toolchain or link-order change could move the victim; `verify.py` would then show the shipped
  app not crashing, which is why it is rerun after any ESP-IDF bump.
- **Timing in hidden tests uses printed virtual-time stamps or `run_for_ms`, never `within_s`
  for "nothing happened before T".** Why: `within_s` is wall time and the emulator runs between
  2× slower and ~5× faster than real time depending on load (an idle app ran 68 virtual s in
  15 s).
- **`verify.py` merges into `verify.json`** instead of overwriting it, so verifying a subset of
  apps keeps the record of the rest (unit-tested in tests/unit/test_bench.py, which also checks
  every task's layout and that every hidden scenario and sensor spec parses).
- **The `emu_start` description documents every sensor model and the `generic` fields.** Why:
  in run hard-a an agent read only the tool description, took `generic` for a register-less
  stub and did not emulate the NAU7802. Tool descriptions are the only documentation an agent
  is guaranteed to read; the README is not.
- **Baseline `build.sh` exports `MSYS_NO_PATHCONV=1`, and `Bash(./build.sh:*)` is allowed.** Why:
  in run hard-a two baseline agents could not compile (Git Bash path mangling; a call form the
  allow-list did not match).
- **hard-a is reported as a null result with its confounds** rather than repeated to "get a
  difference". All ten runs passed. The confounds (baseline compile failures, one MCP run that
  never emulated) are listed next to the numbers in bench/README.md.

## Demo recording prep

- **Presentation is separate from the session.** `run_demo.py` keeps the same tool calls,
  arguments, order and reference patches, and writes the same markdown to `transcript.md`. The
  terminal view (banners, spinner, typing, condensed results, captions) is a `Presenter` that
  only formats; the transcript keeps the full results. Why: the brief asked for a recording-friendly
  demo "without changing what it proves".
- **Narration is held for its reading time (150 words per minute), and subtitles come from the
  real run.** Why: a voiceover recorded at that pace stays in sync without editing, and the
  `.srt` carries the actual cue times (clipped to the next cue, split into two-line blocks of at
  most 42 characters).
- **`--warm-up` shows a cached rebuild in `project_build`.** The short `duration_s` it reports is
  true for a cached build; demo/README.md says so. The committed transcript comes from a cold run.

## Upstream PR prep

- **Recommend sending 0005 alone first.** On esp-develop head it has a reproducible A/B (3 distinct
  logs in 30 runs → 30/30 identical at shift=5) and accounts for the whole measured effect. 0006 is
  generic QEMU core code without a standalone reproducer on stock esp-develop; it waits for one
  (or goes with an explicit caveat), and may belong on qemu-devel.
- **Claims without a committed log were dropped from the PR text** ("8 runs, 2 distinct logs at
  shift=3"). Today's shift=3 runs were 20/20 identical unpatched, so the draft overstated it.

## Robustness (item 4)

- **The "GDB continue → uart_expect timed out under load" failure was not reproduced.** 53 runs of
  the exact tool sequence (`scripts/stress_gdb_resume.py`): 5 idle, 24 with 3 parallel sessions
  and 16 CPU burners, 24 with 4 parallel sessions under a 700 MB memory cap. All passed, and the
  slowest `uart_expect` took 0.03 s. "Hello" is the first statement after the breakpoint, so the
  old 30 s timeout cannot have been a slow-board problem: the CPU was halted. Raising the smoke
  timeout to 90 s only hid that.
- **`uart_expect` now reports a halted CPU instead of timing out.** If the session is paused, or
  GDB has the CPU stopped, for more than 1 s (the grace period lets a racing resume win), it returns
  matched=false with a reason naming the stop location and how to resume. Any recurrence of the
  original failure now explains itself, and agents that call `uart_expect` at a breakpoint get an
  answer in about a second instead of after the full timeout. The smoke timeout is back to 30 s.
- **README quick-start built the wrong image.** `docker build -f docker/Dockerfile -t dryflash .`
  builds the last stage (`test`, CMD pytest); the runtime image needs `--target base`. CI already
  used the right target.

## M5

Milestone brief: docs/provenance/verus-peripherals-prompt.md (SPI sensors, GPIO, MPU-6050, display
capture, UART over TCP; Verus is the acceptance test).

### Step 0 (spike, experiments/m5_spike)

- **Measured, not assumed.** A throwaway SSI device, register traces and `tests/firmware/spi_probe`
  answered the three questions; the evidence is in experiments/m5_spike/README.md. Summary:
  ESP-IDF polling transfers complete, the interrupt-driven path hangs (the controller never raises
  its IRQ), DMA transfers "succeed" with no data, and two controller bugs garble every read
  (`byte`/`i`, already fixed in the unmerged espressif/qemu PR #144; a phantom command phase,
  not reported upstream). Arduino-style libraries drive CS by GPIO and leave all three controller
  CS lines enabled, so correct framing needs a CS from a modelled GPIO pin. User SSI devices
  cannot reach SPI2/SPI3 today; a machine-init-done notifier can wire their CS.
- **The `byte`/`i` fix is not claimed as a finding.** PR #144 (2026-02-28) reported and fixed it
  first; our patch will credit it, or be dropped if #144 merges before we propose ours.
- **Went past the step-0 checkpoint on the owner's `/goal`**, as in M1: the goal ("read the
  prompt and do it") was set with the brief, and the session's stop hook rejected stopping at
  the checkpoint. The checkpoint report was written first (experiments/m5_spike/README.md), and
  the proposals in it were adopted unchanged: GPIO before the SPI chip-select work, bus names
  `spi2`/`spi3`, one patch per change.

### M5b/M5c: GPIO and SPI devices

- **sim-gpio is a separate host-link device, not part of the esp32 GPIO model.** The esp32 model
  (patch 0009) only gains registers and named per-pad lines, so it stays a plain chip model that
  boards can wire; the virtual-time host link (0010) is generic and knows nothing about the esp32.
  The esp32 machine wires them together after `-device` creation (0016).
- **A pad's level = output if enabled, else the external level.** IO_MUX pull-ups and the GPIO
  matrix are not modelled, so declared inputs carry an explicit default (`{pin: 27, default: 1}`)
  and pads routed to a peripheral signal still follow GPIO_OUT/GPIO_ENABLE. GPIO-driven chip
  selects get default 1 automatically.
- **GPIO inputs reach QEMU only while the VM is stopped.** Declared pins put the session in
  virtual-time slices (as sensors do); an event at or beyond the next slice boundary is queued
  and sent at the boundary stop, so its timing is reproducible. Anything else is sent at once and
  the tool result says `deterministic: false`. Output changes are reported by QEMU with a
  blocking write (they are the record of what the guest did) and read after a sync round trip.
- **SPI chip select from the controller or from a GPIO pad (`cs_gpio`), chosen per device.**
  Arduino-style drivers need the GPIO path (step 0, Q2); ESP-IDF's spi_master works with either.
- **One shared register-file core for I2C and SPI sensors (0014), not a second copy.** The brief
  allowed factoring; ssi-sim-sensor (0015) is ~200 lines because of it. The refactor changed no
  behaviour: the I2C sensor tests passed unchanged before and after.
- **The interrupt matrix fix (0018) was found, not planned.** With the SPI IRQ implemented (0013),
  ESP-IDF's interrupt-driven transfers still hung: IDF disables an interrupt by re-routing its
  source and enables it by routing it back, and QEMU's matrix forwarded a source only on a level
  change, so an already-asserted source was lost. It now keeps source levels and ORs the sources
  mapped to each CPU interrupt. All 30 integration and sensor tests, including both determinism
  tests, pass on the new build.
- **MAX31855 open input reads 0x1FFF in D31-D18**, as the datasheet's serial-interface section
  states for unconnected T+/T-. For the short faults the datasheet does not specify the
  temperature bits; the model keeps reporting the injected `tc_c`.

### M5a: MPU-6050

- **Bank selection over several register fields (patch 0007), not gyro-at-±250-only and not two
  selectors.** The brief offered three options. The data the guest must read depends on three
  fields in three registers: SLEEP (PWR_MGMT_1), AFS_SEL (ACCEL_CONFIG) and FS_SEL (GYRO_CONFIG).
  "Accelerometer ranges only" would silently mis-scale gyro data at other ranges, and two
  selectors still could not express SLEEP. A list of up to four `offset:mask` fields forming the
  bank number covers all three (32 banks over 0x3B-0x48) and stays generic (other IMUs split
  their state the same way). The old single-field properties are unchanged, and the ADXL345 and
  ADS1115 tests pass on the new binary.
- **Sleep is a bank, so "reads zero until woken" needs no host reaction.** The 16 SLEEP=1 banks are
  never written and stay zero, which is what the chip returns after power-on. Deviation: a chip put
  back to sleep after running keeps its last sample; the model reads zero. Recorded in the README.
- **Self-clearing bits (patch 0008, `write-clear`).** Adafruit's MPU-6050 driver sets DEVICE_RESET
  and polls until it reads back 0; a plain register file hangs it. Only the bits the register map
  documents as self-clearing are listed: DEVICE_RESET (4.30) and USER_CTRL bits 0-2 (4.29);
  SIGNAL_PATH_RESET is not documented as self-clearing and stays a plain register. The reset's
  side effect (restoring defaults) is not modelled.
- **Datasheet: RM-MPU-6000A-00 revision 4.0 (2012-03-09).** Revision 4.2 is the newest, but its
  official link served an HTML page instead of the PDF, so 4.0 (SparkFun mirror, sha256
  `ccaa6312…7c05d`) was used and **not compared against 4.2**. Section numbers in the code refer
  to 4.0.
- **Default rate 1 kHz**, the accelerometer output rate (4.2). The cost is 16 W lines per sample,
  the same line rate as the ADS1115 at 250 Hz.
- **Addresses are restricted to 0x68/0x69** (AD0), with an error naming both; any other address
  would be a spec mistake, not a chip variant.

### Non-goals (from the brief)

- **BLE and Wi-Fi.** Espressif's QEMU has no radio or Bluetooth controller model. The only route
  would be NimBLE over HCI-UART to a virtual controller on the host, far beyond this milestone.
  Verus's USB-serial fallback covers testing, and M5e makes it reachable from the host.
- **The on-chip ADC, SPI DMA and SPI slave mode.** Not modelled. Step 0 showed DMA transfers return
  `ESP_OK` without data, so firmware under test must use `SPI_DMA_DISABLED`; that limit is
  documented rather than modelled, because sensor transactions fit in the 64-byte buffer.
