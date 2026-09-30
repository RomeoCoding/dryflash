"""Benchmark harness: Claude Code headless (`claude -p`) fixing each bench app, with and without the MCP server.

For every (task, configuration) it copies bench/<task>/app plus TASK.md into a fresh workspace (the
hidden test and reference.patch stay out of reach), runs the agent, then runs the hidden acceptance
scenario with the sensors image's `test-run` CLI. Records success, wall time, turns, tokens and cost.

Configurations
  mcp       the dryflash server (sensors image) is the only MCP server; file tools, no shell
  baseline  file tools plus ./build.sh (compiles in Docker); no emulator, no hardware

Examples (run on the host, with Docker and the claude CLI installed and logged in):
  python bench/harness.py --tasks null_config adc_byte_order --configs mcp baseline   # smoke test
  python bench/harness.py                                                            # full run
See bench/README.md for the cost estimate. Results: bench/results/<run_id>.json and .md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_IMAGE = "dryflash"
SENSORS_IMAGE = "dryflash-sensors"

PROMPT_COMMON = (
    "You are working in an ESP-IDF v6.1 firmware project for the ESP32 (this folder). Read TASK.md "
    "and fix the bug it describes by editing the firmware source. Keep the change minimal and do not "
    "change what the task says must stay. When you are done, reply with a short summary of the root "
    "cause and your fix."
)
PROMPT_MCP = (
    " You have the dryflash MCP server: it builds the project, runs it in Espressif's QEMU, reads "
    "the serial console, debugs with GDB, decodes crashes and can inject I2C sensor data (ADXL345, "
    "ADS1115). Inside the server this project is mounted at /work. The hardware exactly as TASK.md "
    "describes is emulated; declare sensors in emu_start if the firmware reads one."
)
PROMPT_BASELINE = (
    " There is no hardware and no emulator. You can compile the firmware with ./build.sh to check "
    "that it builds."
)


def docker_path(p: Path) -> str:
    return str(p.resolve())


def make_workspace(task: str, config: str, root: Path) -> Path:
    ws = root / f"{task}-{config}"
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(HERE / task / "app", ws)
    shutil.copy(HERE / task / "TASK.md", ws / "TASK.md")
    if config == "baseline":
        vol = f"dryflash-bench-{task}"
        # A build cache left by an earlier run could be newer than the fresh copy's sources.
        subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True)
        (ws / "build.sh").write_text(
            "#!/usr/bin/env bash\n# Compile this project with ESP-IDF v6.1 in Docker (no emulator available).\n"
            f'exec docker run --rm -v "{docker_path(ws)}:/work" -v {vol}:/build {BASE_IMAGE} '
            "idf.py -C /work -B /build/b build 2>&1 | tail -40\n", newline="\n")
    return ws


def agent_command(config: str, ws: Path, model: str, max_turns: int) -> list[str]:
    cmd = ["claude", "-p", PROMPT_COMMON + (PROMPT_MCP if config == "mcp" else PROMPT_BASELINE),
           "--output-format", "json", "--model", model, "--max-turns", str(max_turns),
           "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands"]
    if config == "mcp":
        mcp = {"mcpServers": {"dryflash": {"command": "docker", "args": [
            "run", "-i", "--rm", "-v", f"{docker_path(ws)}:/work", SENSORS_IMAGE]}}}
        cfg = ws.parent / f"{ws.name}.mcp.json"
        cfg.write_text(json.dumps(mcp, indent=2))
        cmd += ["--mcp-config", str(cfg), "--allowedTools", "Read,Edit,Write,Glob,Grep,mcp__dryflash"]
    else:
        cmd += ["--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(./build.sh),Bash(bash build.sh)"]
    return cmd


def hidden_test(task: str, ws: Path) -> dict:
    hidden = HERE / task / "hidden"
    p = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{docker_path(ws)}:/work", "-v", f"{docker_path(hidden)}:/hidden:ro",
         SENSORS_IMAGE, "test-run", "/work", "/hidden/scenario.yaml"],
        capture_output=True, text=True, timeout=1800)
    try:
        r = json.loads(p.stdout[p.stdout.index("{"):])
    except ValueError:
        r = {"passed": False, "reason": f"test-run output unreadable: {p.stdout[-500:]} {p.stderr[-500:]}"}
    return {"passed": bool(r.get("passed")), "reason": r.get("reason")}


def run_one(task: str, config: str, args, root: Path) -> dict:
    ws = make_workspace(task, config, root)
    t0 = time.monotonic()
    try:
        env = dict(os.environ)
        if args.claude_config_dir:
            env["CLAUDE_CONFIG_DIR"] = args.claude_config_dir
        p = subprocess.run(agent_command(config, ws, args.model, args.max_turns), cwd=ws, capture_output=True,
                           text=True, timeout=args.timeout, encoding="utf-8", errors="replace", env=env)
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, err, code = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout", -1
    wall = time.monotonic() - t0
    try:
        agent = json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        agent = {}
    usage = agent.get("usage") or {}
    test = hidden_test(task, ws)
    return {
        "task": task, "config": config, "model": args.model,
        "success": test["passed"], "hidden_test_reason": test["reason"],
        "wall_s": round(wall, 1), "agent_exit": code, "agent_error": agent.get("is_error"),
        "num_turns": agent.get("num_turns"), "cost_usd": agent.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
        "summary": (agent.get("result") or err)[:600],
    }


def write_report(run_id: str, results: list[dict], args) -> Path:
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "model": args.model, "results": results},
                                                   indent=2))
    lines = [f"# Benchmark run {run_id}", "", f"Model: `{args.model}`. N = {len(results)} runs "
             f"({len({r['task'] for r in results})} tasks x {len({r['config'] for r in results})} configurations, "
             "1 attempt each). N is far too small for any significance claim.", "",
             "| task | config | hidden test | wall (s) | turns | output tokens | cost (USD) |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['task']} | {r['config']} | {'pass' if r['success'] else 'fail'} | {r['wall_s']} | "
                     f"{r['num_turns']} | {r['output_tokens']} | {r['cost_usd']} |")
    for cfg in sorted({r["config"] for r in results}):
        rs = [r for r in results if r["config"] == cfg]
        cost = sum(r["cost_usd"] or 0 for r in rs)
        lines.append("")
        lines.append(f"- **{cfg}**: {sum(r['success'] for r in rs)}/{len(rs)} passed the hidden test, "
                     f"total cost ${cost:.2f}, mean wall time {sum(r['wall_s'] for r in rs) / len(rs):.0f} s")
    md = out / f"{run_id}.md"
    md.write_text("\n".join(lines) + "\n")
    return md


def main() -> int:
    tasks_all = sorted(p.name for p in HERE.iterdir() if (p / "hidden" / "scenario.yaml").exists())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", nargs="*", default=tasks_all)
    ap.add_argument("--configs", nargs="*", default=["mcp", "baseline"], choices=["mcp", "baseline"])
    ap.add_argument("--model", default=os.environ.get("BENCH_MODEL", "claude-sonnet-5"))
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per agent run")
    ap.add_argument("--workdir", default=str(HERE / ".work"))
    ap.add_argument("--claude-config-dir", default=None,
                    help="CLAUDE_CONFIG_DIR for the agent runs; point it at a directory holding only your "
                         "credentials to keep your user-level CLAUDE.md out of the benchmark")
    ap.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--resume", action="store_true", help="keep results already in <run_id>.json, run the rest")
    args = ap.parse_args()
    if shutil.which("claude") is None:
        print("claude CLI not found on PATH", file=sys.stderr)
        return 2
    root = Path(args.workdir)
    root.mkdir(parents=True, exist_ok=True)
    results = []
    prev = HERE / "results" / f"{args.run_id}.json"
    if args.resume and prev.exists():
        results = json.loads(prev.read_text())["results"]
    done = {(r["task"], r["config"]) for r in results}
    for task in args.tasks:
        for cfg in args.configs:
            if (task, cfg) in done:
                continue
            print(f"== {task} / {cfg}", flush=True)
            r = run_one(task, cfg, args, root)
            print(f"   hidden test {'PASS' if r['success'] else 'FAIL'}, {r['wall_s']} s, turns={r['num_turns']}, "
                  f"cost=${r['cost_usd']}", flush=True)
            results.append(r)
            write_report(args.run_id, results, args)
    print(f"report: {write_report(args.run_id, results, args)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
