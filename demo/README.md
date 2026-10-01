# Demo: a board-free debugging session

`run_demo.py` drives the real MCP server over stdio through a scripted session, suitable for a
screen recording. Every step is a real tool call. The terminal shows a paced, condensed view
(one line per test step and backtrace frame); `transcript.md` gets the full markdown record of
the same calls. `transcript.md` in this folder is the output of an actual run.

1. **A crash, decoded.** The `null_config` benchmark app (a UART config shell) is built and
   started. The operator types `set name` without a value; the board crashes, and `decode_panic`
   returns the NULL dereference with file and line. The fix (the benchmark's reference patch,
   standing in for the agent's edit) is applied, and `test_run` passes.
2. **A sensor bug no crash dump shows.** The `adc_byte_order` voltmeter is tested with 1.234 V
   injected into its ADS1115 ADC. It reads −3.579 V, because it assembles the big-endian result
   little-endian. After the fix, the same deterministic sensor test passes, including a change to
   2.5 V at t = 3 s of virtual time.

## Quick run

```sh
docker run --rm -it -v "$(pwd)":/opt/dryflash dryflash-sensors \
    /opt/venv/bin/python /opt/dryflash/demo/run_demo.py
```

A full run takes 3–5 minutes, most of it the first (cold) ESP-IDF build. `DEMO_FAST=1` (or
`--pace 0`) removes the pauses.

## Recording

```sh
docker run --rm -it -v "$(pwd)":/opt/dryflash dryflash-sensors \
    /opt/venv/bin/python /opt/dryflash/demo/run_demo.py --warm-up --wait --clear --narration
```

- `--warm-up` builds both apps before anything is shown, so the recorded `project_build` takes
  seconds instead of a minute (the result shows the short `duration_s`, which is honest: it is a
  cached rebuild). `--wait` then waits for Enter: start the screen recorder, press Enter.
- `--clear` starts each section on a clean screen. Section banners, a spinner with elapsed time
  for long calls and tool calls typed at `--typing` characters per second (60; 0 = instant)
  keep the video readable.
- `--pace X` scales every pause (1 = default; 1.5 for a slower video).
- `--narration [FILE]` shows the narration for each step as a caption (default
  [`narration.md`](narration.md)) and holds it for its reading time at 150 words per minute, so
  a voiceover read at that pace stays in sync. After the run, the real cue times are written as
  subtitles to `demo/cues.srt` (`--cues PATH`), split into two-line blocks of at most 42
  characters; it is not committed, because every run has its own timing. Record the
  voiceover against the captions, or import the `.srt` into the video editor.

Measured on the development machine, after a warm-up of about 2 minutes, the recorded part
runs **71 s** without narration and **194 s** with it, at `--pace 1`.

`narration.md` has one `## <step id>` section per step (the ids are `STEP_IDS` in `run_demo.py`;
a unit test keeps them in sync). Edit the wording freely, but keep it true to what the run
shows: the numbers it quotes come from `transcript.md`.

None of these options change which tools are called, with which arguments, or what is checked:
the presentation is separate from the session, and `transcript.md` has the same content with or
without them (only timings differ between runs).
