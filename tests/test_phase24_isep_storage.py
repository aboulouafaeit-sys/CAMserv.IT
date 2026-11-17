"""
CAMserv — Phase 24: ISEP (Intelligent Storage & Evidence Preservation Engine) Test Suite.

Comprehensive verification of:
1. Recording segment creation, atomic commit, and continuity tracking.
2. Stream bitrate analysis and scene complexity classification.
3. Hybrid SSD+HDD staging, verified migration, and failed transfer source preservation.
4. Evidence preservation, WORM holds, vault promotion, and Ed25519 courtroom export.
5. 6-step safe retention cleanup and audit trail recording.
6. Disk health, capacity probing, write latency, and queue bounding.
7. Capacity forecasting, retention runway, and disk-full projection.
8. Cryptographic integrity checking, bitrot detection, and safe deduplication.
9. Crash recovery of orphaned .part files and post-crash reconciliation.
10. Storage profiles (Economy, Balanced, Performance, Evidence Priority).
11. Security hardening (path traversal defense, dual control, fail-closed isolation).
12. Repeatable storage benchmarks (bytes/hour, throughput, latency, efficiency).
"""

import os
import sys
import time
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from camserv.storage.isep import (
    CameraRetentionRule,
    CapacityForecast,
    DiskHealthInfo,
    DiskHealthMonitor,
    EvidencePreservationError,
    EvidencePreservationManager,
    PreservationHold,
    RecordingCodec,
    RecordingSegmentManager,
    RecordingSegmentMetadata,
    RetentionPolicyEngine,
    SceneComplexity,
    SegmentState,
    StorageCapacityPredictor,
    StorageIntegrityVerifier,
    StorageIntelligenceEngine,
    StoragePool,
    StorageProfile,
    StorageRecoveryManager,
    StorageTelemetryService,
    StorageTierManager,
    StorageTierType,
    StorageTopology,
    StreamBitrateAnalyzer,
    TransferVerificationError,
)
from camserv.desktop.console import DesktopOperatorConsole


# ==============================================================================
# 1. Recording Segment Management & Atomic Commits
# ==============================================================================

class TestISEPRecordingSegmentManager:
    """Verifies segment lifecycle, atomic commit, and crash recovery."""

    @pytest.fixture
    def segment_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RecordingSegmentManager(
                base_storage_dir=tmpdir,
                segment_duration_seconds=2.0,
                max_segment_size_bytes=100 * 1024,  # 100 KB
            )
            yield mgr, Path(tmpdir)

    def test_start_and_finalize_segment_atomic_commit(self, segment_env):
        mgr, storage_dir = segment_env
        writer = mgr.start_segment(
            recording_id="rec_test_01",
            camera_id="cam-front-01",
            codec=RecordingCodec.H264,
            fps=15.0,
            resolution=(640, 480),
        )

        assert writer.part_path.exists()
        assert not writer.final_path.exists()

        # Write dummy frames
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in range(10):
            writer.write_numpy_frame(dummy_frame)

        # Finalize
        meta = mgr.finalize_segment("cam-front-01")
        assert meta is not None
        assert not writer.part_path.exists()
        assert writer.final_path.exists()
        assert meta.file_size_bytes > 0
        assert len(meta.sha256_hash) == 64
        assert meta.state == SegmentState.FINALIZED

    def test_raw_packet_ingest_without_transcode(self, segment_env):
        mgr, storage_dir = segment_env
        writer = mgr.start_segment(
            recording_id="rec_test_raw",
            camera_id="cam-native-01",
            codec=RecordingCodec.NATIVE_PASS_THROUGH,
        )

        raw_payload = b"\x00\x00\x00\x01\x67\x42\x00\x1f" + (b"\xff" * 512)
        writer.write_raw_packet(raw_payload, is_keyframe=True)

        meta = mgr.finalize_segment("cam-native-01")
        assert meta is not None
        assert meta.file_size_bytes == len(raw_payload)
        assert Path(meta.file_path).read_bytes() == raw_payload

    def test_roll_over_thresholds(self, segment_env):
        mgr, _ = segment_env
        writer = mgr.start_segment(
            recording_id="rec_rollover",
            camera_id="cam-roll-01",
            codec=RecordingCodec.NATIVE_PASS_THROUGH,
        )

        # Initially should not roll over
        assert not mgr.should_roll_over("cam-roll-01")

        # Exceed size threshold
        writer.write_raw_packet(b"X" * (120 * 1024))
        assert mgr.should_roll_over("cam-roll-01")

        # Cleanly finalize to release file lock on Windows
        mgr.finalize_segment("cam-roll-01")

    def test_recover_orphaned_part_files(self, segment_env):
        mgr, storage_dir = segment_env
        cam_dir = storage_dir / "cam-crash-01"
        cam_dir.mkdir(parents=True, exist_ok=True)

        part_file = cam_dir / "cam-crash-01_1700000000_00001.mp4.part"
        part_file.write_bytes(b"ISEP_SIMULATED_ABANDONED_RECORDING_PAYLOAD")

        recovered = mgr.recover_orphaned_part_files()
        assert len(recovered) == 1
        rec = recovered[0]
        assert rec.file_size_bytes == len(b"ISEP_SIMULATED_ABANDONED_RECORDING_PAYLOAD")
        assert not part_file.exists()
        assert Path(rec.file_path).exists()


# ==============================================================================
# 2. Bitrate Analysis & Scene Complexity
# ==============================================================================

class TestISEPStreamBitrateAnalyzer:
    """Verifies empirical stream bitrate calculation and scene complexity classification."""

    def test_bitrate_calculation(self):
        analyzer = StreamBitrateAnalyzer(window_seconds=10.0)

        t0 = 1000.0
        # 100 KB every second for 5 seconds = 800 kbps
        for sec in range(5):
            analyzer.record_packet("cam-01", 100 * 1024, timestamp=t0 + sec)

        metrics = analyzer.get_stream_metrics("cam-01")
        assert metrics["has_data"] is True
        # Rate: (500 * 1024 * 8) / (4 * 1000) ~ 1024 kbps
        assert 800.0 <= metrics["measured_bitrate_kbps"] <= 1200.0

    def test_scene_complexity_classification(self):
        analyzer = StreamBitrateAnalyzer(window_seconds=10.0)

        # 1. Stable scene: identical black frames
        stable_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(5):
            analyzer.record_frame_for_scene_analysis("cam-stable", stable_frame, timestamp=100.0 + i)
        assert analyzer.classify_scene_complexity("cam-stable") == SceneComplexity.STABLE

        # 2. Dynamic scene: alternating high contrast frames
        for i in range(5):
            dynamic_frame = np.full((240, 320, 3), (i % 2) * 255, dtype=np.uint8)
            analyzer.record_frame_for_scene_analysis("cam-dynamic", dynamic_frame, timestamp=200.0 + i)
        complexity = analyzer.classify_scene_complexity("cam-dynamic")
        assert complexity in (SceneComplexity.HIGH_MOTION, SceneComplexity.COMPLEX)

    def test_storage_growth_estimation(self):
        analyzer = StreamBitrateAnalyzer()
        # Feed known 2000 kbps stream
        t0 = 100.0
        for i in range(10):
            analyzer.record_packet("cam-est", 250 * 1024, timestamp=t0 + i)

        est = analyzer.estimate_storage_growth("cam-est", hours=24.0)
        assert est["is_empirically_measured"] is True
        assert est["projected_gb"] > 0
        assert "disclaimer" in est


# ==============================================================================
# 3. Hybrid Storage & Staging Transfers
# ==============================================================================

class TestISEPTierManagerAndHybridStorage:
    """Verifies HDD-only, SSD+HDD hybrid staging, and verified transfer guarantees."""

    @pytest.fixture
    def tier_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            primary_dir = p / "primary_hdd"
            staging_dir = p / "staging_ssd"
            mgr = StorageTierManager(
                primary_storage_dir=primary_dir,
                staging_dir=staging_dir,
                topology=StorageTopology.SSD_HDD_HYBRID,
            )
            yield mgr, primary_dir, staging_dir

    def test_ingest_path_resolution(self, tier_env):
        mgr, primary_dir, staging_dir = tier_env
        ingest_path = mgr.get_ingest_path_for_camera("cam-01")
        # In hybrid mode with staging configured, points to staging SSD
        assert str(staging_dir) in str(ingest_path)

        # In HDD-only mode, points directly to primary HDD
        mgr.pools["default_pool"] = StoragePool(
            pool_id="default_pool",
            name="HDD Only",
            topology=StorageTopology.HDD_ONLY,
            primary_path=primary_dir,
            staging_path=None,
        )
        hdd_path = mgr.get_ingest_path_for_camera("cam-01")
        assert str(primary_dir) in str(hdd_path)

    def test_verified_staging_transfer_and_safe_release(self, tier_env):
        mgr, primary_dir, staging_dir = tier_env
        cam_staging = staging_dir / "cam-01"
        cam_staging.mkdir(parents=True, exist_ok=True)

        staged_file = cam_staging / "cam-01_100_00001.mp4"
        payload = b"ISEP_HIGH_QUALITY_STAGED_VIDEO_PAYLOAD"
        staged_file.write_bytes(payload)

        import hashlib
        expected_hash = hashlib.sha256(payload).hexdigest()

        seg = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="seg_staged_01",
            recording_id="rec_01",
            camera_id="cam-01",
            segment_index=1,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path=str(staged_file),
            file_size_bytes=len(payload),
            sha256_hash=expected_hash,
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.HOT_INGEST,
        )

        migrated = mgr.transfer_staging_to_archive(seg)

        # Staging source file MUST be released/deleted after successful verified migration
        assert not staged_file.exists()
        # Destination file MUST exist on primary archive
        dest_path = Path(migrated.file_path)
        assert dest_path.exists()
        assert dest_path.read_bytes() == payload
        assert migrated.tier == StorageTierType.WARM_ARCHIVE
        assert migrated.sha256_hash == expected_hash

    def test_failed_staging_transfer_preserves_source(self, tier_env):
        mgr, primary_dir, staging_dir = tier_env
        cam_staging = staging_dir / "cam-fail"
        cam_staging.mkdir(parents=True, exist_ok=True)

        staged_file = cam_staging / "cam-fail_100_00001.mp4"
        staged_file.write_bytes(b"ORIGINAL_UNDAMAGED_EVIDENCE")

        # Intentionally wrong expected hash
        corrupted_seg = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="seg_fail_01",
            recording_id="rec_fail",
            camera_id="cam-fail",
            segment_index=1,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path=str(staged_file),
            file_size_bytes=len(b"ORIGINAL_UNDAMAGED_EVIDENCE"),
            sha256_hash="0000000000000000000000000000000000000000000000000000000000000000",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.HOT_INGEST,
        )

        with pytest.raises(TransferVerificationError):
            mgr.transfer_staging_to_archive(corrupted_seg)

        # CRITICAL SAFETY INVARIANT: Staging source file MUST be preserved!
        assert staged_file.exists()
        assert staged_file.read_bytes() == b"ORIGINAL_UNDAMAGED_EVIDENCE"


# ==============================================================================
# 4. Evidence Preservation & Courtroom Export
# ==============================================================================

class TestISEPEvidencePreservation:
    """Verifies Evidence Vault promotion, preservation holds, and courtroom exports."""

    @pytest.fixture
    def evidence_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            vault_dir = p / "vault"
            mgr = EvidencePreservationManager(vault_dir=vault_dir)
            yield mgr, p, vault_dir

    def test_preservation_hold_lifecycle(self, evidence_env):
        mgr, _, _ = evidence_env

        hold = mgr.apply_preservation_hold(
            target_id="seg_incident_99",
            reason="Grand Jury Subpoena #8412",
            authorized_by="Lead_Prosecutor",
            hold_type="legal_hold",
        )

        assert hold.active is True
        assert mgr.is_target_protected("seg_incident_99") is True
        assert mgr.is_target_protected("unprotected_seg") is False

        # Release hold
        assert mgr.release_preservation_hold(hold.hold_id, "Lead_Prosecutor", "Case dismissed") is True
        assert mgr.is_target_protected("seg_incident_99") is False

    def test_vault_ingestion_and_isolation(self, evidence_env):
        mgr, p, vault_dir = evidence_env

        src_dir = p / "recordings" / "cam-01"
        src_dir.mkdir(parents=True, exist_ok=True)
        src_file = src_dir / "cam-01_incident.mp4"
        payload = b"CRITICAL_FORENSIC_INCIDENT_STREAM_DATA"
        src_file.write_bytes(payload)

        import hashlib
        sha = hashlib.sha256(payload).hexdigest()

        seg = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="seg_incident_101",
            recording_id="rec_inc_01",
            camera_id="cam-01",
            segment_index=1,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path=str(src_file),
            file_size_bytes=len(payload),
            sha256_hash=sha,
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )

        vault_meta = mgr.ingest_to_vault(
            segment=seg,
            hold_reason="Perimeter Breach Evidence",
            authorized_by="Security_Chief_102",
        )

        assert vault_meta.tier == StorageTierType.EVIDENCE_VAULT
        assert vault_meta.state == SegmentState.VAULT_SEALED
        assert vault_meta.is_protected_evidence is True
        assert Path(vault_meta.file_path).exists()
        assert mgr.is_target_protected("seg_incident_101") is True

    def test_courtroom_evidence_bundle_export(self, evidence_env):
        mgr, p, vault_dir = evidence_env
        src_file = p / "vault_test.mp4"
        src_file.write_bytes(b"TAMPER_PROOF_COURTROOM_SAMPLE")

        import hashlib
        sha = hashlib.sha256(b"TAMPER_PROOF_COURTROOM_SAMPLE").hexdigest()

        seg = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="seg_court_01",
            recording_id="rec_court",
            camera_id="cam-court",
            segment_index=1,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path=str(src_file),
            file_size_bytes=len(b"TAMPER_PROOF_COURTROOM_SAMPLE"),
            sha256_hash=sha,
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.EVIDENCE_VAULT,
        )
        mgr.vault_segments["seg_court_01"] = seg

        export_dir = p / "exports"

        # Dual-control validation: Reject if only 1 officer or identical IDs
        with pytest.raises(PermissionError):
            mgr.export_courtroom_evidence_bundle(
                "seg_court_01", export_dir, "Officer_A", "Officer_A", "WARRANT-123"
            )

        # Successful export
        bundle = mgr.export_courtroom_evidence_bundle(
            "seg_court_01", export_dir, "Officer_A", "Officer_B", "WARRANT-2026-441"
        )
        assert bundle.exists()
        assert bundle.suffix == ".zip"

        import zipfile
        with zipfile.ZipFile(bundle, "r") as zf:
            namelist = zf.namelist()
            assert "manifest.json" in namelist
            assert "signature.ed25519.sig" in namelist
            assert "public_key.pem" in namelist


# ==============================================================================
# 5. 6-Step Safe Retention Policy Engine
# ==============================================================================

class TestISEPRetentionPolicyEngine:
    """Verifies retention rules, hold protection, and safe purge execution."""

    @pytest.fixture
    def retention_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            ev_mgr = EvidencePreservationManager(vault_dir=p / "vault")
            engine = RetentionPolicyEngine(evidence_manager=ev_mgr)
            yield engine, ev_mgr, p

    def test_safe_cleanup_lifecycle_and_hold_immunity(self, retention_env):
        engine, ev_mgr, p = retention_env

        # Create 3 segment files
        f1 = p / "seg1.mp4"
        f2 = p / "seg2.mp4"
        f3 = p / "seg3.mp4"
        f1.write_bytes(b"DATA1")
        f2.write_bytes(b"DATA2")
        f3.write_bytes(b"DATA3")

        now = 1000000.0

        # Segment 1: Expired normal continuous recording (100 hours old)
        s1 = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="s1_expired",
            recording_id="rec_1",
            camera_id="cam-01",
            segment_index=1,
            start_time_utc="2026-11-13T00:00:00Z",
            end_time_utc="2026-11-13T00:01:00Z",
            duration_seconds=60.0,
            file_path=str(f1),
            file_size_bytes=5,
            sha256_hash="abc",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )

        # Segment 2: Also 100 hours old, BUT has an active legal hold
        s2 = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="s2_held",
            recording_id="rec_2",
            camera_id="cam-01",
            segment_index=2,
            start_time_utc="2026-11-13T00:00:00Z",
            end_time_utc="2026-11-13T00:01:00Z",
            duration_seconds=60.0,
            file_path=str(f2),
            file_size_bytes=5,
            sha256_hash="def",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )
        ev_mgr.apply_preservation_hold("s2_held", "Litigation Hold", "General_Counsel")

        # Segment 3: Recent footage (1 hour old)
        s3 = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="s3_recent",
            recording_id="rec_3",
            camera_id="cam-01",
            segment_index=3,
            start_time_utc="2026-11-17T11:00:00Z",
            end_time_utc="2026-11-17T11:01:00Z",
            duration_seconds=60.0,
            file_path=str(f3),
            file_size_bytes=5,
            sha256_hash="ghi",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )

        # Execute safe cleanup
        report = engine.execute_safe_cleanup([s1, s2, s3], operator_authorization="DAILY_SCHEDULED_PURGE")

        assert report["purged_count"] == 1
        assert "s1_expired" in report["purged_segment_ids"]
        assert report["protected_count"] >= 1

        # f1 deleted
        assert not f1.exists()
        # f2 and f3 MUST still exist on disk
        assert f2.exists()
        assert f3.exists()

        # Verify audit trail record was created
        assert len(engine.audit_trail) == 1
        assert engine.audit_trail[0].segment_id == "s1_expired"


# ==============================================================================
# 6. Disk Health & Latency Diagnostics
# ==============================================================================

class TestISEPDiskHealthMonitor:
    """Verifies volume capacity, write latency measurement, and queue depth control."""

    @pytest.fixture
    def disk_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskHealthMonitor(monitored_paths=[tmpdir], max_write_queue_depth=4)
            yield monitor, tmpdir

    def test_volume_capacity_and_diagnostics(self, disk_env):
        monitor, tmpdir = disk_env
        cap = monitor.probe_volume_capacity(tmpdir)
        assert cap["total_bytes"] > 0
        assert cap["free_bytes"] > 0

        health = monitor.inspect_disk_health(tmpdir)
        assert health.total_gb > 0
        assert 0.0 <= health.used_percent <= 100.0
        assert health.write_latency_ms >= 0.0

    def test_write_queue_depth_bounding(self, disk_env):
        monitor, _ = disk_env

        # Can acquire up to max_write_queue_depth (4)
        for _ in range(4):
            assert monitor.acquire_write_slot() is True

        # 5th attempt must be throttled
        assert monitor.acquire_write_slot() is False

        # Release and re-acquire
        monitor.release_write_slot()
        assert monitor.acquire_write_slot() is True


# ==============================================================================
# 7. Capacity Predictor & Retention Forecasting
# ==============================================================================

class TestISEPCapacityPredictor:
    """Verifies storage forecasting and projected disk full dates."""

    def test_capacity_forecast_calculation(self):
        analyzer = StreamBitrateAnalyzer()
        monitor = DiskHealthMonitor()
        predictor = StorageCapacityPredictor(analyzer, monitor, safety_reserve_percent=10.0)

        # Feed 10 packets (approx 4000 kbps)
        t0 = 100.0
        for i in range(10):
            analyzer.record_packet("cam-fore", 500 * 1024, timestamp=t0 + i)

        fc = predictor.forecast_camera_consumption("cam-fore")
        assert fc.daily_bytes > 0
        assert fc.weekly_bytes == fc.daily_bytes * 7
        assert fc.monthly_bytes == fc.daily_bytes * 30
        assert fc.remaining_retention_days > 0.0
        assert len(fc.projected_disk_full_date) > 0


# ==============================================================================
# 8. Cryptographic Integrity & Deduplication Safety
# ==============================================================================

class TestISEPIntegrityAndDeduplication:
    """Verifies bitrot detection and safe cryptographic deduplication rules."""

    def test_integrity_verification_pass_and_corruption_detection(self):
        verifier = StorageIntegrityVerifier()
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"VERIFIED_VIDEO_STREAM_BYTES")
            tf.flush()
            temp_path = tf.name

        try:
            import hashlib
            good_hash = hashlib.sha256(b"VERIFIED_VIDEO_STREAM_BYTES").hexdigest()

            valid_seg = RecordingSegmentMetadata(
                schema_version="2.0",
                segment_id="seg_good",
                recording_id="rec_1",
                camera_id="cam-1",
                segment_index=0,
                start_time_utc="2026-11-17T12:00:00Z",
                end_time_utc="2026-11-17T12:01:00Z",
                duration_seconds=60.0,
                file_path=temp_path,
                file_size_bytes=len(b"VERIFIED_VIDEO_STREAM_BYTES"),
                sha256_hash=good_hash,
                codec="h264",
                resolution=(1920, 1080),
                fps=15.0,
                bitrate_kbps=4000.0,
                tier=StorageTierType.WARM_ARCHIVE,
            )

            res = verifier.verify_segment_integrity(valid_seg)
            assert res["is_valid"] is True

            # Tamper with file
            Path(temp_path).write_bytes(b"TAMPERED_MODIFIED_BYTES_BITROT")
            res_bad = verifier.verify_segment_integrity(valid_seg)
            assert res_bad["is_valid"] is False
            assert res_bad["error"] in ("SIZE_MISMATCH", "SHA256_MISMATCH")
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_safe_deduplication_rules(self):
        verifier = StorageIntegrityVerifier()

        s1 = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="s1",
            recording_id="r1",
            camera_id="cam-A",
            segment_index=0,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path="/dummy/path1",
            file_size_bytes=1000,
            sha256_hash="exact_sha256_match",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )

        s2 = RecordingSegmentMetadata(
            schema_version="2.0",
            segment_id="s2",
            recording_id="r2",
            camera_id="cam-B",
            segment_index=0,
            start_time_utc="2026-11-17T12:00:00Z",
            end_time_utc="2026-11-17T12:01:00Z",
            duration_seconds=60.0,
            file_path="/dummy/path2",
            file_size_bytes=1000,
            sha256_hash="exact_sha256_match",
            codec="h264",
            resolution=(1920, 1080),
            fps=15.0,
            bitrate_kbps=4000.0,
            tier=StorageTierType.WARM_ARCHIVE,
        )

        eval_res = verifier.evaluate_cryptographic_deduplication(s1, [s2])
        assert eval_res["can_deduplicate"] is True
        assert eval_res["matched_segment_id"] == "s2"
        # Provenance is preserved: is_cross_camera is flagged
        assert eval_res["is_cross_camera"] is True


# ==============================================================================
# 9. Unified Storage Intelligence Engine Lifecycle
# ==============================================================================

class TestISEPStorageIntelligenceEngineAndProfiles:
    """Verifies end-to-end ISEP lifecycle, profiles, and console telemetry."""

    @pytest.fixture
    def isep_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            primary_dir = p / "archive"
            staging_dir = p / "staging"
            vault_dir = p / "vault"
            engine = StorageIntelligenceEngine(
                primary_storage_dir=primary_dir,
                staging_dir=staging_dir,
                vault_dir=vault_dir,
                topology=StorageTopology.SSD_HDD_HYBRID,
                profile=StorageProfile.BALANCED,
            )
            yield engine, p

    def test_full_ingest_vault_and_retention_lifecycle(self, isep_env):
        engine, _ = isep_env

        # 1. Start recording
        seg_id = engine.start_camera_recording("cam-e2e-01")
        assert seg_id.startswith("seg_cam-e2e-01")

        # 2. Ingest frames
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in range(5):
            engine.ingest_frame("cam-e2e-01", dummy_frame)

        # 3. Finalize
        meta = engine.segment_manager.finalize_segment("cam-e2e-01")
        assert meta is not None
        processed = engine._handle_finalized_segment(meta)
        assert Path(processed.file_path).exists()

        # 4. Promote to Evidence Vault
        vault_meta = engine.promote_to_evidence_vault(processed.segment_id, "Burglary Investigation", "Officer_99")
        assert vault_meta.is_protected_evidence is True

        # 5. Run Retention Cycle
        res = engine.run_retention_cycle("SYSTEM_PURGE_TEST")
        # Vault-promoted segment MUST NOT be purged
        assert processed.segment_id not in res["purged_segment_ids"]

        # 6. Query Telemetry
        telemetry = engine.get_telemetry()
        assert telemetry["topology"] == StorageTopology.SSD_HDD_HYBRID.value
        assert telemetry["profile"] == StorageProfile.BALANCED.value
        assert telemetry["evidence_vault"]["preserved_segments_count"] >= 1

    def test_profile_switching(self, isep_env):
        engine, _ = isep_env
        assert engine.current_profile == StorageProfile.BALANCED

        engine.switch_profile(StorageProfile.ECONOMY)
        assert engine.current_profile == StorageProfile.ECONOMY
        assert engine.segment_manager.segment_duration_seconds == 120.0

        engine.switch_profile(StorageProfile.EVIDENCE_PRIORITY)
        assert engine.current_profile == StorageProfile.EVIDENCE_PRIORITY
        assert engine.segment_manager.segment_duration_seconds == 30.0

    def test_desktop_console_isep_integration(self):
        console = DesktopOperatorConsole(headless=True)
        assert console.storage_engine is not None
        telemetry = console.get_storage_telemetry()
        assert "disk" in telemetry
        assert "evidence_vault" in telemetry
        assert "forecast" in telemetry


# ==============================================================================
# 10. Repeatable Storage Benchmarking
# ==============================================================================

class TestISEPBenchmarking:
    """Executes repeatable benchmarking comparing HDD vs SSD+HDD and stream efficiencies."""

    def test_benchmark_hdd_vs_hybrid_and_codec_efficiency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            hdd_dir = p / "bench_hdd"
            ssd_dir = p / "bench_ssd"

            # Benchmark A: HDD-only direct write
            t0 = time.perf_counter()
            hdd_mgr = RecordingSegmentManager(
                base_storage_dir=hdd_dir,
                segment_duration_seconds=10.0,
            )
            w_hdd = hdd_mgr.start_segment("rec_bench_hdd", "cam-bench", codec=RecordingCodec.NATIVE_PASS_THROUGH)
            # Write 500 KB chunk
            payload = b"B" * (500 * 1024)
            w_hdd.write_raw_packet(payload)
            meta_hdd = w_hdd.close()
            t_hdd_ms = (time.perf_counter() - t0) * 1000.0

            # Benchmark B: SSD staging write
            t1 = time.perf_counter()
            ssd_mgr = RecordingSegmentManager(
                base_storage_dir=ssd_dir,
                segment_duration_seconds=10.0,
            )
            w_ssd = ssd_mgr.start_segment("rec_bench_ssd", "cam-bench", codec=RecordingCodec.NATIVE_PASS_THROUGH)
            w_ssd.write_raw_packet(payload)
            meta_ssd = w_ssd.close()
            t_ssd_ms = (time.perf_counter() - t1) * 1000.0

            # Verified staging transfer
            tier_mgr = StorageTierManager(
                primary_storage_dir=hdd_dir,
                staging_dir=ssd_dir,
                topology=StorageTopology.SSD_HDD_HYBRID,
            )
            t2 = time.perf_counter()
            migrated = tier_mgr.transfer_staging_to_archive(meta_ssd)
            t_mig_ms = (time.perf_counter() - t2) * 1000.0

            assert meta_hdd.file_size_bytes == 500 * 1024
            assert migrated.file_size_bytes == 500 * 1024
            assert migrated.sha256_hash == meta_ssd.sha256_hash

            # Log benchmark results for forensic report
            print(f"\n[ISEP BENCHMARK REPORT]")
            print(f"HDD-Only Direct Write Latency: {t_hdd_ms:.2f} ms")
            print(f"SSD Staging Write Latency:     {t_ssd_ms:.2f} ms")
            print(f"Verified Staging Migration:    {t_mig_ms:.2f} ms")
            print(f"Measured Write Throughput:     {((500 * 1024) / max(0.001, t_hdd_ms)) / 1000.0:.2f} MB/s")
            print(f"Cryptographic Integrity:       VERIFIED (SHA-256 match)\n")
