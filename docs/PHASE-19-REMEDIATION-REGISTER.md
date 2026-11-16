# Phase 19: Security Findings, Defect Remediation & Verification Register

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc3`  
**Previous Baseline:** Commit `2f37982`  
**Auditor:** Independent Enterprise Deployment Auditor & Quality Assurance Lead  
**Evaluation Date:** November 16, 2026  

---

## 1. Executive Summary

During the Phase 19 independent re-audit of the enterprise federation architecture, four concrete architectural and security defects were identified when evaluating the system under physical reboots, network partitions, and decoupled storage boundaries.

All four findings have been remediated in source code, integrated into the core runtime paths, and validated via 10 automated qualification tests in `tests/test_real_cluster_phase19_qualification.py`.

---

## 2. Exhaustive Defect Remediation Register

```
+---------------------------------------------------------------------------------------------------+
| FINDING 19-01: Storage-Level Writer Fencing Decoupling (Reopened Finding 18-02)                   |
+---------------------------------------------------------------------------------------------------+
| Severity:          HIGH (CWE-362 / CVSS 8.4)                                                      |
| Affected Module:   src/camserv/nvr/recording_engine.py (NVRRecordingEngine)                      |
| Root Cause:        In Phase 18, verify_writer_fencing was implemented only at the coordinator.     |
|                    The recording engine wrote frames directly to disk without checking fencing     |
|                    tokens or storage leases, allowing a network-isolated writer to continue       |
|                    writing video files locally and creating dual-writer conflicts upon reconnect. |
| Remediation:       Created StorageLease protocol with time-bounded expiration and monotonic       |
|                    epochs. Integrated lease validation directly into NVRRecordingEngine           |
|                    ingest_frame() and _finalize_current_segment(). Unleased or expired writes are  |
|                    halted with FencedWriterError, and in-flight segments are quarantined to       |
|                    .quarantined.mp4 without touching SQLiteStore.                                 |
| Verification:      tests/test_real_cluster_phase19_qualification.py::                             |
|                    test_storage_level_writer_fencing_rejects_unleased_camera,                     |
|                    test_storage_level_writer_fencing_rejects_expired_lease,                       |
|                    test_storage_level_writer_fencing_quarantines_segment_on_lease_expiry          |
| Status:            REMEDIATED & VERIFIED                                                          |
+---------------------------------------------------------------------------------------------------+
```

```
+---------------------------------------------------------------------------------------------------+
| FINDING 19-02: Volatile Consensus Term & State Reset on Reboot (Reopened Finding 18-01)          |
+---------------------------------------------------------------------------------------------------+
| Severity:          HIGH (CWE-662 / CVSS 7.9)                                                      |
| Affected Module:   src/camserv/central/cluster.py (ClusterCoordinator)                            |
| Root Cause:        Cluster terms, active fencing tokens, and camera epochs were stored only in    |
|                    Python memory (self.cluster_term = 0). A coordinator process crash or reboot   |
|                    reset terms to zero, violating term monotonicity across restarts.              |
| Remediation:       Added durable state persistence to ClusterCoordinator. State is atomically     |
|                    flushed to cluster_state.json via write-and-replace (.tmp -> .json). On reboot,|
|                    the coordinator reloads the persisted term, asserting term monotonicity.       |
| Verification:      tests/test_real_cluster_phase19_qualification.py::                             |
|                    test_durable_consensus_term_recovery_across_reboots                          |
| Status:            REMEDIATED & VERIFIED                                                          |
+---------------------------------------------------------------------------------------------------+
```

```
+---------------------------------------------------------------------------------------------------+
| FINDING 19-03: Volatile Witness Nonce Reset & Post-Reboot Replay (Reopened Finding 18-03)         |
+---------------------------------------------------------------------------------------------------+
| Severity:          HIGH (CWE-294 / CVSS 7.5)                                                      |
| Affected Module:   src/camserv/central/replication.py (DistributedReplicationEngine)              |
| Root Cause:        seen_attestation_nonces was an in-memory set. When a witness appliance rebooted|
|                    for maintenance, observed nonces were wiped, permitting an attacker to replay |
|                    previously captured witness signatures.                                        |
| Remediation:       Added durable state persistence to DistributedReplicationEngine. Observed     |
|                    nonces and primary seals are persisted to seen_nonces.json and                 |
|                    primary_seals.json atomically, maintaining replay immunity across reboots.     |
| Verification:      tests/test_real_cluster_phase19_qualification.py::                             |
|                    test_durable_witness_nonce_persistence_across_reboots,                         |
|                    test_durable_seal_persistence_and_merkle_recovery                             |
| Status:            REMEDIATED & VERIFIED                                                          |
+---------------------------------------------------------------------------------------------------+
```

```
+---------------------------------------------------------------------------------------------------+
| FINDING 19-04: Partitioned Segment Reconnection & Stale Evidence Ingestion Hazard                 |
+---------------------------------------------------------------------------------------------------+
| Severity:          MEDIUM (CWE-436 / CVSS 6.8)                                                    |
| Affected Module:   src/camserv/central/cluster.py (reconcile_partitioned_writer)                  |
| Root Cause:        When a recovered node reconnected, no formal reconciliation protocol verified |
|                    whether segments recorded while offline could be committed or needed to be     |
|                    quarantined, risking silent divergence of forensic timelines.                  |
| Remediation:       Implemented reconcile_partitioned_writer(camera_id, node_id, epoch) on         |
|                    ClusterCoordinator. Compares recovering node epoch with active cluster state;  |
|                    stale epochs are rejected (admitted=False, quarantined=True), preserving       |
|                    majority-committed recordings.                                                 |
| Verification:      tests/test_real_cluster_phase19_qualification.py::                             |
|                    test_partitioned_writer_reconciliation_quarantines_stale_epoch,                |
|                    test_recovering_node_cannot_overwrite_majority_committed_evidence              |
| Status:            REMEDIATED & VERIFIED                                                          |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Summary Status

| Finding ID | Title | Severity | Status |
| :---: | :--- | :---: | :---: |
| **FINDING 19-01** | Storage-Level Writer Fencing Gap | **HIGH** | **CLOSED & VERIFIED** |
| **FINDING 19-02** | Consensus Term Volatility Across Reboots | **HIGH** | **CLOSED & VERIFIED** |
| **FINDING 19-03** | Witness Nonce Volatility Across Reboots | **HIGH** | **CLOSED & VERIFIED** |
| **FINDING 19-04** | Partitioned Segment Reconnection Hazard | **MEDIUM** | **CLOSED & VERIFIED** |

All findings have been completely resolved with zero remaining unmitigated defects.
