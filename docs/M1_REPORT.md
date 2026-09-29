# M1 feasibility report

Date: 2026-09-29. All commands ran inside containers on the owner's Windows 11 host
(Docker Desktop 29.6.2, WSL2 kernel 6.18.33, 16 vCPU, 6.6 GiB given to Docker). The scripts
and raw logs live in `experiments/m1/` and `experiments/m1/logs/`. `$IMG` below means
`espressif/idf:v6.1@sha256:81893c71bb5e570088901f21def8684c25cd2a9020281bd01b843a7655edb18c`.

**Verdict: go.** Every question has a working answer. One small QEMU patch (question 2) is
needed before anything can be attached to the I2C bus, and there is one determinism caveat
(question 4).

## 1. Toolchain: does espressif/idf v6.1 ship QEMU?

Yes. The v6.1 image's Dockerfile runs `idf_tools.py install qemu*`, and `tools.json` pins
`esp_develop_9.2.2_20260417`, which is the same tag as the latest espressif/qemu release. So
nothing needs adding.

```
$ docker run --rm $IMG bash -lc 'which qemu-system-xtensa qemu-system-riscv32; qemu-system-xtensa --version'
/opt/esp/tools/qemu-xtensa/esp_develop_9.2.2_20260417/qemu/bin/qemu-system-xtensa
/opt/esp/tools/qemu-riscv32/esp_develop_9.2.2_20260417/qemu/bin/qemu-system-riscv32
QEMU emulator version 9.2.2 (esp_develop_9.2.2_20260417)
GNU gdb (esp-gdb) 17.1_20260402          # xtensa-esp32-elf-gdb and riscv32-esp-elf-gdb both present
Python 3.12.3
```

hello_world, built from a clean copy and booted in QEMU (`experiments/m1/q1_hello.sh`),
N=2 runs per target:

| target  | `set-target` | `idf.py build` (clean) | QEMU start → "Hello world!" |
|---------|--------------|------------------------|-----------------------------|
| esp32   | 7.1 s / 7.3 s | 16.5 s / 16.0 s        | 1.39 s / 1.39 s             |
| esp32c3 | 7.4 s / 7.5 s | 17.1 s / 17.3 s        | 0.17 s / 0.16 s             |

```
Hello world!
This is esp32 chip with 2 CPU core(s), WiFi/BTBLE, silicon revision v0.0, 2MB external flash
Hello world!
This is esp32c3 chip with 1 CPU core(s), WiFi/BLE, silicon revision v0.3, 2MB external flash
```

The flash image is made with `esptool --chip <t> merge-bin --pad-to-size 4MB -o flash.bin
@flash_args`, run from `build/`. esptool v5 renamed `merge_bin` to `merge-bin`. esp32 runs
without `-icount`; esp32c3 uses `-icount 3`, which is what `idf.py qemu` passes for RISC-V
chips.

## 2. Can a stock I2C target be attached to I2C0 from the command line?

**Not with stock QEMU.** `hw/xtensa/esp32.c` says so itself ("It should be possible to create
an I2C device from the command line, however for this to work the I2C bus must be reachable
from sysbus-default..."), and hard-wires a `tmp105` at 0x48 on I2C0 instead. The I2C
controllers are realized on the SoC-private `esp32-periph-bus`, whose parent (the SoC) has no
bus. `qbus_find()` searches only from `main-system-bus`, so it never sees them. Every spelling
fails (`logs/q2_attach.log`):

```
-device tmp105,address=0x49                       -> No 'i2c-bus' bus found for device 'tmp105'
-device tmp105,bus=i2c,address=0x49               -> Bus 'i2c' not found
-device tmp105,bus=/machine/soc/i2c0/i2c,...      -> Device 'machine' not found
-device tmp105,bus=esp32-periph-bus,...           -> Bus 'esp32-periph-bus' not found
(HMP) device_add tmp105,bus=i2c,address=0x49      -> Error: Bus 'i2c' not found
info qom-tree: /machine/soc/i2c0/i2c (i2c-bus), /machine/soc/i2c1/i2c (i2c-bus)  # both named "i2c"
```

**Smallest fix**, `qemu-patches/0001-hw-xtensa-esp32-allow-I2C-devices-to-be-created-from.patch`
(+19/−11 lines, 2 files):

- realize the two I2C controllers with `sysbus_realize()` (on sysbus-default) instead of on
  `esp32-periph-bus`;
- pass `NULL` as the bus name, so QEMU assigns unique names (`i2c-bus.0`, `i2c-bus.1`) instead
  of two buses both called `i2c`;
- keep the hard-wired tmp105 at 0x48.

The trade-off is that a QEMU *system* reset now also resets the I2C controllers.
`esp32_soc_reset()` already resets them on every peripheral reset, so no guest can observe
the difference.

I built it with `docker/qemu-sensors.Dockerfile`, which downloads the pinned source tarball,
checks its sha256 against the release checksum file (`66015182…c6198`), applies the patches,
and configures with Espressif's flag set. The build took 4 min 16 s. Results
(`logs/q2b_patched.log`, `logs/q2c_qomset.log`):

```
$ qemu-system-xtensa -M esp32 -device tmp105,bus=i2c-bus.0,address=0x49 ...  (info qtree)
  dev: esp32.i2c   bus: i2c-bus.1
  dev: esp32.i2c   bus: i2c-bus.0
      dev: tmp105  address = 73 (0x49)
      dev: tmp105  address = 72 (0x48)

firmware (experiments/m1/i2c_attach), temperatures set with QMP qom-set while held at -S:
port 0 addr 0x48: ESP_OK raw=1900 temp=25.00 C      <- hard-wired device
port 0 addr 0x49: ESP_OK raw=1f80 temp=31.50 C      <- -device ...,bus=i2c-bus.0
port 1 addr 0x4a: ESP_OK raw=f380 temp=-12.50 C     <- -device ...,bus=i2c-bus.1 (9-bit default resolution)
probe port1 0x48 (must be absent): ESP_ERR_NOT_FOUND
```

A side finding: `-device tmp105,...,temperature=31500` reads back as 0, because
`tmp105_reset()` zeroes the temperature after the properties are applied. Setting it over QMP
after reset works, as shown above. My own device will keep its state in properties that
survive reset, and gets its data over the chardev.

## 3. Does the v6.1 `i2c_master` driver complete a register read through esp32_i2c.c?

**Yes, with no driver or model changes** (`experiments/m1/i2c_probe`, stock QEMU,
`logs/q3_i2c_probe.log`):

```
probe 0x48: ESP_OK
probe 0x50 (absent): ESP_ERR_NOT_FOUND          <- NACK path (ACK_ERR interrupt) works
read temp (reg 0x00): ESP_OK 19 00              <- write pointer + repeated start + 2-byte read
write config 0x60: ESP_OK 01 60
read config (reg 0x01): ESP_OK 60
read 40 bytes: ESP_OK 19 00 ff ff               <- longer than the 32-byte FIFO: END-chunked
```

The model implements RSTART, WRITE, READ, STOP and END, the TRANS_COMPLETE, END_DETECT and
ACK_ERR interrupts, and FIFO reset. That is everything the driver's interrupt-driven path
uses. Limitations that matter later:

- a whole command list executes synchronously when TRANS_START is written, in zero virtual
  time, so bus timing (clock stretching, SCL speed) isn't modelled;
- slave mode and non-FIFO (APB) mode aren't implemented, and ARBITRATION and TIME_OUT
  interrupts are never raised;
- a read from an empty RX FIFO returns 0xee and prints an error.

None of these affect a master reading sensors.

## 4. Determinism with -icount

`experiments/m1/timer_det` interleaves a 1 kHz `esp_timer` callback with busy tasks on both
cores and prints `esp_timer_get_time()`. Each run captures the full UART log from reset,
including the boot-log timestamps, and the logs are compared by md5. N=10 per configuration
(`logs/q4b_n10.log`):

| QEMU flags                   | distinct logs in 10 runs | wall-clock s per virtual s (mean ± sd) |
|------------------------------|--------------------------|----------------------------------------|
| none                         | 10 (every run differs)   | n/a (virtual clock follows the host)   |
| `-icount shift=2,sleep=off`  | **1**                    | 2.85 ± 0.10                            |
| `-icount shift=3,sleep=off`  | **1**                    | 1.59 ± 0.02                            |
| `-icount shift=5,sleep=off`  | 2 (6 / 4 split)          | 0.70 ± 0.03                            |

An earlier N=3 pass (`logs/q4_determinism.log`) agrees: shift 1, 2 and 3 were identical,
shift 5 wasn't, and `shift=3,sleep=on` was identical in 2/2 runs. In wall time, the same app
took 4.6 s with shift=3 against 2.9 s without icount, which is **about 1.6× slower**.

The shift=5 divergence is a single line: `I (1250) app_init` vs `I (1251) app_init`. All 59
clock uses in the ESP32 device models are `QEMU_CLOCK_VIRTUAL`, so the leak is in generic
QEMU code (icount/round-robin TCG). I haven't root-caused it; it's logged in
`docs/UPSTREAM_ISSUES.md`.

Decision: deterministic mode uses `-icount shift=3,sleep=off` (8 ns per instruction, about
125 MIPS; a real ESP32 at 240 MHz is closer to shift=2). CPU-bound code therefore runs about
2× slower in virtual time than on silicon. The shift is configurable. The M3 integration test
repeats the byte-identical check on the demo app, so a regression in determinism would show
up there.

## 5. Feasibility of the custom I2C device (M3): go

Evidence that the pieces exist:

- patch 0001 makes any `I2CSlave` attachable from the command line (question 2);
- the driver path works end to end (question 3);
- `-icount shift=3` is deterministic for this workload (question 4);
- QEMU's `CharBackend` front-end (`qemu_chr_fe_set_handlers` with `can_read`/`read` callbacks
  on the main loop) and `timer_new_ns(QEMU_CLOCK_VIRTUAL, ...)` give a non-blocking host link
  and virtual-time application of updates;
- the patched build is 4 minutes and cacheable.

Design points already settled by what I found:

- **Register stride.** ADS1115 registers are 16-bit and addressed by a pointer. With a plain
  byte-addressed file, pointer 0x01 would alias byte 1 of the conversion register. The device
  needs a `stride` property: bytes per register address, with auto-increment across bytes.
- **Determinism against host timing.** The host sends updates stamped with `virtual_ns`, plus
  a "horizon" (data is complete up to T). If virtual time reaches the horizon, the device
  calls `vm_stop()` from its virtual-clock timer. It never blocks, and the stop point is
  exact under icount. The server refills and sends `cont` over QMP. In non-deterministic
  mode, late updates are simply applied on arrival.
- **Address clash.** The ADS1115's default address 0x48 collides with the hard-wired tmp105.
  Examples will use 0x49 (ADDR pin to VDD).

**Main risk:** getting the horizon/`vm_stop` handshake right, so that two runs stay
byte-identical while the host streams data mid-run. **Fallback if it fails:** drop the
streaming chardev path. All sensor data is then sent before the CPU starts (`-S`, bulk
load, `cont`), and mid-run `sensor_set` only happens while the VM is paused over QMP.
Streaming then works only in non-deterministic mode. That still meets the demo-app
requirement, which injects a waveform declared at `emu_start`.

## 6. Project names

Checked 2026-09-29: PyPI (`GET https://pypi.org/pypi/<name>/json`), GitHub
(`GET https://api.github.com/search/repositories?q=<name>+in:name`), and the search pages of
Glama (`glama.ai/mcp/servers?query=`), mcp.so (`mcp.so/search?q=`) and PulseMCP
(`pulsemcp.com/servers?q=`).

| name              | PyPI | GitHub repos | Glama | mcp.so | PulseMCP | note |
|-------------------|------|--------------|-------|--------|----------|------|
| **boardless-mcp** | 404  | 0            | none named so (1 unrelated hit: "Vivado Agent MCP" uses "boardless" in its description) | 0 | 0 | brand-neutral; says what it does. Bare `boardless` has 22 unrelated repos |
| **espwright**     | 404  | 0            | 0     | 0      | 0        | "Playwright for ESP32". Contains Espressif's "ESP" mark; check their trademark guidance first |
| **xtensim**       | 404  | 0            | 0     | 0      | 0        | undersells the RISC-V targets |

Also checked and rejected: `phantom-esp` (23 repos), `benchless` (5 repos), `ghostboard` and
`sim32` (both taken on PyPI), `qesp` (40 repos), `espbench` (5 repos, and ESPBench is an
existing benchmark).

My recommendation is **boardless-mcp**. The working name stays until the owner picks.

## Facts from the brief, re-checked

- Correct: QEMU tag `esp-develop-9.2.2-20260417`; `esp32_i2c.c` is 283 lines; two
  controllers named `i2c0`/`i2c1`, each with a bus called `i2c`; `idf.py` QEMU support; no
  ADC model.
- Stronger than stated: CLI attach isn't merely "may be ambiguous", it is impossible without
  the patch (question 2).
- New: the machine hard-wires a tmp105 at 0x48, and `esp32_i2c.c` is also compiled for
  esp32s3, but no s3 machine instantiates it.
