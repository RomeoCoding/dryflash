# Session Summary
Last updated: 2026-09-30 (+03:00)

## What was just done
All four milestones' content is done. Benchmark smoke run finished (4/4 hidden tests passed, N=4,
~$0.86), bench/README.md filled in; demo/run_demo.py ran and wrote demo/transcript.md. Final test
pass running (scratch/final_tests.log), then the M4 commit.

## Current state of the project
- M1 3049bd2, M2 b0c2d02, M3 7b61fe2, M4 WIP 94ac7c6 (+ final M4 commit pending). Nothing pushed.
- Images: esp32-sim-mcp, esp32-sim-mcp-sensors (runtime), esp32-sim-mcp:test, :test-sensors.
- qemu-patches 0001-0006; staged whole files in qemu-src/ (gitignored), regen script in scratchpad.

## Active decisions
See DECISIONS.md (M1-M4). Deterministic mode: -icount shift=3,sleep=off -seed 1; emu_reset = QEMU
restart; uart_expect matches complete lines; sensors via SensorHub slicing on sim-clock.

## Next steps
Owner decides: project name (M1 report recommends boardless-mcp), whether to run the full
benchmark (bench/README.md cost estimate), pushing/publishing, upstream PRs for patches 0005/0006.

## Open questions
Agent benchmark runs inherit the user-level CLAUDE.md unless --claude-config-dir is used.
