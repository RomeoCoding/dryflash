#!/usr/bin/env bash
# Build an IDF project copied from /m1/<dir> and run it in QEMU until <marker> appears.
# Usage: run_app.sh <dir> <target> <marker> [extra qemu args...]
set -euo pipefail
. "$IDF_PATH/export.sh" >/dev/null 2>&1
D=$1 T=$2 M=$3; shift 3
W=/tmp/app_$(basename "$D")_$T
rm -rf "$W" && cp -r "/m1/$D" "$W" && cd "$W"
idf.py set-target "$T" >/dev/null 2>&1
idf.py build >/tmp/build.log 2>&1 || { grep -E "error|Error" /tmp/build.log | head -20; exit 1; }
(cd build && esptool --chip "$T" merge-bin --pad-to-size 4MB -o ../flash.bin @flash_args >/dev/null)
case $T in esp32) Q="qemu-system-xtensa -machine esp32";; *) Q="qemu-system-riscv32 -machine $T";; esac
rm -f /tmp/uart.log
t0=$(date +%s.%N)
timeout 120 $Q -nographic -no-reboot -drive file=flash.bin,if=mtd,format=raw -serial file:/tmp/uart.log -monitor none "$@" >/tmp/qemu_stderr.log 2>&1 &
QP=$!
for i in $(seq 1 1200); do grep -q "$M" /tmp/uart.log 2>/dev/null && break; kill -0 $QP 2>/dev/null || break; sleep 0.1; done
t1=$(date +%s.%N)
kill $QP 2>/dev/null; wait $QP 2>/dev/null || true
python3 -c "print(f'wall_to_marker={$t1-$t0:.2f}s')"
echo "--- qemu stderr ---"; grep -v "^Adding SPI\|^Not initializing" /tmp/qemu_stderr.log | head -20
echo "--- uart (app section) ---"; sed -n '/main_task: Calling app_main/,$p' /tmp/uart.log | head -60
cp /tmp/uart.log "/m1/logs/uart_$(basename "$D")_$T.log"
