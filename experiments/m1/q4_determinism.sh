#!/usr/bin/env bash
# M1 Q4: are two -icount runs of a timer-driven app byte-identical over UART, and what does it cost?
set -euo pipefail
. "$IDF_PATH/export.sh" >/dev/null 2>&1
W=/tmp/tdet && rm -rf $W && cp -r /m1/timer_det $W && cd $W
idf.py set-target esp32 >/dev/null 2>&1 && idf.py build >/tmp/b.log 2>&1 || { tail -20 /tmp/b.log; exit 1; }
(cd build && esptool --chip esp32 merge-bin --pad-to-size 4MB -o ../flash.bin @flash_args >/dev/null)
run() {  # $1=label $2=run# rest=qemu args
  local L=$1 R=$2; shift 2
  local out=/tmp/u_${L}_$R.log; rm -f $out
  local t0=$(date +%s.%N)
  timeout 300 qemu-system-xtensa -machine esp32 -nographic -no-reboot -drive file=flash.bin,if=mtd,format=raw \
      -serial file:$out -monitor none "$@" >/dev/null 2>&1 &
  local QP=$!
  until grep -q "TIMER_DET_DONE" $out 2>/dev/null; do kill -0 $QP 2>/dev/null || break; sleep 0.02; done
  local t1=$(date +%s.%N)
  kill $QP 2>/dev/null; wait $QP 2>/dev/null || true
  python3 -c "print(f'{\"$L\":<22} run$R wall={$t1-$t0:6.2f}s md5=' + __import__('hashlib').md5(open('$out','rb').read()).hexdigest() + ' lines=' + str(sum(1 for _ in open('$out','rb'))))"
}
for R in 1 2 3; do run no_icount $R; done
for S in 1 2 3 5; do for R in 1 2 3; do run icount_shift$S $R -icount shift=$S,sleep=off; done; done
for R in 1 2; do run icount_shift3_sleep_on $R -icount shift=3,sleep=on; done
echo "--- diff no_icount run1 vs run2 (first lines) ---"
diff /tmp/u_no_icount_1.log /tmp/u_no_icount_2.log | head -8 || true
echo "--- icount shift=3 app output tail ---"
grep -E "^(A|B) i=19|TIMER_DET_DONE" /tmp/u_icount_shift3_1.log
cp /tmp/u_*.log /m1/logs/q4/ 2>/dev/null || true
