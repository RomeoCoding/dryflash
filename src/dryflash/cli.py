"""Command line: `serve` (the MCP server, default) and `test-run` (a scenario without an MCP client).

  dryflash test-run <project_dir> <scenario.yaml> [--no-build] [--transcript]

Prints the test_run result as JSON and exits 0 on pass, 1 on fail, 2 on usage errors. CI and the
benchmark's hidden acceptance tests use this.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dryflash")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the MCP server on stdio (default)")
    tr = sub.add_parser("test-run", help="build a project and run a scenario")
    tr.add_argument("project_dir")
    tr.add_argument("scenario")
    tr.add_argument("--no-build", action="store_true")
    tr.add_argument("--transcript", action="store_true", help="include the full UART transcript in the JSON")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        from .server import main as serve
        serve()
        return 0

    from .scenario import ScenarioError
    from .session import SessionManager
    from .testrun import resolve_scenario, run_test

    async def go() -> dict:
        mgr = SessionManager()
        try:
            proj = Path(args.project_dir).resolve()
            return await run_test(mgr, proj, resolve_scenario(proj, args.scenario), build=not args.no_build)
        finally:
            await mgr.stop_all()

    try:
        result = asyncio.run(go())
    except (ScenarioError, FileNotFoundError, ValueError) as e:
        print(json.dumps({"passed": False, "reason": f"{type(e).__name__}: {e}"}))
        return 2
    if not args.transcript:
        result["transcript"] = result.get("transcript", "")[-2000:]
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
