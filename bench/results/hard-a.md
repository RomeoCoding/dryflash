# Benchmark run hard-a

Model: `claude-sonnet-5`. N = 10 runs (5 tasks x 2 configurations, 1 attempt each). N is far too small for any significance claim.

Cost is Claude Code's API-price estimate (`total_cost_usd`); on a subscription login the runs use plan usage instead. Incomplete runs (cut off by a usage/rate limit) are excluded from the pass counts.

| task | config | hidden test | wall (s) | turns | output tokens | API-equivalent cost (USD) |
|---|---|---|---|---|---|---|
| humidity_logger | mcp | pass | 157.7 | 19 | 5759 | 0.3824742 |
| humidity_logger | baseline | pass | 164.0 | 27 | 13976 | 0.4337959999999999 |
| scale_display | mcp | pass | 140.1 | 16 | 8199 | 0.271172 |
| scale_display | baseline | pass | 265.4 | 25 | 19209 | 0.5363006 |
| vibration_telemetry | mcp | pass | 239.5 | 27 | 13028 | 0.4694016 |
| vibration_telemetry | baseline | pass | 304.5 | 31 | 17106 | 0.5222544 |
| pressure_alarm | mcp | pass | 368.5 | 43 | 26808 | 0.8767124 |
| pressure_alarm | baseline | pass | 296.9 | 25 | 25946 | 0.6201606000000001 |
| tank_gauge | mcp | pass | 233.9 | 28 | 11555 | 0.4646683999999999 |
| tank_gauge | baseline | pass | 206.4 | 35 | 12357 | 0.517386 |

- **baseline**: 5/5 passed the hidden test, API-equivalent cost $2.63, mean wall time 247 s

- **mcp**: 5/5 passed the hidden test, API-equivalent cost $2.46, mean wall time 228 s
