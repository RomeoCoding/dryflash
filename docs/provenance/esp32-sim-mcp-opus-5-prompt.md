# Opus 5.5 prompt: ESP32-in-QEMU MCP server with sensor injection

## Recommended settings

| Setting | Value | Why |
|---|---|---|
| Model | `claude-opus-5-5` | Long-horizon, multi-language (Python + QEMU C) build from an empty folder |
| Effort | `xhigh` | End-to-end project across four milestones, including a C device model in a large, unfamiliar codebase |
| Thinking | enabled | Leave it on; if cost bites, lower effort before touching thinking |
| Context | 1M default | Long session; no special handling needed |

How to start: open Claude Code in `C:\Users\Romeo Mattar\Projects\esp32-sim-mcp`, set the
model and effort above, start Docker Desktop, then paste everything inside the fenced block
below as the first message.

What to watch on the first run:
- The session should stop after M1 with `docs/M1_REPORT.md`. If it carries on into M2
  without stopping, the `<workflow>` block is the one to strengthen.
- If its milestone updates run long, strengthen the `<tone_preference>` tail block. Effort
  won't fix verbosity.
- If it spins up several subagents for small things, tighten `<subagent_policy>`.

---

## The prompt

```
<role_and_objective>
You are a coding agent building a new open-source project from an empty folder: an MCP
server that lets AI agents build ESP32 firmware, run it in Espressif's QEMU fork, drive it
like a developer would (serial console, debugger, crash decoding), and feed it realistic
sensor data over the emulated I2C bus. Firmware can then be developed and tested without a
board. This is the owner's personal portfolio project, so depth, correctness and honest
documentation matter more than feature count.
</role_and_objective>

<background_already_verified>
The owner's previous session checked these facts on 2026-09-29, and they shaped the plan.
Treat them as strong leads, re-confirm the ones you depend on, and record any that turn out
wrong in DECISIONS.md.

- Espressif's QEMU fork: github.com/espressif/qemu, branch esp-develop. Latest release tag
  esp-develop-9.2.2-20260417. Machines exist for esp32, esp32s3 (hw/xtensa) and esp32c3,
  esp32c6 (hw/riscv).
- hw/i2c/esp32_i2c.c (283 lines) is a real ESP32 I2C controller model. It creates a
  standard QEMU I2C bus with i2c_init_bus(DEVICE(s), "i2c") and implements command
  execution via i2c_start_transfer / i2c_send / i2c_recv. hw/xtensa/esp32.c instantiates
  ESP32_I2C_COUNT controllers ("i2c0", "i2c1"), each with its own bus named "i2c". Two
  buses with the same name may make `-device ...,bus=` addressing ambiguous; check with
  `info qtree`.
- There is no I2C model for esp32c3/c6/s3 in hw/i2c, no ADC model at all, and I2S is
  registered as an unimplemented device (esp32.i2s0/i2s1). No Wi-Fi or BLE. UART, GPIO,
  SPI, SPI flash, LEDC, timers, TWAI, crypto, eFuse, flash encryption, SD/MMC, OpenCores
  Ethernet and a virtual framebuffer are modelled.
- ESP-IDF docs (stable v6.1) cover `idf.py qemu [monitor|gdb]`, `--gdb`, `--graphics`,
  `--efuse-file`, `--flash-file` and `--qemu-extra-args`, plus
  `idf_tools.py install qemu-xtensa qemu-riscv32`. Raw usage:
  `qemu-system-xtensa -nographic -machine esp32 -drive file=flash.bin,if=mtd,format=raw`,
  with `-s -S` for GDB and `-serial tcp::5555,server,nowait`.
- Prior art, to position against in the README rather than copy:
  - Espressif's ESP-IDF Tools MCP has only set_target / build / flash / clean, with no
    emulation.
  - Wokwi's CLI has an official but experimental MCP mode. It's cloud-based and needs a
    token.
  - atomicdog/renode-mcp is a thin Renode wrapper (12 tools, marked inactive) with no
    debugger and no sensor injection.
  - A Veecle article (2026-08-13) calls hardware-free firmware execution the missing piece
    for agents.
- Host machine: Windows 11. Docker Desktop is installed but may not be running. There is
  no WSL, and no ESP-IDF, QEMU or gh CLI on the host. Everything toolchain-related runs in
  containers.
</background_already_verified>

<task_specification>
Build the project in four milestones. M1 ends in a stop-and-report checkpoint; M2 to M4 run
without stopping.

ARCHITECTURE (the owner's decisions; don't revisit them without a finding that forces it)
- The MCP server is Python 3.12 with the official MCP Python SDK, speaking stdio.
- The server runs INSIDE a Docker image together with ESP-IDF v6.1, the ESP32 toolchain,
  its GDB, and QEMU. A client registers it as `docker run -i --rm -v <project>:/work ...`,
  so the host needs nothing but Docker.
- Pin everything: base images by digest or exact tag, the ESP-IDF version, the QEMU tag,
  and Python dependencies with exact versions (uv lockfile).
- GDB goes through the GDB/MI interface (pygdbmi or equivalent). QEMU control uses QMP.
- Licence: MIT for the server and Python code. The QEMU device lives as a patch series
  under qemu-patches/, licensed GPL-2.0-or-later like QEMU, and is built into a second
  image by a Dockerfile that applies the patches to the pinned esp-develop tag. Explain
  the split in the README.
- Primary target: esp32, the only chip with an I2C model. esp32c3 (and s3 if it works
  cleanly) are supported for build, run, serial and debug, without sensors.

M1: FEASIBILITY CHECK (about a day), then STOP
Answer each question with evidence (the exact commands, and output excerpts), in
docs/M1_REPORT.md:
1. Toolchain: does espressif/idf (pinned v6.1) already ship QEMU? If not, how do you add
   it? Build and run hello_world in QEMU for esp32 and esp32c3 inside the container, and
   report timings.
2. I2C attach: can a stock QEMU I2C target (e.g. tmp105, or at24c-eeprom) be attached to
   the esp32 machine's I2C0 bus from the command line? What exact syntax works, given the
   duplicate bus names? If it can't be done from the command line, what is the smallest
   change that fixes it?
3. Driver compatibility: does ESP-IDF v6.1's i2c_master driver complete a register read
   from that attached device through esp32_i2c.c? If not, what fails (which command-list
   features are missing)?
4. Determinism: with -icount (shift=N, sleep=off), do two runs of a timer-driven app give
   byte-identical UART output? What does that cost in speed?
5. Feasibility of the custom device in M3: go or no-go, with the main risk and your
   fallback if it's no-go.
6. Names: propose three project names. For each, check that no GitHub repo, PyPI package
   or MCP registry entry (Glama, mcp.so, PulseMCP) already uses it, and show what you
   checked.
Commit, then stop and wait for the owner's go. Don't start M2 in the same turn.

M2: CORE SERVER
Tools are session-based: a session is one running emulator. Write every tool description
for a model reader: what it returns, when to call it, and what to call next. Expected
tools (adjust names and granularity if you find a better design, and record why in
DECISIONS.md):
- project_build(project_dir, target) -> ok/failed, compiler errors parsed to file:line:msg,
  binary sizes.
- emu_start(project_dir|image, target, deterministic, wait_for_gdb, sensors=[]) ->
  session_id. emu_stop, emu_status, emu_reset.
- uart_read(session, cursor, max_bytes), cursor-based because MCP has no push.
  uart_write. uart_expect(session, regex, timeout_s) returns the match plus surrounding
  context, or a timeout with the last output.
- emu_run_for(session, virtual_ms) and pause/continue via QMP, meaningful in
  deterministic mode.
- Debugger: gdb_break (location or address), gdb_continue (until a stop or timeout),
  gdb_step, gdb_backtrace, gdb_registers, gdb_read_memory, gdb_eval.
- decode_panic(session or text): Guru Meditation or abort output -> symbolized backtrace
  (addr2line on the ELF), register dump, and the probable cause in one line.
- test_run(project_dir, scenario_file): build, start, apply sensor inputs, check a list of
  UART expectations with timeouts, and return pass/fail with a transcript. This is the
  tool CI and the benchmark use.
Scenario files are YAML with a documented schema. Temp files, ports and processes are
cleaned up on stop, on error, and when the MCP client disconnects. Parallel sessions must
not collide on ports.

M3: SENSOR INJECTION
- A small, generic QEMU I2C target device in C, as a patch on esp-develop:
  - It has a 256-byte register file with the usual pointer-then-auto-increment protocol.
  - It is configured with properties: address, a chardev for the host link, and optional
    "bank select" rules, so a mux or config register can pick which bank a data register
    reads from. That covers ADC chips like the ADS1115 without chip-specific C.
  - Sensor semantics live in Python on the host side, not in C.
  - The host sends time-stamped updates (virtual_ns, register, bytes). The device applies
    them on QEMU_CLOCK_VIRTUAL, so deterministic mode stays deterministic no matter how
    fast the host is.
  - Never block QEMU's main loop waiting on the host.
  - Aim for a device small enough to review in one sitting (roughly under 600 lines).
    Follow QEMU coding style, so an upstream PR to espressif/qemu is realistic.
- Python sensor models:
  - ADXL345: DEVID 0xE5, power and data-format registers, DATA_READY in INT_SOURCE,
    0x32..0x37 data in the configured range and resolution.
  - ADS1115: config register with the mux selecting the bank, the OS/conversion-ready
    bit, conversion values from the channel's waveform at the configured PGA.
  - A generic register-map model for anything else.
- Waveform sources: a CSV of recorded samples, and synthetic specs (sine sums, noise,
  steps, imbalance-style 1x rotation lines). Both are resampled onto the virtual timeline.
- Tools: sensors declared at emu_start, plus sensor_set and sensor_stream for mid-run
  changes.
- Demo app: examples/vibration_monitor reads the ADXL345 over I2C, computes RMS per
  block, and prints it. Injecting a synthetic waveform must print the expected RMS within
  tolerance. Two deterministic runs must produce byte-identical UART logs.

M4: PROOF IT WORKS
- bench/ holds 10 small ESP-IDF apps. Each has one planted bug and a hidden acceptance
  scenario. Use a mix of bug types, and make at least 3 of them need sensor injection to
  detect (for example a wrong register, a wrong byte order, or a unit-scaling bug).
  Include a stack overflow, a watchdog starvation, a ring-buffer off-by-one and a FreeRTOS
  race.
- Prove that each hidden test discriminates: it fails on the planted bug and passes on a
  reference fix kept in bench/<app>/reference.patch.
- A harness runs Claude Code headless (`claude -p`) on each task in two configurations:
  with this MCP server registered, and without it (build tools only). It records success,
  wall time and token use.
  - Run only a smoke test yourself: 2 tasks x 2 configurations.
  - Write the full-run command and a cost estimate into bench/README.md. The owner decides
    whether to spend the tokens.
  - Report results with N stated. Make no significance claims: N is small, and the README
    must say so.
- CI: a GitHub Actions workflow that builds both images and runs the unit and integration
  tests (including one QEMU run of the demo app), with layer caching. Commit it, but
  nothing is pushed.
- README:
  - what the project is and why it exists
  - a 5-minute quickstart for Claude Code and Claude Desktop on Windows, macOS and Linux
  - a tool reference
  - the scenario schema
  - how sensor injection works, with a diagram
  - limitations: no Wi-Fi, BLE, ADC or I2S; not cycle-accurate; sensors on esp32 only
  - comparison with the prior art above
  - licence split
- demo/: a scripted end-to-end session transcript (build, run, a crash, decode, fix,
  sensor test passing) that the owner can record as a video.
</task_specification>

<environment_and_tools>
- Working directory: C:\Users\Romeo Mattar\Projects\esp32-sim-mcp. It is empty except for
  this prompt file, which you should move to docs/provenance/ and commit. esp32-sim-mcp is
  a working name; don't rename the folder, and leave naming to the owner at M1.
- You have Claude Code's file, shell (PowerShell and Git Bash), search and web tools. Use
  Docker for anything toolchain-related. If Docker Desktop isn't running, ask the owner to
  start it and wait. Starting it needs their hands, and it may ask to enable WSL2.
- Pull images only from official sources (espressif/idf, python, debian or ubuntu).
  Nothing on the host needs admin rights; if something seems to, stop and ask.
- Local git only: `git init`, one or more commits per milestone with clear messages. Never
  push, create a GitHub repo, publish to PyPI or any MCP registry, or open PRs upstream.
  Those are the owner's calls.
- Don't touch anything outside the project folder.
- Tests come before implementation for the Python code. Keep unit tests fast and
  QEMU-free; put QEMU-backed integration tests behind a pytest marker.
</environment_and_tools>

<workflow>
1. M1, then stop with docs/M1_REPORT.md and a short chat summary. Wait for the owner's go.
   They may adjust M3 based on your go/no-go.
2. After the go, run M2, M3 and M4 in order without stopping, committing at each
   milestone. If a finding makes a later milestone impossible as specified, take the
   fallback you proposed in M1, record it in DECISIONS.md, and keep going.
</workflow>

<scope_discipline>
Deliver what was asked, at the scope intended. Make routine judgment calls yourself, and
record the non-obvious ones in DECISIONS.md (one short entry each: the decision, the
alternative, the reason). Check in with the owner only at the M1 checkpoint, or when two
readings of the spec would lead to materially different work. If something outside the
task looks broken (in ESP-IDF, QEMU or the SDK), note it in docs/UPSTREAM_ISSUES.md and
work around it rather than patching it, unless the patch is the M3 device itself. Finish
the whole task, and stop short of actions clearly beyond it.
</scope_discipline>

<subagent_policy>
Delegate to a subagent only for large, genuinely independent tracks of work. For example:
surveying the esp-develop I2C and QEMU-clock code while you set up the container, or
writing the 10 benchmark apps in parallel once the scenario format is fixed. Don't
delegate anything you could finish yourself in a handful of tool calls, and don't use
subagents to check your own work. Keep it to at most two running at once.
</subagent_policy>

<communication>
Before your first tool call, say in one sentence what you're about to do. While working,
speak up only at milestone boundaries, or when you find something that changes the plan.
Example: "esp32_i2c.c doesn't implement the END command, so the v6.1 driver hangs; adding
it to the M3 patch series." When you finish a milestone, lead with the outcome, then the
two or three facts that matter, then what's next.
</communication>

<written_output>
Size documents to the substance. Cover what the task needs, then stop: no filler sections,
no summaries restating what was just said, no boilerplate scaffolding. The README is the
one document that should be complete. It is the project's front page, and the owner will
point employers at it.
</written_output>

<definition_of_done>
At the M1 checkpoint:
- docs/M1_REPORT.md answers all six questions with evidence.
- Everything is committed.

At the end of M4:
- Both Docker images build from clean with the pinned versions.
- `pytest` is green, and the integration marker is green inside the container.
- A scripted MCP client session (scripts/smoke_session.py) completes these steps: list
  tools, build hello_world, start, uart_expect the greeting, break at app_main, backtrace,
  stop.
- examples/vibration_monitor prints the expected RMS from an injected waveform, and two
  deterministic runs give byte-identical logs.
- All 10 bench apps fail their hidden test as shipped and pass with reference.patch.
- The benchmark smoke run's results are in bench/results/.
- These files exist and match the code: README, DECISIONS.md, LICENSE (MIT),
  qemu-patches/LICENSE (GPL-2.0-or-later), and .github/workflows/ci.yml.
- Commits exist for every milestone, and nothing has been pushed anywhere.
</definition_of_done>

<tone_preference>
Keep outputs reasonably concise.
</tone_preference>
```
