"""Scripted end-to-end MCP session for a screen recording: build, run, crash, decode, fix, sensor test.

Every step is a real MCP tool call over stdio to the server; the "fix" steps apply the benchmark's
reference patches, standing in for the edit an agent would make. The terminal shows a paced,
recording-friendly view; demo/transcript.md gets the plain markdown record of the same calls.

  docker run --rm -it -v <repo>:/opt/dryflash dryflash-sensors \
      /opt/venv/bin/python /opt/dryflash/demo/run_demo.py [--warm-up --wait] [--narration] [--clear]

Options: --pace X scales every pause (0 = none; DEMO_FAST=1 or DEMO_PACE also work), --narration
[FILE] shows the narration for each step as a caption and holds it for its reading time (default
file demo/narration.md) and writes the cue times as subtitles (--cues, default demo/cues.srt),
--warm-up builds both apps before the recorded part, --wait waits for Enter before it starts,
--clear clears the screen at each section, --typing CPS types tool calls (0 = instant),
--no-color.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

REPO = Path(__file__).resolve().parents[1]
WORK = Path("/tmp/dryflash-demo")
WIDTH = 78
LOG: list[str] = []

# Every narration cue in main(), in order; demo/narration.md has one section per id.
STEP_IDS = ("intro", "crash", "crash.build", "crash.start", "crash.boot", "crash.type", "crash.panic",
            "crash.decode", "crash.stop", "crash.fix", "crash.test", "sensor", "sensor.fail", "sensor.fix",
            "sensor.pass", "outro")


# ----- narration and cues --------------------------------------------------------------------------
def parse_narration(text: str) -> dict[str, str]:
    """`## <step id>` headings, each followed by the text to say; HTML comments and `#` titles are skipped."""
    out: dict[str, str] = {}
    current, words, in_comment = None, [], False
    for line in text.splitlines() + ["## "]:
        stripped = line.strip()
        if in_comment or stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        if stripped.startswith("## ") or stripped == "##":
            if current is not None:
                out[current] = " ".join(words)
            current, words = stripped[3:].strip() or None, []
            if current in out:
                raise ValueError(f"narration step {current!r} appears twice")
        elif stripped.startswith("# "):
            continue
        elif stripped and current is not None:
            words.append(stripped)
    return out


def reading_time(text: str, words_per_s: float = 2.5, minimum: float = 2.0) -> float:
    """How long a narrator needs for the text, at an unhurried 150 words per minute."""
    return max(minimum, len(text.split()) / words_per_s)


def subtitles(cues: list[tuple[float, float, str]], line_chars: int = 42) -> list[tuple[float, float, str]]:
    """Subtitle-sized cues: each cue ends no later than the next one starts, and its text is split into
    blocks of at most two lines of line_chars, timed back to back in proportion to their words."""
    out = []
    for i, (start, end, text) in enumerate(cues):
        if i + 1 < len(cues):
            end = min(end, cues[i + 1][0])
        lines = textwrap.wrap(text, line_chars)
        blocks = ["\n".join(lines[k:k + 2]) for k in range(0, len(lines), 2)]
        total = sum(len(b.split()) for b in blocks)
        t = start
        for b in blocks:
            dt = (end - start) * len(b.split()) / total
            out.append((round(t, 3), round(t + dt, 3), b))
            t += dt
    return out


def format_srt(cues: list[tuple[float, float, str]]) -> str:
    def ts(s: float) -> str:
        ms = round(s * 1000)
        return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cues, 1))


def resolve_pace(arg: float | None, env) -> float:
    if arg is not None:
        return arg
    if env.get("DEMO_FAST") == "1":
        return 0.0
    return float(env.get("DEMO_PACE", 1.0))


# ----- terminal presentation ----------------------------------------------------------------------
def _step_line(st: dict) -> str:
    mark = "✓" if st.get("passed") else "✗"
    action = st.get("action", "?")
    if action == "sensor_set" and isinstance(st.get("result"), dict):
        r = st["result"]
        return f"{mark} sensor_set {r.get('sensor')} from {r.get('applies_from_ms', 0):g} ms"
    if action in ("expect", "expect_not"):
        return f"{mark} {action} → {st['match']}" if st.get("match") else f"{mark} {action} {st.get('pattern')}"
    return f"{mark} {action}"


def screen_view(body: dict) -> dict:
    """A condensed copy of a tool result for the screen: one line per scenario step and backtrace frame,
    only the headline build sizes. The transcript keeps the full result."""
    view = dict(body)
    if isinstance(view.get("steps"), list):
        view["steps"] = [_step_line(st) for st in view["steps"]]
    if isinstance(view.get("sizes"), dict):
        view["sizes"] = {k: v for k, v in view["sizes"].items() if k in ("app_bin_bytes", "app_partition_free_pct")}
    if isinstance(view.get("backtrace"), list):
        view["backtrace"] = [f"{f['function']} ({f['file']}:{f['line']})" if f.get("function") else f.get("pc")
                             for f in view["backtrace"]]
    return view


class Presenter:
    """Everything the viewer sees. It changes nothing about which tools are called or what they return."""

    def __init__(self, pace: float = 1.0, color: bool = True, narration: dict[str, str] | None = None,
                 typing_cps: float = 0.0, clear: bool = False, out=None):
        self.pace, self.color, self.narration = pace, color, narration or {}
        self.typing_cps, self.clear = typing_cps, clear
        self.out = out or sys.stdout
        self.live = color and hasattr(self.out, "isatty") and self.out.isatty()
        self.cues: list[tuple[float, float, str]] = []
        self.start = time.monotonic()

    def restart_clock(self) -> None:
        self.start = time.monotonic()

    def hold(self, seconds: float) -> None:
        if self.pace > 0:
            time.sleep(seconds * self.pace)

    def _c(self, code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if self.color else s

    def print(self, s: str = "") -> None:
        self.out.write(s + "\n")
        self.out.flush()

    def banner(self, title: str) -> str:
        rule = "━" * WIDTH
        return "\n".join([self._c("36", rule), self._c("1;36", "  " + title), self._c("36", rule)])

    def render_json(self, obj) -> str:
        s = json.dumps(obj, indent=2)
        if not self.color:
            return s
        s = re.sub(r'^(\s*)"([^"]+)":', lambda m: f'{m[1]}{self._c("36", chr(34) + m[2] + chr(34))}:', s,
                   flags=re.M)
        s = re.sub(r"\btrue\b", self._c("32", "true"), s)
        return re.sub(r"\bfalse\b", self._c("31", "false"), s)

    def section(self, title: str, intro: str) -> None:
        if self.clear and self.live:
            self.out.write("\x1b[2J\x1b[H")
        self.print()
        self.print(self.banner(title))
        for line in textwrap.wrap(intro, WIDTH - 2):
            self.print("  " + line)
        self.hold(3)

    def narrate(self, step_id: str) -> None:
        text = self.narration.get(step_id)
        if not text:
            return
        t = time.monotonic() - self.start
        dur = reading_time(text)
        self.cues.append((round(t, 3), round(t + dur, 3), text))
        self.print()
        for line in textwrap.wrap(text, WIDTH - 4):
            self.print(self._c("3;35", "  ▌ " + line))
        self.hold(dur)

    def tool_call(self, name: str, args: dict) -> None:
        text = f"agent → {name} {json.dumps(args)}"
        self.out.write("\n" + self._c("1;33", "▶ "))
        if self.live and self.typing_cps > 0 and self.pace > 0:
            for ch in text:
                self.out.write(self._c("1", ch))
                self.out.flush()
                time.sleep(1 / self.typing_cps)
            self.out.write("\n")
        else:
            self.out.write(self._c("1", text) + "\n")
        self.out.flush()

    async def while_running(self, coro, label: str):
        """Awaits the call; on a terminal, shows a spinner with the elapsed time (a cold build takes a minute)."""
        if not self.live:
            return await coro
        task = asyncio.ensure_future(coro)
        t0, i = time.monotonic(), 0
        while not task.done():
            frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[i % 10]
            self.out.write(f"\r  {self._c('33', frame)} {label} … {time.monotonic() - t0:4.0f} s")
            self.out.flush()
            await asyncio.wait([task], timeout=0.1)
            i += 1
        self.out.write("\r\x1b[2K")
        return task.result()

    def result(self, picked, elapsed: float, error: bool, max_lines: int = 22) -> None:
        lines = self.render_json(picked).splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [self._c("2", f"  … {len(lines) - max_lines} more lines in transcript.md")]
        for line in lines:
            self.print("  " + line)
        self.print(self._c("31" if error else "2", f"  ({elapsed:.1f} s{', tool error' if error else ''})"))

    def diff(self, lines: list[str]) -> None:
        self.print()
        self.print(self._c("1", "✎ agent edits the source:"))
        for line in lines:
            self.print("  " + self._c("32" if line.startswith("+") else "31", line))

    def note(self, text: str) -> None:
        self.print()
        for line in textwrap.wrap(text, WIDTH - 2):
            self.print("  " + self._c("1", line))


# ----- the session -------------------------------------------------------------------------------------
def log(text: str = "") -> None:
    LOG.append(text)


async def call(c: Client, p: Presenter, name: str, show: list[str] | None = None, **args):
    log(f"\n**agent → `{name}`** `{json.dumps(args)}`")
    p.tool_call(name, args)
    t0 = time.monotonic()
    r = await p.while_running(c.call_tool(name, args), name)
    elapsed = time.monotonic() - t0
    body = r.structured_content if r.structured_content is not None else {"text": r.content[0].text}
    picked = {k: body[k] for k in (show or []) if k in body} if show else body
    log(f"```json\n{json.dumps(picked, indent=2)[:1500]}\n```  ({elapsed:.1f}s)")
    p.result(screen_view(picked), elapsed, bool(r.is_error))
    p.hold(1.5)
    if r.is_error:
        raise SystemExit(f"{name} failed: {body}")
    return body


def fix(p: Presenter, app: str) -> None:
    subprocess.run(["patch", "-p1", "-d", str(WORK / app), "-i", str(REPO / "bench" / app / "reference.patch")],
                   check=True, capture_output=True)
    diff = [line for line in (REPO / "bench" / app / "reference.patch").read_text().splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    log("\n*agent edits the source:*\n```diff\n" + "\n".join(diff) + "\n```")
    p.diff(diff)
    p.hold(3)


def section(p: Presenter, title: str, intro: str) -> None:
    log(f"\n## {title}\n\n{intro}")
    p.section(title, intro)


async def main(p: Presenter, warm_up: bool, wait: bool, transcript: Path) -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    for app in ("null_config", "adc_byte_order"):
        shutil.copytree(REPO / "bench" / app / "app", WORK / app)
        shutil.copytree(REPO / "bench" / app / "hidden", WORK / app / "test")
    cfg, adc = str(WORK / "null_config"), str(WORK / "adc_byte_order")
    server = StdioServerParameters(command=sys.executable, args=["-m", "dryflash"], env=dict(os.environ))
    async with Client(server) as c:
        tools = (await c.list_tools()).tools
        if warm_up:
            # Off camera: fills the build cache so the recorded project_build takes seconds, not a minute.
            for d in (cfg, adc):
                await p.while_running(c.call_tool("project_build", {"project_dir": d}), "warming up (off camera)")
            p.print("warm-up done: both apps are built")
        if wait:
            input("start the recording, then press Enter ")
            if p.live:
                p.out.write("\x1b[2J\x1b[H")
        p.restart_clock()
        cue = p.narrate

        log(f"# dryflash demo\n\nConnected over stdio: {len(tools)} tools.")
        p.print(p.banner("dryflash: debugging ESP32 firmware without a board"))
        p.print(f"  MCP client connected over stdio: {len(tools)} tools. Every step below is a real tool call.")
        cue("intro")
        p.hold(2)

        section(p, "1. A crash, decoded",
                "A config shell reboots when an operator types `set name` with no value.")
        cue("crash")
        cue("crash.build")
        await call(c, p, "project_build", show=["ok", "duration_s", "sizes"], project_dir=cfg)
        cue("crash.start")
        s = await call(c, p, "emu_start", show=["session_id", "state", "target"], project_dir=cfg)
        sid = s["session_id"]
        cue("crash.boot")
        await call(c, p, "uart_expect", show=["matched", "match"], session_id=sid, pattern="config shell ready",
                   timeout_s=60)
        cue("crash.type")
        await call(c, p, "uart_write", session_id=sid, text="set name")
        cue("crash.panic")
        await call(c, p, "uart_expect", show=["matched", "reason"], session_id=sid, pattern="name=", timeout_s=10)
        cue("crash.decode")
        await call(c, p, "decode_panic", show=["kind", "exception", "cause", "backtrace"], session_id=sid)
        cue("crash.stop")
        await call(c, p, "emu_stop", show=["state"], session_id=sid)
        cue("crash.fix")
        fix(p, "null_config")
        cue("crash.test")
        await call(c, p, "test_run", show=["passed", "steps", "duration_s"], project_dir=cfg,
                   scenario_file="test/scenario.yaml")

        section(p, "2. A sensor bug no crash dump can show",
                "A voltmeter reads an ADS1115 ADC over I2C. "
                "The test injects 1.234 V on AIN0, then 2.5 V at t = 3 s of virtual time.")
        cue("sensor")
        cue("sensor.fail")
        await call(c, p, "test_run", show=["passed", "failed_step", "reason"], project_dir=adc,
                   scenario_file="test/scenario.yaml")
        cue("sensor.fix")
        fix(p, "adc_byte_order")
        cue("sensor.pass")
        await call(c, p, "test_run", show=["passed", "steps", "duration_s"], project_dir=adc,
                   scenario_file="test/scenario.yaml")
        closing = ("Both bugs were found and fixed without a board: the crash from its decoded backtrace, "
                   "the sensor bug from injected, deterministic ADC data.")
        log(f"\n{closing}")
        p.note(closing)
        cue("outro")
        p.hold(3)
    transcript.write_text("\n".join(LOG) + "\n")
    print(f"\ntranscript written to {transcript}")


def cli(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pace", type=float, default=None, help="pause multiplier (default 1, or DEMO_PACE / DEMO_FAST)")
    ap.add_argument("--narration", nargs="?", const=str(REPO / "demo" / "narration.md"), default=None,
                    help="caption file (default demo/narration.md)")
    ap.add_argument("--cues", default=str(REPO / "demo" / "cues.srt"), help="subtitle file written with --narration")
    ap.add_argument("--typing", type=float, default=60.0, help="characters per second for tool calls (0 = instant)")
    ap.add_argument("--warm-up", action="store_true", help="build both apps before the recorded part")
    ap.add_argument("--wait", action="store_true", help="wait for Enter before the recorded part starts")
    ap.add_argument("--clear", action="store_true", help="clear the screen at each section")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--transcript", default=str(REPO / "demo" / "transcript.md"))
    a = ap.parse_args(argv)
    narration = parse_narration(Path(a.narration).read_text(encoding="utf-8")) if a.narration else None
    if narration is not None and set(narration) != set(STEP_IDS):
        missing, unknown = set(STEP_IDS) - set(narration), set(narration) - set(STEP_IDS)
        sys.exit(f"narration file does not match the demo steps: missing {sorted(missing)}, unknown {sorted(unknown)}")
    color = not a.no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    p = Presenter(pace=resolve_pace(a.pace, os.environ), color=color, narration=narration,
                  typing_cps=a.typing, clear=a.clear)
    asyncio.run(main(p, a.warm_up, a.wait, Path(a.transcript)))
    if narration is not None:
        Path(a.cues).write_text(format_srt(subtitles(p.cues)), encoding="utf-8")
        print(f"narration cues written to {a.cues}")


if __name__ == "__main__":
    cli()
