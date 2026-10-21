# ETHICS — DASE Research Framework

## Research Context

DASE is a graduate capstone project studying defensive resilience: how adaptive
routing responds to node interdiction. The findings inform *defense*: kill-chain
disruption strategies, C2 detection signatures, and attribution of adaptive command
infrastructures.

## Why This Is Not a Weapon

- **Isolated testbed:** All 149 nodes run on a private Proxmox bridge
  (`192.168.200.0/24`) with no external connectivity, no real hosts, and no
  production data. There is nothing to exfiltrate; payloads are synthetic
  test messages.
- **Non-deployable as-is:** The daemon is a single-threaded Python test harness
  with no implant capability, no evasion, no persistence beyond an OpenRC service
  in throwaway containers, and hard-coded ports.
- **Fixed topology:** Results depend on a specific circulant graph; no general
  deployment tooling exists, by design.
- **No weaponization roadmap:** No effort is or will be made to productionize
  the framework. Techniques studied are drawn from publicly documented APT
  tradecraft literature.

## Responsible Conduct

- Work conducted attending an NCAE-CO designated institution under faculty supervision.
- All adversarial simulation targets infrastructure owned and operated by the
  researcher.
- Findings will be published to the school; no classified or restricted
  tradecraft is involved or developed.

## Dual-Use Acknowledgment

Adaptive C2 routing is dual-use knowledge. This project mitigates misuse risk
by (a) operating purely in simulation, (b) framing all analysis around defensive
detection and disruption, and (c) not releasing operational tooling. Results
are reported as measurements, not as software.