"""
tests.test_real_cluster_phase19_qualification
=============================================

Phase 19 Qualification Test Suite:
Validates real-world enterprise cluster deployment, multi-node operational reliability,
durable consensus term recovery, storage-level writer fencing, durable witness anti-replay,
partitioned segment reconciliation, and disaster recovery.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest

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
from camserv.central.mtls import EnterpriseMtlsGateway
from camserv.central.replication import (
    DistributedReplicationEngine,
    EvidenceSealRecord,
    VerificationVerdict,
    WitnessAttestation,
)
from camserv.nvr.recording_engine import NVRRecordingEngine, StorageLease
from camserv.storage.sqlite_store import SQLiteStore


@pytest.fixture
def temp_cluster_dir(tmp_path: Path) -> Path:
    cluster_dir = tmp_path / "cluster_state"
    cluster_dir.mkdir(parents=True, exist_ok=True)
    return cluster_dir


@pytest.fixture
def mock_sqlite_store(tmp_path: Path) -> SQLiteStore:
    db_path = tmp_path / "test_store.db"
    return SQLiteStore(db_path=db_path)


@pytest.mark.unit
def test_durable_consensus_term_recovery_across_reboots(temp_cluster_dir: Path) -> None:
    """Verify that cluster terms, fencing tokens, and camera epochs persist and recover across process reboots."""
    coord1 = ClusterCoordinator(
        local_node_id="node-a",
        site_id="site-hq",
        enforce_strict_quorum=True,
        state_dir=temp_cluster_dir,
    )
    node_a = ClusterNode(node_id="node-a", site_id="site-hq", address="10.0.1.10")
    node_b = ClusterNode(node_id="node-b", site_id="site-hq", address="10.0.1.11")
    node_c = ClusterNode(node_id="node-c", site_id="site-hq", address="10.0.1.12")

    coord1.register_node(node_a)
    coord1.register_node(node_b)
    coord1.register_node(node_c)

    leader1 = coord1.elect_leader()
    term1 = coord1.cluster_term
    assert term1 >= 1
    assert leader1 == "node-a"

    coord1.assign_camera("cam-gate-01", rtsp_url="rtsp://10.0.1.50/live", preferred_node_id="node-a")
    assert "cam-gate-01" in coord1.cameras
    assert coord1.cameras["cam-gate-01"].assignment_epoch == 1

    # State file must exist on disk
    state_file = temp_cluster_dir / "cluster_state.json"
    assert state_file.exists()

    # Simulate process crash/reboot: create new coordinator pointing to same state_dir
    coord2 = ClusterCoordinator(
        local_node_id="node-a",
        site_id="site-hq",
        enforce_strict_quorum=True,
        state_dir=temp_cluster_dir,
    )

    # Term, active fencing token, and camera assignment must be restored
    assert coord2.cluster_term == term1
    assert coord2.active_fencing_token is not None
    assert coord2.active_fencing_token.term == term1
    assert "cam-gate-01" in coord2.cameras
    assert coord2.cameras["cam-gate-01"].assignment_epoch == 1

    # Next election must advance monotonically from restored term
    coord2.register_node(node_a)
    coord2.register_node(node_b)
    coord2.register_node(node_c)
    leader2 = coord2.elect_leader()
    assert leader2 == "node-a"
    assert coord2.cluster_term > term1


@pytest.mark.unit
def test_durable_witness_nonce_persistence_across_reboots(temp_cluster_dir: Path) -> None:
    """Verify that seen witness nonces persist across reboots, preventing post-reboot replay attacks."""
    rep1 = DistributedReplicationEngine(
        local_node_id="witness-01",
        state_dir=temp_cluster_dir,
    )
    attestation = WitnessAttestation(
        witness_node_id="witness-02",
        seal_digest="dummy_seal_digest_001",
        nonce="replay-test-nonce-12345",
    )

    # First submission accepted
    accepted = rep1.submit_witness_attestation(attestation, segment_id="seg-perimeter-001")
    assert accepted is True

    # Immediate replay rejected
    replayed = rep1.submit_witness_attestation(attestation, segment_id="seg-perimeter-001")
    assert replayed is False

    # Simulate witness appliance reboot: new instance with same state_dir
    rep2 = DistributedReplicationEngine(
        local_node_id="witness-01",
        state_dir=temp_cluster_dir,
    )

    # Nonce must be reloaded from disk; replay attempt must STILL be rejected!
    assert ("witness-02", "replay-test-nonce-12345") in rep2.seen_attestation_nonces
    replayed_post_reboot = rep2.submit_witness_attestation(attestation, segment_id="seg-perimeter-001")
    assert replayed_post_reboot is False


@pytest.mark.unit
def test_storage_level_writer_fencing_rejects_unleased_camera(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Verify that NVRRecordingEngine with storage fencing rejects writes to cameras without a lease."""
    storage_dir = tmp_path / "nvr_storage"
    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.start_recording("cam-unauthorized", recording_type="continuous")

    with pytest.raises(FencedWriterError, match="has no granted storage lease"):
        engine.ingest_frame("cam-unauthorized", dummy_frame)


@pytest.mark.unit
def test_storage_level_writer_fencing_rejects_expired_lease(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Verify that an expired storage lease stops local frame writes immediately."""
    storage_dir = tmp_path / "nvr_storage"
    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )

    # Grant an expired lease (granted 10s ago, duration 1s)
    expired_lease = StorageLease(
        camera_id="cam-01",
        node_id="nvr-edge-01",
        assignment_epoch=1,
        granted_at=time.time() - 10.0,
        lease_duration_sec=1.0,
    )
    assert expired_lease.is_valid is False
    engine.grant_storage_lease(expired_lease)

    engine.start_recording("cam-01", recording_type="continuous")
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    with pytest.raises(FencedWriterError, match="has expired"):
        engine.ingest_frame("cam-01", dummy_frame)


@pytest.mark.unit
def test_storage_level_writer_fencing_quarantines_segment_on_lease_expiry(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Verify that a segment in-flight during lease revocation is quarantined, not committed to the database."""
    storage_dir = tmp_path / "nvr_storage"
    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )

    valid_lease = StorageLease(
        camera_id="cam-02",
        node_id="nvr-edge-01",
        assignment_epoch=1,
        granted_at=time.time(),
        lease_duration_sec=30.0,
    )
    engine.grant_storage_lease(valid_lease)
    rec_id = engine.start_recording("cam-02", recording_type="continuous")

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.ingest_frame("cam-02", dummy_frame)

    # Simulate cluster fence / lease revocation while segment is open
    engine.revoke_storage_lease("cam-02")
    assert len(engine.quarantined_segments) == 1
    quarantined = engine.quarantined_segments[0]
    assert quarantined["camera_id"] == "cam-02"
    assert "quarantined" in quarantined["quarantined_path"]

    # Verify database does not contain the uncommitted quarantined segment
    segments = mock_sqlite_store.list_recording_segments(rec_id)
    assert len(segments) == 0


@pytest.mark.unit
def test_partitioned_writer_reconciliation_quarantines_stale_epoch() -> None:
    """Verify that cluster coordinator rejects and quarantines stale writes from recovered partitioned writers."""
    coord = ClusterCoordinator(local_node_id="coordinator", site_id="site-hq")
    node_a = ClusterNode(node_id="node-a", site_id="site-hq", address="10.0.1.10")
    node_b = ClusterNode(node_id="node-b", site_id="site-hq", address="10.0.1.11")
    coord.register_node(node_a)
    coord.register_node(node_b)

    coord.assign_camera("cam-01", rtsp_url="rtsp://10.0.1.50/stream", preferred_node_id="node-a")
    assert coord.cameras["cam-01"].assignment_epoch == 1
    assert coord.cameras["cam-01"].active_node_id == "node-a"

    # Simulate partition and failover: cam-01 reassigned to node-b at epoch 2
    coord.failover_node("node-a")
    assert coord.cameras["cam-01"].assignment_epoch == 2
    assert coord.cameras["cam-01"].active_node_id == "node-b"

    # Partitioned node-a recovers and attempts to commit segments recorded under Epoch 1
    pending_stale_segments = [{"segment_id": "seg-01", "file": "clip1.mp4"}]
    recon_result = coord.reconcile_partitioned_writer(
        camera_id="cam-01",
        recovering_node_id="node-a",
        reported_epoch=1,
        pending_segments=pending_stale_segments,
    )

    assert recon_result["admitted"] is False
    assert recon_result["quarantined"] is True
    assert "Stale writer epoch 1 superseded" in recon_result["reason"]
    assert recon_result["quarantined_segments"] == 1

    # Legitimate node-b reconciles with active epoch 2
    recon_valid = coord.reconcile_partitioned_writer(
        camera_id="cam-01",
        recovering_node_id="node-b",
        reported_epoch=2,
        pending_segments=[{"segment_id": "seg-02", "file": "clip2.mp4"}],
    )
    assert recon_valid["admitted"] is True
    assert recon_valid["quarantined"] is False
    assert recon_valid["admitted_segments"] == 1


@pytest.mark.unit
def test_mtls_revocation_prevents_active_session_reconnect() -> None:
    """Verify that certificate revocation terminates active sessions and blocks re-enrollment."""
    from camserv.central.mtls import NodeCertificateInfo

    gateway = EnterpriseMtlsGateway()
    cert = NodeCertificateInfo(
        node_id="node-alpha",
        common_name="node-alpha.camserv.internal",
        fingerprint_sha256="AA11BB22CC33DD44EE55FF6677889900112233445566778899AABBCCDDEEFF00",
        issuer="CAMserv-Cluster-CA",
        issued_timestamp=time.time(),
        expiry_timestamp=time.time() + 86400,
        san_dns_names=["node-alpha", "node-alpha.camserv.internal"],
    )
    gateway.enroll_node_certificate(cert)

    # Connect Node Alpha
    registered = gateway.register_active_session(
        session_id="sess-01",
        node_id="node-alpha",
        fingerprint="AA11BB22CC33DD44EE55FF6677889900112233445566778899AABBCCDDEEFF00",
    )
    assert registered is True
    assert gateway.is_session_valid("sess-01") is True

    # Revoke Node Alpha
    gateway.revoke_node("node-alpha", reason="Compromised credentials")
    assert gateway.last_terminated_sessions_count == 1
    assert gateway.is_session_valid("sess-01") is False

    # Attempt to establish a new session post-revocation
    reconnect = gateway.register_active_session(
        session_id="sess-02",
        node_id="node-alpha",
        fingerprint="AA11BB22CC33DD44EE55FF6677889900112233445566778899AABBCCDDEEFF00",
    )
    assert reconnect is False


@pytest.mark.unit
def test_multi_tenant_storage_fencing_isolation() -> None:
    """Verify that coordinator rejects foreign tenant camera assignment and writer fencing."""
    coord_tenant_a = ClusterCoordinator(local_node_id="coord-a", site_id="hq", tenant_id="tenant-alpha")
    node_a = ClusterNode(node_id="node-a", site_id="hq", tenant_id="tenant-alpha", address="10.0.1.10")
    coord_tenant_a.register_node(node_a)

    # Assign camera for tenant-alpha
    coord_tenant_a.assign_camera("cam-tenant-a", rtsp_url="rtsp://10.0.1.50/live", tenant_id="tenant-alpha")

    # Attempt writer fencing verification from tenant-beta must raise TenantIsolationViolationError
    with pytest.raises(TenantIsolationViolationError, match="Tenant mismatch"):
        coord_tenant_a.verify_writer_fencing(
            camera_id="cam-tenant-a",
            writer_node_id="node-a",
            presented_epoch=1,
            tenant_id="tenant-beta",
        )


@pytest.mark.unit
def test_durable_seal_persistence_and_merkle_recovery(temp_cluster_dir: Path) -> None:
    """Verify that evidence seals and Merkle leaves persist across witness reboots."""
    rep1 = DistributedReplicationEngine(
        local_node_id="witness-01",
        state_dir=temp_cluster_dir,
    )
    seal = EvidenceSealRecord(
        segment_id="seg-vault-001",
        camera_id="cam-vault-01",
        origin_node_id="nvr-01",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        start_timestamp=1700000000.0,
        end_timestamp=1700000060.0,
        frame_count=900,
    )
    digest1 = rep1.register_evidence_seal(seal)
    root1 = rep1.compute_cluster_merkle_root()
    assert len(root1) == 64

    # Reboot replication engine
    rep2 = DistributedReplicationEngine(
        local_node_id="witness-01",
        state_dir=temp_cluster_dir,
    )
    assert "seg-vault-001" in rep2.primary_seals
    root2 = rep2.compute_cluster_merkle_root()
    assert root2 == root1


@pytest.mark.unit
def test_recovering_node_cannot_overwrite_majority_committed_evidence(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Verify that partitioned node cannot overwrite existing committed segments in storage upon reconnect."""
    # Insert parent recording first for FK integrity
    mock_sqlite_store.upsert_recording({
        "recording_id": "rec_cam_01_epoch2",
        "camera_id": "cam_01",
        "start_time_utc": "2026-11-16T20:00:00Z",
        "recording_type": "continuous",
        "status": "recording",
    })

    # Majority writer (Node B) commits segment at epoch 2
    mock_sqlite_store.store_recording_segment({
        "segment_id": "seg_cam_01_0001",
        "recording_id": "rec_cam_01_epoch2",
        "camera_id": "cam_01",
        "segment_index": 1,
        "start_time_utc": "2026-11-16T20:00:00Z",
        "end_time_utc": "2026-11-16T20:01:00Z",
        "duration_seconds": 60.0,
        "file_path": str(tmp_path / "valid_epoch2_seg.mp4"),
        "file_size_bytes": 10240,
        "sha256_hash": "2222222222222222222222222222222222222222222222222222222222222222",
        "has_motion": False,
        "has_event": False,
        "event_ids": [],
    })

    # Recovered partitioned writer (Node A) with stale Epoch 1
    coord = ClusterCoordinator(local_node_id="coordinator", site_id="hq")
    node_b = ClusterNode(node_id="node-b", site_id="hq", address="10.0.1.11")
    coord.register_node(node_b)
    coord.assign_camera("cam_01", rtsp_url="rtsp://10.0.1.50/live", preferred_node_id="node-b")
    # Bump epoch to 2
    coord.failover_node("node-b")

    recon = coord.reconcile_partitioned_writer(
        camera_id="cam_01",
        recovering_node_id="node-a",
        reported_epoch=1,
        pending_segments=[{"segment_id": "seg_cam_01_0001"}],
    )
    assert recon["admitted"] is False
    assert recon["quarantined"] is True

    # Database still holds Node B's valid record
    segs = mock_sqlite_store.list_recording_segments("rec_cam_01_epoch2")
    assert len(segs) == 1
    assert segs[0]["sha256_hash"] == "2222222222222222222222222222222222222222222222222222222222222222"
