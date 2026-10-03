# M5 step 0: SPI, CS and GPIO in Espressif's QEMU (spike, 2026-10-03)

Base: `esp-develop-9.2.2-20260417` + `qemu-patches/0001-0006`, ESP-IDF v6.1, deterministic mode
(`-icount shift=3`). Firmware: `tests/firmware/spi_probe`. The QEMU side is throwaway
instrumentation (`apply_spike.py`, never part of the patch series):

- `spike-ssi`, a CS-active-low SSI device that returns `de ad be ef`, then `0x10 + index`. It logs
  every byte and CS edge with the virtual time to `$SPIKE_LOG`.
- Register traces of SPI2/SPI3 (`CMD`, `SLAVE` reads, all writes but `CTRL*`) and of every GPIO
  access.
- A prototype of the Q3 hook (below).

Three runs, all with one `spike-ssi` on SPI3 CS0 and one on SPI2 CS0:

| run | QEMU | UART | device + register trace |
|---|---|---|---|
| unfixed | controller model as shipped | `uart-unfixed.txt` | `trace-unfixed.log` |
| fixed | + `byte`→`i` and command-phase fixes (`apply_spike.py --fixes`) | `uart-fixed.txt` | `trace-fixed.log` |
| fixed, CS unwired | as *fixed*, with the controller CS lines left unconnected | `uart-fixed-nowire.txt` | `trace-fixed-nowire.log` |

## Q1: which ESP-IDF transfer paths complete?

| path (SPI3, `SPI_DMA_DISABLED`) | completes? | data, unfixed model | data, fixed model |
|---|---|---|---|
| `spi_device_polling_transmit`, rx only (A1) | yes, `ESP_OK` in 14 µs | `ad be ef 40` (stale W0) | `de ad be ef` |
| polling, full duplex, tx `ff ff ff ff` (A2) | yes | `ff ff ff ff` (own tx) | `de ad be ef` |
| polling, full duplex, tx `80 00 00 00` (A3) | yes | `80 ef 14 15` | `de ad be ef` |
| interrupt path: `queue_trans` + `get_trans_result` (A4) | **no**: `ESP_ERR_TIMEOUT` after 500 ms | n/a | n/a |
| polling with `SPI_DMA_CH_AUTO` on SPI2 (C1, C2) | yes (`ESP_OK`) | **nothing arrives**: `00 00 00 00`; a DMA buffer keeps its `a5` fill | same |

- **The interrupt-driven path hangs.** `spi_device_transmit()` is `queue_trans` +
  `get_trans_result` with `portMAX_DELAY` (IDF v6.1 `spi_master.c:1287-1292`), so it blocks
  forever. `esp32_spi.c` creates the IRQ (`sysbus_init_irq`) and `esp32.c` routes it to the
  interrupt matrix (`ETS_SPI0_INTR_SOURCE + i`), but nothing calls `qemu_set_irq` on it. The
  polling path works only because `SLAVE` always reads `TRANS_DONE | TRANS_INTEN` (`0x210` in the
  trace), and IDF polls `slave.trans_done` (`spi_ll.h:219-222`).
- **DMA fails silently.** The controller clocks the right bytes out to the device (trace: idx 0-9 on
  `ssi[hspi]`), but `DMA_CONF`/`DMA_IN_LINK` (`0x100`, `0x108`) are ignored, so received data
  never reaches the guest's buffer, and the call still returns `ESP_OK`. Firmware must use
  `SPI_DMA_DISABLED`. That limits a transaction to 64 bytes, which is fine for sensors.
- **Even polling reads were wrong, because of two controller bugs:**
  1. **`byte` vs `i` in `esp32_spi_txrx_buffer()`.** It is confirmed, but **not new**: espressif/qemu
     PR #144 ("fix RX bounds check and add dummy cycle handling", QEMU-282, open since
     2026-02-28, unmerged) fixes exactly this in the esp32, esp32c3 and esp32s3 models. When a tx
     byte value ≥ the rx length, the received byte is dropped and the guest reads its own tx
     data back (A2 and B1: `ff ff ff ff`).
  2. **Phantom command phase (new; no upstream issue found).** The USR path sends a command
     phase when `SPI_USER.USR_COMMAND` is set **or** `SPI_USER2.COMMAND_BITLEN` is non-zero.
     - ESP-IDF says "no command" with `usr_command = 0` and `usr_command_bitlen = 0 - 1 = 15`
       (`spi_ll.h:921-924`). The model then clocks **two** extra bytes before the data
       (trace: `xfer cmd=2 ... tx=4 rx=4`).
     - Arduino leaves `USER2` at its reset value (bitlen 4), which gives **one** extra byte (B2:
       `ad be ef 14`).
     - Every read is shifted by 1-2 bytes.
     - The fix keys the phase on `USR_COMMAND` alone. NVS and raw flash read/write/erase through
       SPI1 still work with it (section E, both runs), as do the boot-time flash ID and the IDF
       flash driver.
     - The ESP32 TRM v5.8 backs the fix. §20.3 (p. 356): "A certain phase is enabled only when
       its corresponding control bit is set to 1". Register 20.8 `SPI_USER2_REG`:
       `SPI_USR_COMMAND_BITLEN` "is only valid when SPI_USR_COMMAND is set to 1".
     - For the IRQ patch, `SPI_SLAVE_REG` (p. 375): `SPI_TRANS_DONE` is "the raw interrupt status
       bit for the SPI_TRANS_DONE_INT interrupt. It is set by hardware and cleared by software",
       and `SPI_TRANS_INTEN` is its enable bit.

## Q2: what do Arduino-style libraries do with CS?

Sources (pinned tags): arduino-esp32 **3.3.12**, Adafruit_BusIO **1.17.4**,
Adafruit-MAX31855-library **1.4.2**.

- `Adafruit_MAX31855::spiread32()` calls `spi_dev.read(buf, 4)` (`Adafruit_MAX31855.cpp:198-208`).
  - `Adafruit_SPIDevice::read()` fills the buffer with `sendvalue`, which defaults to `0xFF`
    (`Adafruit_SPIDevice.h:113`). It then asserts CS with `digitalWrite(_cs, LOW)`
    (`beginTransactionWithAssertingCS` → `setChipSelect`, `.cpp:310-324, 406-410`) and does
    one `SPI.transfer(buf, 4)`.
  - `begin()` makes CS a GPIO output, driven HIGH (`.cpp:110-114`).
- `SPIClass` starts with `_use_hw_ss = false` (`SPI.cpp:39`). Hardware CS is used only after
  `setHwCs(true)` (`SPI.cpp:148-160`).
- `spiStartBus()` → `spiInitBus()` writes `pin.val = 0` (`esp32-hal-spi.c:757`). That **enables
  CS0-CS2 in the controller**, without routing any of them to a pin. It also sets `usr_mosi`,
  `usr_miso` and `doutdin` (`:932-934`).
- `spiTransferBytesNL()` loads `W0..`, sets `CMD.USR` and polls until it clears (`:1585ff`).
- `digitalWrite` → `gpio_set_level` → `GPIO_OUT_W1TS`/`W1TC` (`0x008`/`0x00c`). The trace shows
  `gpio W 0x008 <- 0x00000020 (ignored)`: the GPIO model drops them.

Consequences in QEMU:

1. The controller asserts its CS lines once per USR transaction, regardless of the library's GPIO
   CS. A single-transfer read (MAX31855: one 4-byte transaction) is framed correctly **by
   accident**.
2. Two transfers inside one GPIO-CS window (`write_then_read`, any SPI register sensor) are
   framed as two frames. In B3 the device restarts after the first byte (`de de ad be`, should
   be `de ad be ef`).
3. All three CS lines assert together (`pin = 0x0`), so two devices on one bus would both answer.
4. With the `0xFF` filler, the `byte`/`i` bug makes the Adafruit read return `ff ff ff ff` today
   (B1).

**So a device's CS must be able to come from a modelled GPIO pin.** This needs the M5c GPIO model,
so **M5c has to come before (or with) the SSI CS work in M5b.** ESP-IDF's `spi_master` with
`spics_io_num >= 0` uses the controller's CS (`pin` = `0x6`, only CS0 enabled) and does not need it.

GPIO itself, from section D:
- After `gpio_set_level(25, 1)`, `GPIO_OUT`, `GPIO_ENABLE` and `gpio_get_level(25)` all read 0.
- GPIO27 configured as input with pull-up reads **0**. An active-low button therefore reads
  "pressed" forever on today's QEMU.
- `gpio_install_isr_service` and `gpio_isr_handler_add` return `ESP_OK`, but nothing can fire.

## Q3: can user-created SSI devices sit on SPI2/SPI3 with CS connected?

- **Not today.**
  - The four SPI controllers are realized on the SoC's private `periph_bus`, so they don't
    appear in `info qtree`.
  - All four buses are named `"spi"`.
  - `-device gd25q32,bus=spi` fails with `Bus 'spi' not found`; the `spi.0` and QOM-path forms
    fail too.
- **Hook that works (prototype in `apply_spike.py`):**
  1. Realize SPI2/SPI3 on sysbus-default, as patch 0001 did for I2C, and give the buses unique
     names. The prototype used QEMU's auto-names `ssi.2`/`ssi.3`. The SPI1 flash/PSRAM code then
     takes the bus by pointer instead of by the name `"spi"`.
  2. Register a **machine-init-done notifier** (`qemu_add_machine_init_done_notifier`). `-device`
     devices are created before those notifiers run. The notifier walks each bus's children and
     connects the controller's `ssi-gpio-cs[cs]` output to the device's `ssi-gpio-cs` input, then
     drives it high (idle).
  - Evidence: `info qtree` lists `bus: ssi.3` → `dev: spike-ssi`, and the trace starts with
    `machine-init-done: spi3 has spike-ssi cs=0 -> wired to controller CS` followed by
    `cs=1 (deasserted)`.
- **The CS must be wired.** A CS-active-low SSI device with an unconnected CS input has
  `cs = false` (ssi.c), so it is **always selected and never sees a frame start**. In the unwired
  run the bytes just run on across transactions: `14 15 16 17`, `18 19 1a 1b`, ...

## Proposed design for M5b/M5c (for approval)

1. **Order: M5c (GPIO) before M5b's CS work.**
   - The GPIO model exposes per-pin output lines. The output line level is `ENABLE ? OUT :`
     the pin's declared external level, so a CS pin idles deasserted until the firmware drives it.
   - The SSI device takes `cs-gpio=N`. The same machine-init-done notifier then connects GPIO
     output N, instead of the controller CS.
2. **Separate patches:**
   - SPI2/SPI3 reachable from `-device`, with the CS notifier;
   - phantom command phase;
   - `byte`/`i` (crediting PR #144, or dropped if #144 merges first);
   - SPI completion IRQ: a real `trans_done` latch, cleared by the guest, with the IRQ raised
     while `trans_done & trans_inten`;
   - `ssi-sim-sensor`;
   - GPIO registers and interrupts.
3. **Bus names:** explicit `spi2` / `spi3` (matching IDF's `SPI2_HOST`/`SPI3_HOST`), rather than
   the auto names `ssi.N`.
4. **Documented limits:** no DMA (firmware must use `SPI_DMA_DISABLED`; the call succeeds but data
   is lost), and no dummy phase on SPI2/3.

Also noted for M5d: `i2c-sim-sensor` keeps a `uint8_t` pointer into its 256-byte register file, and
the `G` notice reports the min..max written range of that file. A 1 KB SSD1306 data stream (control
byte `0x40`, then data) therefore wraps around and folds into the register file; it does not
arrive as a stream. This is from reading the source and is still to be confirmed with a run;
M5d needs a write-capture mode either way.
