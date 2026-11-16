# Phase 17: Cluster Failover & Automated Ingestion Orchestration Report

**Target Release:** 0.10.0-rc1  
**Primary Module:** `src/camserv/central/cluster.py` (`ClusterCoordinator`)  
**Classification:** `IMPLEMENTED_AND_TESTED`  

---

## 1. Executive Summary

In mission-critical enterprise surveillance, camera recording must not stop when an NVR appliance suffers a hardware failure, power loss, or network partition. Phase 17 validates the implementation of automated, dynamic camera stream failover across cluster nodes.

---

## 2. Failover State Machine

```
              +---------------------------+
              |    ONLINE (Ingesting)     |
              +---------------------------+
                            |
                 Heartbeat Timeout (t > 10s)
                            v
              +---------------------------+
              |          OFFLINE          |
              +---------------------------+
                            |
                     Evacuate Cameras
                            v
              +---------------------------+
              |       FAILING_OVER        |
              | Re-assigning to Surviving |
              |  Nodes with Free Channels |
              +---------------------------+
                            |
                    Failover Complete
                            v
              +---------------------------+
              |     BACKUP INGESTING      |
              | (Surviving Node Records)  |
              +---------------------------+
```

---

## 3. Dynamic Load Balancing & Evacuation Algorithm

1. **Capacity Accounting:** Each node specifies `capacity_channels` (default: 16). Load is calculated as `current_load = len(assigned_cameras)`.
2. **Channel Assignment:** Cameras are placed on nodes minimizing load variance:
   $$\text{Target Node} = \arg\min_{n \in \text{Eligible}} (\text{load}(n), \text{node\_id}(n))$$
3. **Emergency Evacuation:** When a node times out:
   - Its assigned camera list is extracted and cleared.
   - For each orphaned camera, surviving nodes are sorted by lowest current load and capacity.
   - Ingestion connection strings (RTSP URLs) are transferred to the backup node.
   - An immutable failover audit event is logged with microsecond timestamps.

---

## 4. Verification Evidence

- **Unit Test:** `test_cluster_node_heartbeat_timeout_and_failover` — PASSED.
  - Successfully detected node timeout on `nvr-alpha`.
  - Automatically re-routed 2 orphaned camera streams to `nvr-beta`.
  - Re-established zero unassigned channels.
- **Unit Test:** `test_cluster_node_quarantine_and_channel_evacuation` — PASSED.
