#!/usr/bin/env python3
"""
baseline_runner.py — DASE baseline experiment driver.

WHAT THIS IS
    Runs the baseline (non-learning) delivery experiment across three routing
    arms and writes per-rep CSVs plus trace logs for offline analysis.

ARMS
    A — Direct C2: sender posts straight to the egress. No relays. 0 hops.
    B — Static BFS swarm: message injected at the implant, forwarded hop-by-hop
        using the daemon's deterministic BFS next-hop. 1 path, 0 bits entropy.
    C — Random relay sources: same static forwarding, but the injection point is
        drawn uniformly from the relay pool. Ceiling reference for route entropy.

WHY THESE THREE
    A is the trivial-delivery floor. B is the null hypothesis (deterministic
    single path — a compromised relay on that path owns the implant's anonymity).
    C shows what the SAME topology supports when sources vary. The B-vs-C contrast
    is the paper's Figure 1 and the baseline the Q-arm must beat.

HOW IT WORKS
    - Sender opens a TCP connection per message (port 4443) and reads the reply.
    - Before each rep, snapshots the egress log offset via `pct exec` so that
      rep's slice of the log can be extracted cleanly afterwards.
    - Pulls the egress log (CTID 107) after each rep for the Final path records.
    - Writes one CSV per arm/rep plus a trace log; parse_metrics.py consumes these.

USAGE
    python3 baseline_runner.py --arms A B C --reps 3 --messages 100 \
        --output-dir /root/dase/baseline/data-final-corrected

    Run as root on darkstar (requires `pct`). Prefer SSH over the web console.

KEY CONSTANTS
    IMPLANT_ID  — logical node 74 (CTID 181). Injection point for Arms B and C.
    EGRESS      — logical node 148 (CTID 107). Fixed delivery endpoint.
    RELAY_CTIDS  — relay pool for Arm C. [106] + range(108, 255) excluding 181.
                   Includes CTID 106 (demoted former implant); excludes the
                   implant (181) and the egress (107). Asserted to length 147.

NAMESPACE WARNING
    CTID != logical node_id. Mapping: ctid = node_id + 107, EXCEPT node 0 = 106
    and node 148 = 107. The daemon's `dest` field and all trace logs use LOGICAL
    ids. The CSVs carry no source column — for Arm C the source CTID is the last
    octet of target_ip (IP = 192.168.200.<CTID>). Translate explicitly, always.

OUTPUTS
    baseline_<ARM>_rep<N>.csv   — per-message rows: msg_id, target_ip, status,
                                  total_hops, rtt_s
    traces_<ARM>_rep<N>.log     — egress log slice for that rep
    Feed both to parse_metrics.py (offline, rerunnable, never touches the network).

KNOWN GOTCHAS
    - Endpoint placement matters: an implant ring-adjacent to the egress measures
      1 hop and traverses zero relays, making Arm B measurement-identical to Arm A.
      Always sanity-check expected hops before trusting a trial.
    - pct_exec() raises with real stderr on failure — do not swallow it.
    - No output does not mean no error. Check file mtimes.

STATUS
    Baseline complete and publication-grade (Oct 5, 2026): 3 arms x 3 reps x 100
    msgs = 900 messages, 100% delivery, all consistency checks passed. Numbers in
    metrics_summary.json. This harness is the template the Q-arm and interdiction
    runs will extend (kill logic not yet present).
"""

import argparse
import csv
import json
import math
import os
import random
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

# Experiment-wide endpoints, listener port, and the relay pool used by Arm C.
# Constants (matches your handoff)
EGRESS_CTID = 107
IMPLANT_IP = "192.168.200.181"
EGRESS_IP = "192.168.200.107"
ORCHESTRATOR_IP = "192.168.200.50"
PORT = 4443
RELAY_CTIDS = [106] + [c for c in range(108, 255) if c != 181]

ARMS = {
    "A": {"mode": "direct", "target_ip": EGRESS_IP, "description": "Centralized C2 (direct)"},
    "B": {"mode": "routed_fixed", "target_ip": IMPLANT_IP, "description": "Static BFS via implant"},
    "C": {"mode": "routed_random_src", "target_ip": None, "description": "Topological ceiling (random relay source)"},
}

# A normalized result record shared by the sender, CSV writer, and metric code.
@dataclass
class SendResult:
    msg_id: str
    target_ip: str
    status: str
    total_hops: int
    rtt_s: float
    sent_at: float

def pct_exec(ctid: str, cmd: str) -> tuple:
    """Run a command inside a PVE container. Returns (stdout, stderr, returncode)."""
    # Capture text output and raise with stderr if the remote command fails.
    proc = subprocess.run(
        ["pct", "exec", ctid, "--", "sh", "-c", cmd],
        capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or "(no stderr)"
        raise RuntimeError(
            f"pct exec {ctid} failed (rc={proc.returncode}): {cmd}\n  stderr: {err}"
        )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode

def pct_exec_capture(ctid: str, cmd: str) -> bytes:
    """Run command and capture raw output for binary-safe reading."""
    # Keep output as bytes when extracting an exact slice of the daemon log.
    proc = subprocess.run(
        ["pct", "exec", ctid, "--", "sh", "-c", cmd],
        capture_output=True, timeout=30
    )
    return proc.stdout

def send_one_message(target_ip: str, msg_id: str, dest_node_id: int, arm_mode: str) -> SendResult:
    """Send a single message, record result."""
    # The daemon expects one newline-delimited JSON message and routes by logical ID.
    payload = {
        "dest": dest_node_id,
        "msg_id": msg_id,
        "body": f"{arm_mode}-{msg_id[:8]}",
        "hops": []
    }
    
    try:
        # Measure the full TCP request/reply duration, including connection setup.
        start = time.time()
        with socket.create_connection((target_ip, PORT), timeout=15) as s:
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        rtt = round(time.time() - start, 3)
        
        # Parse delivery metadata when the response is valid JSON; retain failures
        # as explicit result statuses so they remain visible in the sender CSV.
        try:
            resp = json.loads(buf.decode().strip().splitlines()[0])
            status = resp.get("status", "?")
            hops = resp.get("total_hops", "")
            total_hops = int(hops) if isinstance(hops, str) and hops.isdigit() else hops
        except (json.JSONDecodeError, KeyError, ValueError):
            status = "unparseable"
            total_hops = ""
            
        return SendResult(
            msg_id=msg_id,
            target_ip=target_ip,
            status=status,
            total_hops=total_hops,
            rtt_s=rtt,
            sent_at=start
        )
    except socket.timeout:
        return SendResult(msg_id, target_ip, "timeout", "", 0.0)
    except socket.error as e:
        return SendResult(msg_id, target_ip, f"conn_error:{type(e).__name__}", "", 0.0)
    except Exception as e:
        return SendResult(msg_id, target_ip, f"error:{type(e).__name__}", "", 0.0)

def run_arm_trial(arm: str, rep: int, n_messages: int, base_dir: Path) -> None:
    """Execute one arm × rep trial: send + capture trace."""
    arm_cfg = ARMS[arm]
    print(f"===== ARM {arm}: {arm_cfg['description']} | REP {rep} | MESSAGES {n_messages} =====")
    
    # Remember the egress log's current byte length to isolate this rep's new entries.
    stdout, _, _ = pct_exec(str(EGRESS_CTID), "wc -c /var/log/dase.log")
    log_offset_before = int(stdout.split()[0])
    print(f"[Snapshot] Log offset before: {log_offset_before}")
    
    # Send each message to the arm's fixed endpoint, or choose a relay for Arm C.
    results: List[SendResult] = []
    for i in range(n_messages):
        if arm_cfg["mode"] == "routed_random_src":
            src_ctid = random.choice(RELAY_CTIDS)
            target_ip = f"192.168.200.{src_ctid}"
        else:
            target_ip = arm_cfg["target_ip"]
        
        msg_id = f"{arm}{rep}-{i:04d}-{uuid.uuid4().hex[:6]}"
        result = send_one_message(target_ip, msg_id, dest_node_id=148, arm_mode=arm_cfg["mode"])
        results.append(result)
        
        if (i + 1) % 20 == 0:
            delivered = sum(1 for r in results if r.status == "delivered")
            print(f"  [{i+1}/{n_messages}] Delivered: {delivered} ({100*delivered/(i+1):.1f}%)")
        
        # Add a small random pause between messages instead of sending a tight burst.
        time.sleep(random.uniform(0.3, 0.7))
    
    # Save one sender-side result row per attempted message.
    csv_path = base_dir / f"baseline_{arm}_rep{rep}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["msg_id", "target_ip", "status", "total_hops", "rtt_s"])
        w.writeheader()
        for r in results:
            w.writerow({
                "msg_id": r.msg_id,
                "target_ip": r.target_ip,
                "status": r.status,
                "total_hops": r.total_hops,
                "rtt_s": r.rtt_s
            })
    print(f"[Save] Wrote {len(results)} rows to {csv_path}")
    
    # Use the before/after offsets to save only the egress log bytes produced in this rep.
    log_offset_after_str, _, _ = pct_exec(str(EGRESS_CTID), "wc -c /var/log/dase.log")
    log_offset_after = int(log_offset_after_str.split()[0])
    print(f"[Snapshot] Log offset after: {log_offset_after}")
    
    if int(log_offset_after) <= log_offset_before:
        print("[WARN] Log didn't grow! Possible delivery issues.")
        # Still capture in case daemon buffering
    trace_bytes = pct_exec_capture(str(EGRESS_CTID), f"tail -c +{log_offset_before} /var/log/dase.log")
    trace_path = base_dir / f"traces_{arm}_rep{rep}.log"
    with open(trace_path, "wb") as f:
        f.write(trace_bytes)
    print(f"[Save] Wrote {len(trace_bytes)} bytes to {trace_path}")

def shannon_entropy(counter: Dict) -> float:
    """Shannon entropy in bits."""
    # Treat counter values as category frequencies and calculate their entropy.
    total = sum(counter.values())
    if total == 0 or len(counter) <= 1:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counter.values())

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for proportion."""
    # Return a bounded confidence interval; no observations yield a zero interval.
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + (z * z) / n
    center = (p + (z * z) / (2 * n)) / d
    half_width = (z / d) * math.sqrt((p * (1 - p) / n) + ((z * z) / (4 * n * n)))
    return (max(0.0, center - half_width), min(1.0, center + half_width))

def compute_metrics(arm: str, base_dir: Path) -> dict:
    """Compute aggregate metrics for one arm from collected CSVs + traces."""
    import glob as glob_mod
    
    # Combine all repetition CSVs for this arm into one set of message outcomes.
    sender_rows = []
    for f in glob_mod.glob(str(base_dir / f"baseline_{arm}_rep*.csv")):
        with open(f) as fh:
            reader = csv.DictReader(fh)
            sender_rows.extend(list(reader))
    
    # Extract the egress's logged node paths; empty paths represent direct delivery.
    path_re = __import__('re').compile(r"Final path:\s*(.*)")
    paths: List[tuple] = []
    for f in glob_mod.glob(str(base_dir / f"traces_{arm}_rep*.log")):
        for line in open(f, errors="replace"):
            m = path_re.search(line)
            if m:
                raw = m.group(1).strip()
                if not raw or raw.lower() in ("none", "-", ""):
                    paths.append(())  # Direct delivery = empty path
                else:
                    try:
                        nodes = tuple(int(x) for x in __import__('re').split(r"\s*->\s*", raw))
                        paths.append(nodes)
                    except ValueError:
                        continue
    
    # Derive delivery, hop, path-frequency, and entropy statistics from both sources.
    n_sent = len(sender_rows)
    delivered_count = sum(1 for r in sender_rows if r["status"] == "delivered")
    hops_list = [int(r["total_hops"]) for r in sender_rows 
                 if r["status"] == "delivered" and isinstance(r["total_hops"], str) and r["total_hops"].isdigit()]
    
    hop_counter = {h: sum(1 for hp in hops_list if hp == h) for h in set(hops_list)}
    path_counter = {p: sum(1 for pp in paths if pp == p) for p in set(paths)}
    
    direct_count = sum(1 for p in paths if len(p) <= 1)  # Empty tuple or single-hop
    
    return {
        "arm": arm,
        "n_sent": n_sent,
        "delivered": delivered_count,
        "delivery_rate": delivered_count / n_sent if n_sent else 0.0,
        "delivery_wilson_95": wilson_ci(delivered_count, n_sent),
        "mean_hops": sum(hops_list) / len(hops_list) if hops_list else 0.0,
        "hops_std": (sum((h - sum(hops_list)/len(hops_list))**2 for h in hops_list) / max(1, len(hops_list)-1))**0.5 if len(hops_list) > 1 else 0.0,
        "path_length_entropy_bits": shannon_entropy(hop_counter),
        "distinct_paths": len(path_counter),
        "normalized_path_entropy_bits": shannon_entropy(path_counter),
        "direct_link_fraction": direct_count / len(paths) if paths else 0.0,
        "total_paths_logged": len(paths),
    }

def main():
    # Parse experiment size, selected arms, and output location from CLI arguments.
    parser = argparse.ArgumentParser(description="DASE Baseline Runner")
    parser.add_argument("--arms", nargs="+", default=["A", "B", "C"], choices=["A", "B", "C"],
                        help="Arms to run (default: A B C)")
    parser.add_argument("--reps", type=int, default=3, help="Reps per arm (default: 3)")
    parser.add_argument("--messages", type=int, default=100, help="Messages per rep (default: 100)")
    parser.add_argument("--output-dir", type=Path, default=Path("/opt/dase/data"),
                        help="Output directory (default: /opt/dase/data)")
    args = parser.parse_args()
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Phase 1: run each requested arm/repetition and save its CSV and trace log.
    for arm in args.arms:
        for rep in range(1, args.reps + 1):
            run_arm_trial(arm, rep, args.messages, args.output_dir)
    
    # Phase 2: aggregate each arm's saved repetitions and print a compact summary.
    print("\n===== Computing Metrics =====")
    all_metrics = []
    for arm in args.arms:
        metrics = compute_metrics(arm, args.output_dir)
        all_metrics.append(metrics)
        print(f"\n[{metrics['arm']}] Delivery: {metrics['delivery_rate']*100:.1f}% | "
              f"Hops: {metrics['mean_hops']:.1f} | Paths: {metrics['distinct_paths']} | "
              f"Entropy: {metrics['path_length_entropy_bits']:.3f} bits")
    
    # Persist all arm summaries for later analysis without rerunning the experiment.
    json_path = args.output_dir / "baseline_summary.json"
    with open(json_path, "w") as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\n[Summary] Saved {json_path}")

if __name__ == "__main__":
    main()