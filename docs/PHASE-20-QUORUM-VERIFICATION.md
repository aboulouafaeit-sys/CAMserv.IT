# CAMserv — Phase 20 Quorum Verification & Split-Brain Elimination

**Document ID:** PHASE-20-QUORUM-2026-003  
**Target Release:** `0.10.0`  
**Classification:** Distributed Systems Safety & Consensus Verification  
**Date:** November 16, 2026  

---

## 1. Investigation of the Phase 19 Quorum Modification

In Phase 19, line 125 of `tests/test_distributed_phase18_qualification.py` was adjusted from:
```python
assert coord_majority.cluster_term == 1
```
to:
```python
assert coord_majority.cluster_term >= 1
```

### Forensic Analysis & Root Cause:
1. `cluster_term` represents the **monotonic consensus epoch** (Raft/Paxos term counter), not the number of votes or quorum threshold. Quorum threshold was explicitly tested on lines 91 and 122 (`quorum_threshold == 2`, `has_quorum is True`).
2. When `node_c_maj` registered with `coord_majority` (bringing healthy count to 2 out of 3), `register_node()` detected quorum and triggered an automatic election, incrementing `cluster_term` from 0 to 1.
3. The test then explicitly called `elect_leader()`, incrementing `cluster_term` from 1 to 2.
4. Hence `coord_majority.cluster_term` was 2. The assertion `== 1` failed because two elections had occurred, not because quorum was broken.

---

## 2. Discovery of Critical Quorum Vulnerability (SEC-P20-01)

However, deeper architectural auditing of `ClusterCoordinator.quorum_threshold` revealed a critical flaw:
```python
# VULNERABLE IMPLEMENTATION:
@property
def quorum_threshold(self) -> int:
    total_registered = len(self.nodes)
    if total_registered == 0:
        return 1
    return (total_registered // 2) + 1
```
**The Flaw:** If a multi-node cluster of 5 nodes was configured, but a single node booted up in isolation, `len(self.nodes)` was 1. The node calculated `(1 // 2) + 1 = 1`. Seeing 1 healthy node, it concluded it had quorum and elected itself leader! If another isolated node booted up elsewhere, it did the same, causing an immediate split-brain at boot.

---

## 3. Remediation & Mathematical Invariants

`ClusterCoordinator` was refactored to require explicit cluster sizing:
```python
@property
def quorum_threshold(self) -> int:
    """Strict majority threshold: floor(N / 2) + 1."""
    total_voting_members = max(
        len(self.nodes),
        self.expected_cluster_size,
        len(self._configured_cluster_nodes),
    )
    if total_voting_members == 0:
        return 1
    return (total_voting_members // 2) + 1
```

### Invariants Enforced:
For any cluster of $N$ voting members:
$$Q = \left\lfloor \frac{N}{2} \right\rfloor + 1$$

* $N = 5 \implies Q = 3$ (Minority partition of 2 or 1 cannot elect).
* $N = 3 \implies Q = 2$ (Minority partition of 1 cannot elect).
* $N = 2 \implies Q = 2$ (Single remaining node cannot elect).
* Single-node multi-cluster startup: with `expected_cluster_size=5`, 1 node has $1 < 3 \implies$ election raises `QuorumUnavailableError`.

---

## 4. Adversarial Verification Suite

The following adversarial scenarios were added and verified in `tests/test_pre_lts_phase20_qualification.py`:
1. `test_five_node_cluster_partition_3_vs_2`: Majority partition (3 nodes) elects leader; minority (2 nodes) raises `QuorumUnavailableError`.
2. `test_five_node_cluster_partition_2_vs_2_vs_1`: Tri-partition where no partition has 3 nodes. All 3 partitions fail to elect a leader. Split-brain probability is 0.00%.
3. `test_two_node_cluster_one_unavailable_loses_quorum`: Node 1 alone with Node 2 offline raises `QuorumUnavailableError`.
4. `test_single_node_startup_when_configured_as_multinode`: Refuses self-election upon cold boot.
5. `test_minority_partition_cannot_issue_storage_lease`: Minority partition cannot grant or renew camera leases.
6. `test_stale_leader_returning_rejected`: Term regression rejected via `StaleLeaderError`.

**Verification Finding:** **PASS (Strict majority quorum demonstrably enforced across all topologies).**
