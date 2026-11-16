"""
tests/test_distributed_phase18_qualification.py
===============================================

Phase 18 Comprehensive Distributed Systems Verification Suite:
1. Invariant: Audit log inviolate verification (20,977 bytes, matching SHA-256).
2. Distributed Consensus & Split-Brain Prevention (3-node topology, quorum threshold > N/2).
3. Stale Leader Rejection & Fencing Token Invalidation.
4. Camera Ownership Fencing: Monotonic epochs and rejection of stale dual writers.
5. Canonical Evidence Serialization (RFC 8785 / CAMSERV-FORENSIC-SEAL-V2) and delimiter injection defense.
6. Anti-Replay Nonce Validation on Peer Witness Attestations.
7. Merkle Tree Inclusion Proof Generation and Cryptographic Verification.
8. Zero-Trust mTLS SAN Identity Binding and Instant In-Flight Session Invalidation.
9. Enterprise Multi-Tenant Boundary Isolation.
10. Version Consistency Across API Endpoints and Package Manifests.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from camserv import __version__
from camserv.central.cluster import (
    CameraAssignment,
    ClusterCoordinator,
    ClusterNode,
    ClusterNodeRole,
    ClusterNodeState,
    FencedWriterError,
    FencingToken,
    QuorumUnavailableError,
    StaleLeaderError,
    TenantIsolationViolationError,
)
from camserv.central.mtls import (
    EnterpriseMtlsGateway,
    NodeCertificateInfo,
)
from camserv.central.replication import (
    DistributedReplicationEngine,
    EvidenceSealRecord,
    VerificationVerdict,
    WitnessAttestation,
)
from camserv.desktop.client import DesktopServiceClient


@pytest.mark.unit
def test_inviolate_audit_log_preserved() -> None:
    """Invariant Rule 1: Audit log must remain exactly 20,977 bytes with verified SHA-256."""
    audit_path = Path("logs/audit.jsonl")
    assert audit_path.exists(), "Audit log file is missing!"
    size = audit_path.stat().st_size
    assert size == 20977, f"Audit log size mismatch: got {size}, expected 20977 bytes"

    content = audit_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest().upper()
    assert (
        digest == "F2A2484A0395140C4449C359200D1763381176A4CC825F56F0E65F881FEC1525"
    ), f"Audit log SHA-256 mismatch: {digest}"


@pytest.mark.unit
def test_split_brain_prevention_strict_majority_quorum() -> None:
    """
    Split-Brain Simulation (Section 5.3):
    In a 3-node cluster (Node A, Node B, Node C), quorum threshold is 2 (floor(3/2) + 1).
    A network partition isolates Node A from {Node B, Node C}:
    - Minority partition {Node A} has 1 node: cannot elect a leader, raises QuorumUnavailableError.
    - Majority partition {Node B, Node C} has 2 nodes: elects Node B as leader for Term 2.
    """
    # Coordinator on minority partition (Node A alone)
    coord_minority = ClusterCoordinator(
        local_node_id="node-a",
        site_id="site-central",
        enforce_strict_quorum=True,
    )
    node_a = ClusterNode(node_id="node-a", site_id="site-central", address="10.0.1.10", capacity_channels=8)
    node_b = ClusterNode(node_id="node-b", site_id="site-central", address="10.0.1.11", capacity_channels=8)
    node_c = ClusterNode(node_id="node-c", site_id="site-central", address="10.0.1.12", capacity_channels=8)

    coord_minority.register_node(node_a)
    coord_minority.register_node(node_b)
    coord_minority.register_node(node_c)

    assert coord_minority.quorum_threshold == 2
    assert coord_minority.has_quorum is True

    # Initial election: Node A elected
    leader = coord_minority.elect_leader()
    assert leader == "node-a"
    assert coord_minority.cluster_term >= 1

    # Simulate partition: Node B and Node C disconnect from Node A
    node_b.state = ClusterNodeState.OFFLINE
    node_c.state = ClusterNodeState.OFFLINE

    assert coord_minority.has_quorum is False
    with pytest.raises(QuorumUnavailableError, match="strict majority of 2 required"):
        coord_minority.elect_leader()
    assert coord_minority.current_leader_id is None

    # Coordinator on majority partition {Node B, Node C}
    coord_majority = ClusterCoordinator(
        local_node_id="node-b",
        site_id="site-central",
        enforce_strict_quorum=True,
    )
    node_b_maj = ClusterNode(node_id="node-b", site_id="site-central", address="10.0.1.11", capacity_channels=8)
    node_c_maj = ClusterNode(node_id="node-c", site_id="site-central", address="10.0.1.12", capacity_channels=8)
    node_a_maj = ClusterNode(node_id="node-a", site_id="site-central", address="10.0.1.10", capacity_channels=8, state=ClusterNodeState.OFFLINE)

    coord_majority.register_node(node_a_maj)
    coord_majority.register_node(node_b_maj)
    coord_majority.register_node(node_c_maj)

    assert coord_majority.has_quorum is True
    majority_leader = coord_majority.elect_leader()
    assert majority_leader == "node-b"
    assert coord_majority.cluster_term == 1
    assert coord_majority.active_fencing_token is not None
    assert coord_majority.active_fencing_token.leader_id == "node-b"


@pytest.mark.unit
def test_stale_leader_fencing_rejection() -> None:
    """Verify that commands carrying stale leadership terms or unauthorized IDs are rejected."""
    coordinator = ClusterCoordinator(local_node_id="node-a", site_id="site-central")
    node_a = ClusterNode(node_id="node-a", site_id="site-central", address="10.0.1.10")
    coordinator.register_node(node_a)

    coordinator.elect_leader()
    active_term = coordinator.cluster_term
    assert active_term >= 1

    # Deposed leader presenting past term (active_term - 1)
    with pytest.raises(StaleLeaderError, match="Stale leader command rejected"):
        coordinator.verify_leader_fencing(presented_term=active_term - 1, presented_leader_id="node-a")

    # Unauthorized node pretending to be leader
    with pytest.raises(StaleLeaderError, match="is not the active leader"):
        coordinator.verify_leader_fencing(presented_term=active_term, presented_leader_id="node-rogue")

    # Valid leader command succeeds
    assert coordinator.verify_leader_fencing(presented_term=active_term, presented_leader_id="node-a") is True


@pytest.mark.unit
def test_camera_writer_fencing_epoch_and_dual_writer_prevention() -> None:
    """
    Verify camera ownership fencing:
    When a camera is failed over from Node A to Node B, its assignment epoch increments.
    If partitioned Node A attempts to continue writing, it is rejected with FencedWriterError.
    """
    coordinator = ClusterCoordinator(local_node_id="node-a", site_id="site-central")
    node_a = ClusterNode(node_id="node-a", site_id="site-central", address="10.0.1.10", capacity_channels=4)
    node_b = ClusterNode(node_id="node-b", site_id="site-central", address="10.0.1.11", capacity_channels=4)

    coordinator.register_node(node_a)
    coordinator.register_node(node_b)

    coordinator.assign_camera("cam-gate-01", "rtsp://10.0.1.201/h264", preferred_node_id="node-a")
    assignment = coordinator.cameras["cam-gate-01"]
    assert assignment.active_node_id == "node-a"
    assert assignment.assignment_epoch == 1

    # Node A writes with valid epoch 1 -> Accepted
    assert coordinator.verify_writer_fencing("cam-gate-01", writer_node_id="node-a", presented_epoch=1) is True

    # Failover occurs: Node A times out, Node B takes over -> Epoch bumps to 2
    coordinator.failover_node("node-a")
    assert assignment.active_node_id == "node-b"
    assert assignment.assignment_epoch == 2

    # Deposed Node A attempts to write presenting stale epoch 1 -> REJECTED
    with pytest.raises(FencedWriterError, match="Stale camera writer rejected"):
        coordinator.verify_writer_fencing("cam-gate-01", writer_node_id="node-a", presented_epoch=1)

    # Deposed Node A attempts to write even if guessing epoch 2 -> REJECTED (not active owner)
    with pytest.raises(FencedWriterError, match="Unauthorized writer 'node-a' rejected"):
        coordinator.verify_writer_fencing("cam-gate-01", writer_node_id="node-a", presented_epoch=2)

    # Legitimate owner Node B writes with epoch 2 -> Accepted
    assert coordinator.verify_writer_fencing("cam-gate-01", writer_node_id="node-b", presented_epoch=2) is True


@pytest.mark.unit
def test_canonical_evidence_serialization_and_delimiter_injection_immunity() -> None:
    """
    Verify canonical evidence serialization (RFC 8785 style):
    Ensure that delimiters (| or :) in field values cannot cause hash collisions or delimiter injection.
    """
    seal_clean = EvidenceSealRecord(
        segment_id="SEG-001",
        camera_id="cam-front",
        origin_node_id="node-alpha",
        sha256_hash="E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
        start_timestamp=100.0,
        end_timestamp=200.0,
        frame_count=3000,
        nonce="NONCE-01",
    )

    # Delimiter injection attempt: inject pipes and delimiters into camera_id
    seal_injected = EvidenceSealRecord(
        segment_id="SEG-001|cam-front",
        camera_id="",
        origin_node_id="node-alpha",
        sha256_hash="E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
        start_timestamp=100.0,
        end_timestamp=200.0,
        frame_count=3000,
        nonce="NONCE-01",
    )

    digest_clean = seal_clean.compute_canonical_evidence_digest()
    digest_injected = seal_injected.compute_canonical_evidence_digest()

    assert digest_clean != digest_injected, "Canonical serialization must be immune to delimiter injection"
    assert len(digest_clean) == 64


@pytest.mark.unit
def test_anti_replay_nonce_protection_on_attestations() -> None:
    """Verify that replaying a previously seen witness attestation is blocked."""
    engine = DistributedReplicationEngine(local_node_id="node-alpha", quorum_threshold=2)

    seal = EvidenceSealRecord(
        segment_id="SEG-REPLAY-001",
        camera_id="cam-01",
        origin_node_id="node-alpha",
        sha256_hash="AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899",
        start_timestamp=100.0,
        end_timestamp=200.0,
        frame_count=500,
    )
    digest = engine.register_evidence_seal(seal)

    attestation = WitnessAttestation(
        seal_digest=digest,
        witness_node_id="witness-beta",
        nonce="UNIQUE-NONCE-12345",
    )

    # First submission accepted
    assert engine.submit_witness_attestation(attestation, "SEG-REPLAY-001") is True

    # Replay attack: submitting identical attestation with same nonce -> REJECTED
    assert engine.submit_witness_attestation(attestation, "SEG-REPLAY-001") is False


@pytest.mark.unit
def test_merkle_tree_inclusion_proof_verification() -> None:
    """Verify Merkle inclusion proof generation and cryptographic verification."""
    engine = DistributedReplicationEngine(local_node_id="node-alpha")

    seals = [
        EvidenceSealRecord(f"SEG-{i}", f"cam-{i}", "node-alpha", f"HASH_{i}", 100.0, 200.0, 100, nonce=f"N{i}")
        for i in range(4)
    ]
    digests = [engine.register_evidence_seal(s) for s in seals]
    root = engine.compute_cluster_merkle_root()

    # Generate and verify proof for leaf 2
    proof_leaf_2 = engine.generate_inclusion_proof(digests[2])
    assert len(proof_leaf_2) > 0
    assert engine.verify_inclusion_proof(digests[2], proof_leaf_2, root) is True

    # Forged leaf must fail verification
    assert engine.verify_inclusion_proof("FORGED_LEAF_DIGEST_XYZ", proof_leaf_2, root) is False


@pytest.mark.unit
def test_mtls_san_identity_binding_and_active_session_invalidation() -> None:
    """
    Verify zero-trust mTLS:
    1. Rejects certificates presenting mismatched Common Name / SAN.
    2. Active sessions are immediately invalidated when node is quarantined.
    """
    gateway = EnterpriseMtlsGateway(cluster_ca_fingerprint="CLUSTER_CA_FINGERPRINT_123")

    cert = NodeCertificateInfo(
        node_id="nvr-east",
        common_name="nvr-east.cluster.camserv.internal",
        fingerprint_sha256="FINGERPRINT_EAST_12345",
        issuer="CAMserv Cluster CA",
        issued_timestamp=time.time() - 100,
        expiry_timestamp=time.time() + 86400,
        san_dns_names=["nvr-east.local", "node-east.camserv.lan"],
    )
    gateway.enroll_node_certificate(cert)

    # 1. Valid handshake matching common name
    ok, _ = gateway.validate_peer_connection("nvr-east", "FINGERPRINT_EAST_12345", "nvr-east.cluster.camserv.internal")
    assert ok is True

    # 2. Handshake presenting unauthorized Common Name -> REJECTED
    ok_spoof, reason_spoof = gateway.validate_peer_connection("nvr-east", "FINGERPRINT_EAST_12345", "nvr-west.cluster.camserv.internal")
    assert ok_spoof is False
    assert "Identity mismatch" in reason_spoof

    # 3. Register active in-flight TLS session
    assert gateway.register_active_session("SESSION-999", "nvr-east", "FINGERPRINT_EAST_12345") is True
    assert gateway.is_session_valid("SESSION-999") is True

    # 4. Quarantine / Revoke node -> Active session instantly invalidated
    terminated_count = gateway.revoke_node("nvr-east", reason="Suspicious WAN Traffic")
    assert terminated_count == 1
    assert gateway.is_session_valid("SESSION-999") is False

    # New connections fail
    ok_new, _ = gateway.validate_peer_connection("nvr-east", "FINGERPRINT_EAST_12345")
    assert ok_new is False


@pytest.mark.unit
def test_tenant_boundary_isolation_enforcement() -> None:
    """Verify that operations strictly disallow cross-tenant data access or node binding."""
    coord_tenant_a = ClusterCoordinator(local_node_id="node-a", site_id="site-a", tenant_id="tenant-alpha")

    node_tenant_b = ClusterNode(node_id="node-b", site_id="site-b", address="10.0.1.20", tenant_id="tenant-beta")

    # Attempting to enroll tenant-beta node into tenant-alpha cluster -> REJECTED
    with pytest.raises(TenantIsolationViolationError, match="does not match cluster tenant"):
        coord_tenant_a.register_node(node_tenant_b)

    # Cross-tenant evidence replication access -> REJECTED
    engine_tenant_a = DistributedReplicationEngine(local_node_id="node-a", tenant_id="tenant-alpha")
    seal_a = EvidenceSealRecord(
        segment_id="SEG-TENANT-A",
        camera_id="cam-01",
        origin_node_id="node-a",
        sha256_hash="HASH_A",
        start_timestamp=10.0,
        end_timestamp=20.0,
        frame_count=100,
        tenant_id="tenant-alpha",
    )
    engine_tenant_a.register_evidence_seal(seal_a)

    verdict, info = engine_tenant_a.verify_segment_integrity("SEG-TENANT-A", b"HASH_A_BYTES", tenant_id="tenant-beta")
    assert verdict == VerificationVerdict.TENANT_MISMATCH
    assert "Cross-tenant" in info["error"]


@pytest.mark.unit
def test_api_version_identity_consistency() -> None:
    """Verify FastAPI application and /health endpoint dynamically report canonical package version."""
    from camserv.api.app import create_app
    from camserv.config.settings import get_settings
    from fastapi.testclient import TestClient

    settings = get_settings()
    app = create_app(settings)
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["app"] == "CAMserv"
    assert data["version"] == __version__
    assert app.version == __version__
