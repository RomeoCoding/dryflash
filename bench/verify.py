"""Prove every hidden benchmark test discriminates: it must FAIL on the app as shipped (planted bug)
and PASS once bench/<app>/reference.patch is applied.

Runs inside the sensors image (four apps need sensor injection):
  docker run --rm -v <repo>:/work esp32-sim-mcp-sensors python /work/bench/verify.py [app ...]
Writes bench/results/verify.json and exits non-zero if any app does not discriminate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from esp32_sim_mcp.build import build_dir_for  # noqa: E402
from esp32_sim_mcp.session import SessionManager  # noqa: E402
from esp32_sim_mcp.testrun import run_test  # noqa: E402


def apps() -> list[str]:
    return sorted(p.name for p in HERE.iterdir() if (p / "app" / "CMakeLists.txt").exists())


async def verify(name: str, work_root: Path) -> dict:
    src = HERE / name
    work = work_root / name
    shutil.rmtree(work, ignore_errors=True)
    # Fresh mtimes and no stale build dir: otherwise ninja can reuse the previous (fixed) binary.
    shutil.rmtree(build_dir_for(work, "esp32"), ignore_errors=True)
    shutil.copytree(src / "app", work, copy_function=shutil.copy)
    scenario = src / "hidden" / "scenario.yaml"
    mgr = SessionManager()
    t0 = time.monotonic()
    try:
        shipped = await run_test(mgr, work, scenario)
        patch = subprocess.run(["patch", "-p1", "-d", str(work), "-i", str(src / "reference.patch")],
                               capture_output=True, text=True)
        if patch.returncode != 0:
            return {"app": name, "ok": False, "error": f"reference.patch did not apply: {patch.stdout}{patch.stderr}"}
        fixed = await run_test(mgr, work, scenario)
    finally:
        await mgr.stop_all()
    return {
        "app": name,
        "ok": (not shipped["passed"]) and fixed["passed"],
        "shipped_passed": shipped["passed"],
        "shipped_reason": shipped.get("reason"),
        "shipped_panic": (shipped.get("panic") or {}).get("cause"),
        "fixed_passed": fixed["passed"],
        "fixed_reason": fixed.get("reason"),
        "duration_s": round(time.monotonic() - t0, 1),
    }


async def main(selected: list[str], jobs: int) -> int:
    work_root = Path("/tmp/esp32-sim-mcp/bench-verify")
    sem = asyncio.Semaphore(jobs)

    async def one(name):
        async with sem:
            r = await verify(name, work_root)
            flag = "OK  " if r["ok"] else "FAIL"
            print(f"{flag} {name:<22} shipped={'pass' if r.get('shipped_passed') else 'fail'} "
                  f"fixed={'pass' if r.get('fixed_passed') else 'fail'}  ({r.get('duration_s')}s)  "
                  f"{r.get('shipped_reason') or r.get('error') or ''}"[:220], flush=True)
            return r

    results = await asyncio.gather(*(one(n) for n in selected))
    out = HERE / "results" / "verify.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "results": results}, indent=2))
    bad = [r["app"] for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)}/{len(results)} hidden tests discriminate" + (f"; failing: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("apps", nargs="*")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apps or apps(), a.jobs)))
