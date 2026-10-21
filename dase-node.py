#!/usr/bin/env python3
"""DASE Node Daemon v2 — k-chorded topology, destination-addressed routing.
Q-learning variant: ε-greedy Q-routing with per-hop discounted credit assignment."""
import json
import logging
import os
import random
import socket
import sys
import threading
from datetime import datetime
from socketserver import ThreadingTCPServer, BaseRequestHandler

# Local configuration, logs, and persistent data paths for the node process.
CONFIG_FILE = "/etc/dase/neighbors.json"
LOG_FILE = "/var/log/dase.log"
DATA_DIR = "/var/lib/dase"
MAX_HOPS = 64

# Q-routing tuning: update size, exploration schedule, reward scale, and save cadence.
ALPHA = 0.1        # learning rate
EPS_DECAY = 0.995  # per-decision decay
EPS_FLOOR = 0.05
STEP_PENALTY = 0.01
FLUSH_EVERY = 50

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("dase")

class RouteError(Exception):
    """Raised when a message cannot be routed to its destination."""
    pass

def read_line(sock):
    """Read one newline-delimited request, or return the available bytes on close."""
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.split(b"\n")[0]

class DASENode:
    def __init__(self):
        # Populated from CONFIG_FILE before the TCP server starts.
        self.node_id = None
        self.role = None
        self.neighbors = []
        self.peer_ips = {}
        self.next_hop_egress = None
        self.node_count = None
        self.egress_id = None
        self.port = 4443

        # Q-routing state; the node-specific table can override these defaults.
        self.qtable = {}
        self.routing_mode = "static"
        self.epsilon = 0.3
        self.qlock = threading.Lock()
        self._updates_since_flush = 0

    def load_config(self):
        # Load this node's identity, neighbors, destination, and network addresses.
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        self.node_id = cfg["node_id"]
        self.role = cfg["role"]
        self.neighbors = cfg["neighbors"]
        self.port = cfg.get("port", 4443)
        self.node_count = cfg.get("node_count")
        self.egress_id = cfg.get("egress_id")
        self.next_hop_egress = cfg.get("next_hop_egress")
        self.peer_ips = {int(k): v for k, v in cfg.get("peer_ips", {}).items()}

        # Reject incomplete topology data before accepting any traffic.
        if not self.neighbors:
            raise ValueError("empty neighbors list")
        for nb in self.neighbors:
            if nb not in self.peer_ips:
                raise ValueError(f"neighbor {nb} missing from peer_ips")

        # Node ID determines which per-node Q-table file should be loaded.
        qpath = f"/etc/dase/qtable_node_{self.node_id}.json"
        try:
            with open(qpath) as fh:
                qdata = json.load(fh)
            self.routing_mode = qdata.get("routing_mode", "static")
            self.epsilon = qdata.get("epsilon", 0.3)
            for dkey, entry in qdata.get("table", {}).items():
                self.qtable[int(dkey.split("_")[1])] = {
                    int(k.split("_")[1]): v for k, v in entry.items()
                }
            logger.info(f"[Q] routing_mode={self.routing_mode}, "
                        f"dests={sorted(self.qtable)}, eps={self.epsilon}")
        except FileNotFoundError:
            logger.info("[Q] no qtable file — static mode")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[Q] qtable corrupt/unreadable ({e}) — static mode")

        logger.info(f"Loaded config: role={self.role}, neighbors={self.neighbors}")
        return True

    def choose_next_hop(self, dest, visited):
        # Nothing to forward when this node is itself the requested destination.
        if dest == self.node_id:
            return None
        candidates = [n for n in self.neighbors if n not in visited]
        if not candidates:
            # If every neighbor was visited, allow a choice anyway; MAX_HOPS
            # in forward() remains the final bound against routing loops.
            candidates = list(self.neighbors)

        if self.routing_mode != "qlearn" or dest not in self.qtable:
            # Static fallback: use the configured egress hop or nearest ring neighbor.
            if dest == self.egress_id and self.next_hop_egress in candidates:
                return self.next_hop_egress
            n = self.node_count
            # Ring distance is the shorter of the two directions around node IDs.
            cdist = lambda a, b: min((a - b) % n, (b - a) % n)
            return min(candidates, key=lambda nb: cdist(nb, dest))

        # Q-mode: explore randomly with probability epsilon; otherwise choose
        # the available neighbor with the highest stored score.
        q_entry = self.qtable[dest]
        if random.random() < self.epsilon:
            choice = random.choice(candidates)
            action = "explore"
        else:
            scored = [(q_entry.get(nb, float("-inf")), nb) for nb in candidates]
            best_val = max(s[0] for s in scored)
            tied = [nb for val, nb in scored if val == best_val]
            choice = random.choice(tied)
            action = "exploit"
        # Reduce exploration after every decision, regardless of which branch ran.
        with self.qlock:
            self.epsilon = max(EPS_FLOOR, self.epsilon * EPS_DECAY)
        top3 = sorted(((q_entry.get(nb, float("-inf")), nb) for nb in candidates),
                      reverse=True)[:3]
        logger.info(f"[Q] dest={dest} chose={choice} ({action}) eps={self.epsilon:.2f} "
                    f"top3={[(nb, round(v, 3)) for v, nb in top3]}")
        return choice

    def update_q(self, dest, action, reward):
        # Move this destination/action score toward the observed reward by ALPHA.
        with self.qlock:
            q_entry = self.qtable.setdefault(dest, {})
            old = q_entry.get(action, 0.0)
            new = old + ALPHA * (reward - old)
            q_entry[action] = new
            self._updates_since_flush += 1
            due = self._updates_since_flush >= FLUSH_EVERY
        logger.info(f"[Q-update] dest={dest} action={action} "
                    f"r={reward:.3f} {old:.3f}->{new:.3f} eps={self.epsilon:.3f}")
        if due:
            self.flush_qtable()

    def flush_qtable(self):
        # Serialize scores using the same key format expected by load_config().
        path = f"/etc/dase/qtable_node_{self.node_id}.json"
        tmp = path + ".tmp"
        table = {f"dest_{d}": {f"neighbor_{nb}": round(v, 6)
                               for nb, v in entry.items()}
                 for d, entry in self.qtable.items()}
        payload = {"node_id": self.node_id, "routing_mode": self.routing_mode,
                   "epsilon": round(self.epsilon, 4), "table": table}
        try:
            # Write a complete temporary file, then replace the old table atomically.
            with open(tmp, "w") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)  # atomic
            logger.info("[Q-flush] table persisted")
        except OSError as e:
            logger.warning(f"[Q-flush] failed: {e}")
        finally:
            with self.qlock:
                self._updates_since_flush = 0

    def deliver(self, msg):
        # The egress records the route summary and replies with delivery metadata.
        hops = msg.get("hops", [])
        logger.info("*** MESSAGE DELIVERED TO EGRESS ***")
        logger.info("Final path: " + " -> ".join(str(h["node_id"]) for h in hops))
        logger.info(f"Total hops: {len(hops)}")
        return json.dumps({
            "status": "delivered",
            "final_hop": self.node_id,
            "total_hops": len(hops),
        }).encode()

    def forward(self, msg):
        # Record this node in the path and stop messages that exceed the hop limit.
        hops = msg.setdefault("hops", [])
        if len(hops) >= MAX_HOPS:
            raise RouteError("MAX_HOPS exceeded")
        hops.append({"node_id": self.node_id, "ts": datetime.now().isoformat()})

        visited = {h["node_id"] for h in hops}
        nxt = self.choose_next_hop(msg.get("dest"), visited)
        if nxt is None:
            raise RouteError("self is destination but not egress")
        ip = self.peer_ips.get(nxt)
        if ip is None:
            raise RouteError(f"no IP for neighbor {nxt}")

        logger.info(f"Hops so far: {len(hops)}")
        logger.info(f"Forwarding to node {nxt} ({ip})")

        # Send one JSON request line to the selected neighbor over a fresh TCP connection.
        out = (json.dumps(msg) + "\n").encode()
        s = socket.create_connection((ip, self.port), timeout=10)
        try:
            s.sendall(out)
            resp = read_line(s)
        finally:
            s.close()
        if not resp:
            raise RouteError(f"no response from {nxt}")

        # Use the downstream response as feedback for the neighbor chosen above.
        dest = msg.get("dest")
        if self.routing_mode == "qlearn" and dest in self.qtable:
            # pos is this node's 1-based position in the recorded path.
            pos = len(hops)
            try:
                r = json.loads(resp)
            except (ValueError, TypeError):
                r = None
            if r and isinstance(r, dict) and r.get("status") == "delivered":
                total = r.get("total_hops", None)
                if total is None:
                    raise ValueError(f"[Q] record missing total_hops: {r}")
                # Penalize the remaining hops after this node; shorter suffixes
                # produce rewards closer to zero and therefore higher Q-values.
                net = -STEP_PENALTY * max(total - pos, 0)
                reward = net
                self.update_q(dest, nxt, reward)
            elif resp == b"ROUTE_FAILED":
                self.update_q(dest, nxt, -1.0)

        return resp

    def process(self, raw):
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            # Support plain-text input by treating it as a payload for the egress.
            msg = {"payload": raw.decode("utf-8", errors="ignore"),
                   "dest": self.egress_id, "hops": []}
        logger.info(f"Message payload: {str(msg.get('payload'))[:50]}")

        if msg.get("dest", self.egress_id) == self.node_id:
            return self.deliver(msg)
        return self.forward(msg)

NODE = DASENode()

# Each TCP connection is handled independently by the threaded server.
class Handler(BaseRequestHandler):
    def handle(self):
        self.request.settimeout(20)
        try:
            raw = read_line(self.request)
            if not raw:
                return
            self.request.sendall(NODE.process(raw))
        except RouteError as e:
            # Return a recognizable failure response so upstream nodes can learn from it.
            logger.error(f"ROUTE_FAILED at node {NODE.node_id}: {e}")
            try: self.request.sendall(b"ROUTE_FAILED")
            except OSError: pass
        except Exception as e:
            logger.error(f"Handler error: {e}")
            try: self.request.sendall(b"ROUTE_FAILED")
            except OSError: pass

def main():
    # Load topology before binding the listening socket; fail startup if unavailable.
    if not NODE.load_config():
        logger.critical("Failed to load configuration. Exiting.")
        sys.exit(1)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Permit quick restarts on the same address after the previous process exits.
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("0.0.0.0", NODE.port), Handler)
    server.daemon_threads = True
    logger.info(f"DASE v2 node {NODE.node_id} ({NODE.role}) listening on {NODE.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()