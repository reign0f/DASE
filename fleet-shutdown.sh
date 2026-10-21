#!/bin/bash
# /root/dase/fleet-shutdown.sh

echo "Stopping dased service on all nodes..."
for ctid in $(tail -n +2 /root/dase/dase-manifest.csv | cut -d, -f2); do
  pct exec $ctid -- rc-service dased stop
done

echo "Waiting 5s for daemons to terminate..."
sleep 5

echo "Stopping all 149 containers (waves of 30)..."
for ctid in $(seq 106 135); do pct stop $ctid; done
for ctid in $(seq 136 165); do pct stop $ctid; done
for ctid in $(seq 166 195); do pct stop $ctid; done
for ctid in $(seq 196 225); do pct stop $ctid; done
for ctid in $(seq 226 254); do pct stop $ctid; done

echo "Waiting 30s for all containers to power off..."
sleep 30

# Verification
RUNNING=0
for ctid in $(tail -n +2 /root/dase/dase-manifest.csv | cut -d, -f2); do
  if pct status $ctid | grep -q "running"; then
    RUNNING=$((RUNNING+1))
  fi
done

echo "Containers running: $RUNNING/149"
if [ $RUNNING -gt 0 ]; then
  echo "WARNING: Some containers may still be running. Check manually."
else
  echo "All containers powered off safely."
fi