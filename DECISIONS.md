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
