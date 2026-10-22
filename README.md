# DASE — Decentralized Adversarial Swarm Egress

## Purpose

DASE (Decentralized Adversarial Swarm Egress) is a research testbed investigating a specific question in command-and-control (C2) network resilience: when a routing policy is rewarded only for message delivery, what does it spend in route diversity to survive attacks, and how much?

The motivation: decentralized P2P botnets are hard to take down precisely because no single node is critical. But resilience research measures whether these networks keep delivering messages under attack but fail to ask what survival cost is in traceability. A policy that learns to route around killed nodes may concentrate traffic onto fewer, shorter, more predictable paths. The fast way out of a broken network is the shortest way out, and the shortest way out is the easiest one to watch.

DASE tests this with a 149-node k-chorded circulant topology (C₁₄₉(1, 5, 15)) deployed on isolated Proxmox infrastructure, comparing:

    a static-routed swarm (fixed BFS-derived tables),
    a Q-learning swarm (each node learns forwarding from a delivery-only reward,hop count to destination, with no term for diversity, anonymity, or attribution),
    a centralized single-relay C2 arm (zero-diversity reference).

Route diversity and path-length entropy are treated as proxies measurable from within the swarm, not as anonymity itself. They map to anonymizing capacity only under a defined adversary model (a passive observer with a limited watching budget), following the precedent of LASTor and the anonymity-metrics literature.

This is an empirical research framework for analyzing adaptive C2 resilience. It is not a production deployment tool, contains no propagation, persistence, or infection capability, and runs entirely on isolated infrastructure with synthetic traffic.

## STATUS: What is complete

- **Fleet deployment.** The final reward-fixed daemon is deployed and
  hash-verified on all 149 containers. The dormant per-hop discount factor
  was removed from source prior to the push. Routing mode is data-driven:
  each node's mode is read from its Q-table file (`/etc/dase/qtable_node_<id>.json`),
  which overrides the code default.

- **Baseline arms.** Three configurations have been executed on the live
  swarm, 100 messages each, all with 100/100 delivery.All three are reproduced 
  from archived artifacts by the notebook.

- **Learning confirmation.** Post-run Q-tables were compared against
  warm-start values for the implant node. Three of six neighbor values
  drifted (e.g. −0.040 → −0.043 for the preferred neighbor); the remaining
  three are exact fixed points under the reward function. Drift confirms
  table updates occur, not merely ε decay.

- **First-hop diversity.** The ≤70% top-share criterion **fails** in the
  five-node configuration (76% concentration). The full-swarm
  configuration passes (37%) via reward-noise-driven argmax dispersion.
  
- **Analysis notebook.** `dase_analysis.ipynb` reproduces every measurement
  above from archived artifacts, and includes a reduced routing simulator
  that runs without fleet hardware.

## What is pending

- **Interdiction harness execution.** The harness is designed and its
  failure semantics are documented, but no interdiction scenario has been
  run against the real swarm. This is the central experiment of the project
  and is currently the gating item.

- **Interdiction initial condition.** Undecided: pristine warm-start tables
  ("cold" control) versus trained tables. Planned resolution is to run both,
  isolating the contribution of learned state from that of ε-exploration.

- **First-hop criterion redefinition.** The current ≤70% top-share threshold
  is not satisfiable under the configured ε schedule and must be replaced
  (e.g. entropy-versus-ceiling ratio) before interdiction results are scored.

- **True route entropy.** Reported entropies are over path *lengths*, a lower
  bound. Distinct-route counting requires extracting final-path records from
  the egress log and has not yet been performed.

- **Convergence study.** Whether to characterize the exploration regime as
  measured, or run an extended soak sufficient for per-node convergence
  (~15k+ messages per node at the current schedule).

## The notebook (dase_analysis.ipynb)

The analysis notebook re-derives every reported metric from the raw captured artifacts in data/, Concatenated JSON response streams from each experimental arm, the implant's routing-decision log, and dumped Q-tables. Specifically, it:

    Parses response streams and computes delivery rate, hop-count statistics, and path-length entropy for each arm.
    Compares hop distributions across arms (the README figure).
    Extracts the implant's first-hop forwarding decisions from the run log, checking the top-share and entropy criteria against the exploration schedule.
    Diffs the post-run Q-table against the warm start to confirm learning occurred.
    Contains a stub cell for the interdiction analysis, to be populated once harness artifacts exist.
    Runs a reduced simulator (circulant topology, analytic warm start, same hyperparameters and failure semantics as the daemon) including a simulated chokepoint-kill scenario. This simulator is fully self-contained and provides a qualitative cross-check of swarm behavior, but it is a model, not the swarm.

## Reproducibility boundary

The swarm itself runs on dedicated private hardware: 149 nodes as Linux containers, plus the implant and egress roles, orchestrated outside this repository. The daemon code ships with this release. The full experiment sequence requires a matching environment which is 149 LXC containers on a Proxmox host, degree-6 circulant topology on an isolated bridge, which reviewers must provision on their own hardware. The analysis notebook reproduces all reported measurements from the archived artifacts in data/ without any fleet This is a known limitation of this release, not a defect: the repository is intended to make the analysis and the captured results independently verifiable, not to reproduce the swarm from scratch.

## Data

The data/ directory contains the archived experimental artifacts from all measurement runs performed on the live swarm which are the raw delivery records, per-node learned routing tables, daemon decision logs, and the fleet manifest that maps container IDs to network nodes. Every number and figure produced by dase_analysis.ipynb is derived from these files.


## System Architecture

**Fleet:** 149 Alpine LXC containers (CTIDs 106–254, mapped to node_ids 0–148)

**Topology:** Degree-6 circulant graph with chords ±1, ±5, ±15 (each node connects to 6 neighbors)

**Daemon:** `dase-node.py` (v2), single-threaded Python HTTP-like listener on port 4443, per-node Q-table persistence

**Routing Modes (per-node):**
- **Static:** Minimum circulant distance to destination, no adaptation (Arm B)
- **Q-Learning:** ε-greedy over learned Q-values, ε decays 0.30→0.05 per decision (Arm Q)

**Reward Function:**
python
net = -STEP_PENALTY * max(total_hops - pos, 0)  # STEP_PENALTY = 0.01
reward = net

## Cloning the Repository
```bash
git clone https://github.com/reign0f/DASE.git
```

### Setup (recommended: virtualenv)

```bash
cd DASE
python -m venv test-env
source test-env/bin/activate
```

# Install dependencies
```bash
pip install -r requirements.txt
```

## Running the Notebook

`jupyter lab dase_analysis.ipynb` reproduces every measurement in this README from the
archived artifacts in `data/`. No fleet hardware required.
