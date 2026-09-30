"""Pure construction of the QEMU command line for one emulator session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .targets import Target

DEFAULT_ICOUNT_SHIFT = 3  # fastest shift that was byte-identical in 10/10 runs (docs/M1_REPORT.md Q4)


@dataclass
class QemuOptions:
    target: Target
    flash: Path
    efuse: Path | None
    run_dir: Path
    gdb_port: int
    deterministic: bool = False
    icount_shift: int = DEFAULT_ICOUNT_SHIFT
    reboot: bool = False
    watchdogs: bool = True
    extra_args: list[str] = field(default_factory=list)

    @property
    def qmp_socket(self) -> Path:
        return self.run_dir / "qmp.sock"

    @property
    def uart_socket(self) -> Path:
        return self.run_dir / "uart0.sock"


def build_qemu_cmdline(o: QemuOptions) -> list[str]:
    t = o.target
    cmd = [t.qemu, "-machine", t.machine]
    if t.memory:
        cmd += ["-m", t.memory]
    cmd += [
        "-nographic",
        "-monitor", "none",
        # Always start halted: the server connects to the UART socket first (so no boot output is
        # lost) and only then resumes the CPU, optionally after a debugger or sensor preload.
        "-S",
        "-qmp", f"unix:{o.qmp_socket},server=on,wait=off",
        "-chardev", f"socket,id=uart0,path={o.uart_socket},server=on,wait=off",
        "-serial", "chardev:uart0",
        "-gdb", f"tcp:127.0.0.1:{o.gdb_port}",
        "-drive", f"file={o.flash},if=mtd,format=raw",
    ]
    if o.efuse is not None:
        cmd += [
            "-drive", f"file={o.efuse},if=none,format=raw,id=efuse",
            "-global", f"driver=nvram.{t.machine}.efuse,property=drive,value=efuse",
        ]
    if o.deterministic:
        # -seed: the RNG peripheral reads qemu_guest_getrandom, which is host entropy otherwise.
        cmd += ["-icount", f"shift={o.icount_shift},sleep=off", "-seed", "1"]
    elif t.arch == "riscv32":
        cmd += ["-icount", "3"]  # what idf.py qemu uses for the RISC-V chips
    if not o.reboot:
        # A guest reset (panic, watchdog, esp_restart) ends the session instead of boot-looping,
        # which keeps the crash output at the end of the UART log.
        cmd.append("-no-reboot")
    if not o.watchdogs:
        cmd += ["-global", f"driver=timer.{t.machine}.timg,property=wdt_disable,value=true"]
    cmd += o.extra_args
    return cmd
