#!/usr/bin/env bash
# Sets up the ESP-IDF environment, then runs the MCP server (default) or any command.
# export.sh talks on stdout, which would corrupt the MCP stdio stream, so it is silenced.
set -e
. "$IDF_PATH/export.sh" >/dev/null 2>&1
case "${1:-serve}" in
    serve) shift || true; exec /opt/venv/bin/python -m dryflash serve "$@" ;;
    test-run) exec /opt/venv/bin/python -m dryflash "$@" ;;
    pytest) shift; cd "$DRYFLASH_HOME"; exec /opt/venv/bin/python -m pytest "$@" ;;
    *) exec "$@" ;;
esac
