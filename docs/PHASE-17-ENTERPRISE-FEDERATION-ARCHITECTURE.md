# Phase 17: Enterprise Federation & Multi-Node Architecture Report

**Target Release:** 0.10.0-rc1  
**Evaluated Modules:** `src/camserv/central/` (`cluster.py`, `replication.py`, `mtls.py`, `registry.py`)  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

Phase 17 expands CAMserv from standalone edge/desktop installations into an enterprise-class **Multi-Node Federated Surveillance Mesh**. Multiple NVR appliances (Debian appliances, rockchip edge boxes, and Windows 11 workstation nodes) collaborate under a unified coordinator with automated consensus, dynamic camera channel failover, distributed forensic witness sealing, and zero-trust mutual TLS.

---

## 2. Federation Topology

```
+---------------------------------------------------------------------------------+
|                         CAMserv Central Management Cluster                      |
|                                                                                 |
|  +---------------------------+             +---------------------------------+  |
|  | ClusterCoordinator        |             | EnterpriseMtlsGateway           |  |
|  | - Leader Election (Cons.) |             | - Node mTLS Handshake           |  |
|  | - Channel Load Balancing  |             | - Zero-Trust Revocation Lists   |  |
|  | - Automated Failover      |             | - Instant Node Quarantine       |  |
|  +---------------------------+             +---------------------------------+  |
|                ^                                            ^                   |
+----------------|--------------------------------------------|-------------------+
                 |                                            |
        mTLS WAN / LAN                               mTLS WAN / LAN
                 |                                            |
                 v                                            v
+------------------------------------+       +------------------------------------+
| Node A: Debian NVR Appliance       |       | Node B: Windows 11 Surveillance Stn|
| - Cameras 01 - 08 (Primary)        | <---> | - Cameras 09 - 16 (Primary)        |
| - Active Video Recorder            |       | - Backup Standby Ingestion         |
| - Local SHA-256 Segment Sealer     | Peer  | - Peer Witness Attestation Signer  |
| - Distributed Merkle Leaf Sync     | Sync  | - Desktop Operator Console GUI     |
+------------------------------------+       +------------------------------------+
```

---

## 3. High-Availability Operational Model

1. **Active-Active Clustering:** Each node ingests, records, and analyzes its assigned camera streams locally.
2. **Deterministic Leader Consensus:** Leader election sorts eligible nodes deterministically, designating a primary coordinator while maintaining warm state on followers.
3. **Automated Heartbeat Keepalive:** Nodes broadcast telemetry heartbeats every 2 seconds. A node missing heartbeats for longer than `heartbeat_timeout_sec` is marked `OFFLINE`.
4. **Non-Disruptive Failover:** Orphaned camera streams on offline nodes are immediately re-routed to surviving cluster members with available capacity.

---

## 4. Verification Evidence

- **Unit Test:** `test_cluster_coordinator_registration_and_leader_election` — PASSED.
- **Unit Test:** `test_cluster_camera_assignment_and_load_balancing` — PASSED.
