"""Scenario files: YAML descriptions of an emulator run and the UART behaviour it must show.

The schema is documented in README.md ("Scenario schema") and in docs/scenario-schema.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .sensors.gpio import GpioBank, GpioSpecError, check_pad
from .targets import TARGETS

DEFAULT_FAIL_ON = [
    r"Guru Meditation Error",
    r"abort\(\) was called",
    r"\*\*\*ERROR\*\*\* A stack overflow",
    r"assert failed:",
    r"task_wdt: Task watchdog got triggered",
    r"CORRUPT HEAP",
]

ACTIONS = ("expect", "expect_not", "write", "run_for_ms", "sensor_set", "sensor_stream",
           "gpio_set", "gpio_pulse", "expect_gpio", "expect_display")


class ScenarioError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmulatorConfig(_Strict):
    deterministic: bool = True
    icount_shift: int = Field(3, ge=0, le=10)
    reboot: bool = False
    watchdogs: bool = True
    qemu_args: list[str] = []
    uart_tcp_port: int | None = Field(None, ge=1, le=65535)


def _pad(v: int) -> int:
    try:
        return check_pad(v)
    except GpioSpecError as e:
        raise ValueError(str(e)) from None


class GpioSet(_Strict):
    pin: int
    level: int = Field(ge=0, le=1)
    at_ms: float | None = Field(None, ge=0)
    _pin = field_validator("pin")(classmethod(lambda cls, v: _pad(v)))


class GpioPulse(_Strict):
    pin: int
    width_ms: float = Field(gt=0)
    at_ms: float | None = Field(None, ge=0)
    level: int | None = Field(None, ge=0, le=1)
    _pin = field_validator("pin")(classmethod(lambda cls, v: _pad(v)))


class ExpectGpio(_Strict):
    """Run exactly within_ms of virtual time, then check the pad over that window."""
    pin: int
    within_ms: float = Field(gt=0)
    level: int | None = Field(None, ge=0, le=1)       # level at the end of the window
    min_edges: int | None = Field(None, ge=0)
    max_edges: int | None = Field(None, ge=0)
    freq_hz: tuple[float, float] | None = None        # from the rising edges in the window
    _pin = field_validator("pin")(classmethod(lambda cls, v: _pad(v)))

    @model_validator(mode="after")
    def _something_to_check(self):
        if self.level is None and self.min_edges is None and self.max_edges is None and self.freq_hz is None:
            raise ValueError("expect_gpio needs at least one of level, min_edges, max_edges, freq_hz")
        return self


class ExpectDisplay(_Strict):
    """Wait until text read off an ssd1306 contains a substring or matches a regex."""
    sensor: str
    contains: str | None = None
    regex: str | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.contains is None) == (self.regex is None):
            raise ValueError("expect_display needs exactly one of contains, regex")
        if self.regex is not None:
            try:
                re.compile(self.regex)
            except re.error as e:
                raise ValueError(f"invalid regex {self.regex!r}: {e}") from None
        return self


class Step(_Strict):
    name: str | None = None
    expect: str | None = None
    expect_not: str | None = None
    write: str | None = None
    run_for_ms: int | None = Field(None, gt=0)
    sensor_set: dict[str, Any] | None = None
    sensor_stream: dict[str, Any] | None = None
    gpio_set: GpioSet | None = None
    gpio_pulse: GpioPulse | None = None
    expect_gpio: ExpectGpio | None = None
    expect_display: ExpectDisplay | None = None
    timeout_s: float = Field(10.0, gt=0)
    within_s: float = Field(1.0, gt=0)
    value_range: tuple[float, float] | None = None

    @property
    def action(self) -> str:
        return next(a for a in ACTIONS if getattr(self, a) is not None)

    @model_validator(mode="after")
    def _one_action(self):
        present = [a for a in ACTIONS if getattr(self, a) is not None]
        if len(present) != 1:
            raise ValueError(f"a step needs exactly one of {', '.join(ACTIONS)}; got {present or 'none'}")
        for key in ("expect", "expect_not"):
            rx = getattr(self, key)
            if rx is not None:
                try:
                    compiled = re.compile(rx)
                except re.error as e:
                    raise ValueError(f"invalid regex {rx!r}: {e}") from None
                if key == "expect" and self.value_range is not None and compiled.groups < 1:
                    raise ValueError("value_range needs a capture group in the expect regex")
        if self.value_range is not None and self.expect is None:
            raise ValueError("value_range only applies to expect steps")
        return self


class Scenario(_Strict):
    name: str
    description: str = ""
    target: str = "esp32"
    timeout_s: float = Field(120.0, gt=0)
    emulator: EmulatorConfig = EmulatorConfig()
    sensors: list[dict[str, Any]] = []
    gpio: list[dict[str, Any]] = []
    fail_on: list[str] = DEFAULT_FAIL_ON
    steps: list[Step] = Field(min_length=1)

    @field_validator("target")
    @classmethod
    def _target(cls, v):
        if v not in TARGETS:
            raise ValueError(f"unknown target {v!r}; supported: {', '.join(TARGETS)}")
        return v

    @field_validator("fail_on")
    @classmethod
    def _fail_on(cls, v):
        for rx in v:
            try:
                re.compile(rx)
            except re.error as e:
                raise ValueError(f"invalid regex {rx!r}: {e}") from None
        return v

    @field_validator("gpio")
    @classmethod
    def _gpio(cls, v):
        try:
            GpioBank(v)
        except GpioSpecError as e:
            raise ValueError(str(e)) from None
        return v

    @model_validator(mode="after")
    def _sensors_target(self):
        if self.sensors and not TARGETS[self.target].sensors:
            raise ValueError(f"sensors are supported only on esp32 (the only chip with an I2C model), "
                             f"not {self.target}")
        if self.gpio and not TARGETS[self.target].sensors:
            raise ValueError(f"gpio injection is supported only on esp32, not {self.target}")
        return self


def parse_scenario(text: str) -> Scenario:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ScenarioError(f"scenario is not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ScenarioError("scenario must be a YAML mapping")
    try:
        return Scenario.model_validate(data)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"{loc}: {err['msg']}".replace("Value error, ", ""))
        raise ScenarioError("invalid scenario: " + "; ".join(msgs)) from None


def load_scenario(path: Path) -> Scenario:
    return parse_scenario(Path(path).read_text())
