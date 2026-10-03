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


SPI_BUSES = ("spi2", "spi3")  # the esp32's general-purpose SPI controllers (SPI2_HOST/HSPI, SPI3_HOST/VSPI)
SPI_CS_LINES = 3               # hardware CS outputs per controller


class SensorModel:
    model = ""
    interface = "i2c"  # or "spi"
    channels: tuple[str, ...] = ()
    default_address = 0
    addresses: tuple[int, ...] = ()  # the addresses the chip can strap to; empty: any
    default_rate_hz = 100.0
    unit = ""

    def __init__(self, spec: dict, base_dir: Path | None = None):
        if not spec.get("name"):
            raise SensorSpecError("every sensor needs a 'name'")
        self.name = str(spec["name"])
        if self.interface == "spi":
            self._init_spi(spec)
        else:
            self._init_i2c(spec)
        self.rate_hz = float(spec.get("rate_hz", self.default_rate_hz))
        if not 0 < self.rate_hz <= 10000:
            raise SensorSpecError(f"sensor {self.name}: rate_hz must be in (0, 10000]")
        self.base_dir = base_dir
        self._timeline: dict[str, list[tuple[int, Waveform]]] = {c: [(0, parse_waveform(0.0))] for c in self.channels}
        self.guest_regs = bytearray(256)
        self.guest_regs[:] = self.initial_registers()  # describe() is right before the first guest write
        self.schedule(0, spec.get("waveform", {}) or {})

    def _init_spi(self, spec: dict) -> None:
        if "address" in spec:
            raise SensorSpecError(f"sensor {self.name}: a {self.model} is an SPI device; give bus "
                                  f"({'/'.join(SPI_BUSES)}), cs and optionally cs_gpio, not an address")
        self.bus = str(spec.get("bus", "spi3")).lower()
        if self.bus not in SPI_BUSES:
            raise SensorSpecError(f"sensor {self.name}: bus must be one of {', '.join(SPI_BUSES)} "
                                  f"(SPI2_HOST/SPI3_HOST), got {spec.get('bus')!r}")
        self.cs = _int(spec.get("cs", 0), "cs")
        if not 0 <= self.cs < SPI_CS_LINES:
            raise SensorSpecError(f"sensor {self.name}: cs must be 0-{SPI_CS_LINES - 1} (the controller's CS "
                                  "lines); to wire CS to a GPIO pad give cs_gpio as well")
        self.cs_gpio: int | None = None
        if spec.get("cs_gpio") is not None:
            from .gpio import GpioSpecError, check_pad
            try:
                self.cs_gpio = check_pad(spec["cs_gpio"], f"sensor {self.name}: cs_gpio")
            except GpioSpecError as e:
                raise SensorSpecError(str(e)) from None
        self.address = None

    def _init_i2c(self, spec: dict) -> None:
        for key in ("cs", "cs_gpio"):
            if key in spec:
                raise SensorSpecError(f"sensor {self.name}: {key} applies to SPI sensors; a {self.model} is on I2C")
        self.bus = _int(spec.get("bus", 0), "bus")
        if self.bus not in (0, 1):
            raise SensorSpecError(f"sensor {self.name}: bus must be 0 or 1 (the esp32 I2C controllers)")
        self.address = _int(spec.get("address", self.default_address), "address")
        if not 0x08 <= self.address <= 0x77:
            raise SensorSpecError(f"sensor {self.name}: address 0x{self.address:02x} is not a 7-bit I2C address")
        if self.addresses and self.address not in self.addresses:
            raise SensorSpecError(f"sensor {self.name}: a {self.model} answers only at "
                                  f"{' or '.join(f'0x{a:02x}' for a in self.addresses)}, not 0x{self.address:02x}")
        if self.bus == 0 and self.address == TMP105_ADDRESS:
            raise SensorSpecError(f"sensor {self.name}: address 0x48 on bus 0 is taken by the tmp105 the esp32 "
                                  "machine hard-wires; pick another address (e.g. ADS1115 with ADDR=VDD is 0x49)")

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

    def on_stream(self, t_ns: int, data: bytes) -> None:
        """A whole guest write transfer (I2C stream mode, e.g. a display); ignored by register chips."""

    def describe(self) -> dict:
        d = {"name": self.name, "model": self.model, "bus": self.bus}
        if self.interface == "spi":
            d.update(cs=self.cs, cs_gpio=self.cs_gpio)
        else:
            d["address"] = f"0x{self.address:02x}"
        d.update(rate_hz=self.rate_hz, channels=list(self.channels), unit=self.unit,
                 guest_config=self.guest_config())
        return d


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


class Mpu6050(SensorModel):
    """InvenSense MPU-6050 6-axis IMU. Channels x, y, z (g), gx, gy, gz (deg/s), temp_c (degC).

    Register behaviour follows the MPU-6000/MPU-6050 Register Map and Descriptions, RM-MPU-6000A-00
    rev 4.0 (section numbers below). The bank number is SLEEP | AFS_SEL << 1 | FS_SEL << 3 over the
    data registers 0x3B..0x48, so the guest reads data scaled for its own ranges, and zeros while the
    chip sleeps (power-on state), without the host reacting to guest writes.
    """

    model = "mpu6050"
    channels = ("x", "y", "z", "gx", "gy", "gz", "temp_c")
    default_address = 0x68
    addresses = (0x68, 0x69)  # AD0 low / high (4.34)
    default_rate_hz = 1000.0  # accelerometer output rate is 1 kHz (4.2)
    unit = "g (x, y, z), deg/s (gx, gy, gz), degC (temp_c)"
    DATA = 0x3B
    ACCEL_LSB_PER_G = (16384, 8192, 4096, 2048)       # AFS_SEL 0..3: +-2/4/8/16 g (4.18)
    GYRO_LSB_PER_DPS = (131.0, 65.5, 32.8, 16.4)      # FS_SEL 0..3: +-250/500/1000/2000 deg/s (4.20)

    def device_props(self):
        return {"bank-fields": "0x6b:0x40,0x1c:0x18,0x1b:0x18",  # PWR_MGMT_1 SLEEP, ACCEL_CONFIG, GYRO_CONFIG
                "bank-first": "0x3b", "bank-last": "0x48",
                "read-set": "0x3a:0x01",                          # INT_STATUS DATA_RDY_INT (4.17)
                # DEVICE_RESET (4.30) and FIFO/I2C_MST/SIG_COND_RESET (4.29) clear themselves
                "write-clear": "0x6b:0x80,0x6a:0x07",
                "read-only": "0x3a-0x60,0x72-0x73,0x75"}           # status, data, FIFO_COUNT, WHO_AM_I

    def initial_registers(self):
        r = bytearray(256)  # every register resets to 0x00 except these two (section 3)
        r[0x6B] = 0x40      # PWR_MGMT_1: SLEEP
        r[0x75] = 0x68      # WHO_AM_I: upper 6 bits of the address, AD0 not reflected (4.34)
        self.guest_regs[:] = r
        return r

    def encode(self, values):
        temp = _clip(round((values["temp_c"] - 36.53) * 340), 16)  # T = raw/340 + 36.53 (4.19)
        out = []
        for fs, dps_lsb in enumerate(self.GYRO_LSB_PER_DPS):
            gyro = [_clip(round(values[a] * dps_lsb), 16) for a in ("gx", "gy", "gz")]
            for afs, g_lsb in enumerate(self.ACCEL_LSB_PER_G):
                accel = [_clip(round(values[a] * g_lsb), 16) for a in ("x", "y", "z")]
                data = b"".join(v.to_bytes(2, "big", signed=True) for v in (*accel, temp, *gyro))
                out.append((afs << 1 | fs << 3, self.DATA, data))  # SLEEP=0 banks; sleep banks stay 0
        return out

    def guest_config(self):
        r = self.guest_regs
        dlpf = r[0x1A] & 7
        gyro_rate = 8000.0 if dlpf in (0, 7) else 1000.0  # (4.2)
        return {"sleeping": bool(r[0x6B] & 0x40), "accel_range_g": 2 << ((r[0x1C] >> 3) & 3),
                "gyro_range_dps": 250 << ((r[0x1B] >> 3) & 3),
                "sample_rate_hz": gyro_rate / (1 + r[0x19]), "dlpf_cfg": dlpf, "clock_source": r[0x6B] & 7}


FAULTS = ("none", "open", "short_gnd", "short_vcc")


def _fault_codes(spec: Any) -> Any:
    """Waveform specs for a fault channel may name the faults; turn the names into codes 0-3."""
    if isinstance(spec, str):
        if spec.lower() not in FAULTS:
            raise SensorSpecError(f"unknown fault {spec!r}; use one of {', '.join(FAULTS)}")
        return FAULTS.index(spec.lower())
    if isinstance(spec, dict):
        return {k: (_fault_codes(v) if k in ("steps", "value") else v) for k, v in spec.items()}
    if isinstance(spec, list):
        return [_fault_codes(v) for v in spec]
    return spec


class _ThermocoupleModel(SensorModel):
    interface = "spi"

    def schedule(self, from_ns, waveforms):
        if isinstance(waveforms, dict) and "fault" in waveforms:
            waveforms = dict(waveforms, fault=_fault_codes(waveforms["fault"]))
        super().schedule(from_ns, waveforms)

    @staticmethod
    def fault_code(v: float) -> int:
        return max(0, min(len(FAULTS) - 1, round(v)))

    def device_props(self):
        return {"mode": "frame"}  # a read-only shift register, frame at offset 0

    def describe(self):
        d = super().describe()
        d["faults"] = list(FAULTS[:len(self.fault_bits)])
        return d


class Max31855(_ThermocoupleModel):
    """Maxim MAX31855 thermocouple-to-digital converter (K type): 32-bit read-only SPI frame.

    Datasheet 19-5793 Rev 2 (2/12), Tables 2-5. Channels: tc_c (the thermocouple temperature the
    chip reports, after its cold-junction compensation and linear 41.276 uV/degC conversion),
    cj_c (internal reference-junction temperature) and fault (none, open, short_gnd, short_vcc).
    """

    model = "max31855"
    channels = ("tc_c", "cj_c", "fault")
    default_rate_hz = 10.0  # conversion time 100 ms max (Electrical Characteristics)
    unit = "degC (tc_c, cj_c); fault: none/open/short_gnd/short_vcc"
    fault_bits = (0, 0x1, 0x2, 0x4)  # D0 OC, D1 SCG, D2 SCV (Table 2)

    def frame(self, values: dict[str, float]) -> int:
        fault = self.fault_code(values["fault"])
        if fault == 1:
            tc = 0x1FFF  # open input: sign bit 0 and D[30:18] all ones ("Serial Interface")
        else:
            tc = _clip(round(values["tc_c"] / 0.25), 14) & 0x3FFF       # 0.25 degC, Table 4
        cj = _clip(round(values["cj_c"] / 0.0625), 12) & 0x0FFF         # 0.0625 degC, Table 5
        return tc << 18 | (1 if fault else 0) << 16 | cj << 4 | self.fault_bits[fault]

    def encode(self, values):
        return [(-1, 0, self.frame(values).to_bytes(4, "big"))]


class Max6675(_ThermocoupleModel):
    """Maxim MAX6675 K-thermocouple converter: 16-bit read-only SPI frame (datasheet 19-2235 Rev 1).

    D15 dummy sign bit 0, D14-D3 temperature in 0.25 degC from 0 to 1023.75, D2 open input,
    D1 device ID 0, D0 three-state (reads 0 here). Channels tc_c and fault (none or open).
    """

    model = "max6675"
    channels = ("tc_c", "fault")
    default_rate_hz = 5.0  # conversion time 0.22 s max
    unit = "degC (tc_c); fault: none/open"
    fault_bits = (0, 0x4)

    def schedule(self, from_ns, waveforms):
        if isinstance(waveforms, dict) and isinstance(waveforms.get("fault"), str) \
                and waveforms["fault"].lower() not in FAULTS[:2]:
            raise SensorSpecError(f"sensor {self.name}: a max6675 only detects an open input; fault is "
                                  "none or open")
        super().schedule(from_ns, waveforms)

    def frame(self, values: dict[str, float]) -> int:
        fault = min(self.fault_code(values["fault"]), 1)
        t = max(0, min(4095, round(values["tc_c"] / 0.25)))
        return t << 3 | self.fault_bits[fault]

    def encode(self, values):
        return [(-1, 0, self.frame(values).to_bytes(2, "big"))]


class Ssd1306(SensorModel):
    """Solomon Systech SSD1306 128x64 / 128x32 OLED controller on I2C (datasheet Rev 1.1).

    Not a sensor: the device runs in stream mode and every write transfer is decoded into the
    display state (sensors/display.py). Reads return 0. No channels.
    """

    model = "ssd1306"
    channels = ()
    default_address = 0x3C
    addresses = (0x3C, 0x3D)  # SA0 low / high (8.1.5)
    default_rate_hz = 1.0     # nothing to sample
    unit = ""

    def __init__(self, spec, base_dir=None):
        from .display import Ssd1306State
        self.display = Ssd1306State()
        self.last_write_ns: int | None = None
        super().__init__(spec, base_dir)

    def device_props(self):
        return {"stream": "on"}

    def encode(self, values):
        return []

    def on_stream(self, t_ns, data):
        self.display.feed_transfer(data)
        self.last_write_ns = t_ns

    def guest_config(self):
        return self.display.describe()


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


MODELS = {m.model: m for m in (Adxl345, Ads1115, Mpu6050, Max31855, Max6675, Ssd1306, GenericRegisterMap)}


def make_model(spec: dict, base_dir: Path | None = None) -> SensorModel:
    if not isinstance(spec, dict):
        raise SensorSpecError("a sensor spec is a mapping with at least 'model' and 'name'")
    cls = MODELS.get(str(spec.get("model", "")).lower())
    if cls is None:
        raise SensorSpecError(f"unknown sensor model {spec.get('model')!r}; available: {', '.join(MODELS)}")
    return cls(spec, base_dir)
