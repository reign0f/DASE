#!/bin/bash

# Stop on command errors, unset variables, or failures within a pipeline.
set -euo pipefail

# Run from darkstar as root
# Directory containing the per-node JSON Q-tables generated earlier.
SRC_DIR=/root/dase/qtables
NUM_NODES=149

# Deploy one table for each logical node ID from 0 through 148.
for node_id in $(seq 0 $((NUM_NODES - 1))); do
    # Map logical node IDs to Proxmox container IDs. The implant and egress
    # use reserved CTIDs; other nodes follow the node_id + 107 mapping.
    if [[ $node_id -eq 0 ]]; then
        ctid=106
    elif [[ $node_id -eq 148 ]]; then
        ctid=107
    else
        ctid=$((node_id + 107))
    fi

    SRC_FILE="${SRC_DIR}/node_${node_id}.json"
    
    # Fail before pushing if this node's generated table is missing.
    if [[ ! -f "$SRC_FILE" ]]; then
        echo "ERROR: Missing Q-table for node ${node_id} (CTID ${ctid})" >&2
        exit 1
    fi
    
    # Copy the table into this container at its node-specific configuration path.
    pct push "${ctid}" "${SRC_FILE}" "/etc/dase/qtable_node_${node_id}.json" || {
        echo "FAIL: Could not push to node ${node_id}" >&2
        exit 1
    }
done

echo "All Q-tables deployed to /etc/dase/ on ${NUM_NODES} nodes"