#!/usr/bin/env bash
# Restart a single service without touching the others.
# Usage: ./restart.sh <service>
#
# Note: ./stop.sh will still cleanly stop all services including restarted ones.
# Ctrl-C on the original start.sh will NOT kill a restarted service — use stop.sh instead.
#
# Restart order matters for tool cache correctness:
#   MCP services (audit-mcp, etc.) → aggregator → chat-ui
# If you restart an MCP service, you must also restart aggregator then chat-ui
# so the backend's in-memory tool cache (mcp_client._tool_cache) reflects the new tool list.

set -e
set -m  # each backgrounded service gets its own process group — see scripts/lib/supervise.sh
cd "$(dirname "$0")"
ROOT="$(pwd)"
source scripts/lib/supervise.sh

# mcp-aggregator/server ships its own bundled .env (AGGREGATOR_PORT=8100, for the
# submodule's standalone mock/testing use) — python-dotenv's load_dotenv() finds
# that one first walking up from the aggregator's cwd and never reaches this
# checkout's real root .env, since it doesn't override already-set vars. Read the
# real value here and pass it explicitly so a second checkout (M10 multi-plant)
# with a different AGGREGATOR_PORT isn't silently shadowed back to 8100.
AGGREGATOR_PORT="$(grep -E '^AGGREGATOR_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)"
AGGREGATOR_PORT="${AGGREGATOR_PORT:-8100}"

SERVICE="$1"
# mqtt-mcp/opcua-mcp aren't standalone services — the aggregator spawns them itself
# as stdio subprocesses (see backends.json). Restarting "aggregator" restarts them too.
SERVICES="simulator bridge influxdb-mcp audit-mcp control-mcp memory-mcp topology-builder aggregator chat-ui frontend"

if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service>"
    echo "Services: $SERVICES"
    exit 1
fi

# ── Kill existing instance ────────────────────────────────────────────────────
#
# supervise_stop identity-checks the recorded PID against its process start
# time before touching it (guards against PID reuse, e.g. after a reboot)
# and group-kills it (SIGTERM, then SIGKILL after a short grace period) so
# wrapper-forked children (uv, npm) are reaped too — see
# scripts/lib/supervise.sh. That makes the old pkill-by-checkout-path
# fallback below unnecessary: it existed only to catch children the single
# recorded PID couldn't reach, and it never covered bridge/influxdb-mcp/
# topology-builder/frontend in the first place.

PID_FILE=".pids/${SERVICE}.pid"
supervise_stop "$PID_FILE" "$SERVICE"

# ── Restart ───────────────────────────────────────────────────────────────────

mkdir -p logs .pids

start_one() {
    supervise_start "$1" "$2" "$3" ".pids/${1}.pid"
}

case "$SERVICE" in
    simulator)        start_one simulator        simulator              "uv run python simulator.py" ;;
    bridge)           start_one bridge            mqtt-influx-bridge    "uv run python bridge.py" ;;
    influxdb-mcp)     start_one influxdb-mcp      influxdb-mcp          "uv run python server.py" ;;
    audit-mcp)        start_one audit-mcp         audit-mcp             "uv run python server.py" ;;
    control-mcp)      start_one control-mcp       control-mcp           "uv run python server.py" ;;
    memory-mcp)       start_one memory-mcp        memory-mcp            "uv run python server.py" ;;
    topology-builder) start_one topology-builder  topology-builder      "uv run python server.py" ;;
    # BACKENDS_FILE and AGGREGATOR_PORT must be set explicitly — the aggregator's
    # own defaults resolve to the submodule's bundled example config, not this
    # checkout's real one. Matches start.sh.
    aggregator)       start_one aggregator        mcp-aggregator/server "BACKENDS_FILE=../backends.json AGGREGATOR_PORT=${AGGREGATOR_PORT} uv run python server.py" ;;
    chat-ui)          start_one chat-ui           chat-ui               "uv run python backend.py" ;;
    frontend)         start_one frontend          chat-ui/frontend      "npm run dev" ;;
    *)
        echo "Unknown service: $SERVICE"
        echo "Services: $SERVICES"
        exit 1
        ;;
esac
