# dryflash

An MCP server that lets AI agents develop ESP32 firmware without a board. It builds ESP-IDF
projects, runs them in Espressif's QEMU, and drives them the way a developer would: serial console,
GDB, crash decoding. It also feeds realistic sensor data (accelerometer, ADC or any register-mapped
chip) over the emulated I2C bus, on a virtual timeline that makes runs repeatable byte for byte.

```
agent ──MCP/stdio──▶ dryflash (Docker: ESP-IDF v6.1 + QEMU + GDB)
                       ├─ project_build ─▶ idf.py ─▶ errors as file:line, sizes
                       ├─ emu_*  uart_* ─▶ QEMU esp32 / esp32c3 / esp32s3  (QMP, UART socket)
                       ├─ gdb_*          ─▶ xtensa/riscv GDB via GDB/MI ─▶ QEMU gdbstub
                       ├─ decode_panic   ─▶ Guru Meditation / abort / WDT → symbolized cause
                       ├─ sensor_*       ─▶ I2C sensor devices in QEMU, fed from Python models
                       └─ test_run       ─▶ YAML scenario → pass/fail + transcript
```

## Why

Firmware work is where coding agents stall: the feedback loop ends at "it compiles". Whether it
boots, crashes, or reads the accelerometer correctly needs a board on a desk and a human watching
a serial console. Emulation closes most of that loop. The missing parts were an agent-friendly
interface to it, and a way to put realistic, time-varying sensor data behind the firmware's I2C
driver. This project provides both, locally, with nothing to install but Docker.

It was built to answer a practical question: does an agent fix embedded bugs more reliably when
it can run and observe the firmware than when it can only compile it? `bench/` contains the setup
to measure that; see [Benchmark](#benchmark).

## Quickstart (about 5 minutes plus the image build)

You need Docker (Docker Desktop on Windows/macOS; on Windows it needs WSL2). Build the images once,
from a clone of this repository:

```sh
docker build -f docker/Dockerfile -t dryflash .                           # ~13 GB on disk (ESP-IDF v6.1, all targets)
docker build -f docker/qemu-sensors.Dockerfile \
             --build-arg BASE_IMAGE=dryflash -t dryflash-sensors .    # + patched QEMU, ~4 min
```

`dryflash-sensors` is a superset (stock tools plus sensor injection and exact virtual-time
control); use it unless you specifically want Espressif's unmodified QEMU.

The server runs in a container and sees your firmware project through a bind mount at `/work`.

**Claude Code** (from your project directory):

```sh
# macOS / Linux
claude mcp add dryflash -- docker run -i --rm -v "$(pwd)":/work dryflash-sensors
# Windows (PowerShell)
claude mcp add dryflash -- docker run -i --rm -v "${PWD}:/work" dryflash-sensors
```

**Claude Desktop**: add to `claude_desktop_config.json` (Settings → Developer → Edit Config), with
an absolute path to your project:

```json
{
  "mcpServers": {
    "dryflash": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "/home/me/my-firmware:/work", "dryflash-sensors"]
    }
  }
}
```

On Windows use a path such as `"C:\\Users\\me\\my-firmware:/work"`; on macOS `"/Users/me/my-firmware:/work"`.

Then ask, for example: *"Build this project, run it and tell me why it reboots."* The agent will
typically call `project_build`, `emu_start`, `uart_expect`, and on a crash `decode_panic`, which
returns something like:

```json
{"kind": "guru_meditation", "exception": "LoadProhibited",
 "cause": "NULL pointer dereference (read at 0x00000000) in apply_setting (main/main.c:22).",
 "backtrace": [{"function": "apply_setting", "file": "main/main.c", "line": 22}, ...]}
```

To try it without an agent, `examples/hello_world` and `examples/vibration_monitor` are ready to run:

```sh
docker run --rm -v "$(pwd)":/work dryflash-sensors test-run /work/examples/vibration_monitor scenario.yaml
```

## Tools

Sessions are running emulators, addressed by `session_id`. Every tool description is written for
the model: what it returns, when to call it, and what to call next.

| tool | what it does |
|---|---|
| `project_build(project_dir, target, clean)` | `idf.py build` out of tree. Returns ok, errors/warnings as `{file, line, column, message}` (errors first), binary and memory sizes. |
| `emu_start(project_dir \| image, target, deterministic, wait_for_gdb, sensors, reboot, watchdogs, icount_shift, qemu_args)` | Starts QEMU with the firmware and returns a session. Builds first if the project was never built. |
| `emu_stop`, `emu_status`, `emu_reset` | Stop (and clean up), inspect, or power-cycle a session. The reset keeps the flash, so NVS persists. |
| `emu_pause`, `emu_continue`, `emu_run_for(virtual_ms)` | Run control. `emu_run_for` is exact to the nanosecond of virtual time on the sensors image. |
| `uart_read(cursor, max_bytes)` | Cursor-based console reads (MCP has no push). |
| `uart_write(text)` | Type into the firmware's stdin. |
| `uart_expect(pattern, timeout_s, cursor)` | Wait for a regex. Returns groups and context, or the last output on timeout. Matches complete lines by default. |
| `gdb_break`, `gdb_continue`, `gdb_step`, `gdb_backtrace`, `gdb_registers`, `gdb_read_memory`, `gdb_eval` | GDB over GDB/MI. It attaches on first use; start with `wait_for_gdb=true` to break early. |
| `decode_panic(session_id \| text)` | Guru Meditation, abort, assert, stack overflow, task/interrupt watchdog, heap corruption → kind, registers, symbolized backtrace (addr2line), one-line probable cause. |
| `test_run(project_dir, scenario_file)` | Build + fresh session + scenario → pass/fail, per-step results, transcript, decoded crash. The tool CI and the benchmark use. |
| `sensor_set(sensor, values, at_ms)`, `sensor_stream(sensor, waveform, at_ms)` | Change injected sensor data mid-run: constants, synthetic waveforms or recorded CSV. |

The same scenario runner is available without MCP: `docker run ... dryflash[-sensors] test-run <project> <scenario.yaml>`
(prints JSON; exit code 0 on pass).

**Targets:** `esp32` has everything. `esp32c3` and `esp32s3` support build, run, UART, GDB and crash
decoding, but no sensors (Espressif's QEMU models I2C only for the esp32).

## Scenario schema

A scenario is a YAML file describing one emulator run and what the UART must show. Unknown keys are
rejected, and errors name the offending step.

```yaml
name: vibration monitor tracks injected vibration   # required
description: optional free text
target: esp32                 # esp32 | esp32c3 | esp32s3
timeout_s: 120                # whole scenario
emulator:
  deterministic: true         # -icount shift=N,sleep=off -seed 1: byte-identical runs
  icount_shift: 3             # 2^N ns per instruction
  reboot: false               # false: a guest reset ends the run (crash stays at the end of the log)
  watchdogs: true             # false disables the timer-group watchdogs (like idf.py qemu)
  qemu_args: []               # extra QEMU arguments
sensors:                      # esp32 + sensors image only; see "Sensor injection"
  - {model: adxl345, name: accel, address: 0x53, rate_hz: 400, waveform: {z: 1.0}}
fail_on:                      # regexes that fail the run as soon as they appear anywhere
  - 'Guru Meditation Error'   # (default: panics, abort, assert, stack overflow, task WDT, heap corruption)
steps:                        # run in order; each step has exactly one action
  - expect: 'block 2 rms_x=([0-9.]+)'   # regex; searches after the previous match
    timeout_s: 30
    value_range: [0.3465, 0.3607]       # optional: capture group 1 as a number must be in range
  - expect_not: 'overflow'              # fail if it appears within the window
    within_s: 1
  - write: "reset\n"                    # to the firmware's UART RX
  - run_for_ms: 500                     # let virtual time pass
  - sensor_set: {sensor: accel, values: {x: 0.0}, at_ms: 3000}
  - sensor_stream: {sensor: accel, waveform: {x: {type: csv, path: rec.csv, column: x}}}
```

`expect` matches only complete lines, so a number is never read before its line has fully
arrived. For deterministic sensor changes, give `at_ms` (virtual time); "now" on a running
emulator depends on host timing.

## Sensor injection

The sensors image adds a small patch series to Espressif's QEMU (`qemu-patches/`, built by
`docker/qemu-sensors.Dockerfile`):

- **`i2c-sim-sensor`**: a generic I2C target. It has a 256-byte register file behind the usual
  "write a pointer, then read or write with auto-increment" protocol. Its contents come from the
  host over a chardev: the host sends `(virtual_ns, bank, register, bytes)` updates, and a
  `QEMU_CLOCK_VIRTUAL` timer applies each one at its timestamp. The device never waits for the
  host. Four generic mechanisms cover real chips without chip-specific C:
  - a register **stride** (16-bit registers);
  - one **bank selector** (a register field, e.g. the ADS1115 MUX/PGA, picks which bank a data
    register reads from);
  - **read-set** bits (ready flags);
  - **read-only** ranges.
- **`sim-clock`**: a host link that reads the virtual clock and pauses the VM at an exact virtual
  time.

Sensor semantics live in Python (`src/dryflash/sensors/`). A model turns channel values (g,
volts, ...) into register bytes for every configuration the firmware could select. So the host
never has to react to what the firmware writes, which would make timing host-dependent.

```mermaid
sequenceDiagram
    participant FW as Firmware (i2c_master driver)
    participant Q as QEMU: esp32_i2c ➜ i2c-sim-sensor
    participant C as QEMU: sim-clock
    participant H as Host: SensorHub (Python)
    H->>Q: registers at t=0, samples for [0, 200 ms)  (W lines)
    H->>Q: S 1  (sync)
    Q-->>H: A 1  (all queued)
    H->>C: stop at 200 ms
    Note over FW,Q: VM runs; each sample is applied at its virtual timestamp
    FW->>Q: I2C read DATAX0..Z1
    Q-->>FW: bytes for the current bank
    C-->>H: X 200 ms  (VM paused exactly here)
    H->>Q: samples for [200, 300 ms), then sync
    H->>C: stop at 300 ms, then QMP cont
```

Because the guest can never reach a virtual time whose data is still in flight, a deterministic run
gives the same UART output however fast or slow the host is. `tests/integration/test_sensors.py`
checks this by running the vibration demo twice and comparing the logs byte for byte.

**Models**

| model | channels (unit) | notes |
|---|---|---|
| `adxl345` | `x`, `y`, `z` (g) | DEVID 0xE5, BW_RATE/POWER_CTL/DATA_FORMAT; all ranges, 10-bit and full resolution; DATA_READY always set. Default address 0x53. |
| `ads1115` | `ain0`..`ain3` (V) | Config register: MUX (all 8 inputs incl. differential) and PGA select the result, OS bit reads "done". Default address **0x49**: 0x48 is taken by the tmp105 the esp32 machine hard-wires. |
| `generic` | declared per sensor | `registers` (initial contents), `channels` → `{offset, format (u)int8/16/24/32_be/le, scale, bias}`, `stride`, `read_only`, `read_set`. |

**Waveforms** (any channel): a number; `sine {freq_hz, amplitude, offset, phase_deg}`;
`noise {std, mean, seed}` (a pure function of seed and time, so it is reproducible);
`step {steps: [[t_s, v], ...]}`; `rotation {rpm, amplitude, harmonics: [[order, amp], ...]}`
(an imbalance-style 1× running-speed line); `csv {path, column, time_column, time_unit, loop}`
(recorded data, linearly interpolated); or a list, which sums its terms. Samples are taken at the
sensor's `rate_hz` on the virtual timeline.

**Demo**: `examples/vibration_monitor` samples an ADXL345 at 400 Hz and prints per-axis RMS. Its
scenario injects a 25 Hz sine on x (expected RMS 0.3536 g), an 1800 rpm imbalance line on y
(0.1458 g) and gravity plus noise on z. The firmware prints `rms_x=0.3531 rms_y=0.1452`, within
the 3.9 mg quantisation. The scenario then silences x at t = 3 s and checks that a later block
reads zero.

## Limitations

- **No Wi-Fi, BLE, ADC (the on-chip one), I2S, RMT or USB.** Espressif's QEMU doesn't model them;
  I2S is an unimplemented device. Firmware that waits for Wi-Fi will wait forever.
- **Not cycle-accurate.** With `-icount shift=3` each instruction takes 8 ns of virtual time
  (≈125 MIPS vs ~240 on silicon), so CPU-bound code runs about 2× slower in virtual time than on
  hardware. Peripherals are functional models: an I2C transaction completes in zero virtual time,
  and bus timing, clock stretching and arbitration errors aren't modelled.
- **Sensors on esp32 only.** It is the only Espressif machine with an I2C controller model.
- **Deterministic mode costs about 1.6× wall time** (1.59 ± 0.02 wall-seconds per virtual second,
  N=10, in M1). Determinism holds for a given sequence of tool calls; interactive calls on a
  running emulator (`sensor_set` without `at_ms`, `emu_pause`) happen at host-dependent moments.
- **RISC-V crash backtraces** are MEPC plus RA only (IDF prints no backtrace there); use
  `gdb_backtrace` on a live session.
- **Cold builds are slow.** Builds live inside the container, so the first build of a session's
  container compiles ESP-IDF (45–110 s on the development laptop); incremental builds take ~3 s.
- The ADXL345 model has no FIFO, interrupts, tap/activity detection or JUSTIFY; the ADS1115 model
  has no comparator or ALERT pin.

## Comparison with prior art

Checked 2026-09-29/30:

| | runs firmware | debugger | crash decoding | sensor data | local / offline |
|---|---|---|---|---|---|
| **dryflash** | QEMU (esp32, c3, s3) | GDB/MI | yes | I2C, deterministic | yes (Docker) |
| [ESP-IDF Tools MCP](https://developer.espressif.com/blog/2026/04/esp-idf-tools-mcp-server/) (built into `idf.py`, IDF 6.0+) | no: set_target, build, flash, clean | no | no | no | yes |
| [Wokwi CLI MCP mode](https://docs.wokwi.com/wokwi-ci/mcp-support) | Wokwi simulator | no | no | Wokwi parts | no: cloud, needs `WOKWI_CLI_TOKEN`; marked experimental |
| [atomicdog/renode-mcp](https://github.com/atomicdog/renode-mcp) | Renode | no | no | no | yes; thin wrapper (13 tools, one commit) |

Wokwi simulates many more parts, but runs in the cloud and needs an account and token.
dryflash is local and free, gives deterministic replay, and uses Espressif's own QEMU and
toolchain.

## Benchmark

`bench/` holds 15 small ESP-IDF apps, each with one planted bug, a bug report (`TASK.md`) and a
hidden acceptance scenario:

- **General bugs:** stack overflow, watchdog starvation, ring-buffer off-by-one, FreeRTOS race,
  NULL dereference on bad input, timer unit error.
- **Four that need sensor injection to detect:** wrong register, wrong byte order, two
  unit/scaling errors.
- **Five multi-file apps where the symptom does not point at the faulty line:** a 16-bit time
  stamp that wraps after 65 s, a glitch filter that latches on one waveform shape, an `snprintf`
  overflow that crashes in a different module, a sample period truncated by the RTOS tick, and a
  16-bit overflow exercised by a recorded CSV refill.

`bench/verify.py` proves every hidden test discriminates: it fails on the shipped app and passes
with `bench/<app>/reference.patch` (results in `bench/results/verify.json`).

`bench/harness.py` runs Claude Code headless (`claude -p`) on each task with this server, and
without it (compile-only). It records success on the hidden test, wall time, turns, tokens and
cost. Two runs have been done: a 2 × 2 smoke run on the first set, and one attempt per
configuration on each of the five second-set tasks. All 14 runs passed, with and without the
server, so the benchmark does not yet show the server making a difference. See
[bench/README.md](bench/README.md) for the results, the problems the runs exposed, the commands
and cost estimates.
With N this small, no difference between the configurations can be called significant, and no
such claim is made.

## Development

```sh
docker build -f docker/Dockerfile --target test -t dryflash:test .
docker build -f docker/qemu-sensors.Dockerfile --build-arg BASE_IMAGE=dryflash:test -t dryflash:test-sensors .
scripts/dev-test.sh                                  # unit tests, QEMU-free (<10 s)
scripts/dev-test.sh -m integration                   # real builds and QEMU sessions
IMAGE=dryflash:test-sensors scripts/dev-test.sh -m sensors
python scripts/smoke_session.py --docker dryflash   # stdio MCP session end to end
```

The Python code is `src/dryflash/` (Python 3.12, MCP SDK 2.2, dependencies pinned in `uv.lock`).
Design decisions are in [DECISIONS.md](DECISIONS.md), bugs found in ESP-IDF/QEMU in
[docs/UPSTREAM_ISSUES.md](docs/UPSTREAM_ISSUES.md), and the feasibility study in
[docs/M1_REPORT.md](docs/M1_REPORT.md). CI (`.github/workflows/ci.yml`) builds both images with
layer caching and runs the unit, integration and sensor suites.

## Licence

The server, Python code, examples and benchmark are **MIT** ([LICENSE](LICENSE)). The QEMU patch
series in `qemu-patches/` modifies QEMU and is **GPL-2.0-or-later**, like QEMU itself
([qemu-patches/LICENSE](qemu-patches/LICENSE)). The MIT code never links against QEMU: it talks
to it over QMP, sockets and GDB, so the two licences stay separate. The sensors image contains a
QEMU binary built from Espressif's GPL source plus these patches. Anyone distributing that image
must also offer the corresponding source, which is the pinned upstream tarball (checksum in the
Dockerfile) plus `qemu-patches/`.
