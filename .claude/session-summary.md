# Session Summary
Last updated: 2026-09-30 (+03:00)

## What was just done
M3 committed (7b61fe2). M4 mostly done (uncommitted): 10 bench apps + hidden scenarios + reference
patches (verify: 10/10 discriminate, bench/results/verify.json), bench/harness.py, bench/README.md
(SMOKE_RESULTS and COST_ESTIMATE placeholders still to fill), .github/workflows/ci.yml, full README.md,
demo/run_demo.py (NOT yet run; must run it to produce demo/transcript.md), CLI test-run
(src/esp32_sim_mcp/cli.py + testrun.py), 120 unit tests green. Runtime images esp32-sim-mcp and
esp32-sim-mcp-sensors built; the host stdio smoke via --docker passed.

## In progress
Harness smoke run (background): python bench/harness.py --tasks null_config adc_byte_order
--configs mcp baseline --run-id smoke-20260930 -> bench/results/smoke-20260930.{json,md,log}.

## Next steps
1. Fill bench/README.md SMOKE_RESULTS and COST_ESTIMATE from the smoke json (N stated, no
   significance claims); link from the README Benchmark section.
2. Run the demo in the test-sensors image (DEMO_FAST=1) -> demo/transcript.md; add demo/README.md.
3. Final full test pass (unit, integration on both images, sensors), then commit M4.
4. Final summary to the owner. Note: the host smoke once timed out at uart_expect after
   emu_continue under heavy CPU load (it passed when rerun idle).

## Notes
- The scratchpad has regen.sh (rebuilds qemu-patches 0002-0006 from qemu-src/ staged files + msgs/).
- Agent runs inherit the user CLAUDE.md (documented); the harness has --claude-config-dir to isolate.
