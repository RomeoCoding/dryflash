# Session Summary
Last updated: 2026-09-29 11:30 (+03:00)

## What was just done
Started M1 of docs/provenance/esp32-sim-mcp-opus-5-prompt.md (the spec). git init done (repo-local identity
Romeo Mattar <romeomat.work@gmail.com>), prompt moved to docs/provenance/. Docker Desktop could not start:
WSL is not installed. Owner chose to install WSL2 (`wsl --install --no-distribution`, reboot) themselves.

## Current state of the project
M1 in progress, blocked on Docker. Findings so far (pinned QEMU tag esp-develop-9.2.2-20260417):
- hw/xtensa/esp32.c esp32_machine_init_i2c hardwires tmp105 @0x48 on i2c0 and says CLI -device can't
  reach I2C bus: controllers are realized on "esp32-periph-bus" (child of SoC, SoC has no parent bus).
- esp32_i2c.c executes the whole cmd list synchronously on TRANS_START; supports RSTART/WRITE/READ/STOP/END.
- espressif/idf:v6.1 digest sha256:81893c71bb5e570088901f21def8684c25cd2a9020281bd01b843a7655edb18c
- Name checks (PyPI 404 + GH 0 repos): boardless-mcp, qesp-mcp, espbench-mcp, xtensim, benchless(-mcp, GH rate-limited)

## Active decisions
- /goal set by owner: work until the spec is complete (treated as advance go past M1 checkpoint? -> still write M1 report + commit first)
- Proposed fix for Q2: realize I2C controllers on sysbus-default + unique bus names (patch 0001).
- ADS1115 must avoid 0x48 (hardwired tmp105) -> use 0x49.

## Next steps
Once Docker is up: pull espressif/idf:v6.1, check for QEMU, build hello_world esp32/esp32c3, test tmp105 read, icount determinism.

## Open questions
None beyond Docker.
