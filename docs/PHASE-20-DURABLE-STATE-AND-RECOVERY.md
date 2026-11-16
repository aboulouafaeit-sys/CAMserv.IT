# CAMserv — Phase 20 Durable State, Nonce Persistence & Recovery

**Document ID:** PHASE-20-STATE-2026-005  
**Target Release:** `0.10.0`  
**Classification:** Crash Consistency & Anti-Replay Security  
**Date:** November 16, 2026  

---

## 1. State Persistence Architecture & Atomicity

CAMserv maintains three critical persistent state stores for cluster consensus and distributed evidence replication:

```
[ClusterCoordinator] ──> cluster_state.json.tmp ──(flush + fsync)──> atomic rename ──> cluster_state.json
[ReplicationEngine]  ──> seen_nonces.json.tmp   ──(flush + fsync)──> atomic rename ──> seen_nonces.json
[ReplicationEngine]  ──> primary_seals.json.tmp ──(flush + fsync)──> atomic rename ──> primary_seals.json
```

### Atomicity Guarantees:
1. **Synchronous Disk Flush (`os.fsync`):** Every update writes payload to a temporary file (`.tmp`), invokes `f.flush()` and `os.fsync(f.fileno())` to guarantee physical disk platter/flash commit before renaming.
2. **Atomic Directory Entry Replacement (`replace`):** Uses POSIX atomic `rename()` / Win32 `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` to swap `.tmp` over the target file in a single filesystem transaction.
3. **No Partial Writes:** In the event of an abrupt power cut or hardware freeze, the active target file is either completely untouched or completely replaced.

---

## 2. Fail-Closed Security Policy (Remediation of SEC-P20-03 & SEC-P20-04)

Previous implementations caught exceptions when loading JSON files and silently continued with default empty states (0 terms or empty nonce sets). This fail-open behavior could allow replay attacks and term regression following file corruption.

### Remediated Fail-Closed Protocol:
* If `cluster_state.json` contains malformed bytes: `ClusterCoordinator` immediately raises `CorruptedConsensusStateError`. It **refuses** to start or reset term to 0.
* If `seen_nonces.json` contains malformed bytes: `DistributedReplicationEngine` immediately raises `CorruptedReplicationStateError`. It **refuses** to accept or replicate attestations without active anti-replay protection.
* If `primary_seals.json` contains conflicting digests for an existing segment: `DistributedReplicationEngine` raises `DuplicateSealError`.

---

## 3. Crash Point Testing & Recovery

Adversarial recovery tests in `tests/test_pre_lts_phase20_qualification.py` verified:
* `test_corrupted_consensus_state_fails_closed`: Confirms `CorruptedConsensusStateError` is raised.
* `test_corrupted_nonce_cache_fails_closed`: Confirms `CorruptedReplicationStateError` is raised.
* `test_duplicate_and_conflicting_primary_seal_handling`: Confirms conflicting seals raise `DuplicateSealError`, while identical seals are idempotent and do not duplicate Merkle leaves.
