#!/bin/bash
# dase-scaleout.sh — create DASE fleet .126-.254 (129 new nodes)

GOLDEN_CTID=108
STORAGE=local

# Stop the template container before cloning it; pause briefly for shutdown to settle.
echo "Stopping golden container 108 for cloning..."
pct stop $GOLDEN_CTID
sleep 2

# Recreate the output manifest with a header, then add one row per successful clone.
MANIFEST=~/dase-manifest.csv
echo "ip,ctid,hostname" > $MANIFEST

# Track whether cloning failed so later automation can detect an incomplete scale-out.
FAILURES=0
# Use each final IP octet as the new container ID, producing IDs 126 through 254.
for octet in $(seq 126 254); do
  # Clone from the stopped template and set the clone's hostname.
  if pct clone $GOLDEN_CTID $octet --storage $STORAGE --hostname dase-$octet; then
    # Apply resource and network settings, then record the node in the manifest.
    pct set $octet --memory 192 --cores 1 --onboot 0 \
                --net0 name=eth0,bridge=vmbr0,ip=192.168.200.$octet/24
    echo "192.168.200.$octet,$octet,dase-$octet" >> $MANIFEST
  else
    # Stop at the first clone failure rather than continuing with a partial fleet.
    echo "FAILED on $octet — aborting"
    FAILURES=1
    break
  fi
done