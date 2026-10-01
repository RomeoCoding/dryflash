# Benchmark: do agents fix embedded bugs better when they can run the firmware?

Fifteen small ESP-IDF apps, each with **one planted bug**, a bug report written from the user's
side (`TASK.md`: symptoms and required behaviour, no hint at the cause) and a **hidden acceptance
scenario** (`hidden/scenario.yaml`) the agent never sees.

### First set (10 apps, single file each)

| app | bug class | needs sensor injection to observe |
|---|---|---|
| `stack_overflow` | task stack too small for a local array | |
| `wdt_starvation` | busy-wait starves IDLE → task watchdog | |
| `ringbuf_offbyone` | full-check off by one corrupts the queue | |
| `freertos_race` | unprotected read-modify-write between two tasks | |
| `null_config` | NULL dereference on a missing command argument | |
| `timer_units` | esp_timer period given in ms where µs are expected | |
| `accel_wrong_register` | ADXL345 data read from DATAX1 instead of DATAX0 | yes |
| `adc_byte_order` | ADS1115 result assembled little-endian | yes |
| `accel_scaling` | ADXL345 ±8 g converted with the full-resolution scale | yes |
| `adc_pga_threshold` | ADS1115 volts computed with the wrong PGA full scale | yes |

The first set's directory names describe the bug, and the harness names each workspace after
its task (`<task>-<config>`), so the agent sees the hint in its working directory. The second set
uses product names.

### Second set (5 apps): the symptom does not point at the faulty line

The smoke run below showed that the first set's bugs can be found by reading the code once the
symptom is described. These apps are written so that observing the running firmware should
matter. Each has 3–5 source files, and the symptom shows up in a different part of the code
from the bug.

| app | what the user sees | planted bug | why reading alone is harder |
|---|---|---|---|
| `humidity_logger` (HDC1080, generic model) | `sensor fault: no fresh data` about a minute after power-up | the log record keeps the ms time stamp in 16 bits, so it wraps at 65.536 s | appears only after 65 s of virtual time; the fault text points at the sensor and the driver has its own fault path |
| `scale_display` (NAU7802, generic model) | display stays at the old weight after a sack is put on; bench tests with weights pass | the glitch filter fixes its confirmation candidate on the first out-of-band reading and never re-arms, so a dropped load (overshoot, ringing) latches it | appears only with one waveform shape (a fast step that rings); a gentle step works |
| `vibration_telemetry` (ADXL345) | `LoadStorePIFAddrError` in `calib_apply()` on the most strongly vibrating machine | `off += snprintf()` runs past the 64-byte frame when all six min/max fields and the RMS are two-digit; the checksum is then written over the calibration pointer that follows in .bss | the backtrace is in calibration code, two modules and one task away from the overflow; data-dependent (needs ≥ 10 g on every axis) |
| `pressure_alarm` (ADS1115) | the 5 bar/s rise alarm does not trip at 6.5 bar/s | `pdMS_TO_TICKS(15)` is one 10 ms tick, but the slope assumes dt = 15 ms, so every rate reads 2/3 of the truth | a sample-rate/scheduler interaction: the code reads correctly unless you know the tick rate (100 Hz by default) and the truncation |
| `tank_gauge` (ADS1115, CSV) | the volume drops back by hundreds of litres during refills; a field recording ships with the app | `lut_interp()` keeps `(y1 - y0) * frac` in 16 bits, which wraps in the steep middle segments of the strapping table | data-dependent: only segments that rise by more than 256 L, and only part of each one; the hidden test replays `data/refill_2026-09-12.csv` |

`humidity_logger` and `scale_display` use the `generic` register-map model, so an agent must
describe the chip itself (stride, `read_set`, channel formats) from the firmware and `TASK.md`.

## Hidden tests discriminate

`verify.py` runs every hidden scenario twice: on the app as shipped (it must fail) and with
`<app>/reference.patch` applied (it must pass).

```sh
docker run --rm -v "$(pwd)":/opt/dryflash -w /opt/dryflash dryflash-sensors \
    /opt/venv/bin/python bench/verify.py [app ...]  # merges into bench/results/verify.json
```

Result: see `results/verify.json` and `results/verify.log` (**15/15 discriminate**, with each
shipped app's failure reason; the second set was verified on 2026-10-01).

For two second-set tasks I also checked that the hidden test rejects a plausible wrong fix (run
by hand, not part of `verify.py`):

- `scale_display` with the glitch filter deleted: fails (`weight=23.12 kg` appears while the
  knock and ring-down must stay off the display).
- `pressure_alarm` with the threshold lowered to 3.3 bar/s, which hides the 2/3 error: fails
  (the alarm reports 3.44 bar/s, outside the required 5–7).

The `tank_gauge` limits come from the tank geometry, not from the reference firmware's output.
The fixed firmware is within 32 L of the geometry over the whole refill, the tolerance is
±60 L, and the shipped error at the checked times is 512–1024 L.

## Harness

`harness.py` runs Claude Code headless on each task in a fresh workspace that contains only the
app and `TASK.md`, in two configurations:

- **mcp**: this server (the `dryflash-sensors` image) is the only MCP server
  (`--strict-mcp-config`); tools: Read, Edit, Write, Glob, Grep and the server's tools. No shell.
- **baseline**: Read, Edit, Write, Glob, Grep and `./build.sh`, which compiles the project in
  Docker. No emulator, no hardware: the "compile and reason" workflow.

After each run the hidden scenario is executed with the sensors image's `test-run` CLI. The
harness records success, wall time, turns, input/output/cache tokens and the cost reported by
Claude Code, in `results/<run_id>.json` and `results/<run_id>.md`.

**Billing.** The agent runs use the `claude` CLI's login. The harness removes
`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the agent's environment, so with a Pro or Max
login the runs draw on plan usage and nothing is billed per token. The "cost" figures are
Claude Code's API-price estimate (`total_cost_usd`). They are kept as a size measure that can be
compared across configurations, not as money spent. A run cut off by a usage or rate limit (or
API overload) is recorded as **incomplete**, not failed, is left out of the pass counts, and stops
the harness. Rerun with the same `--run-id` and `--resume` after the limit resets.

Prerequisites: Docker with both images built (see the top-level README), the `claude` CLI on PATH
and logged in, Python 3.10+.

```sh
# smoke test (what was run here): 2 tasks x 2 configurations
python bench/harness.py --tasks null_config adc_byte_order --configs mcp baseline
# full run: 10 tasks x 2 configurations, one attempt each
python bench/harness.py
# more attempts for a less noisy estimate: repeat with different --run-id values
python bench/harness.py --run-id full-a && python bench/harness.py --run-id full-b
```

Options: `--model` (default `claude-sonnet-5`, or `$BENCH_MODEL`), `--max-turns` (40),
`--timeout` (1800 s per agent run).

## Smoke run results

Run `smoke-20260930` (`results/smoke-20260930.json`, `.md`, `.log`): model `claude-sonnet-5`,
2 tasks x 2 configurations, **one attempt each, N = 4 runs in total**.

| task | config | hidden test | wall (s) | turns | output tokens | cost (USD) |
|---|---|---|---|---|---|---|
| null_config | mcp | pass | 127 | 16 | 2,296 | 0.19 |
| null_config | baseline | pass | 133 | 19 | 4,573 | 0.23 |
| adc_byte_order | mcp | pass | 124 | 14 | 2,543 | 0.19 |
| adc_byte_order | baseline | pass | 151 | 20 | 4,964 | 0.24 |

All four runs fixed their bug, and all four root-cause summaries are correct. Both bugs turned
out to be findable by reading the code: the missing NULL check and the byte order in
`read_ain0()` are visible once the symptom is described. This smoke run therefore says nothing
about whether the server helps; it shows that the harness works end to end and what a run costs.
The MCP runs used fewer turns and output tokens here (16/14 vs 19/20 turns), which at N = 2 per
configuration is an anecdote, not a measurement.

The runs inherited the operator's user-level CLAUDE.md (see `--claude-config-dir`). Both
configurations saw the same context, but it is not a clean-room setup. The first run was
interrupted by the host running low on memory and resumed with `--resume`; the completed run was
not repeated.

## Cost estimates

All dollar figures below are API-equivalent (see **Billing**). On a subscription login, the real
cost is plan usage. A full set of runs can reach a Pro plan's 5-hour limit, so spread repeated
attempts over several windows.

From the smoke run: $0.19–0.24 per run (mean $0.21) and about 2–2.5 minutes of wall time,
plus a cold ESP-IDF build on the first run of each container.

- **First set, one attempt per task and configuration (20 runs): about $4–5 and 50–60 minutes** at
  smoke-run rates. The remaining tasks include harder ones (the race, the watchdog, the scaling
  bugs), which will take more turns; budget **up to ~$10** for safety.
- **Five attempts each (100 runs), the minimum for a per-task success rate worth reporting:
  about $20–50 and 4–6 hours.**
- A more capable model (`--model`) costs proportionally more per token.

### Second set only

```sh
python bench/harness.py --run-id hard-a --max-turns 60 \
    --tasks humidity_logger scale_display vibration_telemetry pressure_alarm tank_gauge
```

5 tasks × 2 configurations = 10 runs. At the smoke-run rate ($0.21 per run) that is about $2,
but these tasks are bigger and need more turns: an MCP agent will typically build, run several
scenarios and inspect, and each emulator run takes 0.5–3 minutes. Budget **$3–6 and 40–80
minutes** for one attempt each. Three attempts (`--run-id hard-b`, `hard-c`), which is the
smallest set worth reporting per task, cost about **$10–18**. `--max-turns 60` (the default is
40) leaves room for the observe-and-iterate loop. Both configurations get the same limit, but a
run that hits the limit counts as a failure, so report how many runs did.

### Second-set run `hard-a` (2026-10-01)

`results/hard-a.json`, `.md`, `.log`: model `claude-sonnet-5`, `--max-turns 60`, 5 tasks ×
2 configurations, **one attempt each, N = 10 runs**, run on the owner's subscription.

| task | config | hidden test | wall (s) | turns | output tokens | API-equivalent cost (USD) |
|---|---|---|---|---|---|---|
| humidity_logger | mcp | pass | 158 | 19 | 5,759 | 0.38 |
| humidity_logger | baseline | pass | 164 | 27 | 13,976 | 0.43 |
| scale_display | mcp | pass | 140 | 16 | 8,199 | 0.27 |
| scale_display | baseline | pass | 265 | 25 | 19,209 | 0.54 |
| vibration_telemetry | mcp | pass | 240 | 27 | 13,028 | 0.47 |
| vibration_telemetry | baseline | pass | 305 | 31 | 17,106 | 0.52 |
| pressure_alarm | mcp | pass | 369 | 43 | 26,808 | 0.88 |
| pressure_alarm | baseline | pass | 297 | 25 | 25,946 | 0.62 |
| tank_gauge | mcp | pass | 234 | 28 | 11,555 | 0.46 |
| tank_gauge | baseline | pass | 206 | 35 | 12,357 | 0.52 |

**All ten runs fixed their bug.** In the nine runs whose summary states the root cause (the
`pressure_alarm` baseline summary was cut off before stating one), it is the planted bug. So the
second set does not separate the configurations either: without the emulator, the agent found
every bug by reading the code. The turn and token differences go both ways (MCP used fewer turns
on four tasks and more on `pressure_alarm`). At N = 1 per cell they are anecdotes.

The run also exposed three problems, which weaken even this null result:

- **The baseline sometimes could not compile.** In `humidity_logger` the generated `build.sh`
  failed under Git Bash: MSYS rewrote the `-v "<path>:/work"` argument. In `pressure_alarm`
  the agent called the script in a form the allow-list did not match, so the call needed an
  approval that a headless run cannot give. Both runs still passed. Fixed afterwards: `build.sh`
  exports `MSYS_NO_PATHCONV=1`, and `Bash(./build.sh:*)` is allowed.
- **One MCP run never used the emulator.** In `scale_display` the agent decided that the
  `generic` model was "a register-less stub" and fixed the bug by reading the code. The
  `emu_start` description listed only an ADXL345 example; the `generic` model's fields were
  documented only in the top-level README, which the agent never sees. Fixed afterwards: the
  description now documents every model and the `generic` fields, with an example (the sensors
  image was rebuilt).
- **The harness does not record which tools an agent called.** Apart from `tank_gauge` (whose
  summary quotes emulator output) and `scale_display` (which says it did not emulate), I can't
  tell how far the MCP runs relied on observation.

A repeat (`--run-id hard-b`) would measure the fixed setup, but given that every baseline run
passed, it is unlikely to show a difference on these tasks. Separating the configurations needs
tasks where the cause really is not visible in the source: for example a bug in a binary-only
library, a peripheral misbehaviour that the code handles correctly on paper, or a timing
interaction across several tasks.

## How to read the numbers

N is tiny: 15 tasks (7 run so far), one attempt each, one model. Differences between the
configurations at this N are anecdotes, not evidence; nothing here is claimed to be statistically significant. To make a
claim, repeat the run several times (tasks × configurations × attempts) and report per-task
success rates with confidence intervals. The tasks are also written by the author of the tool
being measured, which biases them towards what the tool can observe. The four sensor tasks were
meant to need observation, but the smoke run shows that at least `adc_byte_order` falls to careful
code reading once the symptom is described. "Needs sensor injection to observe" means the bug
shows only with sensor data present, not that it cannot be found without it. The second set
tries to separate the two configurations, but it does not guarantee it. Every planted bug there
is still visible in the source to a careful reader (a 16-bit field, a missing re-arm, an
`snprintf` return value, a truncating tick conversion, a 16-bit product), and a strong model may
find it without running anything. I also designed these tasks knowing what the tool can observe
(time stamps, virtual time, injected waveforms, panic registers), which biases them in the
tool's favour. Treat a gap on this set as "observation helped on tasks built for it", not as a
general result.
