# Release Notes: CAMserv 0.10.0-rc3

**Release Candidate:** `0.10.0-rc3`  
**Previous Release Candidate:** `0.10.0-rc2`  
**Release Date:** November 16, 2026  
**Target Architectures:** AMD64, ARM64  
**Target Platforms:** Windows 11 Pro/Enterprise x64, Windows 10 x64, Debian 12 Bookworm, Debian 13 Trixie  

---

## 1. Overview

CAMserv `0.10.0-rc3` is the hardened Enterprise Cluster Release Candidate of the CAMserv Advanced Security Intelligence Platform. Following the Phase 19 multi-node hardware and distributed recovery qualification, `0.10.0-rc3` introduces storage-level writer fencing, durable consensus term persistence across reboots, durable witness anti-replay protection, and partitioned segment quarantine protocols.

---

## 2. Key Enhancements & New Capabilities

### 2.1 Storage-Level Writer Fencing & Exclusive Leases
- **`StorageLease` Protocol:** Channel recording now requires an active, time-bounded storage lease granted by the cluster coordinator.
- **Atomic Storage Write Gate:** `NVRRecordingEngine` validates the lease before ingesting frames and finalizing segments.
- **In-Flight Segment Quarantine:** If an isolated node's lease expires during capture, the segment is automatically closed, moved to `.quarantined.mp4`, and blocked from being committed to `SQLiteStore`.

### 2.2 Durable Consensus State & Term Monotonicity Across Reboots
- **Atomic State Persistence:** `ClusterCoordinator` persists `cluster_term`, `active_fencing_token`, and camera epochs to `cluster_state.json` via atomic `.tmp` replace.
- **Reboot Monotonicity:** A restarted coordinator reloads its persisted term, ensuring that post-reboot terms strictly advance and prevent cluster deadlock.

### 2.3 Durable Witness Nonce Replay Protection
- **Persistent Nonce Ledgers:** `DistributedReplicationEngine` persists observed witness nonces to `seen_nonces.json`.
- **Post-Reboot Replay Immunity:** Replaying a previously observed witness attestation against a rebooted witness appliance is immediately detected and rejected.

### 2.4 Partitioned Writer Reconciliation & Evidence Safety
- **Safe State Reconciliation:** Reconnecting nodes invoke `reconcile_partitioned_writer()`. Segments recorded under stale epochs are quarantined, preventing silent overwrite of authoritative footage committed by the majority failover writer.

---

## 3. Defects Remediated in this Release Candidate

| Issue ID | Affected Component | Summary of Engineering Remediation |
| :--- | :--- | :--- |
| **FINDING 19-01** | `nvr/recording_engine.py` | Storage-level writer fencing with `StorageLease` and quarantine |
| **FINDING 19-02** | `central/cluster.py` | Durable consensus term persistence to `cluster_state.json` |
| **FINDING 19-03** | `central/replication.py` | Durable witness nonce persistence to `seen_nonces.json` |
| **FINDING 19-04** | `central/cluster.py` | Partitioned writer reconciliation protocol for stale segments |

---

## 4. Test & Qualification Summary

* **Automated Test Suite:** 357 passed / 357 total across 65 test modules (100.0% pass rate).
* **Dedicated Phase 19 Test Suite:** 10 / 10 passed in `tests/test_real_cluster_phase19_qualification.py`.
* **Cryptographic Invariant (Rule 1):** `logs/audit.jsonl` verified inviolate (20,977 bytes, SHA-256 `F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525`).
* **Continuous Soak Duration:** 4.5 hours continuous multi-channel stress run (1,000 cycles) with flat memory profiles.
