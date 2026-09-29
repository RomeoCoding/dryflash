#!/usr/bin/env bash
# M1 Q2: can a stock I2C target be attached to the esp32 machine's I2C bus from the command line?
. "$IDF_PATH/export.sh" >/dev/null 2>&1
Q="qemu-system-xtensa -machine esp32 -nographic -S -serial null"
echo "== info qtree (i2c-related, stock machine) =="
echo -e "info qtree\nquit" | $Q -monitor stdio 2>&1 | grep -n -iE "bus: |dev: esp32.i2c|tmp105|esp32-periph|main-system-bus" | head -40
for b in "" "bus=i2c" "bus=i2c.0" "bus=/machine/soc/i2c0/i2c" "bus=esp32-periph-bus"; do
  echo "== -device tmp105,${b:+$b,}address=0x49 =="
  echo "quit" | timeout 10 $Q -monitor stdio -device tmp105,${b:+$b,}address=0x49 2>&1 | grep -v "^QEMU\|(qemu)" | head -3
done
echo "== device_add at runtime via HMP =="
echo -e "device_add tmp105,bus=i2c,address=0x49\nquit" | timeout 10 $Q -monitor stdio 2>&1 | grep -v "^QEMU" | head -3
echo "== QOM paths =="
echo -e "info qom-tree\nquit" | $Q -monitor stdio 2>&1 | grep -iE "i2c|tmp105" | head
