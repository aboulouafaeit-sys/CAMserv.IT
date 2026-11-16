# CAMserv — Phase 20 Security & Engineering Remediation Register

**Document ID:** PHASE-20-REM-2026-016  
**Target Release:** `0.10.0`  
**Date:** November 16, 2026  

---

## 1. Phase 20 Resolved Findings Register

### SEC-P20-01: Quorum Calculation Vulnerability on Isolated Startup
* **Severity:** CRITICAL
* **Affected Module:** `src/camserv/central/cluster.py` (`ClusterCoordinator.quorum_threshold`)
* **Root Cause:** Dynamic quorum threshold calculation based solely on connected nodes (`len(nodes)`). A single node booting in isolation calculated $Q = \lfloor 1/2 \rfloor + 1 = 1$, electing itself leader despite 4 missing nodes in a 5-node cluster.
* **Remediation:** Added `expected_cluster_size` and static `cluster_nodes`. Threshold calculates $Q = \lfloor \max(\text{len}(nodes), \text{expected}) / 2 \rfloor + 1$.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_single_node_startup_when_configured_as_multinode`
* **Status:** **REMEDIATED & VERIFIED**

---

### SEC-P20-02: Crash Recovery Storage Fencing Bypass
* **Severity:** HIGH
* **Affected Module:** `src/camserv/nvr/recording_engine.py` (`recover_incomplete_recordings`)
* **Root Cause:** Incomplete `.part` files recovered after abrupt shutdown were unconditionally admitted to `SQLiteStore` without validating active storage leases.
* **Remediation:** Enforced lease validation during recovery. Incomplete files belonging to cameras without an active valid lease are quarantined to `.quarantined.mp4`.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_crash_recovery_quarantines_unleased_part_files`
* **Status:** **REMEDIATED & VERIFIED**

---

### SEC-P20-03: Silent Term Regression on Corrupted Consensus State
* **Severity:** HIGH
* **Affected Module:** `src/camserv/central/cluster.py` (`_load_persisted_state`)
* **Root Cause:** Exceptions during state loading were caught and swallowed, silently resetting `cluster_term = 0`.
* **Remediation:** Raised `CorruptedConsensusStateError`. System fails closed and refuses to reset term to 0.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_corrupted_consensus_state_fails_closed`
* **Status:** **REMEDIATED & VERIFIED**

---

### SEC-P20-04: Silent Replay Guard Loss on Corrupted Nonce Cache
* **Severity:** HIGH
* **Affected Module:** `src/camserv/central/replication.py` (`_load_persisted_state`)
* **Root Cause:** Corrupted `seen_nonces.json` fell back to an empty set, allowing replay attacks across restarts.
* **Remediation:** Raised `CorruptedReplicationStateError`, failing closed.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_corrupted_nonce_cache_fails_closed`
* **Status:** **REMEDIATED & VERIFIED**

---

### SEC-P20-05: Conflicting Primary Seal Silent Overwrite
* **Severity:** MEDIUM
* **Affected Module:** `src/camserv/central/replication.py` (`register_evidence_seal`)
* **Root Cause:** Calling `register_evidence_seal` with an existing `segment_id` and divergent hash overwrote the primary seal and duplicated Merkle leaves.
* **Remediation:** Enforced immutability. Conflicting hashes raise `DuplicateSealError`. Identical seals are idempotent.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_duplicate_and_conflicting_primary_seal_handling`
* **Status:** **REMEDIATED & VERIFIED**

---

### SEC-P20-06: Unfenced Writer Lease Issuance on Minority Partition
* **Severity:** HIGH
* **Affected Module:** `src/camserv/central/cluster.py` (`issue_storage_lease`)
* **Root Cause:** Coordinator lacked an explicit quorum-gated lease issuance method.
* **Remediation:** Added `issue_storage_lease()`. Verifies active leader role and strict quorum before issuing leases.
* **Regression Test:** `tests/test_pre_lts_phase20_qualification.py::test_minority_partition_cannot_issue_storage_lease`
* **Status:** **REMEDIATED & VERIFIED**
