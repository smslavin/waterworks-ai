#!/usr/bin/env bash
# Stop all waterworks-ai services started by start.sh.

cd "$(dirname "$0")"
source scripts/lib/supervise.sh

if [ ! -d .pids ] || [ -z "$(ls .pids/*.pid 2>/dev/null)" ]; then
    echo "No running services found (.pids/ is empty)."
    exit 0
fi

# start.pid (start.sh's own pid) is handled explicitly below, not by the
# glob loop: "start" sorts alphabetically between "simulator" and
# "topology-builder", so a naive `for pidfile in .pids/*.pid` kills start.sh
# mid-loop. start.sh's own EXIT trap then concurrently rm -f's the remaining
# pidfiles and kills the remaining PIDs out from under this loop, and later
# iterations here report "already stopped" for services this loop never
# actually touched. Stopping it last, after every real service is already
# individually stopped, means start.sh's cleanup trap (whether it fires from
# our kill below or from `wait` returning) finds only already-dead PIDs and
# already-removed pidfiles — a harmless no-op instead of a race.
echo "Stopping services..."
for pidfile in .pids/*.pid; do
    name=$(basename "$pidfile" .pid)
    [[ "$name" == "start" ]] && continue
    supervise_stop "$pidfile" "$name"
done

if [[ -f .pids/start.pid ]]; then
    supervise_stop .pids/start.pid start
fi

echo "Done."
