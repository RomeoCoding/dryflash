"""Scenario files: YAML descriptions of an emulator run and the UART behaviour it must show.

The schema is documented in README.md ("Scenario schema") and in docs/scenario-schema.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .targets import TARGETS

DEFAULT_FAIL_ON = [
    r"Guru Meditation Error",
    r"abort\(\) was called",
    r"\*\*\*ERROR\*\*\* A stack overflow",
    r"assert failed:",
    r"task_wdt: Task watchdog got triggered",
    r"CORRUPT HEAP",
]

ACTIONS = ("expect", "expect_not", "write", "run_for_ms", "sensor_set", "sensor_stream")


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


class Step(_Strict):
    name: str | None = None
    expect: str | None = None
    expect_not: str | None = None
    write: str | None = None
    run_for_ms: int | None = Field(None, gt=0)
    sensor_set: dict[str, Any] | None = None
    sensor_stream: dict[str, Any] | None = None
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

    @model_validator(mode="after")
    def _sensors_target(self):
        if self.sensors and not TARGETS[self.target].sensors:
            raise ValueError(f"sensors are supported only on esp32 (the only chip with an I2C model), "
                             f"not {self.target}")
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
