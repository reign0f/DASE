#!/bin/bash
# dase-deploy-v2.sh — push circulant configs to all 149 nodes (run from Proxmox host, from anywhere)

DASE_DIR=/root/dase
CONFIG_DIR=$DASE_DIR/dase-configs
MANIFEST=$DASE_DIR/dase-manifest.csv

# Track successful deployments and collect IDs for any nodes that fail.
DEPLOYED=0
FAILED=""

# Read the CSV manifest one row at a time; the first row is its column header.
while IFS=, read -r ip ctid hostname node_id; do
  [ "$ctid" = "ctid" ] && continue   # skip header
  # Remove spaces and carriage returns, then match the generator's padded filenames.
  node_id=$(echo "$node_id" | tr -d ' \r')
  cfg=$(printf "%s/node_%03d.json" "$CONFIG_DIR" "$node_id")

  # Record a missing local config and move on to the next manifest entry.
  if [ ! -f "$cfg" ]; then
    echo "[$ctid] MISSING CONFIG: $cfg (node_id='$node_id')"
    FAILED="$FAILED $ctid"
    continue
  fi

  # Create the destination directory inside the container before pushing the file.
  pct exec $ctid -- mkdir -p /etc/dase || { FAILED="$FAILED $ctid(exec)"; continue; }

  # Copy the node config into place; on success, remove the old log and count it.
  if pct push $ctid "$cfg" /etc/dase/neighbors.json; then
    pct exec $ctid -- sh -c "rm -f /var/log/dase.log" 2>/dev/null
    DEPLOYED=$((DEPLOYED+1))
  else
    echo "[$ctid] PUSH FAILED — see error above"
    FAILED="$FAILED $ctid"
  fi
done < "$MANIFEST"

# Summarize completed pushes and list any container IDs that failed.
echo ""
echo "Deployed $DEPLOYED/149 configs.${FAILED:+ Failed:${FAILED}}"