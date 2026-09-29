#!/usr/bin/env bash
# M1 Q4 follow-up: N=10 runs per icount shift; distinct UART-log hashes and wall-per-virtual-second.
set -euo pipefail
. "$IDF_PATH/export.sh" >/dev/null 2>&1
W=/tmp/tdet && rm -rf $W && cp -r /m1/timer_det $W && cd $W
idf.py set-target esp32 >/dev/null 2>&1 && idf.py build >/tmp/b.log 2>&1
(cd build && esptool --chip esp32 merge-bin --pad-to-size 4MB -o ../flash.bin @flash_args >/dev/null)
for cfg in "shift2:-icount shift=2,sleep=off" "shift3:-icount shift=3,sleep=off" "shift5:-icount shift=5,sleep=off" "none:"; do
  L=${cfg%%:*}; A=${cfg#*:}
  : > /tmp/hashes; : > /tmp/ratios
  for R in $(seq 1 10); do
    out=/tmp/u.log; rm -f $out
    t0=$(date +%s.%N)
    timeout 300 qemu-system-xtensa -machine esp32 -nographic -no-reboot -drive file=flash.bin,if=mtd,format=raw -serial file:$out -monitor none $A >/dev/null 2>&1 &
    QP=$!
    until grep -q "Returned from app_main" $out 2>/dev/null; do kill -0 $QP 2>/dev/null || break; sleep 0.02; done
    t1=$(date +%s.%N)
    kill $QP 2>/dev/null; wait $QP 2>/dev/null || true
    md5sum < $out | cut -c1-12 >> /tmp/hashes
    vms=$(grep -o "I ([0-9]*) main_task: Returned" $out | grep -o "[0-9]*" | head -1)
    python3 -c "print(($t1-$t0)/($vms/1000.0))" >> /tmp/ratios
  done
  python3 - "$L" <<'PY'
import sys, statistics as st
h=[l.strip() for l in open('/tmp/hashes')]; r=[float(l) for l in open('/tmp/ratios')]
print(f"{sys.argv[1]:<7} N={len(h)} distinct_logs={len(set(h))} counts={sorted([h.count(x) for x in set(h)], reverse=True)} "
      f"wall_per_virtual_s mean={st.mean(r):.2f} sd={st.stdev(r):.2f}")
PY
done
