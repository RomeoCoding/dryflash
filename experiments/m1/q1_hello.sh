#!/usr/bin/env bash
# M1 Q1: build hello_world for a target and run it in QEMU. Usage: q1_hello.sh <target>
set -euo pipefail
. "$IDF_PATH/export.sh" >/dev/null 2>&1
T=$1
W=/tmp/hw_$T
rm -rf "$W" && cp -r "$IDF_PATH/examples/get-started/hello_world" "$W" && cd "$W"
t0=$(date +%s.%N)
idf.py set-target "$T" >/dev/null 2>&1
t1=$(date +%s.%N)
idf.py build >"/tmp/build_$T.log" 2>&1 || { tail -30 "/tmp/build_$T.log"; exit 1; }
t2=$(date +%s.%N)
(cd build && esptool --chip "$T" merge-bin --pad-to-size 4MB -o ../flash.bin @flash_args >/dev/null)
case $T in
    esp32) Q="qemu-system-xtensa -machine esp32" ;;
    *) Q="qemu-system-riscv32 -machine $T -icount 3" ;;  # idf.py qemu uses -icount 3 for RISC-V targets
esac
t3=$(date +%s.%N)
timeout 60 $Q -nographic -no-reboot -drive file=flash.bin,if=mtd,format=raw \
    -serial "file:/tmp/uart_$T.log" -monitor none >/dev/null 2>&1 &
QP=$!
until grep -q "Hello world!" "/tmp/uart_$T.log" 2>/dev/null; do sleep 0.05; done
t4=$(date +%s.%N)
kill $QP; wait $QP 2>/dev/null || true
python3 -c "print(f'target=$T set-target={$t1-$t0:.1f}s build={$t2-$t1:.1f}s qemu_boot_to_hello={$t4-$t3:.2f}s')"
grep -E "Hello world|This is" "/tmp/uart_$T.log" | head -3
ls -la build/*.bin | awk '{print $5, $9}'
