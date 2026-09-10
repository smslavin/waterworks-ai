#!/usr/bin/env bash
# Stop all enterprise services started by start.sh.

cd "$(dirname "$0")"
source ../scripts/lib/supervise.sh

if [ ! -d .pids ] || [ -z "$(ls .pids/*.pid 2>/dev/null)" ]; then
    echo "No running enterprise services found (.pids/ is empty)."
    exit 0
fi

# start.pid is handled explicitly below, not by the glob loop — see
# ../stop.sh for why (same "start" sorts into the middle of the glob, races
# with start.sh's own EXIT trap" bug applies here too).
echo "Stopping enterprise services..."
for pidfile in .pids/*.pid; do
    name=$(basename "$pidfile" .pid)
    [[ "$name" == "start" ]] && continue
    supervise_stop "$pidfile" "$name"
done

if [[ -f .pids/start.pid ]]; then
    supervise_stop .pids/start.pid start
fi

echo "Done."
