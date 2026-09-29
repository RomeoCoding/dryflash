#!/usr/bin/env bash
. "$IDF_PATH/export.sh" >/dev/null 2>&1
qemu-system-xtensa --version | head -1
Q="qemu-system-xtensa -machine esp32 -nographic -S -serial null"
echo "== info qtree (patched) =="
echo -e "info qtree\nquit" | $Q -monitor stdio -device tmp105,bus=i2c-bus.0,address=0x49 2>&1 | grep -E "bus: i2c-bus|dev: esp32.i2c|dev: tmp105|address = " | head
echo "== ambiguous bare -device (no bus=) =="
echo quit | timeout 10 $Q -monitor stdio -device tmp105,address=0x49 2>&1 | grep -v "^QEMU\|(qemu)\|SPI" | head -2
echo "== firmware =="
bash /m1/run_app.sh i2c_attach esp32 I2C_ATTACH_DONE \
  -device tmp105,bus=i2c-bus.0,address=0x49,temperature=31500 \
  -device tmp105,bus=i2c-bus.1,address=0x4a,temperature=-12250 | grep -E "port|probe|DONE|wall"
