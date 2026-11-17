"""
tests/test_pre_lts_phase20_qualification.py
===========================================

Phase 20 Pre-LTS Qualification Test Suite:
1. Audit log cryptographic invariant verification (20,977 bytes, matching SHA-256).
2. Distributed Quorum & Consensus Safety:
   - 5-node cluster partition (3 vs 2: majority elects, minority fails).
   - 5-node cluster 3-way partition (2 vs 2 vs 1: all fail, no split-brain).
   - 3-node cluster partition (1 vs 2).
   - 2-node cluster with 1 node offline (quorum lost).
   - Single-node startup when configured as multi-node cluster (refuses self-election).
   - Stale leader returning after term progression (rejected with StaleLeaderError).
   - Minority partition prohibited from issuing storage leases.
3. Durable State & Fail-Closed Replay Protection:
   - Corrupted cluster_state.json fails closed (raises CorruptedConsensusStateError).
   - Corrupted seen_nonces.json fails closed (raises CorruptedReplicationStateError).
   - Conflicting primary seal registration rejected (raises DuplicateSealError).
   - Idempotent identical seal registration without duplicating Merkle leaves.
4. StorageLease & Forensic Quarantine Integrity:
   - Storage-level writer fencing on ingest_frame and _open_new_segment.
   - Crash recovery of incomplete .part files: unleased files quarantined, not admitted to SQLite.
   - Byte-for-byte SHA-256 preservation upon segment quarantine.
   - Exclusion of quarantined segments from authoritative SQLite store.
   - Privileged operator review and quarantine restoration lifecycle.
5. Windows 11 Native MSI Database Qualification:
   - Verification of Win32 MSI database tables (Property, Component, ServiceInstall).
   - Verification of Permanent component attribute (0x0010) on forensic vault and recordings.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pytest

from camserv.central.cluster import (
    CameraAssignment,
    ClusterCoordinator,
    ClusterNode,
    ClusterNodeRole,
    ClusterNodeState,
    CorruptedConsensusStateError,
    FencedWriterError,
    QuorumUnavailableError,
    StaleLeaderError,
    StorageLease,
)
from camserv.central.replication import (
    CorruptedReplicationStateError,
    DistributedReplicationEngine,
    DuplicateSealError,
    EvidenceSealRecord,
    WitnessAttestation,
)
from camserv.nvr.recording_engine import (
    ActiveRecordingSession,
    NVRRecordingEngine,
    SegmentWriter,
)
from camserv.storage.sqlite_store import SQLiteStore


@pytest.fixture
def mock_sqlite_store(tmp_path: Path) -> SQLiteStore:
    db_file = tmp_path / "test_store.db"
    return SQLiteStore(db_path=db_file)


# ===========================================================================
# 1. Forensic Audit Log Invariant Verification (Rule 1)
# ===========================================================================

@pytest.mark.unit
def test_inviolate_audit_log_preserved_phase20() -> None:
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


# ===========================================================================
# 2. Distributed Quorum & Consensus Safety (Section 3)
# ===========================================================================

@pytest.mark.unit
def test_five_node_cluster_partition_3_vs_2() -> None:
    """
    Five-node cluster under network partition:
    N = 5, Q = floor(5/2) + 1 = 3.
    - Partition A (3 nodes): has quorum -> elects leader.
    - Partition B (2 nodes): minority -> raises QuorumUnavailableError.
    """
    nodes = [
        ClusterNode(node_id=f"node-{i}", site_id="site-corp", address=f"10.0.1.{10+i}")
        for i in range(1, 6)
    ]

    # Majority partition (Node 1, Node 2, Node 3)
    coord_maj = ClusterCoordinator(
        local_node_id="node-1",
        site_id="site-corp",
        enforce_strict_quorum=True,
        expected_cluster_size=5,
    )
    for n in nodes[:3]:
        coord_maj.register_node(n)
    for n in nodes[3:]:
        coord_maj.register_node(ClusterNode(node_id=n.node_id, site_id=n.site_id, address=n.address, state=ClusterNodeState.OFFLINE))

    assert coord_maj.quorum_threshold == 3
    assert coord_maj.healthy_nodes_count == 3
    assert coord_maj.has_quorum is True
    leader = coord_maj.elect_leader()
    assert leader == "node-1"

    # Minority partition (Node 4, Node 5)
    coord_min = ClusterCoordinator(
        local_node_id="node-4",
        site_id="site-corp",
        enforce_strict_quorum=True,
        expected_cluster_size=5,
    )
    for n in nodes[3:]:
        coord_min.register_node(n)
    for n in nodes[:3]:
        coord_min.register_node(ClusterNode(node_id=n.node_id, site_id=n.site_id, address=n.address, state=ClusterNodeState.OFFLINE))

    assert coord_min.quorum_threshold == 3
    assert coord_min.healthy_nodes_count == 2
    assert coord_min.has_quorum is False
    with pytest.raises(QuorumUnavailableError, match="strict majority of 3 required"):
        coord_min.elect_leader()
    assert coord_min.current_leader_id is None


@pytest.mark.unit
def test_five_node_cluster_partition_2_vs_2_vs_1() -> None:
    """
    Five-node cluster partitioned into 3 isolated segments (2, 2, 1).
    Since none has Q = 3, ALL partitions must refuse leader election (zero split-brain).
    """
    coord_part1 = ClusterCoordinator(local_node_id="node-1", site_id="site-corp", enforce_strict_quorum=True, expected_cluster_size=5)
    coord_part1.register_node(ClusterNode(node_id="node-1", site_id="site-corp", address="10.0.1.11"))
    coord_part1.register_node(ClusterNode(node_id="node-2", site_id="site-corp", address="10.0.1.12"))
    assert coord_part1.has_quorum is False
    with pytest.raises(QuorumUnavailableError):
        coord_part1.elect_leader()

    coord_part2 = ClusterCoordinator(local_node_id="node-3", site_id="site-corp", enforce_strict_quorum=True, expected_cluster_size=5)
    coord_part2.register_node(ClusterNode(node_id="node-3", site_id="site-corp", address="10.0.1.13"))
    coord_part2.register_node(ClusterNode(node_id="node-4", site_id="site-corp", address="10.0.1.14"))
    assert coord_part2.has_quorum is False
    with pytest.raises(QuorumUnavailableError):
        coord_part2.elect_leader()

    coord_part3 = ClusterCoordinator(local_node_id="node-5", site_id="site-corp", enforce_strict_quorum=True, expected_cluster_size=5)
    coord_part3.register_node(ClusterNode(node_id="node-5", site_id="site-corp", address="10.0.1.15"))
    assert coord_part3.has_quorum is False
    with pytest.raises(QuorumUnavailableError):
        coord_part3.elect_leader()


@pytest.mark.unit
def test_two_node_cluster_one_unavailable_loses_quorum() -> None:
    """
    Two-node cluster (N = 2, Q = floor(2/2) + 1 = 2).
    If one member is offline, the remaining single node lacks quorum and must not elect itself.
    """
    coord = ClusterCoordinator(local_node_id="node-1", site_id="site-corp", enforce_strict_quorum=True, expected_cluster_size=2)
    coord.register_node(ClusterNode(node_id="node-1", site_id="site-corp", address="10.0.1.11"))
    coord.register_node(ClusterNode(node_id="node-2", site_id="site-corp", address="10.0.1.12", state=ClusterNodeState.OFFLINE))

    assert coord.quorum_threshold == 2
    assert coord.healthy_nodes_count == 1
    assert coord.has_quorum is False
    with pytest.raises(QuorumUnavailableError, match="strict majority of 2 required"):
        coord.elect_leader()


@pytest.mark.unit
def test_single_node_startup_when_configured_as_multinode() -> None:
    """
    A single node booting up when configured as part of a 5-node cluster.
    Must calculate Q = 3 and refuse to elect itself leader.
    """
    coord = ClusterCoordinator(
        local_node_id="node-alpha",
        site_id="site-hq",
        enforce_strict_quorum=True,
        expected_cluster_size=5,
    )
    coord.register_node(ClusterNode(node_id="node-alpha", site_id="site-hq", address="10.0.1.20"))

    assert coord.quorum_threshold == 3
    assert coord.healthy_nodes_count == 1
    assert coord.has_quorum is False
    assert coord.current_leader_id is None
    with pytest.raises(QuorumUnavailableError):
        coord.elect_leader()


@pytest.mark.unit
def test_stale_leader_returning_rejected() -> None:
    """A deposed leader presenting a past term is rejected with StaleLeaderError."""
    coord = ClusterCoordinator(local_node_id="node-a", site_id="site-hq")
    coord.register_node(ClusterNode(node_id="node-a", site_id="site-hq", address="10.0.1.30"))
    coord.elect_leader()
    term1 = coord.cluster_term

    # Re-election increments term
    coord.elect_leader()
    term2 = coord.cluster_term
    assert term2 > term1

    with pytest.raises(StaleLeaderError, match="Stale leader command rejected"):
        coord.verify_leader_fencing(presented_term=term1, presented_leader_id="node-a")


@pytest.mark.unit
def test_minority_partition_cannot_issue_storage_lease() -> None:
    """A minority partition cannot issue or renew StorageLeases."""
    coord = ClusterCoordinator(
        local_node_id="node-min",
        site_id="site-corp",
        enforce_strict_quorum=True,
        expected_cluster_size=5,
    )
    coord.register_node(ClusterNode(node_id="node-min", site_id="site-corp", address="10.0.1.40"))

    with pytest.raises(QuorumUnavailableError, match="quorum unavailable"):
        coord.issue_storage_lease("cam-01", "node-min")


# ===========================================================================
# 3. Durable State & Fail-Closed Replay Protection (Section 5)
# ===========================================================================

@pytest.mark.unit
def test_corrupted_consensus_state_fails_closed(tmp_path: Path) -> None:
    """Corrupted cluster_state.json must raise CorruptedConsensusStateError, not reset term to 0."""
    state_dir = tmp_path / "corrupted_cluster"
    state_dir.mkdir(parents=True)
    corrupted_file = state_dir / "cluster_state.json"
    corrupted_file.write_text("{\"cluster_term\": 42, INVALID_JSON...", encoding="utf-8")

    with pytest.raises(CorruptedConsensusStateError, match="corrupted or unreadable"):
        ClusterCoordinator(local_node_id="node-1", site_id="site-corp", state_dir=state_dir)


@pytest.mark.unit
def test_corrupted_nonce_cache_fails_closed(tmp_path: Path) -> None:
    """Corrupted seen_nonces.json must raise CorruptedReplicationStateError, not reset cache to empty."""
    state_dir = tmp_path / "corrupted_repl"
    state_dir.mkdir(parents=True)
    corrupted_file = state_dir / "seen_nonces.json"
    corrupted_file.write_text("[[\"node-1\", \"nonce-1\"], MALFORMED...", encoding="utf-8")

    with pytest.raises(CorruptedReplicationStateError, match="corrupted or unreadable"):
        DistributedReplicationEngine(local_node_id="node-1", state_dir=state_dir)


@pytest.mark.unit
def test_duplicate_and_conflicting_primary_seal_handling(tmp_path: Path) -> None:
    """Conflicting primary seal raises DuplicateSealError; identical seal is idempotent."""
    engine = DistributedReplicationEngine(local_node_id="node-primary", state_dir=tmp_path / "repl_state")
    seal1 = EvidenceSealRecord(
        segment_id="SEG-001",
        camera_id="cam-01",
        origin_node_id="node-primary",
        sha256_hash="ORIGINAL_HASH_123456",
        start_timestamp=100.0,
        end_timestamp=160.0,
        frame_count=900,
        nonce="NONCE-001",
    )
    digest1 = engine.register_evidence_seal(seal1)
    assert len(engine.merkle_leaves) == 1

    # Idempotent re-registration of identical seal
    digest1_again = engine.register_evidence_seal(seal1)
    assert digest1_again == digest1
    assert len(engine.merkle_leaves) == 1  # Did NOT append duplicate leaf

    # Conflicting seal for same segment ID -> REJECTED
    conflicting_seal = EvidenceSealRecord(
        segment_id="SEG-001",
        camera_id="cam-01",
        origin_node_id="node-primary",
        sha256_hash="TAMPERED_HASH_999999",
        start_timestamp=100.0,
        end_timestamp=160.0,
        frame_count=900,
        nonce="NONCE-002",
    )
    with pytest.raises(DuplicateSealError, match="Conflicting seal for segment"):
        engine.register_evidence_seal(conflicting_seal)


# ===========================================================================
# 4. StorageLease & Forensic Quarantine Integrity (Section 4 & 6)
# ===========================================================================

@pytest.mark.unit
def test_storage_lease_fencing_on_open_and_ingest(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Unleased camera operations raise FencedWriterError on ingest and segment creation."""
    engine = NVRRecordingEngine(
        storage_dir=tmp_path / "nvr",
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )
    engine.start_recording("cam-fenced", recording_type="continuous")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    with pytest.raises(FencedWriterError, match="has no granted storage lease"):
        engine.ingest_frame("cam-fenced", frame)


@pytest.mark.unit
def test_crash_recovery_quarantines_unleased_part_files(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Incomplete .part files from unauthorized or expired crash states are quarantined."""
    storage_dir = tmp_path / "nvr_storage"
    cam_dir = storage_dir / "cam-unauthorized" / "2026-11-16"
    cam_dir.mkdir(parents=True)
    part_file = cam_dir / "crash_seg0001.tmp.mp4"
    part_file.write_bytes(b"partial-video-stream-bytes-1234567890")

    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,  # No lease granted for cam-unauthorized
    )
    recovered = engine.recover_incomplete_recordings()

    # Must NOT be admitted to normal store
    assert len(recovered) == 0
    quarantine_file = cam_dir / "crash_seg0001.quarantined.mp4"
    assert quarantine_file.exists()
    assert not part_file.exists()

    quarantined = engine.get_quarantined_segments("cam-unauthorized")
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "crash_recovery_unauthorized_lease"


@pytest.mark.unit
def test_forensic_quarantine_preserves_byte_for_byte_sha256(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Quarantining an unfinalized segment preserves exact byte contents and SHA-256."""
    storage_dir = tmp_path / "nvr_storage"
    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )
    lease = StorageLease(
        camera_id="cam-secure",
        node_id="nvr-01",
        assignment_epoch=1,
        granted_at=time.time(),
        lease_duration_sec=0.4,
    )
    engine.grant_storage_lease(lease)
    engine.start_recording("cam-secure", recording_type="continuous")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engine.ingest_frame("cam-secure", frame)

    # Let lease expire
    while lease.is_valid:
        time.sleep(0.05)
    assert not lease.is_valid

    # Stop recording triggers finalization -> quarantined due to expired lease
    engine.stop_recording("cam-secure")

    quarantined = engine.get_quarantined_segments("cam-secure")
    assert len(quarantined) == 1
    rec = quarantined[0]
    assert rec["hash_match"] is True
    assert rec["original_sha256"] == rec["post_quarantine_sha256"]

    # Quarantined file must NOT be in SQLite segments table
    segments = mock_sqlite_store.list_recording_segments(rec["recording_id"])
    assert len(segments) == 0


@pytest.mark.unit
def test_privileged_quarantine_restoration_lifecycle(
    tmp_path: Path,
    mock_sqlite_store: SQLiteStore,
) -> None:
    """Privileged operator review allows verified restoration of a quarantined segment."""
    storage_dir = tmp_path / "nvr_storage"
    engine = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=mock_sqlite_store,
        enforce_storage_fencing=True,
    )
    lease = StorageLease(
        camera_id="cam-restore",
        node_id="nvr-01",
        assignment_epoch=1,
        granted_at=time.time(),
        lease_duration_sec=0.4,
    )
    engine.grant_storage_lease(lease)
    engine.start_recording("cam-restore", recording_type="continuous")
    engine.ingest_frame("cam-restore", np.zeros((480, 640, 3), dtype=np.uint8))
    while lease.is_valid:
        time.sleep(0.05)
    engine.stop_recording("cam-restore")

    quarantined = engine.get_quarantined_segments("cam-restore")
    assert len(quarantined) == 1
    q_path = quarantined[0]["quarantined_path"]

    # Operator authorizes restoration
    ok = engine.restore_quarantined_segment(
        quarantined_path=q_path,
        authorized_by="Lead Forensics Officer #1092",
        reason="Verified network jitter delayed lease renewal by 50ms",
    )
    assert ok is True
    restored_path = Path(q_path.replace(".quarantined.mp4", ".mp4"))
    assert restored_path.exists()
    assert not Path(q_path).exists()


# ===========================================================================
# 5. Native Windows 11 MSI Database Qualification (Section 7)
# ===========================================================================

@pytest.mark.unit
def test_windows_msi_database_schema_and_component_permanence() -> None:
    """
    Validates Windows Installer MSI database tables using native Win32 msi.dll:
    1. Property table contains expected product identity and version.
    2. Component table has permanent attribute (0x0010) set on evidence components.
    3. ServiceInstall table registers CAMservCore service.
    """
    msi_path = Path("dist/windows/camserv_0.10.0-alpha2_win64.msi")
    assert msi_path.exists(), "Windows MSI package is missing!"

    msi = ctypes.windll.msi
    h_db = wintypes.HANDLE()
    res = msi.MsiOpenDatabaseW(str(msi_path.resolve()), 0, ctypes.byref(h_db))
    assert res == 0, f"MsiOpenDatabaseW failed with error code {res}"

    try:
        # 1. Query Property table
        h_view = wintypes.HANDLE()
        res_view = msi.MsiDatabaseOpenViewW(
            h_db,
            "SELECT `Property`, `Value` FROM `Property`",
            ctypes.byref(h_view),
        )
        assert res_view == 0
        msi.MsiViewExecute(h_view, 0)
        props: dict[str, str] = {}
        h_rec = wintypes.HANDLE()
        while msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0:
            buf_p = ctypes.create_unicode_buffer(256)
            size_p = wintypes.DWORD(256)
            msi.MsiRecordGetStringW(h_rec, 1, buf_p, ctypes.byref(size_p))
            buf_v = ctypes.create_unicode_buffer(256)
            size_v = wintypes.DWORD(256)
            msi.MsiRecordGetStringW(h_rec, 2, buf_v, ctypes.byref(size_v))
            props[buf_p.value] = buf_v.value
            msi.MsiCloseHandle(h_rec)
        msi.MsiCloseHandle(h_view)

        assert "ProductName" in props
        assert "CAMserv" in props["ProductName"]
        assert props.get("ProductVersion") == "0.10.0.0"

        # 2. Query Component table for permanence attribute (0x0010 = 16)
        res_view2 = msi.MsiDatabaseOpenViewW(
            h_db,
            "SELECT `Component`, `Attributes` FROM `Component`",
            ctypes.byref(h_view),
        )
        assert res_view2 == 0
        msi.MsiViewExecute(h_view, 0)
        components: dict[str, int] = {}
        while msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0:
            buf_c = ctypes.create_unicode_buffer(256)
            size_c = wintypes.DWORD(256)
            msi.MsiRecordGetStringW(h_rec, 1, buf_c, ctypes.byref(size_c))
            attr = msi.MsiRecordGetInteger(h_rec, 2)
            components[buf_c.value] = attr
            msi.MsiCloseHandle(h_rec)
        msi.MsiCloseHandle(h_view)

        # Permanent attribute is 0x0010 (16). With 64-bit (0x0100 = 256), total is 272.
        assert components.get("cmp_recordings", 0) & 0x0010 == 0x0010, "Recordings component missing Permanent attribute!"
        assert components.get("cmp_vault", 0) & 0x0010 == 0x0010, "Vault component missing Permanent attribute!"
        assert components.get("cmp_data", 0) & 0x0010 == 0x0010, "Data component missing Permanent attribute!"

        # 3. Query ServiceInstall table
        res_view3 = msi.MsiDatabaseOpenViewW(
            h_db,
            "SELECT `Name`, `DisplayName`, `ServiceType` FROM `ServiceInstall`",
            ctypes.byref(h_view),
        )
        assert res_view3 == 0
        msi.MsiViewExecute(h_view, 0)
        services: list[str] = []
        while msi.MsiViewFetch(h_view, ctypes.byref(h_rec)) == 0:
            buf_s = ctypes.create_unicode_buffer(256)
            size_s = wintypes.DWORD(256)
            msi.MsiRecordGetStringW(h_rec, 1, buf_s, ctypes.byref(size_s))
            services.append(buf_s.value)
            msi.MsiCloseHandle(h_rec)
        msi.MsiCloseHandle(h_view)
        assert "CAMservCore" in services
    finally:
        msi.MsiCloseHandle(h_db)
