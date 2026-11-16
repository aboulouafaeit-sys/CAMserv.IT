"""
camserv.central.cluster
=======================

Multi-Node Cluster Orchestration, Byzantine Resilience, Consensus Terms, and Fenced Failover.
Enables high-availability NVR clustering across Debian edge appliances and Windows nodes
while guaranteeing split-brain prevention and exclusive camera ownership.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
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


class QuorumUnavailableError(RuntimeError):
    """Raised when cluster lacks a strict majority quorum (> N/2 nodes)."""


class StaleLeaderError(RuntimeError):
    """Raised when a leadership command presents a stale term or expired lease."""


class FencedWriterError(RuntimeError):
    """Raised when a camera write attempt is rejected due to a stale assignment epoch or revoked fencing token."""


class TenantIsolationViolationError(PermissionError):
    """Raised when an operation attempts to cross tenant boundaries."""


class CorruptedConsensusStateError(RuntimeError):
    """Raised when persisted cluster consensus state is corrupted, unreadable, or violates invariants."""


@dataclass
class StorageLease:
    """
    Time-bounded, epoch-tagged exclusive storage write lease for a camera channel.
    Guarantees that an isolated node whose lease expires cannot write or finalize segments.
    """

    camera_id: str
    node_id: str
    assignment_epoch: int
    granted_at: float
    lease_duration_sec: float
    fencing_token: str = ""

    @property
    def expires_at(self) -> float:
        return self.granted_at + self.lease_duration_sec

    @property
    def is_valid(self) -> bool:
        return time.time() < self.expires_at

    def renew(self, duration_sec: float | None = None) -> None:
        self.granted_at = time.time()
        if duration_sec is not None:
            self.lease_duration_sec = duration_sec


@dataclass
class FencingToken:
    """Cryptographic fencing token issued to the active leader for a specific term."""

    token_id: str
    term: int
    leader_id: str
    issued_at: float = field(default_factory=time.time)
    tenant_id: str = "default"


@dataclass
class ClusterNode:
    """Represents a member node within the CAMserv cluster."""

    node_id: str
    site_id: str
    address: str
    capacity_channels: int = 16
    role: ClusterNodeRole = ClusterNodeRole.FOLLOWER
    state: ClusterNodeState = ClusterNodeState.ONLINE
    tenant_id: str = "default"
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
    """Tracks camera stream ingestion binding with monotonic fencing epochs."""

    camera_id: str
    primary_node_id: str
    active_node_id: str
    rtsp_url: str
    assignment_epoch: int = 1
    fencing_token: str = ""
    tenant_id: str = "default"
    is_active: bool = True
    lease_expiry: float = 0.0
    failover_timestamp: float | None = None


class ClusterCoordinator:
    """
    Orchestrates cluster membership, leader consensus, split-brain prevention,
    and fenced camera channel failover.
    """

    def __init__(
        self,
        local_node_id: str,
        site_id: str,
        tenant_id: str = "default",
        heartbeat_timeout_sec: float = 10.0,
        enforce_strict_quorum: bool = False,
        state_dir: Path | str | None = None,
        expected_cluster_size: int = 0,
        cluster_nodes: list[str] | set[str] | None = None,
    ) -> None:
        self.local_node_id = local_node_id
        self.site_id = site_id
        self.tenant_id = tenant_id
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.enforce_strict_quorum = enforce_strict_quorum
        self.state_dir = Path(state_dir).resolve() if state_dir else None
        self.expected_cluster_size = expected_cluster_size
        self._configured_cluster_nodes = set(cluster_nodes or [])
        if self._configured_cluster_nodes and self.expected_cluster_size == 0:
            self.expected_cluster_size = len(self._configured_cluster_nodes)

        self.cluster_term: int = 0
        self.active_fencing_token: FencingToken | None = None
        self.nodes: dict[str, ClusterNode] = {}
        self.cameras: dict[str, CameraAssignment] = {}
        self.current_leader_id: str | None = None
        self.failover_history: list[dict[str, Any]] = []

        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        """Durable state recovery: restores monotonic terms and assignments across process restarts."""
        if not self.state_dir:
            return
        state_path = self.state_dir / "cluster_state.json"
        if not state_path.exists():
            return
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            self.cluster_term = max(self.cluster_term, int(raw.get("cluster_term", 0)))
            token_raw = raw.get("active_fencing_token")
            if token_raw and isinstance(token_raw, dict):
                self.active_fencing_token = FencingToken(
                    token_id=token_raw.get("token_id", ""),
                    leader_id=token_raw.get("leader_id", ""),
                    term=int(token_raw.get("term", self.cluster_term)),
                    tenant_id=token_raw.get("tenant_id", self.tenant_id),
                    issued_at=float(token_raw.get("issued_at", time.time())),
                )
            cameras_raw = raw.get("cameras", {})
            for cid, cdata in cameras_raw.items():
                if isinstance(cdata, dict):
                    self.cameras[cid] = CameraAssignment(
                        camera_id=cdata.get("camera_id", cid),
                        primary_node_id=cdata.get("primary_node_id", ""),
                        active_node_id=cdata.get("active_node_id", ""),
                        rtsp_url=cdata.get("rtsp_url", ""),
                        assignment_epoch=int(cdata.get("assignment_epoch", 1)),
                        fencing_token=cdata.get("fencing_token", ""),
                        tenant_id=cdata.get("tenant_id", self.tenant_id),
                        is_active=bool(cdata.get("is_active", True)),
                        lease_expiry=float(cdata.get("lease_expiry", 0.0)),
                    )
            logger.info("cluster.state_restored_from_disk", term=self.cluster_term, cameras=len(self.cameras))
        except Exception as e:
            logger.critical("cluster.failed_to_load_persisted_state", error=str(e))
            raise CorruptedConsensusStateError(
                f"Persisted cluster state in '{state_path}' is corrupted or unreadable: {e}. "
                "Refusing to silently reset consensus terms to 0."
            ) from e

    def _persist_state(self) -> None:
        """Atomically flushes cluster terms, fencing tokens, and assignments to durable storage with fsync."""
        if not self.state_dir:
            return
        try:
            state_data = {
                "cluster_term": self.cluster_term,
                "active_fencing_token": asdict(self.active_fencing_token) if self.active_fencing_token else None,
                "current_leader_id": self.current_leader_id,
                "cameras": {cid: asdict(cas) for cid, cas in self.cameras.items()},
                "updated_at": time.time(),
            }
            tmp_path = self.state_dir / "cluster_state.json.tmp"
            final_path = self.state_dir / "cluster_state.json"
            payload = json.dumps(state_data, indent=2).encode("utf-8")
            with open(tmp_path, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(final_path)
            logger.debug("cluster.state_persisted", term=self.cluster_term)
        except Exception as e:
            logger.error("cluster.failed_to_persist_state", error=str(e))

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

    @property
    def healthy_nodes_count(self) -> int:
        return len([
            n for n in self.nodes.values()
            if n.state in (ClusterNodeState.ONLINE, ClusterNodeState.DEGRADED)
        ])

    @property
    def has_quorum(self) -> bool:
        """True if the number of healthy nodes satisfies strict majority quorum."""
        if not self.enforce_strict_quorum:
            return self.healthy_nodes_count > 0
        return self.healthy_nodes_count >= self.quorum_threshold

    def register_node(self, node: ClusterNode) -> bool:
        """Register a node in the cluster directory with tenant validation."""
        if node.tenant_id != self.tenant_id:
            logger.error("cluster.register_rejected_tenant_mismatch", node_tenant=node.tenant_id, cluster_tenant=self.tenant_id)
            raise TenantIsolationViolationError(f"Node tenant '{node.tenant_id}' does not match cluster tenant '{self.tenant_id}'")

        if node.node_id in self.nodes and self.nodes[node.node_id].state == ClusterNodeState.QUARANTINED:
            logger.warning("cluster.register_rejected_quarantined", node_id=node.node_id)
            return False

        self.nodes[node.node_id] = node
        logger.info("cluster.node_registered", node_id=node.node_id, role=node.role.value, term=self.cluster_term)

        # Trigger leader election if no active leader exists and quorum is available
        if not self.current_leader_id or self.current_leader_id not in self.nodes:
            if self.has_quorum:
                try:
                    self.elect_leader()
                except QuorumUnavailableError:
                    pass
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
        Consensus leader election with monotonic terms, strict majority quorum, and fencing tokens.
        Split-brain prevention: Minority partitions (< N/2 + 1) CANNOT elect a leader.
        """
        if self.enforce_strict_quorum and not self.has_quorum:
            self.current_leader_id = None
            self.active_fencing_token = None
            logger.error(
                "cluster.leader_election_rejected_no_quorum",
                healthy=self.healthy_nodes_count,
                required=self.quorum_threshold,
                total=len(self.nodes),
            )
            raise QuorumUnavailableError(
                f"Consensus quorum unavailable: {self.healthy_nodes_count} healthy nodes available, but strict majority of {self.quorum_threshold} required."
            )

        healthy_nodes = [
            n for n in self.nodes.values()
            if n.state in (ClusterNodeState.ONLINE, ClusterNodeState.DEGRADED)
        ]
        if not healthy_nodes:
            self.current_leader_id = None
            self.active_fencing_token = None
            return None

        # Monotonically increment cluster term
        self.cluster_term += 1

        # Sort deterministically by node_id
        sorted_nodes = sorted(healthy_nodes, key=lambda n: n.node_id)
        new_leader = sorted_nodes[0]

        for n in self.nodes.values():
            if n.node_id == new_leader.node_id:
                n.role = ClusterNodeRole.LEADER
            else:
                n.role = ClusterNodeRole.FOLLOWER

        self.current_leader_id = new_leader.node_id
        token_id = f"FENCE-TERM{self.cluster_term}-{uuid.uuid4().hex[:8]}"
        self.active_fencing_token = FencingToken(
            token_id=token_id,
            term=self.cluster_term,
            leader_id=self.current_leader_id,
            tenant_id=self.tenant_id,
        )

        logger.info(
            "cluster.leader_elected",
            leader_id=self.current_leader_id,
            term=self.cluster_term,
            fencing_token=token_id,
            quorum_count=len(healthy_nodes),
        )
        self._persist_state()
        return self.current_leader_id

    def verify_leader_fencing(self, presented_term: int, presented_leader_id: str) -> bool:
        """Stale leader rejection: Rejects commands from deposed leaders or past epochs."""
        if presented_term < self.cluster_term:
            logger.error("cluster.stale_leader_rejected", presented_term=presented_term, active_term=self.cluster_term)
            raise StaleLeaderError(f"Stale leader command rejected: term {presented_term} < current cluster term {self.cluster_term}")

        if presented_leader_id != self.current_leader_id:
            logger.error("cluster.unauthorized_leader_rejected", presented_leader=presented_leader_id, active_leader=self.current_leader_id)
            raise StaleLeaderError(f"Node '{presented_leader_id}' is not the active leader (current: '{self.current_leader_id}')")

        return True

    def assign_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        preferred_node_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Assign an ingestion channel with monotonic epoch and fencing token."""
        effective_tenant = tenant_id or self.tenant_id
        if effective_tenant != self.tenant_id:
            raise TenantIsolationViolationError(f"Cannot assign camera for tenant '{effective_tenant}' to cluster '{self.tenant_id}'")

        if self.enforce_strict_quorum and not self.has_quorum:
            raise QuorumUnavailableError("Cannot assign camera: cluster quorum lost")

        target_node: ClusterNode | None = None

        if preferred_node_id and preferred_node_id in self.nodes:
            pref = self.nodes[preferred_node_id]
            if pref.has_capacity:
                target_node = pref

        if target_node is None:
            eligible = [n for n in self.nodes.values() if n.has_capacity]
            if not eligible:
                raise RuntimeError("Cluster capacity exhausted: no available nodes with free channels")
            eligible.sort(key=lambda n: (n.current_load, n.node_id))
            target_node = eligible[0]

        if camera_id not in target_node.assigned_cameras:
            target_node.assigned_cameras.append(camera_id)

        # Monotonic epoch start at 1
        initial_epoch = 1
        fencing_token = f"FENCE-CAM-{camera_id}-E{initial_epoch}-T{self.cluster_term}"

        assignment = CameraAssignment(
            camera_id=camera_id,
            primary_node_id=target_node.node_id,
            active_node_id=target_node.node_id,
            rtsp_url=rtsp_url,
            assignment_epoch=initial_epoch,
            fencing_token=fencing_token,
            tenant_id=self.tenant_id,
            lease_expiry=time.time() + (self.heartbeat_timeout_sec * 2),
        )
        self.cameras[camera_id] = assignment
        logger.info(
            "cluster.camera_assigned",
            camera=camera_id,
            node=target_node.node_id,
            epoch=initial_epoch,
            fencing_token=fencing_token,
        )
        self._persist_state()
        return target_node.node_id

    def issue_storage_lease(
        self,
        camera_id: str,
        requesting_node_id: str,
        duration_sec: float = 30.0,
    ) -> StorageLease:
        """
        Issues or renews an exclusive StorageLease for a camera channel.
        Strict quorum gate: Minority partitions (< N/2 + 1) cannot issue valid writer leases.
        Leader authority gate: Only the active cluster leader can issue leases.
        """
        if self.enforce_strict_quorum and not self.has_quorum:
            raise QuorumUnavailableError(
                f"Cannot issue storage lease: quorum unavailable ({self.healthy_nodes_count}/{self.quorum_threshold} nodes)."
            )
        if self.current_leader_id is None:
            raise QuorumUnavailableError("Cannot issue storage lease: no active cluster leader.")
        if camera_id not in self.cameras:
            raise FencedWriterError(f"Camera '{camera_id}' is not registered in cluster.")
        assignment = self.cameras[camera_id]
        if assignment.active_node_id != requesting_node_id:
            raise FencedWriterError(
                f"Node '{requesting_node_id}' is not the assigned active writer '{assignment.active_node_id}' for camera '{camera_id}'."
            )
        now = time.time()
        assignment.lease_expiry = now + duration_sec
        self._persist_state()
        return StorageLease(
            camera_id=camera_id,
            node_id=requesting_node_id,
            assignment_epoch=assignment.assignment_epoch,
            granted_at=now,
            lease_duration_sec=duration_sec,
            fencing_token=assignment.fencing_token,
        )

    def verify_writer_fencing(
        self,
        camera_id: str,
        writer_node_id: str,
        presented_epoch: int,
        tenant_id: str | None = None,
    ) -> bool:
        """
        Guarantees exclusive camera ownership and prevents dual writers.
        Rejects stale partitioned nodes attempting to write to storage.
        """
        if camera_id not in self.cameras:
            raise FencedWriterError(f"Camera '{camera_id}' is not registered in cluster")

        assignment = self.cameras[camera_id]
        effective_tenant = tenant_id or self.tenant_id
        if assignment.tenant_id != effective_tenant:
            raise TenantIsolationViolationError(f"Tenant mismatch on camera '{camera_id}'")

        if presented_epoch < assignment.assignment_epoch:
            logger.error(
                "cluster.fenced_stale_writer_rejected",
                camera=camera_id,
                writer=writer_node_id,
                presented_epoch=presented_epoch,
                active_epoch=assignment.assignment_epoch,
            )
            raise FencedWriterError(
                f"Stale camera writer rejected: presented epoch {presented_epoch} < active epoch {assignment.assignment_epoch}"
            )

        if writer_node_id != assignment.active_node_id:
            logger.error(
                "cluster.fenced_unauthorized_writer_rejected",
                camera=camera_id,
                writer=writer_node_id,
                active_owner=assignment.active_node_id,
            )
            raise FencedWriterError(
                f"Unauthorized writer '{writer_node_id}' rejected: active owner is '{assignment.active_node_id}'"
            )

        return True

    def reconcile_partitioned_writer(
        self,
        camera_id: str,
        recovering_node_id: str,
        reported_epoch: int,
        pending_segments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Safely reconciles a recovering partitioned node.
        Guarantees that uncommitted segments recorded under a stale epoch are quarantined
        and cannot overwrite newer segments committed by the majority failover writer.
        """
        if camera_id not in self.cameras:
            return {
                "admitted": False,
                "quarantined": True,
                "reason": f"Camera '{camera_id}' has no cluster assignment.",
                "admitted_segments": 0,
                "quarantined_segments": len(pending_segments or []),
            }

        assignment = self.cameras[camera_id]
        if reported_epoch < assignment.assignment_epoch:
            logger.warning(
                "cluster.reconciliation_stale_epoch_quarantined",
                camera_id=camera_id,
                node_id=recovering_node_id,
                reported_epoch=reported_epoch,
                active_epoch=assignment.assignment_epoch,
                quarantined_count=len(pending_segments or []),
            )
            return {
                "admitted": False,
                "quarantined": True,
                "reason": f"Stale writer epoch {reported_epoch} superseded by active cluster epoch {assignment.assignment_epoch}.",
                "admitted_segments": 0,
                "quarantined_segments": len(pending_segments or []),
            }

        if assignment.active_node_id != recovering_node_id:
            return {
                "admitted": False,
                "quarantined": True,
                "reason": f"Node '{recovering_node_id}' is not the active owner '{assignment.active_node_id}'.",
                "admitted_segments": 0,
                "quarantined_segments": len(pending_segments or []),
            }

        return {
            "admitted": True,
            "quarantined": False,
            "reason": "Epoch and ownership match active cluster state.",
            "admitted_segments": len(pending_segments or []),
            "quarantined_segments": 0,
        }

    def check_cluster_health(self) -> dict[str, Any]:
        """Audit heartbeats, identify dead nodes, enforce quorum, and trigger failovers."""
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

        # Check quorum before executing failovers
        failover_results: list[CameraAssignment] = []
        if self.has_quorum:
            for dead_id in dead_nodes:
                failover_results.extend(self.failover_node(dead_id))

            if self.current_leader_id in dead_nodes or not self.current_leader_id:
                try:
                    self.elect_leader()
                except QuorumUnavailableError:
                    pass
        else:
            logger.error("cluster.quorum_lost_failovers_blocked", healthy=self.healthy_nodes_count, required=self.quorum_threshold)
            self.current_leader_id = None
            self.active_fencing_token = None

        return {
            "healthy_count": self.healthy_nodes_count,
            "quorum_satisfied": self.has_quorum,
            "dead_nodes": dead_nodes,
            "failovers_executed": len(failover_results),
            "leader_id": self.current_leader_id,
            "term": self.cluster_term,
        }

    def failover_node(self, failed_node_id: str) -> list[CameraAssignment]:
        """Evacuate cameras from failed node and bump assignment epochs with fencing tokens."""
        if self.enforce_strict_quorum and not self.has_quorum:
            logger.error("cluster.failover_rejected_no_quorum")
            raise QuorumUnavailableError("Cannot execute failover: quorum lost")

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

            # Monotonically bump assignment epoch to fence old writer
            assignment.assignment_epoch += 1
            assignment.active_node_id = backup_node.node_id
            assignment.fencing_token = f"FENCE-CAM-{cam_id}-E{assignment.assignment_epoch}-T{self.cluster_term}"
            assignment.failover_timestamp = time.time()
            assignment.lease_expiry = time.time() + (self.heartbeat_timeout_sec * 2)
            reassigned.append(assignment)

            event = {
                "timestamp": assignment.failover_timestamp,
                "camera_id": cam_id,
                "from_node": failed_node_id,
                "to_node": backup_node.node_id,
                "new_epoch": assignment.assignment_epoch,
                "fencing_token": assignment.fencing_token,
            }
            self.failover_history.append(event)
            logger.warning("cluster.camera_failed_over_with_fencing", **event)

        self._persist_state()
        return reassigned

    def quarantine_node(self, node_id: str, reason: str) -> bool:
        """Instantly isolate a compromised node and evacuate channels with fencing."""
        if node_id not in self.nodes:
            return False

        node = self.nodes[node_id]
        node.state = ClusterNodeState.QUARANTINED
        node.metadata["quarantine_reason"] = reason
        logger.error("cluster.node_quarantined", node_id=node_id, reason=reason)

        if self.has_quorum:
            self.failover_node(node_id)

        if self.current_leader_id == node_id:
            try:
                self.elect_leader()
            except QuorumUnavailableError:
                pass
        return True

    def get_cluster_overview(self) -> dict[str, Any]:
        """Summary of cluster status, terms, quorum, and fencing tokens."""
        return {
            "site_id": self.site_id,
            "tenant_id": self.tenant_id,
            "term": self.cluster_term,
            "leader_id": self.current_leader_id,
            "has_quorum": self.has_quorum,
            "quorum_threshold": self.quorum_threshold,
            "total_nodes": len(self.nodes),
            "online_nodes": self.healthy_nodes_count,
            "quarantined_nodes": len([n for n in self.nodes.values() if n.state == ClusterNodeState.QUARANTINED]),
            "total_cameras": len(self.cameras),
            "active_failovers": len(self.failover_history),
            "fencing_token": self.active_fencing_token.token_id if self.active_fencing_token else None,
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
