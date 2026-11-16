"""
tests/test_central_phase17_qualification.py
===========================================

Phase 17 Independent Qualification Test Suite for Central Enterprise Federation.
Validates:
1. Invariant: Audit log inviolate verification (20,977 bytes, matching SHA-256).
2. Multi-Node Cluster Orchestration, Leader Election, and Load Balancing.
3. Automated Camera Channel Failover upon Node Timeout.
4. Instant Node Quarantine and Emergency Channel Evacuation.
5. Distributed Evidence Replication, Peer Witness Attestation & Merkle Root.
6. Cryptographic Tamper Detection against modified video files and rogue witnesses.
7. Enterprise Zero-Trust Mutual TLS (mTLS) Gateway & Certificate Revocation.
8. Desktop Operator Console Enterprise Federation Client API.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from camserv.central.cluster import (
    CameraAssignment,
    ClusterCoordinator,
    ClusterNode,
    ClusterNodeRole,
    ClusterNodeState,
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
def test_cluster_coordinator_registration_and_leader_election() -> None:
    """Verify cluster node enrollment and consensus leader election."""
    coordinator = ClusterCoordinator(local_node_id="node-01", site_id="site-central")

    node_a = ClusterNode(node_id="nvr-alpha", site_id="site-central", address="10.0.1.10:8080", capacity_channels=8)
    node_b = ClusterNode(node_id="nvr-beta", site_id="site-central", address="10.0.1.11:8080", capacity_channels=8)

    assert coordinator.register_node(node_a) is True
    assert coordinator.register_node(node_b) is True

    # Deterministic leader election: nvr-alpha sorted first
    leader = coordinator.elect_leader()
    assert leader == "nvr-alpha"
    assert coordinator.nodes["nvr-alpha"].role == ClusterNodeRole.LEADER
    assert coordinator.nodes["nvr-beta"].role == ClusterNodeRole.FOLLOWER


@pytest.mark.unit
def test_cluster_camera_assignment_and_load_balancing() -> None:
    """Verify camera channels are distributed evenly based on node capacity."""
    coordinator = ClusterCoordinator(local_node_id="node-01", site_id="site-central")

    node_a = ClusterNode(node_id="nvr-alpha", site_id="site-central", address="10.0.1.10", capacity_channels=2)
    node_b = ClusterNode(node_id="nvr-beta", site_id="site-central", address="10.0.1.11", capacity_channels=2)

    coordinator.register_node(node_a)
    coordinator.register_node(node_b)

    # Assign 4 cameras: should alternate between alpha and beta
    c1 = coordinator.assign_camera("cam-01", "rtsp://10.0.1.101/stream")
    c2 = coordinator.assign_camera("cam-02", "rtsp://10.0.1.102/stream")
    c3 = coordinator.assign_camera("cam-03", "rtsp://10.0.1.103/stream")
    c4 = coordinator.assign_camera("cam-04", "rtsp://10.0.1.104/stream")

    assert node_a.current_load == 2
    assert node_b.current_load == 2

    # Attempting to assign 5th camera must raise capacity exhaustion
    with pytest.raises(RuntimeError, match="Cluster capacity exhausted"):
        coordinator.assign_camera("cam-05", "rtsp://10.0.1.105/stream")


@pytest.mark.unit
def test_cluster_node_heartbeat_timeout_and_failover() -> None:
    """Verify dead nodes are identified and their cameras automatically failed over."""
    coordinator = ClusterCoordinator(
        local_node_id="node-01",
        site_id="site-central",
        heartbeat_timeout_sec=1.0,
    )

    node_a = ClusterNode(node_id="nvr-alpha", site_id="site-central", address="10.0.1.10", capacity_channels=4)
    node_b = ClusterNode(node_id="nvr-beta", site_id="site-central", address="10.0.1.11", capacity_channels=4)

    coordinator.register_node(node_a)
    coordinator.register_node(node_b)

    coordinator.assign_camera("cam-01", "rtsp://10.0.1.101/stream", preferred_node_id="nvr-alpha")
    coordinator.assign_camera("cam-02", "rtsp://10.0.1.102/stream", preferred_node_id="nvr-alpha")

    assert coordinator.cameras["cam-01"].active_node_id == "nvr-alpha"
    assert coordinator.cameras["cam-02"].active_node_id == "nvr-alpha"

    # Simulate heartbeat timeout on nvr-alpha
    node_a.last_heartbeat = time.time() - 5.0
    node_b.last_heartbeat = time.time()

    health = coordinator.check_cluster_health()
    assert "nvr-alpha" in health["dead_nodes"]
    assert health["failovers_executed"] == 2

    # Cameras must now be active on nvr-beta
    assert coordinator.cameras["cam-01"].active_node_id == "nvr-beta"
    assert coordinator.cameras["cam-02"].active_node_id == "nvr-beta"
    assert node_b.current_load == 2
    assert node_a.current_load == 0


@pytest.mark.unit
def test_cluster_node_quarantine_and_channel_evacuation() -> None:
    """Verify immediate node quarantine, security isolation, and channel evacuation."""
    coordinator = ClusterCoordinator(local_node_id="node-01", site_id="site-central")

    node_a = ClusterNode(node_id="nvr-alpha", site_id="site-central", address="10.0.1.10", capacity_channels=4)
    node_b = ClusterNode(node_id="nvr-beta", site_id="site-central", address="10.0.1.11", capacity_channels=4)

    coordinator.register_node(node_a)
    coordinator.register_node(node_b)
    coordinator.assign_camera("cam-01", "rtsp://10.0.1.101/stream", preferred_node_id="nvr-alpha")

    # Quarantine node_a due to security breach
    ok = coordinator.quarantine_node("nvr-alpha", reason="Unauthorized SSH root access detected")
    assert ok is True
    assert node_a.state == ClusterNodeState.QUARANTINED
    assert coordinator.cameras["cam-01"].active_node_id == "nvr-beta"

    # Quarantined node cannot send heartbeats
    assert coordinator.heartbeat("nvr-alpha") is False

    # Leader election re-evaluates: nvr-beta becomes LEADER
    assert coordinator.current_leader_id == "nvr-beta"


@pytest.mark.unit
def test_distributed_evidence_witness_sealing_and_tamper_detection() -> None:
    """Verify peer witness quorum verification and cryptographic tamper detection."""
    engine = DistributedReplicationEngine(local_node_id="nvr-alpha", quorum_threshold=2)

    fake_video_content = b"ORIGINAL_HIGH_SECURITY_VIDEO_STREAM_BYTES_FRAME_0_TO_900"
    original_hash = hashlib.sha256(fake_video_content).hexdigest().upper()

    seal = EvidenceSealRecord(
        segment_id="SEG-20261116-001",
        camera_id="cam-01",
        origin_node_id="nvr-alpha",
        sha256_hash=original_hash,
        start_timestamp=1794770000.0,
        end_timestamp=1794770900.0,
        frame_count=900,
    )
    seal_digest = engine.register_evidence_seal(seal)

    # 1. Verification with NO witness attestations -> QUORUM_UNAVAILABLE
    verdict, info = engine.verify_segment_integrity("SEG-20261116-001", fake_video_content)
    assert verdict == VerificationVerdict.QUORUM_UNAVAILABLE

    # 2. Submit 2 peer witness attestations
    attestation_1 = WitnessAttestation(seal_digest=seal_digest, witness_node_id="nvr-beta")
    attestation_2 = WitnessAttestation(seal_digest=seal_digest, witness_node_id="nvr-gamma")
    assert engine.submit_witness_attestation(attestation_1, "SEG-20261116-001") is True
    assert engine.submit_witness_attestation(attestation_2, "SEG-20261116-001") is True

    # 3. Pristine verification succeeds
    verdict, info = engine.verify_segment_integrity("SEG-20261116-001", fake_video_content)
    assert verdict == VerificationVerdict.VERIFIED_PRISTINE
    assert info["witness_quorum"] == 2

    # 4. Tampered video file on disk (single byte changed) -> TAMPER_DETECTED
    tampered_bytes = fake_video_content + b"_ALTERED_BYTE"
    verdict_tamper, info_tamper = engine.verify_segment_integrity("SEG-20261116-001", tampered_bytes)
    assert verdict_tamper == VerificationVerdict.TAMPER_DETECTED
    assert "mismatch" in info_tamper["reason"].lower()

    # 5. Rogue witness submitting divergent digest -> TAMPER_DETECTED
    engine_rogue = DistributedReplicationEngine(local_node_id="nvr-alpha", quorum_threshold=2)
    engine_rogue.register_evidence_seal(seal)
    rogue_attestation = WitnessAttestation(seal_digest="FORGED_DIGEST_XYZ", witness_node_id="nvr-rogue")
    engine_rogue.submit_witness_attestation(attestation_1, "SEG-20261116-001")
    engine_rogue.submit_witness_attestation(rogue_attestation, "SEG-20261116-001")

    verdict_rogue, info_rogue = engine_rogue.verify_segment_integrity("SEG-20261116-001", fake_video_content)
    assert verdict_rogue == VerificationVerdict.TAMPER_DETECTED
    assert "divergence" in info_rogue["reason"].lower()


@pytest.mark.unit
def test_cluster_merkle_root_computation() -> None:
    """Verify deterministic Merkle root calculation across multiple evidence seals."""
    engine = DistributedReplicationEngine(local_node_id="nvr-alpha")

    s1 = EvidenceSealRecord("S1", "C1", "N1", "HASH1", 100.0, 200.0, 100)
    s2 = EvidenceSealRecord("S2", "C2", "N1", "HASH2", 200.0, 300.0, 100)
    s3 = EvidenceSealRecord("S3", "C3", "N2", "HASH3", 300.0, 400.0, 100)

    engine.register_evidence_seal(s1)
    engine.register_evidence_seal(s2)
    engine.register_evidence_seal(s3)

    root1 = engine.compute_cluster_merkle_root()
    root2 = engine.compute_cluster_merkle_root()
    assert root1 == root2, "Merkle root must be deterministic"
    assert len(root1) == 64


@pytest.mark.unit
def test_enterprise_mtls_gateway_enrollment_and_validation() -> None:
    """Verify zero-trust mTLS certificate enrollment and authentication."""
    gateway = EnterpriseMtlsGateway(cluster_ca_fingerprint="CA_SHA256_HASH_123")

    cert = NodeCertificateInfo(
        node_id="nvr-beta",
        common_name="nvr-beta.cluster.camserv.internal",
        fingerprint_sha256="AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899",
        issuer="CAMserv Cluster Root CA",
        issued_timestamp=time.time() - 1000,
        expiry_timestamp=time.time() + 86400,
    )
    assert gateway.enroll_node_certificate(cert) is True

    # 1. Valid handshake
    ok, reason = gateway.validate_peer_connection(
        "nvr-beta",
        "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899",
    )
    assert ok is True
    assert reason == "AUTHORIZED"

    # 2. Unknown node rejected
    ok_unk, reason_unk = gateway.validate_peer_connection("nvr-unknown", "AABBCC...")
    assert ok_unk is False

    # 3. Fingerprint mismatch rejected
    ok_mismatch, _ = gateway.validate_peer_connection("nvr-beta", "WRONG_FINGERPRINT_12345")
    assert ok_mismatch is False

    # 4. Revocation immediately bans the node
    assert gateway.revoke_node("nvr-beta", reason="Compromised private key") is True
    ok_rev, reason_rev = gateway.validate_peer_connection(
        "nvr-beta",
        "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899",
    )
    assert ok_rev is False
    assert "REVOKED" in reason_rev


@pytest.mark.unit
def test_desktop_client_cluster_federation_endpoints() -> None:
    """Verify DesktopServiceClient cluster management methods."""
    client = DesktopServiceClient(base_url="http://127.0.0.1:8080")

    mock_cluster_status = {
        "site_id": "site-central",
        "leader_id": "nvr-alpha",
        "online_nodes": 3,
        "total_cameras": 12,
    }

    with patch.object(client, "_request") as mock_req:
        mock_req.return_value = mock_cluster_status
        status = client.get_cluster_status()
        assert status is not None
        assert status["leader_id"] == "nvr-alpha"
        assert status["online_nodes"] == 3

        mock_req.return_value = {"status": "quarantined"}
        assert client.quarantine_cluster_node("nvr-rogue", "Security Incident") is True
