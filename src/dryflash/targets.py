"""Chip targets: which QEMU binary, machine, debugger and binutils belong to each."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownTargetError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    arch: str  # "xtensa" or "riscv32"
    qemu: str
    machine: str
    gdb: str
    addr2line: str
    # QEMU memory argument idf.py uses for the target ("" = none); PSRAM size on Xtensa chips.
    memory: str
    # Only esp32 has an I2C controller model in Espressif's QEMU.
    sensors: bool


TARGETS: dict[str, Target] = {
    "esp32": Target("esp32", "xtensa", "qemu-system-xtensa", "esp32", "xtensa-esp32-elf-gdb",
                    "xtensa-esp32-elf-addr2line", "4M", True),
    "esp32s3": Target("esp32s3", "xtensa", "qemu-system-xtensa", "esp32s3", "xtensa-esp32s3-elf-gdb",
                      "xtensa-esp32s3-elf-addr2line", "32M", False),
    "esp32c3": Target("esp32c3", "riscv32", "qemu-system-riscv32", "esp32c3", "riscv32-esp-elf-gdb",
                      "riscv32-esp-elf-addr2line", "", False),
}


def get_target(name: str) -> Target:
    try:
        return TARGETS[name]
    except KeyError:
        raise UnknownTargetError(f"unknown target {name!r}; supported: {', '.join(TARGETS)}") from None
