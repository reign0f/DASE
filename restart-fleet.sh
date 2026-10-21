#!/bin/bash

echo "Starting all 149 containers (waves of 30)..."
for ctid in $(seq 106 135); do pct start $ctid; sleep 1; done
for ctid in $(seq 136 165); do pct start $ctid; sleep 1; done
for ctid in $(seq 166 195); do pct start $ctid; sleep 1; done
for ctid in $(seq 196 225); do pct start $ctid; sleep 1; done
for ctid in $(seq 226 254); do pct start $ctid; sleep 1; done

echo "Waiting 30s for all containers to settle..."
sleep 30

echo "Restarting dased service on all nodes..."
for ctid in $(tail -n +2 /root/dase/dase-manifest.csv | cut -d, -f2); do
  pct exec $ctid -- rc-service dased restart
done

echo "Waiting 8s for daemons to settle..."
sleep 8

# Verification
OK=0; DEAD=""
for ctid in $(tail -n +2 /root/dase/dase-manifest.csv | cut -d, -f2); do
  if pct exec $ctid -- rc-service dased status > /dev/null 2>&1; then
    OK=$((OK+1))
  else
    DEAD="$DEAD $ctid"
  fi
done
echo "Daemons running: $OK/149${DEAD:+  Dead:${DEAD}}"