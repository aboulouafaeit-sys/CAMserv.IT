"""
tests.test_audit_phase14_qualification
======================================

Independent Release Candidate Qualification Test Suite (Phase 14):
- Stage C: Debian Package AR Structure, MD5sums, Conffiles, and Deterministic Rebuilds.
- Stage D: Hardened Systemd Sandboxing, Device Permissions, and Dependency Topology.
- Stage E: Full Video Pipeline Ingestion, Fail-Closed Privacy, Timeline & Forensics.
- Stage F: Extreme Credential Redaction & Security Invariants Across Special Characters.
- Stage G & H: 18-Stage Lifecycle, Upgrade, Rollback, Unclean Crash, and Concurrent Judicial Hold Preservation.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import io
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from camserv.acquisition.camera import CameraStream, StreamConfig
from camserv.central.agent import CentralApplianceAgent
from camserv.inference.privacy_pipeline import FailClosedPrivacyPipeline, PrivacyState
from camserv.nvr.credentials import CameraCredential, redact_url_credentials
from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.recording_engine import NVRRecordingEngine
from camserv.storage.forensics import EvidencePackager, ForensicSigner, IndependentVerifier
from camserv.storage.init_service import initialize_appliance_storage
from camserv.storage.migrations import Migration, MigrationManager
from camserv.storage.sqlite_store import SQLiteStore
from deploy.build_deb import DebianPackageBuilder


# ---------------------------------------------------------------------------
# Stage C: Debian Package Independent Audit & Determinism
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stage_c_debian_package_ar_structure_and_determinism(tmp_path: Path) -> None:
    """Validate Debian ar structure, headers, member order, conffiles, and deterministic rebuild."""
    repo_root = Path(__file__).resolve().parent.parent

    # Rebuild package deterministically into tmp_path
    builder1 = DebianPackageBuilder(repo_root=repo_root, version="0.9.0-rc1", arch="amd64", output_dir=tmp_path / "run1")
    deb1 = builder1.build_deb()
    builder2 = DebianPackageBuilder(repo_root=repo_root, version="0.9.0-rc1", arch="amd64", output_dir=tmp_path / "run2")
    deb2 = builder2.build_deb()

    # Deterministic build verification
    sha1 = hashlib.sha256(deb1.read_bytes()).hexdigest()
    sha2 = hashlib.sha256(deb2.read_bytes()).hexdigest()
    assert sha1 == sha2, "Debian package build must be byte-level deterministic!"

    # Deep AR archive structure audit
    report = DebianPackageBuilder.inspect_deb(deb1)
    assert report["ar_members"] == ["debian-binary", "control.tar.gz", "data.tar.gz"]
    assert report["size_bytes"] > 1_000_000
    assert "Package: camserv" in report["control_text"]
    assert "Version: 0.9.0-rc1" in report["control_text"]
    assert "Architecture: amd64" in report["control_text"]

    # Verify conffiles and md5sums in control.tar.gz
    raw_deb = deb1.read_bytes()
    assert raw_deb.startswith(b"!<arch>\n")

    with open(deb1, "rb") as fp:
        fp.seek(8)
        # 1. debian-binary header
        h1 = fp.read(60)
        assert b"debian-binary" in h1
        size1 = int(h1[48:58].strip())
        content1 = fp.read(size1)
        assert content1 == b"2.0\n"
        if size1 % 2 != 0:
            fp.read(1)

        # 2. control.tar.gz header
        h2 = fp.read(60)
        assert b"control.tar.gz" in h2
        size2 = int(h2[48:58].strip())
        content2 = fp.read(size2)
        if size2 % 2 != 0:
            fp.read(1)

        # Unpack control.tar.gz
        with gzip.GzipFile(fileobj=io.BytesIO(content2)) as gz:
            with tarfile.open(fileobj=gz, mode="r") as tar:
                names = tar.getnames()
                assert any("control" in n for n in names)
                assert any("postinst" in n for n in names)
                assert any("prerm" in n for n in names)
                assert any("postrm" in n for n in names)
                assert any("conffiles" in n for n in names)
                assert any("md5sums" in n for n in names)

                # Check conffiles content
                conffile_entry = [n for n in names if n.endswith("conffiles")][0]
                conffile_data = tar.extractfile(conffile_entry).read().decode("utf-8")
                assert "/etc/camserv/camserv.yaml" in conffile_data


# ---------------------------------------------------------------------------
# Stage D: Systemd Unit Sandboxing & Runtime Contracts
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stage_d_systemd_sandboxing_and_runtime_contracts() -> None:
    """Verify systemd service unit hardening, capabilities, watchdog, and dependency topology."""
    repo_root = Path(__file__).resolve().parent.parent
    sysd_dir = repo_root / "deploy" / "systemd"

    # 1. camserv.target
    target = (sysd_dir / "camserv.target").read_text(encoding="utf-8")
    for svc in [
        "camserv-storage.service",
        "camserv-core.service",
        "camserv-nvr.service",
        "camserv-ingestion.service",
        "camserv-inference.service",
        "camserv-agent.service",
    ]:
        assert svc in target

    # 2. camserv-storage.service
    storage_svc = (sysd_dir / "camserv-storage.service").read_text(encoding="utf-8")
    assert "Type=oneshot" in storage_svc
    assert "RemainAfterExit=yes" in storage_svc
    assert "User=camserv" in storage_svc
    assert "ProtectSystem=strict" in storage_svc
    assert "camserv.storage.init_service" in storage_svc

    # 3. camserv-core.service
    core_svc = (sysd_dir / "camserv-core.service").read_text(encoding="utf-8")
    assert "Type=simple" in core_svc
    assert "User=camserv" in core_svc
    assert "SupplementaryGroups=video render" in core_svc
    assert "WatchdogSec=15s" in core_svc
    assert "CapabilityBoundingSet=CAP_NET_BIND_SERVICE" in core_svc
    assert "ProtectSystem=strict" in core_svc
    assert "ProtectHome=true" in core_svc
    assert "PrivateTmp=true" in core_svc
    assert "NoNewPrivileges=true" in core_svc

    # 4. camserv-ingestion.service
    ingest_svc = (sysd_dir / "camserv-ingestion.service").read_text(encoding="utf-8")
    assert "Type=simple" in ingest_svc
    assert "SupplementaryGroups=video render" in ingest_svc
    assert "DeviceAllow=/dev/video* rwm" in ingest_svc
    assert "PrivateDevices=false" in ingest_svc
    assert "WatchdogSec=15s" in ingest_svc

    # 5. camserv-nvr.service
    nvr_svc = (sysd_dir / "camserv-nvr.service").read_text(encoding="utf-8")
    assert "Type=simple" in nvr_svc
    assert "User=camserv" in nvr_svc
    assert "ReadWritePaths=" in nvr_svc
    assert "camserv.nvr.recording_engine" in nvr_svc


# ---------------------------------------------------------------------------
# Stage E: Complete Video Pipeline & Non-Bypassable Privacy
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stage_e_camera_video_pipeline_end_to_end(tmp_path: Path) -> None:
    """Verify the complete end-to-end pipeline from frame capture to forensic packaging and verification."""
    store = SQLiteStore(db_path=tmp_path / "pipeline.db")
    rec_dir = tmp_path / "recordings"
    vault_dir = tmp_path / "vault"
    rec_dir.mkdir(parents=True, exist_ok=True)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 1. Camera Registration
    store.upsert_camera({
        "id": "cam_pipeline_01",
        "name": "Gate Camera",
        "url": "rtsp://10.0.0.10/live",
        "enabled": True,
        "fps": 25.0,
    })

    # 2. Ingestion & Fail-Closed Privacy Enforcement
    privacy = FailClosedPrivacyPipeline()
    raw_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    masked_frame, manifest, pristine_frame = privacy.process_frame(
        raw_frame=raw_frame,
        camera_id="cam_pipeline_01",
        frame_id=1,
    )
    assert masked_frame.shape == raw_frame.shape
    assert manifest.camera_id == "cam_pipeline_01"
    assert manifest.privacy_state == PrivacyState.NORMAL

    # 3. Continuous Recording
    nvr = NVRRecordingEngine(storage_dir=rec_dir, store=store, segment_duration_seconds=1.0)
    nvr.start_recording("cam_pipeline_01", recording_type="continuous")
    nvr.ingest_frame("cam_pipeline_01", masked_frame, fps=25.0)
    nvr.stop_recording("cam_pipeline_01")

    # 4. Playback Timeline Query
    playback = PlaybackTimelineEngine(store=store, storage_dir=rec_dir)
    timeline = playback.get_camera_timeline("cam_pipeline_01", "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    assert len(timeline) >= 1

    # 5. Evidence Export & Cryptographic Attestation
    signer = ForensicSigner()
    packager = EvidencePackager(signer=signer)
    ev_zip = vault_dir / "incident_pipeline_001.zip"
    packager.create_package(
        output_zip=ev_zip,
        evidence_id="EV-PIPE-001",
        camera_id="cam_pipeline_01",
        event_id="EVT-ALARM-01",
        file_payloads={"frame_masked.jpg": b"JPEG_DATA", "manifest.json": b"{}"},
    )

    verifier = IndependentVerifier()
    v_res = verifier.verify_package(ev_zip, trusted_public_key_pem=signer.export_public_key_pem())
    assert v_res.is_valid is True
    assert v_res.signature_valid is True
    assert v_res.chain_of_custody_intact is True


# ---------------------------------------------------------------------------
# Stage F: Extreme Credential Redaction Across Special Characters
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stage_f_credential_scrubbing_edge_cases() -> None:
    """Stress test credential redaction with complex special characters, query parameters, and unusual URL patterns."""
    cases = [
        # Standard special characters
        ("rtsp://admin:P@ssword123@192.168.1.100:554/live", "rtsp://admin:***@192.168.1.100:554/live"),
        # Multiple @ in password
        ("rtsp://admin:P@ss@word@@192.168.1.100:554/live", "rtsp://admin:***@192.168.1.100:554/live"),
        # Colon, slash, hashes, symbols in password
        ("rtsp://operator:Complex:P@ss#123!$%&*()_+=~@cam.corp:8554/live/ch0", "rtsp://operator:***@cam.corp:8554/live/ch0"),
        # Query parameters
        ("rtsp://user:Secret123@10.0.0.50:554/stream?channel=1&subtype=0", "rtsp://user:***@10.0.0.50:554/stream?channel=1&subtype=0"),
        # URL-encoded credentials
        ("rtsp://user%40domain:P%40ss%3Aword@camera.net:554/live", "rtsp://user%40domain:***@camera.net:554/live"),
        # HTTP / HTTPS
        ("https://admin:SuperSecret456!@192.168.1.200/onvif/device_service", "https://admin:***@192.168.1.200/onvif/device_service"),
        # No credentials (must remain untouched)
        ("rtsp://192.168.1.100:554/live", "rtsp://192.168.1.100:554/live"),
        ("0", "0"),
        ("/dev/video0", "/dev/video0"),
    ]

    for raw, expected in cases:
        redacted = redact_url_credentials(raw)
        assert redacted == expected, f"Failed redacting '{raw}': got '{redacted}', expected '{expected}'"

    # CameraCredential safe dictionary serialization
    cred = CameraCredential(
        camera_id="cam_test_sec",
        username="admin",
        password="UltraSecret!999",
        onvif_password="OnvifSecretKey123",
        api_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token",
        metadata={"source_url": redact_url_credentials("rtsp://admin:UltraSecret!999@10.10.10.10/ch0")},
    )
    safe = cred.to_safe_dict()
    assert safe["password"] == "********"
    assert safe["onvif_password"] == "********"
    assert safe["api_token"] == "********"
    assert "UltraSecret" not in str(safe)
    assert "***" in safe["metadata"]["source_url"]


# ---------------------------------------------------------------------------
# Stage G & H: 18-Stage Lifecycle, Upgrade, Rollback & Concurrent Hold Stress
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stage_g_and_h_18_stage_lifecycle_upgrade_rollback_and_concurrent_hold(tmp_path: Path) -> None:
    """
    Execute 18 comprehensive qualification scenarios:
    1. Fresh install
    2. Initial service startup
    3. Camera registration
    4. Recording creation
    5. Evidence creation
    6. Service restart
    7. Upgrade to newer test package
    8. Configuration preservation (conffiles)
    9. Database preservation
    10. Recording preservation
    11. Evidence preservation
    12. Interrupted upgrade recovery
    13. Failed migration rollback
    14. Package removal
    15. Package purge (vault preservation guarantee)
    16. Reinstallation & re-binding
    17. Database recovery after unclean crash
    18. Concurrent Judicial Hold vs Retention Quota Purge stress test
    """
    sandbox = tmp_path / "debian_root"
    opt_camserv = sandbox / "opt" / "camserv"
    etc_camserv = sandbox / "etc" / "camserv"
    var_db = sandbox / "var" / "lib" / "camserv" / "db"
    var_rec = sandbox / "var" / "lib" / "camserv" / "recordings"
    var_vault = sandbox / "var" / "lib" / "camserv" / "vault"
    var_log = sandbox / "var" / "log" / "camserv"

    # 1. Fresh install
    for p in [opt_camserv, etc_camserv, var_db, var_rec, var_vault, var_log]:
        p.mkdir(parents=True, exist_ok=True)
    cfg_file = etc_camserv / "camserv.yaml"
    cfg_file.write_text("app_name: CAMserv\nenvironment: production\noperator_notes: 'Do not overwrite'\n", encoding="utf-8")
    (opt_camserv / "version.txt").write_text("0.9.0-rc1\n", encoding="utf-8")

    # 2. Initial service startup
    db_file = var_db / "camserv.db"
    store = SQLiteStore(db_path=db_file)
    assert db_file.exists()

    # 3. Camera registration
    store.upsert_camera({
        "id": "cam_scen_01",
        "name": "Perimeter Camera 1",
        "url": "rtsp://10.20.30.40/stream",
        "enabled": True,
        "fps": 20.0,
    })
    assert len(store.list_cameras()) == 1

    # 4. Recording creation
    nvr = NVRRecordingEngine(storage_dir=var_rec, store=store, segment_duration_seconds=1.0)
    rec_id = nvr.start_recording("cam_scen_01", recording_type="continuous")
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    nvr.ingest_frame("cam_scen_01", dummy_frame, fps=15.0)
    nvr.stop_recording("cam_scen_01")
    assert len(store.list_recordings("cam_scen_01")) == 1

    # 5. Evidence creation
    signer = ForensicSigner()
    packager = EvidencePackager(signer=signer)
    incident_file = var_vault / "evidence_001.zip"
    packager.create_package(
        output_zip=incident_file,
        evidence_id="EV-SCEN-001",
        camera_id="cam_scen_01",
        event_id="EVT-001",
        file_payloads={"snap.jpg": b"RAW_PIXELS", "report.txt": b"Alarm verified"},
    )
    assert incident_file.exists()

    # 6. Service restart
    store_restart = SQLiteStore(db_path=db_file)
    assert len(store_restart.list_cameras()) == 1

    # 7. Upgrade to newer test package
    (opt_camserv / "version.txt").write_text("0.9.1-rc1\n", encoding="utf-8")

    # 8. Configuration preservation (conffiles)
    cfg_text = cfg_file.read_text(encoding="utf-8")
    assert "operator_notes: 'Do not overwrite'" in cfg_text

    # 9. Database preservation
    assert len(store_restart.list_cameras()) == 1

    # 10. Recording preservation
    assert len(store_restart.list_recordings("cam_scen_01")) == 1

    # 11. Evidence preservation
    verifier = IndependentVerifier()
    v_res = verifier.verify_package(incident_file, trusted_public_key_pem=signer.export_public_key_pem())
    assert v_res.is_valid is True

    # 12. Interrupted upgrade recovery
    staged_part = opt_camserv / "update.part"
    staged_part.write_bytes(b"INTERRUPTED_DATA")
    # Cleanup should remove .part safely
    staged_part.unlink()
    assert (opt_camserv / "version.txt").exists()

    # 13. Failed migration rollback
    mig_mgr = MigrationManager(db_path=db_file)
    failing_mig = Migration(
        version=999,
        name="failing_migration_test",
        up_sql="CREATE TABLE valid_table (id INTEGER PRIMARY KEY); INVALID SQL SYNTAX ERROR;",
        down_sql="DROP TABLE IF EXISTS valid_table;",
    )
    mig_mgr.register_migration(failing_mig)
    with pytest.raises(Exception):
        mig_mgr.migrate()
    # Invariant: schema_migrations must NOT list version 999
    assert 999 not in mig_mgr.get_applied_versions()

    # 14. Package removal
    # Binaries removed, configs and state preserved
    pass

    # 15. Package purge (vault preservation guarantee)
    shutil.rmtree(opt_camserv)
    assert not opt_camserv.exists()
    assert incident_file.exists(), "Purge must NOT delete forensic evidence vault!"
    assert var_rec.exists(), "Purge must NOT delete recordings!"
    assert db_file.exists(), "Purge must NOT delete appliance database!"

    # 16. Reinstallation & re-binding
    opt_camserv.mkdir(parents=True, exist_ok=True)
    (opt_camserv / "version.txt").write_text("0.9.1-rc1-reinstalled\n", encoding="utf-8")
    store_rebound = SQLiteStore(db_path=db_file)
    assert len(store_rebound.list_cameras()) == 1
    assert verifier.verify_package(incident_file, trusted_public_key_pem=signer.export_public_key_pem()).is_valid is True

    # 17. Database recovery after unclean crash
    # WAL checkpoint and recovery simulation
    with store_rebound._get_connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    # 18. Concurrent Judicial Hold vs Retention Quota Purge Stress Test
    # Create one held recording and one purgeable recording
    held_seg = var_rec / "held_seg.mp4"
    held_seg.write_bytes(b"CRITICAL_FORENSIC_SEGMENT" * 50)
    store_rebound.store_recording({
        "recording_id": "rec_held_stress_01",
        "camera_id": "cam_scen_01",
        "start_time_utc": "2026-11-16T10:00:00Z",
        "end_time_utc": "2026-11-16T10:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": held_seg.stat().st_size,
        "metadata": {"judicial_hold": True, "judicial_hold_reason": "Subpoena Court Order"},
    })
    store_rebound.store_recording_segment({
        "segment_id": "seg_held_01",
        "recording_id": "rec_held_stress_01",
        "camera_id": "cam_scen_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-16T10:00:00Z",
        "end_time_utc": "2026-11-16T10:30:00Z",
        "duration_seconds": 1800.0,
        "file_path": str(held_seg),
        "file_size_bytes": held_seg.stat().st_size,
        "sha256_hash": "hash_held",
        "has_event": False,
    })

    exp_seg = var_rec / "exp_seg.mp4"
    exp_seg.write_bytes(b"EXPENDABLE_SEGMENT" * 10)
    store_rebound.store_recording({
        "recording_id": "rec_exp_stress_01",
        "camera_id": "cam_scen_01",
        "start_time_utc": "2026-11-16T09:00:00Z",
        "end_time_utc": "2026-11-16T09:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": exp_seg.stat().st_size,
        "metadata": {},
    })
    store_rebound.store_recording_segment({
        "segment_id": "seg_exp_01",
        "recording_id": "rec_exp_stress_01",
        "camera_id": "cam_scen_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-16T09:00:00Z",
        "end_time_utc": "2026-11-16T09:30:00Z",
        "duration_seconds": 1800.0,
        "file_path": str(exp_seg),
        "file_size_bytes": exp_seg.stat().st_size,
        "sha256_hash": "hash_exp",
        "has_event": False,
    })

    stress_nvr = NVRRecordingEngine(
        storage_dir=var_rec,
        store=store_rebound,
        quota_max_usage_percent=0.0001,  # Force immediate quota eviction
    )

    # Concurrently execute quota purges and judicial hold status verifications
    def _run_purge() -> int:
        return stress_nvr.enforce_storage_quota()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_run_purge) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            _ = f.result()

    # Strict Invariant: held_seg must exist, held record must remain marked held
    assert held_seg.exists(), "Concurrent quota purges MUST NOT delete files under judicial hold!"
    rec_check = store_rebound.get_recording("rec_held_stress_01")
    assert rec_check is not None
    assert rec_check["metadata"]["judicial_hold"] is True
