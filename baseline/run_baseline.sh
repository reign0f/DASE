#!/bin/bash
# /opt/dase/run_baseline.sh
# Only reason this exists: ensure fleet is alive before Python runs
cd /opt/dase

# Quick health check — 149 containers need to be up
ACTUAL=$(pct list | grep -c "started")
EXPECTED=149

if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "WARNING: Only $ACTUAL/$EXPECTED containers running!"
    echo "Run ./fleet-restore.sh first?"
    read -p "Continue anyway? (y/N) " yn
    [[ "$yn" != "y" ]] && exit 1
fi

echo "Running baseline with $ACTUAL active nodes..."
python3 baseline_runner.py "$@"