# M5 report: SPI sensors, GPIO, MPU-6050, display capture, UART over TCP (2026-10-03)

Brief: docs/provenance/verus-peripherals-prompt.md. Decisions and measurements: DECISIONS.md `## M5`.
Step-0 evidence: experiments/m5_spike/. Arduino check: experiments/m5_arduino/.

## What works

- **Verus end to end** (`examples/verus_pod`, ESP-IDF):
  - MPU-6050, ADS1115 + SS49E, MAX31855 on SPI3, SSD1306, pairing button and LED;
  - only the Verus JSON wire format on UART0.
  - Its scenario passes deterministically, twice byte-identical (`tests/integration/test_sensors.py`).
  - Measured against the injected signals:

    | feature | measured | expected |
    |---|---|---|
    | `vib_rms_g` | 0.0706 | 0.0707 |
    | `hall_ac_mv` | 4.39 | 4.384 |
    | `temp_c` | 31.25 → 85.00 | 31.25 → 85.00 |

  - The probe unplug (`fault: open`) produces the `detached` module line.
  - A button pulse opens pairing: the LED blinks at 2.0004 Hz, and the code read off the OLED
    equals the printed one.
- **Through MCP tools only**, an agent can:
  - build and run the firmware;
  - inject vibration, Hall and thermocouple data, including an unplugged probe (`sensor_set`);
  - press the button (`gpio_pulse`), see the LED blink (`gpio_trace`) and read the code
    (`display_snapshot`).

  A host program reads the same run over `uart_tcp_port`; the integration test does this over a
  socket, as pyserial `socket://` would.
- **New models:**
  - `mpu6050`: all ranges, sleep, self-clearing reset;
  - `max31855`: Tables 2-5, all faults;
  - `max6675`;
  - `ssd1306`: decoder, text reader, PNG.
- **New tools:** `gpio_set`, `gpio_pulse`, `gpio_read`, `gpio_trace`, `display_snapshot`.
- **New scenario steps:** `gpio_set`, `gpio_pulse`, `expect_gpio`, `expect_display`, plus
  `gpio:` and `emulator.uart_tcp_port`.
- **ESP-IDF SPI master:** both polling and interrupt-driven transfers work.
- **Arduino:** Arduino-style register sequences work, including GPIO chip select.
- **A real Arduino-ESP32 2.0.17 image** (PlatformIO) reading the same three sensors runs
  unmodified.
- **Tests:**
  - 250 unit tests;
  - 34 integration and sensor tests on a `dryflash:test-sensors` image built from scratch with
    all 18 patches.
  - In the full run, `test_expect_timeout_reports_tail` failed once and passed when rerun alone
    (timing under load). `test_exact_run_for_and_sensor_set_while_paused` failed because of the
    deliberate `emu_run_for` change and was fixed.

## What deviates from real hardware

- **No DMA on SPI.** A DMA transfer returns `ESP_OK` with no data.
- **SPI2/3:** no dummy phase and no slave mode.
- **No BLE/Wi-Fi.** The serial fallback is the test path.
- **GPIO:**
  - no IO_MUX, so there are no pull-ups and declared inputs carry a default level instead;
  - no GPIO-matrix routing, so pin numbers matter only for GPIO and `cs_gpio`;
  - no NMIs, no RTC IO;
  - both CPUs' GPIO interrupts share one matrix source.
- **MPU-6050:**
  - reads zero while asleep, not the last sample;
  - DEVICE_RESET does not restore the other registers;
  - no FIFO, DMP, interrupts or self-test.
- **MAX31855/MAX6675:**
  - `tc_c` is the reported value; the K-type linearisation is not modelled;
  - under short faults the temperature bits keep the injected value.
- **SSD1306:**
  - text is read only for the Adafruit 5x7 font;
  - scrolling and the analog settings are accepted but not rendered;
  - the image assumes the common A1h/C8h module orientation.
- **Emulated ADCs are sample-and-hold.** Polling at nearly the device rate occasionally re-reads
  or skips a sample, which moves `hall_ac_mv` by up to 3 %.
- **Determinism:**
  - 24/24 idle runs byte-identical;
  - **15/16 under 12 CPU burners**, with one `vib_rms_g` digit differing after the OLED flush.
    The cause is not found.
  - Input from a UART TCP client is host-timed.
- **`emu_run_for` on a running sliced session starts at the next slice stop** (at most 100 ms
  ahead). This is the price of reproducible stop points.

## Measured overheads

| quantity | value |
|---|---|
| deterministic `emu_run_for`, `vibration_monitor` | 0.58 ± 0.03 wall s per virtual s (N=10) |
| deterministic `emu_run_for`, `verus_pod` (4 devices + GPIO) | 1.87 ± 0.35 wall s per virtual s (N=10) |
| register updates sent for `verus_pod` | about 55 000 per virtual second (MPU 16 banks × 1 kHz, ADS 64 banks × 860 Hz) |
| QEMU build | unchanged flags; `-Werror` clean |

## Patches ready to propose upstream (espressif/qemu)

Each is one logical change, checkpatch-clean except where noted, with a commit message ready to use.

| patch | what | upstream readiness |
|---|---|---|
| 0011 | SPI: no command phase unless `SPI_USR_COMMAND` | **Ready.** Small, TRM-cited, real bug for every SPI2/3 user; NVS/flash re-tested. |
| 0013 | SPI: latch `TRANS_DONE`, raise the completion IRQ | **Ready with 0018.** Needed for `spi_device_transmit()`. |
| 0018 | Interrupt matrix keeps source levels, ORs shared sources | **Ready, and the most important one.** Affects every interrupt-driven IDF driver that uses `esp_intr_disable`/`enable`. Needs a reviewer-runnable reproducer (the io_probe interrupt read). |
| 0009 | GPIO output/input/interrupt registers | **Ready** after review of the `pins` property approach (keeps esp32c3/s3 unchanged). |
| 0016 | SPI2/SPI3 on sysbus-default with named buses, CS wired at machine-init-done | Ready for the bus part. The sim-gpio wiring inside it is dryflash-specific and should be split out first. |
| 0012 | SPI `byte`/`i` | **Do not send.** Superseded by PR #144; kept here only until #144 merges. |
| 0007, 0008, 0010, 0014, 0015, 0017 | sim-sensor / sim-gpio host-link devices | Not for upstream as is: they serve dryflash's host protocol. 0014 triggers checkpatch's complex-macro check on the property list; 0010/0015 trigger the MAINTAINERS reminder. |

The earlier recommendation stands: send 0005 first (docs/upstream-pr.md).
