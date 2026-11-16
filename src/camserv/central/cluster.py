"""
camserv.central.cluster
=======================

Multi-Node Cluster Orchestration, Leader Election, and Dynamic Camera Failover.
Enables high-availability NVR clustering across Debian edge appliances and Windows nodes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ClusterNodeRole(str, Enum):
    LEADER = "LEADER"
    FOLLOWER = "FOLLOWER"
    STANDBY = "STANDBY"


class ClusterNodeState(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    QUARANTINED = "QUARANTINED"
    FAILING_OVER = "FAILING_OVER"


@dataclass
class ClusterNode:
    """Represents a member node within the CAMserv cluster."""

    node_id: str
    site_id: str
    address: str
    capacity_channels: int = 16
    role: ClusterNodeRole = ClusterNodeRole.FOLLOWER
    state: ClusterNodeState = ClusterNodeState.ONLINE
    assigned_cameras: list[str] = field(default_factory=list)
    last_heartbeat: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current_load(self) -> int:
        return len(self.assigned_cameras)

    @property
    def has_capacity(self) -> bool:
        return self.current_load < self.capacity_channels and self.state == ClusterNodeState.ONLINE


@dataclass
class CameraAssignment:
    """Tracks camera stream ingestion binding across the cluster."""

    camera_id: str
    primary_node_id: str
    active_node_id: str
    rtsp_url: str
    is_active: bool = True
    failover_timestamp: float | None = None


class ClusterCoordinator:
    """
    Orchestrates cluster membership, leader consensus, and automated camera channel failover.
    """

    def __init__(
        self,
        local_node_id: str,
        site_id: str,
        heartbeat_timeout_sec: float = 10.0,
    ) -> None:
        self.local_node_id = local_node_id
        self.site_id = site_id
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.nodes: dict[str, ClusterNode] = {}
        self.cameras: dict[str, CameraAssignment] = {}
        self.current_leader_id: str | None = None
        self.failover_history: list[dict[str, Any]] = []

    def register_node(self, node: ClusterNode) -> bool:
        """Register a node in the cluster directory."""
        if node.node_id in self.nodes and self.nodes[node.node_id].state == ClusterNodeState.QUARANTINED:
            logger.warning("cluster.register_rejected_quarantined", node_id=node.node_id)
            return False

        self.nodes[node.node_id] = node
        logger.info("cluster.node_registered", node_id=node.node_id, role=node.role.value)

        # Trigger leader election if no active leader exists
        if not self.current_leader_id or self.current_leader_id not in self.nodes:
            self.elect_leader()
        return True

    def heartbeat(self, node_id: str, telemetry: dict[str, Any] | None = None) -> bool:
        """Process keepalive heartbeat from a cluster node."""
        if node_id not in self.nodes:
            return False

        node = self.nodes[node_id]
        if node.state == ClusterNodeState.QUARANTINED:
            return False

        node.last_heartbeat = time.time()
        if node.state == ClusterNodeState.OFFLINE:
            node.state = ClusterNodeState.ONLINE
            logger.info("cluster.node_recovered", node_id=node_id)

        if telemetry:
            node.metadata.update(telemetry)
        return True

    def elect_leader(self) -> str | None:
        """
        Consensus leader election: selects the healthy node with highest priority / lowest ID.
        """
        healthy_nodes = [
            n for n in self.nodes.values()
            if n.state in (ClusterNodeState.ONLINE, ClusterNodeState.DEGRADED)
        ]
        if not healthy_nodes:
            self.current_leader_id = None
            return None

        # Sort deterministically by node_id
        sorted_nodes = sorted(healthy_nodes, key=lambda n: n.node_id)
        new_leader = sorted_nodes[0]

        for n in self.nodes.values():
            if n.node_id == new_leader.node_id:
                n.role = ClusterNodeRole.LEADER
            else:
                n.role = ClusterNodeRole.FOLLOWER

        self.current_leader_id = new_leader.node_id
        logger.info("cluster.leader_elected", leader_id=self.current_leader_id)
        return self.current_leader_id

    def assign_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        preferred_node_id: str | None = None,
    ) -> str:
        """Assign an ingestion channel to the optimal cluster node."""
        target_node: ClusterNode | None = None

        if preferred_node_id and preferred_node_id in self.nodes:
            pref = self.nodes[preferred_node_id]
            if pref.has_capacity:
                target_node = pref

        if target_node is None:
            # Find node with lowest load that has capacity
            eligible = [n for n in self.nodes.values() if n.has_capacity]
            if not eligible:
                raise RuntimeError("Cluster capacity exhausted: no available nodes with free channels")
            eligible.sort(key=lambda n: (n.current_load, n.node_id))
            target_node = eligible[0]

        if camera_id not in target_node.assigned_cameras:
            target_node.assigned_cameras.append(camera_id)

        assignment = CameraAssignment(
            camera_id=camera_id,
            primary_node_id=target_node.node_id,
            active_node_id=target_node.node_id,
            rtsp_url=rtsp_url,
        )
        self.cameras[camera_id] = assignment
        logger.info("cluster.camera_assigned", camera=camera_id, node=target_node.node_id)
        return target_node.node_id

    def check_cluster_health(self) -> dict[str, Any]:
        """Audit heartbeats, identify dead nodes, and trigger automated failovers."""
        now = time.time()
        dead_nodes: list[str] = []

        for node_id, node in self.nodes.items():
            if node.state == ClusterNodeState.QUARANTINED:
                continue

            if (now - node.last_heartbeat) > self.heartbeat_timeout_sec:
                if node.state != ClusterNodeState.OFFLINE:
                    node.state = ClusterNodeState.OFFLINE
                    dead_nodes.append(node_id)
                    logger.warning("cluster.node_timed_out", node_id=node_id)

        # Trigger failover for all dead nodes
        failover_results: list[CameraAssignment] = []
        for dead_id in dead_nodes:
            failover_results.extend(self.failover_node(dead_id))

        # Re-elect leader if leader went down
        if self.current_leader_id in dead_nodes or not self.current_leader_id:
            self.elect_leader()

        return {
            "healthy_count": len([n for n in self.nodes.values() if n.state == ClusterNodeState.ONLINE]),
            "dead_nodes": dead_nodes,
            "failovers_executed": len(failover_results),
            "leader_id": self.current_leader_id,
        }

    def failover_node(self, failed_node_id: str) -> list[CameraAssignment]:
        """Evacuate and reassign cameras from a failed node to available online nodes."""
        failed_node = self.nodes.get(failed_node_id)
        if not failed_node or not failed_node.assigned_cameras:
            return []

        reassigned: list[CameraAssignment] = []
        orphaned_cameras = list(failed_node.assigned_cameras)
        failed_node.assigned_cameras.clear()

        for cam_id in orphaned_cameras:
            assignment = self.cameras.get(cam_id)
            if not assignment:
                continue

            # Select backup node with available capacity
            candidates = [
                n for n in self.nodes.values()
                if n.node_id != failed_node_id and n.has_capacity
            ]
            if not candidates:
                logger.error("cluster.failover_exhausted", camera=cam_id)
                continue

            candidates.sort(key=lambda n: (n.current_load, n.node_id))
            backup_node = candidates[0]
            backup_node.assigned_cameras.append(cam_id)

            assignment.active_node_id = backup_node.node_id
            assignment.failover_timestamp = time.time()
            reassigned.append(assignment)

            event = {
                "timestamp": assignment.failover_timestamp,
                "camera_id": cam_id,
                "from_node": failed_node_id,
                "to_node": backup_node.node_id,
            }
            self.failover_history.append(event)
            logger.warning("cluster.camera_failed_over", **event)

        return reassigned

    def quarantine_node(self, node_id: str, reason: str) -> bool:
        """Instantly isolate a compromised node and evacuate its channels."""
        if node_id not in self.nodes:
            return False

        node = self.nodes[node_id]
        node.state = ClusterNodeState.QUARANTINED
        node.metadata["quarantine_reason"] = reason
        logger.error("cluster.node_quarantined", node_id=node_id, reason=reason)

        # Evacuate assigned cameras
        self.failover_node(node_id)

        # Re-elect if leader was quarantined
        if self.current_leader_id == node_id:
            self.elect_leader()
        return True

    def get_cluster_overview(self) -> dict[str, Any]:
        """Summary of cluster status, leader, channels, and nodes."""
        return {
            "site_id": self.site_id,
            "leader_id": self.current_leader_id,
            "total_nodes": len(self.nodes),
            "online_nodes": len([n for n in self.nodes.values() if n.state == ClusterNodeState.ONLINE]),
            "quarantined_nodes": len([n for n in self.nodes.values() if n.state == ClusterNodeState.QUARANTINED]),
            "total_cameras": len(self.cameras),
            "active_failovers": len(self.failover_history),
            "nodes": {
                nid: {
                    "role": n.role.value,
                    "state": n.state.value,
                    "load": n.current_load,
                    "capacity": n.capacity_channels,
                    "cameras": n.assigned_cameras,
                }
                for nid, n in self.nodes.items()
            },
        }
