"""test_run: build a project, run a scenario in a fresh session, report. Shared by the MCP tool and the CLI."""

from __future__ import annotations

import json
from pathlib import Path

from .build import build_dir_for, build_project
from .panic import decode_panic_text, make_addr2line_symbolizer
from .runner import run_scenario
from .scenario import load_scenario
from .session import SessionConfig, SessionManager


def resolve_scenario(project_dir: Path, scenario_file: str) -> Path:
    p = Path(scenario_file)
    if p.is_absolute():
        return p
    return project_dir / p if (project_dir / p).exists() else p.resolve()


async def run_test(mgr: SessionManager, project_dir: Path, scenario_path: Path, build: bool = True) -> dict:
    scenario = load_scenario(scenario_path)
    if build:
        res = await build_project(project_dir, scenario.target)
        if not res.ok:
            return {"scenario": scenario.name, "passed": False, "reason": "build failed", "build": res.to_dict()}
    bdir = build_dir_for(project_dir, scenario.target)
    desc = bdir / "project_description.json"
    if not desc.exists():
        return {"scenario": scenario.name, "passed": False, "reason": "project was never built; run with build"}
    elf = bdir / json.loads(desc.read_text())["app_elf"]
    emu = scenario.emulator
    s = await mgr.start(SessionConfig(
        target=scenario.target, flash_image=bdir / "flash_qemu.bin", elf=elf, project_dir=project_dir,
        deterministic=emu.deterministic, icount_shift=emu.icount_shift, reboot=emu.reboot,
        watchdogs=emu.watchdogs, extra_args=list(emu.qemu_args), sensors=list(scenario.sensors),
        gpio=list(scenario.gpio), uart_tcp_port=emu.uart_tcp_port))
    try:
        result = await run_scenario(s, scenario)
        if not result["passed"]:
            crash = decode_panic_text(s.uart.tail(65536).decode(errors="replace"),
                                      make_addr2line_symbolizer(s.target.addr2line, elf, project_dir))
            if crash.kind != "none":
                result["panic"] = crash.to_dict()
    finally:
        await mgr.stop(s.id)
    return result
