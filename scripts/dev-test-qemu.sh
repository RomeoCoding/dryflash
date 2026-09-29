#!/usr/bin/env bash
# Like dev-test.sh, but first swaps in the QEMU binary from the qemu-dev volume (the development
# build of the patch series), so QEMU changes can be tested without rebuilding the image.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if command -v cygpath >/dev/null; then ROOT=$(cygpath -w "$ROOT"); fi
MSYS_NO_PATHCONV=1 exec docker run --rm -v qemu-dev:/dev-src -v esp32sim-builds:/tmp/esp32-sim-mcp \
  -v "$ROOT:/opt/esp32-sim-mcp" "${IMAGE:-esp32-sim-mcp:test-sensors}" bash -c \
  'cp /dev-src/qemu/build/qemu-system-xtensa $(dirname $(command -v qemu-system-xtensa))/ && cd /opt/esp32-sim-mcp && exec /opt/venv/bin/python -m pytest "$@"' _ "$@"
