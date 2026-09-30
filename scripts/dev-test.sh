#!/usr/bin/env bash
# Run pytest inside the test image against the working tree (mounted over the baked-in copy).
# Usage: scripts/dev-test.sh [pytest args...]   e.g. scripts/dev-test.sh -m integration -x
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=${IMAGE:-dryflash:test}
if command -v cygpath >/dev/null; then ROOT=$(cygpath -w "$ROOT"); fi
MSYS_NO_PATHCONV=1 exec docker run --rm ${DOCKER_ARGS:-} -v "$ROOT:/opt/dryflash" "$IMAGE" pytest "$@"
