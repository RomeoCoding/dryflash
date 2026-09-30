# Demo: a board-free debugging session

`run_demo.py` drives the real MCP server over stdio through a scripted session, suitable for a
screen recording. It prints each tool call and the relevant part of its result, then writes
`transcript.md`. `transcript.md` in this folder is the output of an actual run.

1. **A crash, decoded.** The `null_config` benchmark app (a UART config shell) is built and
   started. The operator types `set name` without a value; the board crashes, and `decode_panic`
   returns the NULL dereference with file and line. The fix (the benchmark's reference patch,
   standing in for the agent's edit) is applied, and `test_run` passes.
2. **A sensor bug no crash dump shows.** The `adc_byte_order` voltmeter is tested with 1.234 V
   injected into its ADS1115 ADC. It reads −3.579 V, because it assembles the big-endian result
   little-endian. After the fix, the same deterministic sensor test passes, including a change to
   2.5 V at t = 3 s of virtual time.

```sh
docker run --rm -it -v "$(pwd)":/opt/esp32-sim-mcp esp32-sim-mcp-sensors \
    /opt/venv/bin/python /opt/esp32-sim-mcp/demo/run_demo.py
```

The script pauses briefly after each step, for the recording; set `DEMO_FAST=1` to skip the
pauses. A full run takes about 5 minutes, most of it the first (cold) ESP-IDF build.
