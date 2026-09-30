# Benchmark: do agents fix embedded bugs better when they can run the firmware?

Ten small ESP-IDF apps, each with **one planted bug**, a bug report written from the user's side
(`TASK.md`: symptoms and required behaviour, no hint at the cause) and a **hidden acceptance
scenario** (`hidden/scenario.yaml`) the agent never sees.

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

## Hidden tests discriminate

`verify.py` runs every hidden scenario twice: on the app as shipped (it must fail) and with
`<app>/reference.patch` applied (it must pass).

```sh
docker run --rm -v "$(pwd)":/opt/esp32-sim-mcp -w /opt/esp32-sim-mcp esp32-sim-mcp-sensors \
    /opt/venv/bin/python bench/verify.py            # writes bench/results/verify.json
```

Result: see `results/verify.json` and `results/verify.log` (10/10 discriminate, with each shipped
app's failure reason).

## Harness

`harness.py` runs Claude Code headless on each task in a fresh workspace that contains only the
app and `TASK.md`, in two configurations:

- **mcp**: this server (the `esp32-sim-mcp-sensors` image) is the only MCP server
  (`--strict-mcp-config`); tools: Read, Edit, Write, Glob, Grep and the server's tools. No shell.
- **baseline**: Read, Edit, Write, Glob, Grep and `./build.sh`, which compiles the project in
  Docker. No emulator, no hardware: the "compile and reason" workflow.

After each run the hidden scenario is executed with the sensors image's `test-run` CLI. The
harness records success, wall time, turns, input/output/cache tokens and the cost reported by
Claude Code, in `results/<run_id>.json` and `results/<run_id>.md`.

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

SMOKE_RESULTS

## Cost estimate for the full run

COST_ESTIMATE

## How to read the numbers

N is tiny: 10 tasks, one attempt each, one model. Differences between the configurations at this
N are anecdotes, not evidence; nothing here is claimed to be statistically significant. To make a
claim, repeat the run several times (tasks × configurations × attempts) and report per-task
success rates with confidence intervals. The tasks are also written by the author of the tool
being measured, which biases them towards what the tool can observe; the four sensor tasks in
particular are hard to solve by reading code alone *by construction*, and the six others are the
fairer comparison.
