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
