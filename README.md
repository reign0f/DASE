# DASE — Decentralized Adversarial Swarm Egress

> **STATUS: Work in progress.** This repository documents ongoing research.
> Baseline measurements (static vs. Q-routed swarm) are complete; the interdiction
> experimentswhich is the core of the thesis question, has not yet been run.
> See "Experiment Sequence" for current progress. Expect missing sections,
> placeholder cells, and evolving analysis until the project concludes.

## Purpose

DASE evaluates whether Q-learning-based decentralized routing can sustain route diversity (a necessary
condition for anonymity against specific adversary classes) under node interdiction while preserving
delivery performance.

Route diversity and path-length entropy are treated as proxies measurable from within the swarm, not
as anonymity itself. They map to anonymizing capacity only under defined adversary models:

This is an empirical research framework for analyzing adaptive C2 resilience, not a production deployment tool.

## System Architecture

**Fleet:** 149 Alpine LXC containers (CTIDs 106–254, mapped to node_ids 0–148)

**Topology:** Degree-6 circulant graph with chords ±1, ±5, ±15 (each node connects to 6 neighbors)

**Daemon:** `dase-node.py` (v2), single-threaded Python HTTP-like listener on port 4443, per-node Q-table persistence

**Routing Modes (per-node):**
- **Static:** Minimum circulant distance to destination, no adaptation (Arm B)
- **Q-Learning:** ε-greedy over learned Q-values, ε decays 0.30→0.05 per decision (Arm Q)

**Reward Function:**
```python
net = -STEP_PENALTY * max(total_hops - pos, 0)  # STEP_PENALTY = 0.01
reward = net

## Running the Notebook

`dase_analysis.ipynb` reproduces every measurement in this README from the
archived artifacts in `data/`. No fleet hardware required.

**Prerequisites:** Python 3.8+ (validated on 3.11), Jupyter, matplotlib.

### Setup (recommended: virtualenv)

```bash
# Create and activate an environment
python -m venv env
source env/bin/activate            # Windows: .\env\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install jupyter