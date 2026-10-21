#!/usr/bin/env python3
"""DASE Circulant Generator v2 — k-chorded ring with routing tables and IP map"""
import json
import sys
from pathlib import Path
from collections import deque


def ctid_for(node_id):
    """Map a logical node ID to its Proxmox CTID and final IP octet."""
    # Implant and egress use reserved IDs; relay IDs follow the node_id + 107 rule.
    if node_id == 0:
        return 106
    elif node_id == 148:
        return 107
    else:
        return node_id + 107


def bfs_dist(adjacency, source):
    # Breadth-first search computes the minimum hop count from source to each node.
    dist = {source: 0}
    q = deque([source])
    while q:
        u = q.popleft()
        for v in adjacency[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)  
    return dist


def gen_circulant(n, chords):
    # Build an undirected ring by connecting each node at positive and negative
    # chord offsets, wrapping indices at the ends of the node-ID range.
    adjacency = {}
    # Verify every generated link is reciprocal before using the graph.
    for i in range(n):
        adjacency[i] = sorted({(i + s) % n for s in [c for c in chords] + [-c for c in chords]})

    for i in range(n):
        for j in adjacency[i]:
            assert i in adjacency[j], f"Asymmetry: {i}->{j} but {j} missing {i}"

    # Check connectivity from the egress and precompute one shortest-path next hop.
    dist_from_egress = bfs_dist(adjacency, n - 1)
    assert len(dist_from_egress) == n, f"Graph disconnected: {n - len(dist_from_egress)} nodes unreachable"

    next_hop_egress = {}
    for u in range(n):
        if u == n - 1:
            continue
        next_hop_egress[u] = min(adjacency[u], key=lambda v: dist_from_egress[v])

    # Resolve each peer's IP from the same node-ID-to-CTID mapping.
    peer_ips = {nid: f"192.168.200.{ctid_for(nid)}" for nid in range(n)}

    # Assemble the configuration object consumed by each DASE node daemon.
    configs = {}
    for i in range(n):
        cfg = {
            "node_id": i,
            "neighbors": adjacency[i],
            "role": "implant" if i == 74 else ("egress" if i == n - 1 else "relay"),  
            "port": 4443,
            "node_count": n,
            "egress_id": n - 1,
            "next_hop_egress": next_hop_egress.get(i),
            "peer_ips": peer_ips,
        }
        configs[i] = cfg
    return configs

    # NOTE: This CLI block is nested in gen_circulant() after its return, so it
    # is unreachable as written and does not act as the module's script entry point.
    if __name__ == "__main__":
        # Require a node count and comma-separated chord distances on the command line.
        if len(sys.argv) != 3:
            sys.exit(f"Usage: {sys.argv[0]} <n_nodes> <chord1,chord2,...>\nExample: {sys.argv[0]} 149 1,5,15")
        n = int(sys.argv[1])
        chords = [int(c) for c in sys.argv[2].split(',')]

        configs = gen_circulant(n, chords)
        # Create the output directory and write one zero-padded JSON file per node.
        out_dir = Path("/root/dase/dase-configs")
        out_dir.mkdir(parents=True, exist_ok=True)
        for nid, cfg in configs.items():
            with open(out_dir / f"node_{nid:03d}.json", "w") as f:
                json.dump(cfg, f, indent=2)
        print(f"Total: {n} configs written to {out_dir}")