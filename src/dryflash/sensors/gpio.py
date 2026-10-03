"""GPIO pads on the virtual timeline: host-driven input levels and a trace of every pad change.

The sim-gpio device (qemu-patches/) drives each esp32 pad's *external* level, which is what the
pad reads while the firmware does not drive it as an output, and reports every pad level change
with its virtual time. IO_MUX pull-ups are not modelled, so a declared input gets an explicit
default level (e.g. 1 for a button to ground with INPUT_PULLUP).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

PADS = tuple(range(0, 20)) + (21, 22, 23, 25, 26, 27) + tuple(range(32, 40))  # GPIO_PINn_REG exists
INPUT_ONLY = tuple(range(34, 40))


class GpioSpecError(ValueError):
    """A bad GPIO pin or declaration (reported to the agent like a sensor spec error)."""


def check_pad(pin: Any, what: str = "pin") -> int:
    try:
        p = int(pin)
    except (TypeError, ValueError):
        raise GpioSpecError(f"{what} must be a GPIO number, got {pin!r}") from None
    if p not in PADS:
        raise GpioSpecError(f"{what} {p} is not an ESP32 GPIO pad (pads: 0-19, 21-23, 25-27, 32-39)")
    return p


@dataclass
class PadTrace:
    times: list[int] = field(default_factory=list)   # virtual ns of each change
    levels: list[int] = field(default_factory=list)  # level after the change

    def level_at(self, t_ns: int, initial: int = 0) -> int:
        i = bisect.bisect_right(self.times, t_ns) - 1
        return self.levels[i] if i >= 0 else initial


class GpioBank:
    """Declared inputs, the queue of level changes to send, and the trace of pad changes."""

    def __init__(self, specs: list[dict] | None):
        self.defaults: dict[int, int] = {}
        self.names: dict[int, str] = {}
        for i, spec in enumerate(specs or []):
            if not isinstance(spec, dict) or "pin" not in spec:
                raise GpioSpecError(f"gpio[{i}]: give at least 'pin', e.g. {{pin: 27, default: 1}}")
            unknown = set(spec) - {"pin", "default", "name"}
            if unknown:
                raise GpioSpecError(f"gpio[{i}]: unknown keys {sorted(unknown)}; allowed: pin, default, name")
            pin = check_pad(spec["pin"], f"gpio[{i}].pin")
            if pin in self.defaults:
                raise GpioSpecError(f"gpio[{i}]: pin {pin} is declared twice")
            default = spec.get("default", 0)
            if default not in (0, 1):
                raise GpioSpecError(f"gpio[{i}].default must be 0 or 1 (IO_MUX pull-ups are not modelled)")
            self.defaults[pin] = int(default)
            if spec.get("name"):
                self.names[pin] = str(spec["name"])
        self.traces: dict[int, PadTrace] = {}
        self.pending: list[tuple[int, int, int]] = []  # (virtual_ns, pad, level), not yet sent

    def add_default(self, pin: int, level: int, owner: str) -> None:
        """A pad another device needs at a fixed idle level (e.g. a GPIO chip select)."""
        if pin in self.defaults and self.defaults[pin] != level:
            raise GpioSpecError(f"{owner} uses GPIO{pin} with idle level {level}, but gpio declares "
                                f"default {self.defaults[pin]}")
        self.defaults.setdefault(pin, level)

    @property
    def declared(self) -> bool:
        return bool(self.defaults)

    def initial_lines(self) -> list[tuple[int, int, int]]:
        return [(0, pin, level) for pin, level in sorted(self.defaults.items())]

    def on_change(self, t_ns: int, pad: int, level: int) -> None:
        tr = self.traces.setdefault(pad, PadTrace())
        tr.times.append(t_ns)
        tr.levels.append(level)

    def default_of(self, pin: int) -> int:
        return self.defaults.get(pin, 0)

    def schedule(self, t_ns: int, pin: int, level: int) -> None:
        self.pending.append((t_ns, pin, 1 if level else 0))

    def take_pending(self) -> list[tuple[int, int, int]]:
        out, self.pending = sorted(self.pending, key=lambda e: e[0]), []
        return out

    def level(self, pin: int, t_ns: int) -> int:
        tr = self.traces.get(pin)
        return tr.level_at(t_ns) if tr else 0

    def edges(self, pin: int, start_ns: int, end_ns: int) -> list[tuple[int, int]]:
        tr = self.traces.get(pin)
        if not tr:
            return []
        lo = bisect.bisect_left(tr.times, start_ns)
        hi = bisect.bisect_right(tr.times, end_ns)
        return list(zip(tr.times[lo:hi], tr.levels[lo:hi]))

    def trace(self, pin: int, cursor: int = 0, max_edges: int = 200) -> dict:
        tr = self.traces.get(pin, PadTrace())
        cursor = max(0, min(cursor, len(tr.times)))
        sel = list(zip(tr.times, tr.levels))[cursor:cursor + max_edges]
        return {"pin": pin, "edges": [{"t_ms": round(t / 1e6, 6), "level": lv} for t, lv in sel],
                "cursor": cursor + len(sel), "total_edges": len(tr.times),
                "more": cursor + len(sel) < len(tr.times)}

    def describe(self) -> dict:
        return {"declared_inputs": [{"pin": p, "default": d, **({"name": self.names[p]} if p in self.names else {})}
                                    for p, d in sorted(self.defaults.items())],
                "pads_seen_changing": sorted(self.traces)}


def window_stats(edges: list[tuple[int, int]], start_ns: int, end_ns: int) -> dict:
    """Edge count and frequency of a pad over [start_ns, end_ns] from its change list."""
    rising = [t for t, lv in edges if lv == 1]
    freq = None
    if len(rising) >= 2:
        freq = (len(rising) - 1) / ((rising[-1] - rising[0]) / 1e9)
    return {"window_ms": [round(start_ns / 1e6, 3), round(end_ns / 1e6, 3)], "edges": len(edges),
            "rising_edges": len(rising), "freq_hz": round(freq, 4) if freq is not None else None}
