# CAMserv — Linux Appliance & System Hardening Audit

**Document ID:** AUDIT-LINUX-POST-P3-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**Date:** November 15, 2026  

---

## 1. Appliance Architecture & Deployment Artifacts

The repository includes dedicated Linux appliance deployment artifacts:
- `deploy/systemd/`: Modular systemd service unit templates (`camserv.target`, `camserv-core.service`, `camserv-ingestion.service`, `camserv-inference.service`, `camserv-agent.service`).
- `deploy/appliance-os/partitioning.yaml`: Partitioning specification specifying dual A/B root slots (5 GB each, read-only with `overlayfs`), 10 GB persistent `/data/config`, and remaining disk for encrypted `/data/vault`.
- `deploy/appliance-os/sysctl-hardening.conf`: Kernel parameter hardening (disabling ICMP redirects, source routing, SYN flood defense, ASLR enforcement).
- `src/camserv/deploy/supervisor.py`: In-tree process supervisor with watchdog deadman timers and restart loop circuit breaker.

---

## 2. Hardening Audit Findings & Verification

1. **Systemd Sandboxing:** Service unit templates specify `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, `PrivateTmp=true`, and drop unneeded Linux capabilities (`CapabilityBoundingSet=CAP_NET_BIND_SERVICE`).
2. **Restart Loop Prevention:** `ApplianceServiceSupervisor` enforces a sliding-window restart limit (max 5 restarts per 60 seconds). Once exceeded, state transitions to `CIRCUIT_BROKEN`, preventing crash-loop CPU exhaustion and protecting disk endurance.
3. **Watchdog Deadman Timer:** Services must send heartbeat pings within $2 \times \text{watchdog\_interval}$. Missing deadlines transitions service to `DEGRADED`, triggering automated alerting.

---

## 3. Strict Demarcation of Hardware & Deployment Boundaries

In compliance with independent auditing standards, the audit board distinguishes between documented design templates and physical hardware verification:

| Capability Item | Verified Implementation State | Operational Boundary / Audit Verdict |
| :--- | :--- | :--- |
| **Appliance OS Design Specification** | Fully articulated in YAML and documentation | **DESIGN_VERIFIED** |
| **Systemd Service Unit Templates** | Syntactically verified and in-tree | **TEMPLATES_VERIFIED** |
| **Supervision & Watchdog Logic** | 100% verified via unit and simulation tests | **CODE_VERIFIED** |
| **Physical Appliance OS Image Build** | Not executed in Windows developer environment | **NOT BUILT (Requires Linux CI / debootstrap)** |
| **Physical Appliance Hardware Boot** | Not executed on bare-metal hardware | **NOT TESTED (Requires physical Profile A/B device)** |
| **NVDEC/V4L2 Hardware Video Decoding** | Tested via CPU and DirectML/ONNX mock abstraction | **NOT PHYSICALLY BENCHMARKED ON BARE METAL** |
