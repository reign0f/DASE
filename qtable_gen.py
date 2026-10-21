#!/usr/env python3
"""
Generate warm-start Q-tables for all 149 nodes in DASE swarm.
No external dependencies. Computes BFS distances from circulant topology.
"""
import json
import os
from collections import deque

N_NODES = 149
# Each node connects around the ring at these forward and backward offsets.
CHORDS = [1, 5, 15]
# Convert hop distance into a small negative routing score.
ALPHA = 0.01
# All generated tables route toward the egress node.
DEST_ID = 148
OUT_DIR = "/root/dase/qtables"


def get_neighbors(node_id):
    """Return list of 6 neighbors for a circulant ring."""
    neighbors = []
    # Wrap each positive and negative chord offset around the node-ID range.
    for delta in CHORDS:
        for sign in [1, -1]:
            neighbor = (node_id + sign * delta) % N_NODES
            neighbors.append(neighbor)
    return neighbors


def bfs_distance(start, end):
    """Compute shortest path distance using BFS."""
    if start == end:
        return 0
    visited = {start}
    queue = deque([(start, 0)])
    # Explore the graph in increasing hop count; the first match is shortest.
    while queue:
        current, dist = queue.popleft()
        for neighbor in get_neighbors(current):
            if neighbor == end:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return float('inf')  # unreachable


def gen_qtable(node_id, dest_id):
    """Build one node's destination table, scoring each available next hop."""
    neighbors = get_neighbors(node_id)
    q_entry = {}
    for nb in neighbors:
        # Score a move by the remaining distance from that neighbor to the destination.
        d = bfs_distance(nb, dest_id)
        q_entry[f"neighbor_{nb}"] = round(-ALPHA * d, 4)
    return {
        "node_id": node_id,
        "routing_mode": "qlearn",
        "epsilon": 0.3,
        "table": {f"dest_{dest_id}": q_entry}
    }


if __name__ == "__main__":
    # Create the output directory if it does not already exist.
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating Q-tables for {N_NODES} nodes...")

    written = 0
    # Generate a separate JSON routing table for every node ID.
    for nid in range(N_NODES):
        q = gen_qtable(nid, DEST_ID)
        path = os.path.join(OUT_DIR, f"node_{nid}.json")
        with open(path, "w") as fh:
            json.dump(q, fh, indent=2)
        written += 1

    print(f"Done. Wrote {written} tables to {OUT_DIR}")
    # Print part of one generated file as a quick output-format sanity check.
    print("Sample table (node 74):")
    with open(os.path.join(OUT_DIR, "node_74.json")) as fh:
        print(json.dumps(json.load(fh), indent=2)[:500])