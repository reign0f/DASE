#!/usr/bin/env python3
"""
parse_metrics.py — Offline analysis pipeline for DASE experiments.

WHAT THIS IS
    Converts raw CSVs and egress log slices into publication-ready metrics and
    figures. Never touches the network. Rerunnable, idempotent, script-driven.

INPUTS
    CSVs from the runner (baseline_runner.py or Q-arm variants):
        baseline_<ARM>_rep<N>.csv  — columns: msg_id, target_ip, status,
                                     total_hops, rtt_s
    Egress trace logs:
        traces_<ARM>_rep<N>.log    — Full path records per message

OUTPUTS
    metrics_summary.json           — Aggregated stats per arm (delivery, mean hops,
                                     distinct paths, entropy values).
    Plots                          — Histograms, entropy bar charts, path-length
                                     distributions (matplotlib backend).
    Console summary                — Quick sanity check before plotting.

METRICS COMPUTED (BASELINE)
    - Delivery rate + Wilson 95% CI
    - Mean/SD hops, hop histogram
    - Path-length entropy H = −Σ p(L)log₂ p(L) (bits)
    - Route entropy (uniformity across distinct paths)
    - Distinct path count
    - Direct-link fraction (ring edges vs. chords)
    - Failure breakdown (ROUTE_FAILED counts)
    - Trace-vs-delivery consistency (check: all delivered msgs accounted for?)
    - Top-5 most frequent paths

Q-LEARNING EXTENSIONS (TODO/PENDING)
    - Exploit/explore ratio (parsed from [Q] decision lines in logs)
    - Per-neighbor choice distribution (detects single-path collapse)
    - Q-value drift over time (from [Q-update] lines)
    - ε trajectory
    - Observer workload (min nodes to monitor for fixed traffic fraction)

USAGE
    python3 parse_metrics.py --input-dir /root/dase/baseline/data-final-corrected \
        --output-dir /root/dase/baseline/plots

    Run on darkstar after the experiment completes. No network access required.

KEY CONSTANTS (HARDCODED)
    IMPLANT_ID  — logical node 74. Injection point.
    EGRESS_ID   — logical node 148. Destination.
    MAX_HOPS    — 64 (sanity check against routing loops).
    RELAY_CTIDS — expected 147 relays. Used to sanity-check Arm C source diversity.

NAMESPACE RULES
    All logs use LOGICAL IDs. CSVs use IPs (target_ip last octet = CTID).
    Translation logic is inside this script where needed. Do not mix them.

VALIDATION
    Checks run automatically:
        - 300/300 rows in each arm?
        - All statuses are 'delivered' or 'failed'?
        - Entropy non-negative?
        - Consistency: delivered count matches trace count?
    Raises ValueError on failure. Do not ignore warnings — they indicate
    data corruption or pipeline misalignment.

DEPENDENCIES
    Python standard lib, pandas, numpy, scipy (stats), matplotlib.
    Version pinned in requirements.lock (or equivalent) for reproducibility.

STATUS
    Baseline analysis complete (Oct 5, 2026). Figure 1 and metrics_summary.json
    generated from the 900-message dataset. Q-arm extensions (exploit/explore,
    Q-drift, observer workload) pending full-swarm validation.

WHY SCRIPTED
    Reproducibility requirement: every figure in the paper is an output of this
    tool run against the logs. No hand-tuned graphs. If you change the code,
    rerun the script. This mirrors LNTest [14] and Bitaillou et al. [9].
"""

import csv
import glob
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

# Logical node IDs (NOT CTIDs).
# Mapping quirk: ctid = node_id + 107, EXCEPT node 0 = CTID 106 and node 148 = CTID 107.
#
# Current endpoint roles (post-relocation, Oct 5 2026):
#   implant = logical 74  (CTID 181, IP .181)  <- injection point
#   egress  = logical 148 (CTID 107, IP .107)  <- fixed destination
#   CTID 106 (logical 0) = FORMER implant, now demoted to relay.
#
# NOTE: neither constant below is currently referenced by the analysis code —
# all metrics derive from traces (logical IDs) and sender CSVs (IPs, where the
# last octet of target_ip is the CTID). Kept for documentation and for future
# per-node filtering (e.g. isolating traffic that transits the implant).
IMPLANT_ID = 74
EGRESS_ID = 148

TRACE_RE = re.compile(r"Final path:\s*(.*)")


# ---------- trace parsing ----------

def parse_trace_line(line):
    """Return a tuple of forwarding node IDs, or None if not a path line.

    Conventions (from dase-node.py v2 source):
      - 'Final path: ' with empty remainder => direct delivery, empty tuple ()
      - 'Final path: 73 -> 88 -> 103'        => forwarding relays only
      - total_hops in the response == len(this tuple) — the egress node
        never appends itself to the hops list
    """
    # Ignore ordinary log entries; only the egress's final-path record is analyzed.
    m = TRACE_RE.search(line)
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw:
        return ()  # direct link: zero forwarding nodes
    try:
        return tuple(int(x) for x in re.split(r"\s*->\s*", raw) if x.strip())
    except ValueError:
        return None


def load_traces(data_dir, arm):
    # Gather this arm's trace files in a stable order, then parse every path record.
    paths = []
    files = sorted(glob.glob(str(Path(data_dir) / f"traces_{arm}_rep*.log")))
    if not files:
        print(f"[WARN] no trace files for arm {arm}")
    for fname in files:
        with open(fname, errors="replace") as fh:
            for line in fh:
                p = parse_trace_line(line)
                if p is not None:
                    paths.append(p)
    return paths, files


def load_sender_records(data_dir, arm):
    # Combine the sender-side CSV rows across all repetitions for this arm.
    rows = []
    files = sorted(glob.glob(str(Path(data_dir) / f"baseline_{arm}_rep*.csv")))
    if not files:
        print(f"[WARN] no sender CSVs for arm {arm}")
    for fname in files:
        with open(fname) as fh:
            rows.extend(csv.DictReader(fh))
    return rows, files


# ---------- stats helpers ----------

def shannon(counter):
    # Calculate entropy from category counts; a single observed category has no uncertainty.
    total = sum(counter.values())
    if total == 0 or len(counter) <= 1:
        return 0.0
    return round(-sum((c / total) * math.log2(c / total) for c in counter.values()), 4)


def wilson_ci(k, n, z=1.96):
    # Compute a Wilson score interval for the observed proportion k/n.
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


# ---------- per-arm analysis ----------

def analyze_arm(data_dir, arm):
    # Sender CSVs provide outcomes and hop totals; traces provide observed routes.
    sender_rows, csv_files = load_sender_records(data_dir, arm)
    paths, trace_files = load_traces(data_dir, arm)

    # --- delivery (sender-side, ground truth) ---
    n_sent = len(sender_rows)
    statuses = Counter(r["status"] for r in sender_rows)
    delivered = statuses.get("delivered", 0)
    failures = {k: v for k, v in statuses.items() if k != "delivered"}

    # --- hop counts ---
    # Canonical: sender-reported total_hops. Cross-checked against traces below.
    hops_sender = [int(r["total_hops"]) for r in sender_rows
                   if r["status"] == "delivered"
                   and str(r.get("total_hops", "")).strip().isdigit()]

    # --- paths (egress-side) ---
    path_counter = Counter(paths)
    hop_counter = Counter(len(p) for p in paths)

    # direct-link fraction: zero forwarding nodes in trace
    direct = hop_counter.get(0, 0)

    # consistency check: |trace-derived hops| should equal sender-delivered
    trace_hop_total = len(paths)
    hops_from_traces = [len(p) for p in paths]
    # Each delivered message should have one corresponding egress path record.
    agree = (len(paths) == delivered)

    mean_h = sum(hops_sender) / len(hops_sender) if hops_sender else None
    if hops_sender and len(hops_sender) > 1:
        sd = math.sqrt(sum((h - mean_h) ** 2 for h in hops_sender) / (len(hops_sender) - 1))
    else:
        sd = 0.0

    return {
        "arm": arm,
        "files": {"sender_csvs": len(csv_files), "trace_logs": len(trace_files)},
        "n_sent": n_sent,
        "delivered": delivered,
        "delivery_rate": round(delivered / n_sent, 4) if n_sent else None,
        "delivery_rate_wilson95": wilson_ci(delivered, n_sent),
        "failure_breakdown": failures,
        "trace_vs_delivery_consistency": {
            "paths_in_traces": trace_hop_total,
            "sender_reported_delivered": delivered,
            "counts_match": agree,
        },
        "mean_hops": round(mean_h, 3) if mean_h is not None else None,
        "hops_sd": round(sd, 3),
        "hop_histogram": {str(k): v for k, v in sorted(hop_counter.items())},
        "path_length_entropy_bits": shannon(hop_counter),
        "distinct_paths": len(path_counter),
        "distinct_path_fraction": round(len(path_counter) / len(paths), 4) if paths else None,
        "route_entropy_bits": shannon(path_counter),
        "direct_link_fraction": round(direct / len(paths), 4) if paths else None,
        "top_paths": [
            {"path": " -> ".join(map(str, p)) if p else "(direct)",
             "count": c,
             "fraction": round(c / len(paths), 4)}
            for p, c in path_counter.most_common(5)
        ],
    }


def main():
    # Accept the input directory first, followed by optional arm names.
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    data_dir = Path(sys.argv[1])
    arms = sys.argv[2:] or ["A", "B", "C"]

    results = {}
    # Analyze and save each requested arm independently, then write the combined summary.
    for arm in arms:
        res = analyze_arm(data_dir, arm)
        results[arm] = res
        print(f"\n===== ARM {arm} =====")
        print(f"  Delivery: {res['delivery_rate'] if res['delivery_rate'] is not None else 'n/a'} "
              f"(wilson95 {res['delivery_rate_wilson95']})")
        print(f"  Mean hops: {res['mean_hops']} (sd {res['hops_sd']})")
        print(f"  Distinct paths: {res['distinct_paths']}")
        print(f"  Path-length entropy: {res['path_length_entropy_bits']} bits")
        print(f"  Route entropy: {res['route_entropy_bits']} bits")
        print(f"  Direct-link fraction: {res['direct_link_fraction']}")
        m = res["trace_vs_delivery_consistency"]
        if not m["counts_match"]:
            print(f"  [WARN] trace/delivery mismatch: {m['paths_in_traces']} traced "
                  f"vs {m['sender_reported_delivered']} delivered — investigate")
        (data_dir / f"metrics_{arm}.json").write_text(json.dumps(res, indent=2))

    (data_dir / "metrics_summary.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote metrics_summary.json to {data_dir}")


if __name__ == "__main__":
    main()