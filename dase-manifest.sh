#!/bin/bash
# rebuild-manifest.sh — regenerate the complete 149-node manifest from scratch
M=/root/dase/dase-manifest.csv

# Start with a fresh manifest; the header is included in the final line count.
echo "ip,ctid,hostname,node_id" > $M

# Fixed endpoint entries use reserved node IDs at the ends of the range.
echo "192.168.200.106,106,implant,0" >> $M

# Legacy relay names map in order to node IDs 1 through 18.
LETTERS=(a b c d e f g h i j k l m n o p q r)
for i in $(seq 0 17); do
  ctid=$((108 + i))
  echo "192.168.200.$ctid,$ctid,node-${LETTERS[$i]},$((i + 1))" >> $M
done

# New relay node IDs are derived from the final octet: ctid - 107 gives 19..147.
for ctid in $(seq 126 254); do
  echo "192.168.200.$ctid,$ctid,dase-$ctid,$((ctid - 107))" >> $M
done
y
# Egress uses the final node ID, 148, completing the 0..148 range.
echo "192.168.200.107,107,egress,148" >> $M

# Check total CSV rows, distinct data-row IDs, and the minimum/maximum data-row IDs.
# The expected 150 lines include the header; 149 IDs should cover 0 through 148.
LINES=$(wc -l < $M)
IDS=$(tail -n +2 $M | cut -d, -f4 | sort -n | uniq | wc -l)
MIN=$(tail -n +2 $M | cut -d, -f4 | sort -n | head -1)
MAX=$(tail -n +2 $M | cut -d, -f4 | sort -n | tail -1)
echo "Lines: $LINES (expect 150) | Unique node_ids: $IDS (expect 149) | Range: $MIN..$MAX (expect 0..148)"