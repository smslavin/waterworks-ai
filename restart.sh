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
cd "$(dirname "$0")"
ROOT="$(pwd)"

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

PID_FILE=".pids/${SERVICE}.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping $SERVICE (pid $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Fallback: pkill any matching process not covered by the PID file
# (catches services started manually outside of start.sh / restart.sh)
#
# Patterns are anchored on $ROOT (this checkout's absolute path) rather than
# a bare "python simulator.py"-style argv match. uv run's own argv is
# identical text across every checkout (cwd isn't part of argv), and its
# child python process's argv only carries an absolute path via its venv
# interpreter (.venv/bin/python3 ...) — so an unanchored pattern kills the
# same-named service in every other checkout too, not just this one. Matters
# once a second waterworks-ai checkout (M10 multi-plant) runs side by side.
case "$SERVICE" in
    chat-ui)          pkill -f "${ROOT}/chat-ui/.venv"    2>/dev/null || true ;;
    simulator)        pkill -f "${ROOT}/simulator/.venv"  2>/dev/null || true ;;
    aggregator)       pkill -P "$(pgrep -f "${ROOT}/mcp-aggregator/server" | head -1)" 2>/dev/null || true; kill "$(pgrep -f "${ROOT}/mcp-aggregator/server/.venv")" 2>/dev/null || true ;;
    audit-mcp)        pkill -f "${ROOT}/audit-mcp/.venv"  2>/dev/null || true ;;
    control-mcp)      pkill -f "${ROOT}/control-mcp/.venv" 2>/dev/null || true ;;
    memory-mcp)       pkill -f "${ROOT}/memory-mcp/.venv" 2>/dev/null || true ;;
esac
sleep 0.5

# ── Restart ───────────────────────────────────────────────────────────────────

mkdir -p logs .pids

start_one() {
    local name="$1" dir="$2" cmd="$3"
    (cd "$dir" && eval "$cmd") > "logs/${name}.log" 2>&1 &
    local pid=$!
    echo "$pid" > ".pids/${name}.pid"
    echo "  [$name] started — pid $pid — logs/${name}.log"
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
