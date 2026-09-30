"""Waveform sources: functions of time (seconds since the segment started) that drive sensor channels.

Spec forms (JSON/YAML):
  1.0                                        constant
  [spec, spec, ...]                          sum of the specs
  {type: constant, value}
  {type: sine, freq_hz, amplitude=1, offset=0, phase_deg=0}
  {type: noise, std, mean=0, seed=0}         Gaussian, a pure function of (seed, time)
  {type: step, steps: [[t_s, value], ...]}   piecewise constant
  {type: rotation, rpm, amplitude, harmonics=[[order, amplitude], ...], phase_deg=0}
                                             imbalance-style 1x running-speed line plus harmonics
  {type: csv, path, column, time_column=0, time_unit=s|ms, loop=false, scale=1, offset=0}
                                             recorded samples, linearly interpolated
"""

from __future__ import annotations

import bisect
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WaveformError(ValueError):
    pass


class Waveform:
    def value(self, t: float) -> float:
        raise NotImplementedError


@dataclass
class Constant(Waveform):
    v: float

    def value(self, t):
        return self.v


@dataclass
class Sum(Waveform):
    terms: list[Waveform]

    def value(self, t):
        return sum(w.value(t) for w in self.terms)


@dataclass
class Sine(Waveform):
    freq_hz: float
    amplitude: float = 1.0
    offset: float = 0.0
    phase_deg: float = 0.0

    def value(self, t):
        return self.offset + self.amplitude * math.sin(2 * math.pi * self.freq_hz * t
                                                       + math.radians(self.phase_deg))


@dataclass
class Noise(Waveform):
    std: float
    mean: float = 0.0
    seed: int = 0

    def value(self, t):
        # Seeded by (seed, time in ns): the same instant always gets the same value, however the
        # timeline is chunked or re-sent, which keeps deterministic runs deterministic.
        return random.Random(self.seed * 1_000_003 + round(t * 1e9)).gauss(self.mean, self.std)


@dataclass
class Step(Waveform):
    times: list[float]
    values: list[float]

    def value(self, t):
        i = bisect.bisect_right(self.times, t) - 1
        return self.values[max(i, 0)]


@dataclass
class Rotation(Waveform):
    rpm: float
    amplitude: float
    harmonics: list[tuple[float, float]]
    phase_deg: float = 0.0

    def value(self, t):
        f1 = self.rpm / 60.0
        ph = math.radians(self.phase_deg)
        v = self.amplitude * math.sin(2 * math.pi * f1 * t + ph)
        for order, amp in self.harmonics:
            v += amp * math.sin(2 * math.pi * order * f1 * t + order * ph)
        return v


@dataclass
class Recorded(Waveform):
    times: list[float]
    values: list[float]
    loop: bool

    def value(self, t):
        if self.loop and self.times[-1] > self.times[0]:
            span = self.times[-1] - self.times[0]
            t = self.times[0] + (t - self.times[0]) % span
        if t <= self.times[0]:
            return self.values[0]
        if t >= self.times[-1]:
            return self.values[-1]
        i = bisect.bisect_right(self.times, t)
        t0, t1 = self.times[i - 1], self.times[i]
        v0, v1 = self.values[i - 1], self.values[i]
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def _num(spec: dict, key: str, default: Any = None) -> float:
    if key not in spec:
        if default is None:
            raise WaveformError(f"{spec.get('type')} waveform needs {key!r}")
        return default
    try:
        return float(spec[key])
    except (TypeError, ValueError):
        raise WaveformError(f"{key!r} must be a number, got {spec[key]!r}") from None


def _load_csv(spec: dict, base_dir: Path | None) -> Recorded:
    path = Path(spec.get("path", ""))
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    if not path.is_file():
        raise WaveformError(f"CSV file not found: {path}")
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].lstrip().startswith("#")]
    header = rows[0]
    has_header = any(not _is_number(c) for c in header)
    data = rows[1:] if has_header else rows

    def col(ref, default):
        ref = spec.get(ref, default)
        if isinstance(ref, int):
            return ref
        if has_header and ref in header:
            return header.index(ref)
        raise WaveformError(f"CSV column {ref!r} not found in {path.name} (columns: {header})")

    tc, vc = col("time_column", 0), col("column", 1)
    scale_t = 1e-3 if spec.get("time_unit", "s") == "ms" else 1.0
    scale, offset = _num(spec, "scale", 1.0), _num(spec, "offset", 0.0)
    try:
        times = [float(r[tc]) * scale_t for r in data]
        values = [float(r[vc]) * scale + offset for r in data]
    except (ValueError, IndexError) as e:
        raise WaveformError(f"bad CSV data in {path.name}: {e}") from None
    if len(times) < 2 or any(b <= a for a, b in zip(times, times[1:])):
        raise WaveformError(f"{path.name}: need at least 2 rows with strictly increasing time")
    return Recorded(times, values, bool(spec.get("loop", False)))


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_waveform(spec: Any, base_dir: Path | None = None) -> Waveform:
    if isinstance(spec, bool):
        raise WaveformError("a waveform is a number, list or mapping")
    if isinstance(spec, (int, float)):
        return Constant(float(spec))
    if isinstance(spec, list):
        return Sum([parse_waveform(s, base_dir) for s in spec])
    if not isinstance(spec, dict):
        raise WaveformError(f"a waveform is a number, list or mapping, got {spec!r}")
    kind = spec.get("type")
    if kind == "constant":
        return Constant(_num(spec, "value"))
    if kind == "sine":
        return Sine(_num(spec, "freq_hz"), _num(spec, "amplitude", 1.0), _num(spec, "offset", 0.0),
                    _num(spec, "phase_deg", 0.0))
    if kind == "noise":
        return Noise(_num(spec, "std"), _num(spec, "mean", 0.0), int(spec.get("seed", 0)))
    if kind == "step":
        steps = sorted((float(t), float(v)) for t, v in spec.get("steps", []))
        if not steps:
            raise WaveformError("step waveform needs 'steps': [[t_s, value], ...]")
        return Step([t for t, _ in steps], [v for _, v in steps])
    if kind == "rotation":
        harmonics = [(float(o), float(a)) for o, a in spec.get("harmonics", [])]
        return Rotation(_num(spec, "rpm"), _num(spec, "amplitude"), harmonics, _num(spec, "phase_deg", 0.0))
    if kind == "csv":
        return _load_csv(spec, base_dir)
    if kind == "sum":
        return Sum([parse_waveform(s, base_dir) for s in spec.get("terms", [])])
    raise WaveformError(f"unknown waveform type {kind!r}; use constant, sine, noise, step, rotation, csv")
