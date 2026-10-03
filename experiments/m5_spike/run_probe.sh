#!/usr/bin/env bash
# usage: experiments/m5_spike/run_probe.sh <out-name>
# Runs tests/firmware/spi_probe on the QEMU binary in the qemu-dev volume (built with
# apply_spike.py applied); UART result -> scratch/<out-name>.json, device trace -> scratch/<out-name>.log.
# SPIKE_ENV="-e SPIKE_NO_CS_WIRE=1" leaves the test devices' CS unconnected.
cd "$(dirname "$0")/../.."
mkdir -p scratch
R=$(cygpath -w "$PWD")
MSYS_NO_PATHCONV=1 docker run --rm ${SPIKE_ENV:-} -e SPIKE_LOG=/work/scratch/$1.log -v qemu-dev:/dev-src -v dryflash-builds:/tmp/dryflash -v "$R:/work" dryflash:test-sensors bash -c \
 "cp /dev-src/qemu/build/qemu-system-xtensa \$(dirname \$(command -v qemu-system-xtensa))/ && rm -f /work/scratch/$1.log && cd /opt/dryflash && /opt/venv/bin/python -m dryflash test-run /work/tests/firmware/spi_probe ${2:-scenario.yaml} > /work/scratch/$1.json"
python -c "
import json,sys;d=json.load(open('scratch/$1.json'));t=d.get('transcript','');print('passed',d['passed'],d.get('reason'));print(t[t.find('PROBE start'):])"
