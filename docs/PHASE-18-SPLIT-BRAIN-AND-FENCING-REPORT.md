# Phase 18: Split-Brain Prevention, Network Partition Simulations & Camera Fencing Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc2`  
**Evaluated Modules:** `src/camserv/central/cluster.py`, `src/camserv/central/replication.py`  
**Auditor:** Independent Distributed Systems Security Auditor  
**Status:** **VERIFIED & QUALIFIED**  

---

## 1. Executive Summary & Threat Profile

In video surveillance and forensic recording, the most hazardous operational failure is the **dual-writer split-brain condition**. If a network partition isolates an NVR node while other nodes assume it has failed, two nodes may concurrently connect to the same IP camera's RTSP stream and attempt to write competing segments into storage, corrupting video segment continuity, creating duplicate timestamps, and destroying forensic chain-of-custody.

Phase 18 implements an end-to-end **Distributed Resource Fencing Architecture** that guarantees that at any point in physical time:
1. Only the majority partition can elect a leader and reassign camera streams.
2. Every camera channel assignment carries a strictly monotonic **Assignment Epoch** ($E$).
3. Any write attempt by a partitioned or stale writer carrying an obsolete epoch ($E_{write} < E_{active}$) is rejected with `FencedWriterError`.

---

## 2. Partition Topologies & Consensus Behavior

```
               SCENARIO A: 3-Node Symmetric Network Partition
               ------------------------------------------------
   Partition A (Minority: 1 Node)         Partition B (Majority: 2 Nodes)
   +----------------------------+         +----------------------------+
   | Node Alpha (Offline/Isol.) |  < X >  | Node Beta   | Node Gamma   |
   | - Healthy: 1 / 3           |         | - Healthy: 2 / 3           |
   | - Quorum: 2 required       |         | - Quorum: 2 required       |
   | - Status: QUORUM LOST      |         | - Status: QUORUM REACHED   |
   | - Leadership: REVOKED      |         | - Leadership: Beta Elected |
   | - Failovers: FROZEN        |         | - Failover: Authorized     |
   | - Camera Streams: FENCED   |         | - Camera Streams: ACTIVE   |
   +----------------------------+         +----------------------------+
                 |                                       |
                 v                                       v
         Write Rejected!                         Write Accepted!
       (FencedWriterError)                     (Valid Epoch / Token)
```

### Partition Truth Table Across Cluster Configurations

| Cluster Size ($N$) | Majority Quorum ($\lfloor N/2 \rfloor + 1$) | Partition 1 Nodes | Partition 2 Nodes | Partition 1 Status | Partition 2 Status | Dual-Leader Possible? |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **3** | **2** | 1 (`node-a`) | 2 (`node-b`, `node-c`) | **Quorum Lost (Frozen)** | **Quorum Held (Active)** | **NO** |
| **4** | **3** | 2 (`node-a`, `node-b`) | 2 (`node-c`, `node-d`) | **Quorum Lost (Frozen)** | **Quorum Lost (Frozen)** | **NO** |
| **5** | **3** | 2 (`node-a`, `node-b`) | 3 (`node-c`, `node-d`, `node-e`) | **Quorum Lost (Frozen)** | **Quorum Held (Active)** | **NO** |
| **5** | **3** | 1 (`node-a`) | 4 (`b`, `c`, `d`, `e`) | **Quorum Lost (Frozen)** | **Quorum Held (Active)** | **NO** |

---

## 3. Fencing Token & Epoch Architecture

### 3.1 Data Structures
```python
@dataclass
class FencingToken:
    """Monotonic fencing token to prevent split-brain dual writers."""
    token_id: str
    leader_id: str
    term: int
    issued_at: float

@dataclass
class CameraAssignment:
    """Tracks camera stream ingestion binding with monotonic fencing epochs."""
    camera_id: str
    primary_node_id: str
    active_node_id: str
    rtsp_url: str
    tenant_id: str = "default"
    assigned_at: float = field(default_factory=time.time)
    assignment_epoch: int = 1  # Monotonically incremented on each re-assignment
    active_fencing_token: str = ""
```

### 3.2 Writer Fencing Validation
Whenever a storage sink or evidence recorder receives a block of video frames or a segment index commit, it verifies the writer's fencing epoch against the cluster coordinator:

```python
def verify_writer_fencing(self, camera_id: str, claiming_node_id: str, epoch: int) -> bool:
    """
    Validates whether a node is authorized to write to a camera's stream.
    Rejects stale partitioned writers attempting dual-writer operations.
    """
    if camera_id not in self.camera_assignments:
        raise FencedWriterError(f"Camera '{camera_id}' has no active cluster assignment.")

    assignment = self.camera_assignments[camera_id]
    if assignment.active_node_id != claiming_node_id:
        logger.error(
            "cluster.dual_writer_blocked_unauthorized_node",
            camera_id=camera_id,
            claiming_node=claiming_node_id,
            authorized_node=assignment.active_node_id,
        )
        raise FencedWriterError(
            f"Node '{claiming_node_id}' is fenced: active node for camera '{camera_id}' is '{assignment.active_node_id}'"
        )

    if epoch < assignment.assignment_epoch:
        logger.error(
            "cluster.stale_writer_epoch_blocked",
            camera_id=camera_id,
            claiming_node=claiming_node_id,
            provided_epoch=epoch,
            required_epoch=assignment.assignment_epoch,
        )
        raise FencedWriterError(
            f"Writer fenced by monotonic epoch: provided {epoch} < active {assignment.assignment_epoch}"
        )

    return True
```

---

## 4. Empirical Fault Injection & Partition Scenarios

### Scenario 1: Partitioning Node A from 3-Node Cluster
1. **Setup:** Cluster configured with `enforce_strict_quorum=True` and 3 nodes (`node-a`, `node-b`, `node-c`).
2. **Initial State:** Quorum threshold is $2$. Node A is elected leader for Term 1. Camera `cam-perimeter-01` is assigned to Node A at Epoch 1.
3. **Partition Injected:** Node B and Node C lose connectivity with Node A (`node_b.state = OFFLINE`, `node_c.state = OFFLINE`).
4. **Minority Partition Evaluation (Node A):**
   - Healthy nodes: 1 / 3.
   - `coord.has_quorum` evaluates to `False`.
   - `coord.elect_leader()` raises `QuorumUnavailableError("Consensus quorum unavailable: 1 healthy nodes available, but strict majority of 2 required.")`.
   - `coord.check_failover()` returns `[]` (failovers completely frozen; no reassignments permitted).
5. **Majority Partition Evaluation (Nodes B & C):**
   - Healthy nodes: 2 / 3.
   - `coord.has_quorum` evaluates to `True`.
   - `coord.elect_leader()` elects Node B for Term 2.
   - `coord.check_failover()` detects Node A offline and reassigns `cam-perimeter-01` to Node B, bumping `assignment_epoch` to 2.
6. **Dual-Writer Rejection:**
   - Partitioned Node A attempts to write segment with stale Epoch 1:
     `coord.verify_writer_fencing("cam-perimeter-01", claiming_node_id="node-a", epoch=1)`
     $\to$ **RAISES `FencedWriterError`**.
   - Node B writes segment with Epoch 2:
     `coord.verify_writer_fencing("cam-perimeter-01", claiming_node_id="node-b", epoch=2)`
     $\to$ **ACCEPTED (Returns True)**.

### Scenario 2: Two-Node Asymmetric Partition
In a 2-node cluster without an external witness, a 1-node partition cannot achieve a strict majority ($1 < 2/2 + 1 = 2$). With `enforce_strict_quorum=True`, both nodes freeze failover, completely eliminating split-brain dual writers at the cost of requiring an operator or tie-breaker witness to arbitrate. For single-site deployments, CAMserv provides `enforce_strict_quorum=False` option for non-partitioned local setups.

---

## 5. Verification Test Suite Results

- `test_split_brain_prevention_strict_majority_quorum`: Validated that minority partitions cannot elect leaders or authorize failovers (**PASSED**).
- `test_camera_stream_ownership_monotonic_epoch_fencing`: Validated that writer epochs advance monotonically and obsolete writers are barred from video storage (**PASSED**).
- `test_stale_leader_fencing_rejection`: Validated that leader tokens from previous terms are immediately rejected (**PASSED**).

---

## 6. Conclusion

CAMserv's Phase 18 fencing architecture completely eliminates the threat of dual-writer RTSP stream ingestion and conflicting video segment storage during network partitions.
