"""Decode ESP-IDF crash output (Guru Meditation, abort, assert, stack overflow, watchdogs).

The parser is pure; symbolization is injected (normally addr2line on the firmware ELF) so the
logic is testable without a toolchain.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

_GURU = re.compile(r"Guru Meditation Error: Core\s+(\d+) panic'ed \(([^)]*(?:\([^)]*\))?[^)]*)\)")
_ABORT = re.compile(r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d+)")
_ASSERT = re.compile(r"assert failed: (\S+) ([^:\s]+):(\d+) \((.*)\)\s*$", re.M)
_STACK_OVF = re.compile(r"\*\*\*ERROR\*\*\* A stack overflow in task (\S+) has been detected")
_CANARY = re.compile(r"Stack canary watchpoint triggered \((\S+)\s*\)")
_TASK_WDT = re.compile(r"task_wdt: Task watchdog got triggered")
_HEAP = re.compile(r"CORRUPT HEAP: (.*)")
_REG = re.compile(r"\b([A-Z][A-Z0-9/]*)\s*:\s*(0x[0-9a-fA-F]{8})")
_BACKTRACE = re.compile(r"^Backtrace:\s*(.*)$", re.M)
_BT_ENTRY = re.compile(r"(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)")
_WDT_STARVED = re.compile(r"task_wdt:\s+-\s+(.+?)\s*$", re.M)
_WDT_RUNNING = re.compile(r"task_wdt: (CPU \d+): (\S+)\s*$", re.M)

_START_MARKERS = [_GURU, _ABORT, _ASSERT, _STACK_OVF, _TASK_WDT, _HEAP]


@dataclass
class Frame:
    pc: int
    function: str | None
    file: str | None
    line: int | None

    def where(self) -> str:
        loc = f"{self.file}:{self.line}" if self.file and self.line else "?"
        return f"{self.function or '??'} ({loc})"


@dataclass
class PanicReport:
    kind: str = "none"  # guru_meditation|abort|assert|stack_overflow|task_wdt|int_wdt|heap_corruption|none
    exception: str | None = None
    core: int | None = None
    task: str | None = None
    registers: dict[str, int] = field(default_factory=dict)
    backtrace: list[Frame] = field(default_factory=list)
    backtrace_corrupted: bool = False
    assertion: dict | None = None
    wdt_starved: list[str] = field(default_factory=list)
    wdt_running: dict[str, str] = field(default_factory=dict)
    abort_caller: Frame | None = None
    cause: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["registers"] = {k: f"0x{v:08x}" for k, v in self.registers.items()}
        d["backtrace"] = [_frame_dict(f) for f in self.backtrace]
        d["abort_caller"] = _frame_dict(self.abort_caller) if self.abort_caller else None
        return d


def _frame_dict(f: Frame) -> dict:
    return {"pc": f"0x{f.pc:08x}", "function": f.function, "file": f.file, "line": f.line}


Symbolizer = Callable[[list[int]], list[Frame]]


def _no_symbols(addrs: list[int]) -> list[Frame]:
    return [Frame(a, None, None, None) for a in addrs]


def find_panic_start(text: str) -> int | None:
    """Offset of the last crash report in text (a boot loop may contain several)."""
    starts = sorted({m.start() for rx in _START_MARKERS for m in rx.finditer(text)})
    if not starts:
        return None
    # Prefer the last report that is complete: output captured while a crash is still being
    # printed (or a repeating task-watchdog report cut mid-way) has no backtrace yet.
    complete = [s for s in starts if re.search(r"^(Backtrace:|Stack memory:)", text[s:], re.M)]
    last = complete[-1] if complete else starts[-1]
    # A task-watchdog report spans several log lines; start at the first one of the last group.
    line_start = text.rfind("\n", 0, last) + 1
    return line_start


def make_addr2line_symbolizer(addr2line: str, elf: Path, cwd: Path | None = None) -> Symbolizer:
    def symbolize(addrs: list[int]) -> list[Frame]:
        if not addrs:
            return []
        out = subprocess.run(
            [addr2line, "-f", "-C", "-e", str(elf)] + [f"0x{a:x}" for a in addrs],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.splitlines()
        frames = []
        for i, a in enumerate(addrs):
            func = out[2 * i] if 2 * i < len(out) else "??"
            loc = out[2 * i + 1] if 2 * i + 1 < len(out) else "??:0"
            file, _, line = loc.rpartition(":")
            line = line.split(" ")[0]
            frames.append(Frame(
                a,
                None if func == "??" else func,
                None if file in ("??", "") else _shorten(file, cwd),
                int(line) if line.isdigit() and line != "0" else None,
            ))
        return frames
    return symbolize


def _shorten(path: str, cwd: Path | None) -> str:
    if cwd is not None:
        try:
            return str(Path(path).resolve().relative_to(cwd.resolve()))
        except ValueError:
            pass
    return path


def decode_panic_text(text: str, symbolize: Symbolizer | None = None) -> PanicReport:
    symbolize = symbolize or _no_symbols
    text = text.replace("\r\n", "\n")  # ESP-IDF consoles emit CRLF
    start = find_panic_start(text)
    r = PanicReport()
    if start is None:
        r.cause = "no crash report found in the text"
        return r
    t = text[start:]

    if m := _GURU.search(t):
        r.core, r.exception = int(m.group(1)), m.group(2).strip()
        r.kind = "int_wdt" if "Interrupt wdt timeout" in r.exception else "guru_meditation"
        if c := _CANARY.search(t):
            r.kind, r.task = "stack_overflow", c.group(1)
    elif m := _STACK_OVF.search(t):
        r.kind, r.task = "stack_overflow", m.group(1)
    elif m := _ASSERT.search(t):
        r.kind = "assert"
        r.assertion = {"function": m.group(1), "file": m.group(2), "line": int(m.group(3)),
                       "expression": m.group(4)}
    elif m := _ABORT.search(t):
        r.kind, r.core = "abort", int(m.group(2))
        r.registers["PC"] = int(m.group(1), 16)
    elif _TASK_WDT.search(t):
        r.kind = "task_wdt"
        r.wdt_starved = _WDT_STARVED.findall(t)
        r.wdt_running = dict(_WDT_RUNNING.findall(t))
    elif m := _HEAP.search(t):
        r.kind = "heap_corruption"
        r.notes.append(m.group(1).strip())

    # Register dump: only the lines between "register dump" and the backtrace/stack section.
    dump = re.search(r"register dump:\n(.*?)(?:\n\s*\n|\nBacktrace|\nStack memory)", t, re.S)
    if dump:
        for name, val in _REG.findall(dump.group(1)):
            r.registers[name] = int(val, 16)

    addrs: list[int] = []
    if bt := _BACKTRACE.search(t):
        addrs = [int(pc, 16) for pc, _sp in _BT_ENTRY.findall(bt.group(1))]
        r.backtrace_corrupted = "CORRUPTED" in bt.group(1)
    elif "MEPC" in r.registers:
        # RISC-V chips print no backtrace; the faulting PC and return address are the best cheap
        # approximation without a GDB-based unwind of the stack dump.
        addrs = [r.registers["MEPC"]] + ([r.registers["RA"]] if "RA" in r.registers else [])
        r.notes.append("RISC-V panics carry no backtrace; frames are MEPC and RA only. "
                       "Use gdb_backtrace on a live session for a full unwind.")
    r.backtrace = symbolize(addrs) if addrs else []
    if r.kind == "abort" and "PC" in r.registers:
        r.abort_caller = symbolize([r.registers["PC"]])[0]
    r.cause = _probable_cause(r)
    return r


def _first_user_frame(r: PanicReport) -> Frame | None:
    for f in r.backtrace:
        if f.function and not f.function.startswith(("panic_", "esp_system_abort", "abort", "__assert",
                                                     "vPortTaskWrapper", "esp_ipc", "xt_")):
            return f
    return r.backtrace[0] if r.backtrace else None


def _probable_cause(r: PanicReport) -> str:
    frame = _first_user_frame(r)
    at = f" in {frame.where()}" if frame and frame.function else ""
    exc = (r.exception or "").lower()
    fault_addr = r.registers.get("EXCVADDR", r.registers.get("MTVAL"))

    if r.kind == "stack_overflow":
        return (f"Stack overflow in task '{r.task}': raise its stack size in xTaskCreate or cut its "
                f"stack use (large locals, deep recursion){at}.")
    if r.kind == "assert":
        a = r.assertion or {}
        return f"Assertion '{a.get('expression')}' failed in {a.get('function')} ({a.get('file')}:{a.get('line')})."
    if r.kind == "abort":
        f = r.abort_caller
        where = f" by {f.where()}" if f and f.function else f" at PC 0x{r.registers.get('PC', 0):08x}"
        return f"abort() was called{where}; the caller detected an unrecoverable error (check its return codes)."
    if r.kind == "task_wdt":
        running = ", ".join(f"{cpu}: {task}" for cpu, task in r.wdt_running.items())
        return (f"Task watchdog: {', '.join(r.wdt_starved) or 'a task'} did not run in time; running were "
                f"[{running}]. A task is busy-looping without blocking (add vTaskDelay or wait on an event).")
    if r.kind == "int_wdt":
        return (f"Interrupt watchdog on core {r.core}: interrupts stayed disabled too long (long ISR, spinning "
                f"in a critical section, or a deadlock on a spinlock){at}.")
    if r.kind == "heap_corruption":
        return "Heap corruption detected: a buffer overrun or use-after-free damaged heap metadata."
    if r.kind == "guru_meditation":
        if exc in ("loadprohibited", "storeprohibited", "load access fault", "store access fault"):
            op = "read" if "load" in exc else "write"
            if fault_addr is not None and fault_addr < 0x1000:
                return f"NULL pointer dereference ({op} at 0x{fault_addr:08x}){at}."
            addr = f" at 0x{fault_addr:08x}" if fault_addr is not None else ""
            return f"Invalid memory {op}{addr} (dangling or corrupted pointer){at}."
        if exc in ("instrfetchprohibited", "instruction access fault"):
            return f"Jump to an invalid address: corrupted function pointer or smashed return address{at}."
        if exc in ("illegalinstruction", "illegal instruction"):
            return f"Illegal instruction: execution went into data or a corrupted code pointer{at}."
        if exc == "integerdividebyzero":
            return f"Integer division by zero{at}."
        if exc in ("loadstorealignment", "load address misaligned", "store address misaligned"):
            return f"Unaligned memory access{at}."
        if "cache disabled" in exc:
            return f"Flash cache was accessed while disabled: code or data used from an ISR is not in IRAM/DRAM{at}."
        if "double exception" in exc:
            return f"Double exception, usually a stack overflow while handling another exception{at}."
        return f"CPU exception '{r.exception}'{at}."
    return "No known crash signature."
