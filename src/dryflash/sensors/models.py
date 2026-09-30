"""Sensor chip models: channel values (g, volts, ...) to register bytes for the i2c-sim-sensor device.

A model is pure data and arithmetic. It says how the generic QEMU device must be configured
(stride, bank selector, read-set bits, read-only ranges), what the registers hold at power-on,
and how one sample of channel values is written: for banked chips, one write per bank the
firmware could select, so the firmware reads a correctly scaled value whatever configuration it
picked, without the host having to react to guest writes (that would make timing host-dependent).
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

from .waveform import Waveform, WaveformError, parse_waveform

TMP105_ADDRESS = 0x48  # hard-wired on I2C0 by the esp32 machine


class SensorSpecError(ValueError):
    pass


def _int(v: Any, what: str) -> int:
    try:
        return int(v, 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise SensorSpecError(f"{what} must be an integer, got {v!r}") from None


class SensorModel:
    model = ""
    channels: tuple[str, ...] = ()
    default_address = 0
    default_rate_hz = 100.0
    unit = ""

    def __init__(self, spec: dict, base_dir: Path | None = None):
        if not spec.get("name"):
            raise SensorSpecError("every sensor needs a 'name'")
        self.name = str(spec["name"])
        self.bus = _int(spec.get("bus", 0), "bus")
        if self.bus not in (0, 1):
            raise SensorSpecError(f"sensor {self.name}: bus must be 0 or 1 (the esp32 I2C controllers)")
        self.address = _int(spec.get("address", self.default_address), "address")
        if not 0x08 <= self.address <= 0x77:
            raise SensorSpecError(f"sensor {self.name}: address 0x{self.address:02x} is not a 7-bit I2C address")
        if self.bus == 0 and self.address == TMP105_ADDRESS:
            raise SensorSpecError(f"sensor {self.name}: address 0x48 on bus 0 is taken by the tmp105 the esp32 "
                                  "machine hard-wires; pick another address (e.g. ADS1115 with ADDR=VDD is 0x49)")
        self.rate_hz = float(spec.get("rate_hz", self.default_rate_hz))
        if not 0 < self.rate_hz <= 10000:
            raise SensorSpecError(f"sensor {self.name}: rate_hz must be in (0, 10000]")
        self.base_dir = base_dir
        self._timeline: dict[str, list[tuple[int, Waveform]]] = {c: [(0, parse_waveform(0.0))] for c in self.channels}
        self.guest_regs = bytearray(256)
        self.schedule(0, spec.get("waveform", {}) or {})

    # ----- values over virtual time ---------------------------------------------------------------
    def schedule(self, from_ns: int, waveforms: dict[str, Any]) -> None:
        """From virtual time from_ns on, drive the given channels with new waveforms; others keep theirs."""
        if not isinstance(waveforms, dict):
            raise SensorSpecError(f"sensor {self.name}: waveform must map channel names ({', '.join(self.channels)}) "
                                  "to waveform specs")
        for ch, spec in waveforms.items():
            if ch not in self._timeline:
                raise SensorSpecError(f"sensor {self.name}: unknown channel {ch!r}; channels are "
                                      f"{', '.join(self.channels)}")
            try:
                w = parse_waveform(spec, self.base_dir)
            except WaveformError as e:
                raise SensorSpecError(f"sensor {self.name}, channel {ch}: {e}") from None
            segs = self._timeline[ch]
            segs[:] = [s for s in segs if s[0] < from_ns] + [(from_ns, w)]

    def values_at(self, t_ns: int) -> dict[str, float]:
        out = {}
        for ch, segs in self._timeline.items():
            i = bisect.bisect_right([s[0] for s in segs], t_ns) - 1
            start, w = segs[max(i, 0)]
            out[ch] = w.value((t_ns - start) / 1e9)
        return out

    # ----- device configuration --------------------------------------------------------------------
    def device_props(self) -> dict[str, str]:
        raise NotImplementedError

    def initial_registers(self) -> bytearray:
        return bytearray(256)

    def initial_writes(self) -> list[tuple[int, int, bytes]]:
        return [(-1, 0, bytes(self.initial_registers()))]

    def encode(self, values: dict[str, float]) -> list[tuple[int, int, bytes]]:
        raise NotImplementedError

    def on_guest_write(self, offset: int, data: bytes) -> None:
        self.guest_regs[offset:offset + len(data)] = data

    def guest_config(self) -> dict:
        return {}

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model, "bus": self.bus, "address": f"0x{self.address:02x}",
                "rate_hz": self.rate_hz, "channels": list(self.channels), "unit": self.unit,
                "guest_config": self.guest_config()}


def _clip(v: int, bits: int, signed: bool = True) -> int:
    lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
    return max(lo, min(hi, v))


class Adxl345(SensorModel):
    """Analog Devices ADXL345 3-axis accelerometer. Channels x, y, z in g."""

    model = "adxl345"
    channels = ("x", "y", "z")
    default_address = 0x53
    default_rate_hz = 400.0
    unit = "g"
    DATA = 0x32
    # DATA_FORMAT bits that change scaling: RANGE[1:0] and FULL_RES (bit 3). JUSTIFY is not modelled.
    BANKS = (0, 1, 2, 3, 8, 9, 10, 11)

    def device_props(self):
        return {"bank-reg": "0x31", "bank-width": "1", "bank-mask": "0x0b", "bank-shift": "0",
                "bank-first": "0x32", "bank-last": "0x37", "read-set": "0x30:0x80",
                "read-only": "0x00-0x1c,0x30,0x39"}

    def initial_registers(self):
        r = bytearray(256)
        r[0x00] = 0xE5  # DEVID
        r[0x2C] = 0x0A  # BW_RATE: 100 Hz
        r[0x30] = 0x83  # INT_SOURCE: DATA_READY, watermark, overrun
        self.guest_regs[:] = r
        return r

    @staticmethod
    def scale(bank: int) -> tuple[float, int]:
        rng = bank & 3
        if bank & 8:
            return 256.0, 10 + rng              # full resolution: 3.9 mg/LSB, 10..13 bits
        return 512.0 / (2 << rng), 10            # 10-bit over +-2/4/8/16 g

    def encode(self, values):
        out = []
        for bank in self.BANKS:
            lsb, bits = self.scale(bank)
            data = b"".join(_clip(round(values[a] * lsb), bits).to_bytes(2, "little", signed=True)
                            for a in self.channels)
            out.append((bank, self.DATA, data))
        return out

    def guest_config(self):
        fmt, bw, pwr = self.guest_regs[0x31], self.guest_regs[0x2C], self.guest_regs[0x2D]
        return {"range_g": 2 << (fmt & 3), "full_resolution": bool(fmt & 8),
                "output_data_rate_hz": 3200 / 2 ** (15 - (bw & 0x0F)), "measuring": bool(pwr & 0x08)}


class Ads1115(SensorModel):
    """TI ADS1115 16-bit ADC. Channels ain0..ain3 in volts; MUX and PGA select the result bank."""

    model = "ads1115"
    channels = ("ain0", "ain1", "ain2", "ain3")
    default_address = 0x49  # ADDR tied to VDD; 0x48 (ADDR=GND) is the esp32 machine's tmp105
    default_rate_hz = 250.0
    unit = "V"
    FULL_SCALE = (6.144, 4.096, 2.048, 1.024, 0.512, 0.256, 0.256, 0.256)
    MUX = (("ain0", "ain1"), ("ain0", "ain3"), ("ain1", "ain3"), ("ain2", "ain3"),
           ("ain0", None), ("ain1", None), ("ain2", None), ("ain3", None))

    def device_props(self):
        # 16-bit registers (stride 2); config is bytes 2..3 and MUX|PGA = config[14:9] picks one of
        # 64 conversion banks. OS (config bit 15) always reads 1: conversions complete at once.
        return {"stride": "2", "bank-reg": "2", "bank-width": "2", "bank-mask": "0x7e00", "bank-shift": "9",
                "bank-first": "0", "bank-last": "1", "read-set": "2:0x80"}

    def initial_registers(self):
        r = bytearray(256)
        r[2:8] = bytes([0x85, 0x83, 0x80, 0x00, 0x7F, 0xFF])  # config, lo_thresh, hi_thresh defaults
        self.guest_regs[:] = r
        return r

    def initial_writes(self):
        return [(-1, 2, bytes(self.initial_registers()[2:8]))]

    def encode(self, values):
        out = []
        for mux, (pos, neg) in enumerate(self.MUX):
            v = values[pos] - (values[neg] if neg else 0.0)
            for pga, fs in enumerate(self.FULL_SCALE):
                code = _clip(round(v / fs * 32768), 16)
                out.append((mux << 3 | pga, 0, code.to_bytes(2, "big", signed=True)))
        return out

    def guest_config(self):
        cfg = int.from_bytes(self.guest_regs[2:4], "big")
        mux = (cfg >> 12) & 7
        pos, neg = self.MUX[mux]
        return {"input": f"{pos}-{neg}" if neg else f"{pos}-gnd",
                "full_scale_v": self.FULL_SCALE[(cfg >> 9) & 7],
                "mode": "single-shot" if cfg & 0x0100 else "continuous",
                "data_rate_sps": (8, 16, 32, 64, 128, 250, 475, 860)[(cfg >> 5) & 7]}


_FORMATS = {f"{s}int{b}_{e}" if b > 8 else f"{s}int{b}": (b, s == "", e)
            for s in ("", "u") for b in (8, 16, 24, 32) for e in ("be", "le")}


class GenericRegisterMap(SensorModel):
    """Any register-mapped chip: initial register contents plus channels encoded as integers."""

    model = "generic"

    def __init__(self, spec: dict, base_dir: Path | None = None):
        chans = spec.get("channels", {}) or {}
        self._chan_cfg = {}
        for ch, c in chans.items():
            fmt = c.get("format", "uint8")
            if fmt not in _FORMATS:
                raise SensorSpecError(f"channel {ch}: unknown format {fmt!r}; use one of {sorted(_FORMATS)}")
            self._chan_cfg[ch] = (_int(c.get("offset", 0), f"channel {ch} offset"), *_FORMATS[fmt],
                                  float(c.get("scale", 1.0)), float(c.get("bias", 0.0)))
        self.channels = tuple(chans)
        self._spec = spec
        super().__init__(spec, base_dir)

    def device_props(self):
        props = {"stride": str(_int(self._spec.get("stride", 1), "stride"))}
        for key, prop in (("read_only", "read-only"), ("read_set", "read-set")):
            if self._spec.get(key):
                props[prop] = str(self._spec[key])
        return props

    def initial_registers(self):
        r = bytearray(256)
        for off, val in (self._spec.get("registers", {}) or {}).items():
            o = _int(off, "register offset")
            data = bytes(_int(v, "register value") for v in val) if isinstance(val, list) else \
                bytes([_int(val, "register value")])
            r[o:o + len(data)] = data
        self.guest_regs[:] = r
        return r

    def encode(self, values):
        out = []
        for ch, (off, bits, signed, endian, scale, bias) in self._chan_cfg.items():
            raw = _clip(round(values[ch] * scale + bias), bits, signed)
            out.append((-1, off, raw.to_bytes(bits // 8, "big" if endian == "be" else "little", signed=signed)))
        return out


MODELS = {m.model: m for m in (Adxl345, Ads1115, GenericRegisterMap)}


def make_model(spec: dict, base_dir: Path | None = None) -> SensorModel:
    if not isinstance(spec, dict):
        raise SensorSpecError("a sensor spec is a mapping with at least 'model' and 'name'")
    cls = MODELS.get(str(spec.get("model", "")).lower())
    if cls is None:
        raise SensorSpecError(f"unknown sensor model {spec.get('model')!r}; available: {', '.join(MODELS)}")
    return cls(spec, base_dir)
