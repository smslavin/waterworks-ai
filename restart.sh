#!/usr/bin/env bash
# Restart a single service without touching the others.
# Usage: ./restart.sh <service>
#
# Note: ./stop.sh will still cleanly stop all services including restarted ones.
# Ctrl-C on the original start.sh will NOT kill a restarted service — use stop.sh instead.

set -e
cd "$(dirname "$0")"

SERVICE="$1"
SERVICES="simulator bridge mqtt-mcp opcua-mcp influxdb-mcp audit-mcp control-mcp memory-mcp topology-builder aggregator chat-ui frontend"

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
    mqtt-mcp)         start_one mqtt-mcp          mcp-servers/mqtt-mcp  "uv run python server.py" ;;
    opcua-mcp)        start_one opcua-mcp         mcp-servers/opcua-mcp "uv run python server.py" ;;
    influxdb-mcp)     start_one influxdb-mcp      influxdb-mcp          "uv run python server.py" ;;
    audit-mcp)        start_one audit-mcp         audit-mcp             "uv run python server.py" ;;
    control-mcp)      start_one control-mcp       control-mcp           "uv run python server.py" ;;
    memory-mcp)       start_one memory-mcp        memory-mcp            "uv run python server.py" ;;
    topology-builder) start_one topology-builder  topology-builder      "uv run python server.py" ;;
    aggregator)       start_one aggregator        mcp-aggregator/server "uv run python server.py" ;;
    chat-ui)          start_one chat-ui           chat-ui               "uv run python backend.py" ;;
    frontend)         start_one frontend          chat-ui/frontend      "npm run dev" ;;
    *)
        echo "Unknown service: $SERVICE"
        echo "Services: $SERVICES"
        exit 1
        ;;
esac
