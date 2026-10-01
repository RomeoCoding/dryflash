#!/usr/bin/env bash
# A/B determinism check for the upstream PR (docs/upstream-pr.md).
#
# Runs experiments/m1/timer_det (an esp_timer callback plus one busy task pinned to each core) N
# times per QEMU binary and -icount shift, and counts distinct UART logs. Each log is cut at the
# app's own TIMER_DET_DONE line, so how long the host takes to notice the line and kill QEMU does
# not change the hash. -seed 1 fixes the esp32 RNG peripheral.
#
# Expects /pr/bin/qemu-<name> binaries, the QEMU source tree at /pr/qemu (for -L pc-bios) and the
# merged image at /pr/tdet_flash.bin; see docs/upstream-pr.md for how they were built.
#   N=20 SHIFTS="3 5" BINS="base p0005 patched" ab_determinism.sh
N=${N:-10}
for bin in ${BINS:-base patched}; do
  for shift in ${SHIFTS:-3 5}; do
    : > /tmp/h
    for r in $(seq 1 "$N"); do
      out=/tmp/u.log; rm -f $out
      timeout 240 /pr/bin/qemu-$bin -L /pr/qemu/pc-bios -machine esp32 -nographic -no-reboot \
        -drive file=/pr/tdet_flash.bin,if=mtd,format=raw -serial file:$out -monitor none \
        -icount shift=$shift,sleep=off -seed 1 >/dev/null 2>&1 &
      qp=$!
      until grep -q "TIMER_DET_DONE" $out 2>/dev/null; do kill -0 $qp 2>/dev/null || break; sleep 0.05; done
      kill $qp 2>/dev/null; wait $qp 2>/dev/null
      sed -n '1,/TIMER_DET_DONE/p' $out | md5sum | cut -c1-10 >> /tmp/h
    done
    echo "$bin shift=$shift N=$N distinct=$(sort -u /tmp/h | wc -l) counts=$(sort /tmp/h | uniq -c | awk '{print $1}' | tr '\n' ' ')"
    sort /tmp/h | uniq -c | sed 's/^/    /'
  done
done
