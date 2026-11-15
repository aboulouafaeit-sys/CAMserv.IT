"""
tests.test_forensics_nvr_integration
=====================================

Comprehensive tests for Phase 7:
- Judicial hold case management across SQLiteStore and NVRRecordingEngine.
- Quota purging preservation of judicial hold recordings.
- Digital forensics export packaging with Ed25519 asymmetric signatures.
- Dual-control quorum enforcement for raw pristine evidence under GDPR Art. 25.
- FastAPI REST endpoints for judicial hold and forensic exports.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from camserv.api.app import create_app
from camserv.config.settings import get_settings
from camserv.nvr.playback import PlaybackTimelineEngine
from camserv.nvr.recording_engine import NVRRecordingEngine
from camserv.security.audit import AuditLogger
from camserv.security.auth import AuthManager, Role
from camserv.storage.forensics import EvidenceVerifier, ForensicSigner
from camserv.storage.sqlite_store import SQLiteStore
from camserv.storage.tiered_storage import ExportAuthorizationError


@pytest.fixture
def temp_db(tmp_path: Path) -> SQLiteStore:
    db_path = tmp_path / "test_forensics.db"
    return SQLiteStore(str(db_path))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = get_settings()
    app = create_app(settings)
    # Direct audit logger to tmp_path to strictly protect production logs/audit.jsonl
    app.state.audit_logger = AuditLogger(log_path=tmp_path / "test_api_audit.jsonl")
    return TestClient(app)


def get_token_for_user(auth_mgr: AuthManager, user_id: str, role: Role | str) -> str:
    """Helper to mint valid token for a given user identity and role."""
    return auth_mgr.create_access_token(
        subject=user_id,
        role=role,
    )


# ---------------------------------------------------------------------------
# Unit & Integration Tests: Judicial Hold Lifecycle & Quota Purging
# ---------------------------------------------------------------------------

def test_sqlite_store_judicial_hold_lifecycle(temp_db: SQLiteStore) -> None:
    """Verify that judicial hold is stored in recording metadata and prevents deletion."""
    rec = {
        "recording_id": "rec_hold_001",
        "camera_id": "cam_01",
        "start_time_utc": "2026-11-15T10:00:00Z",
        "end_time_utc": "2026-11-15T11:00:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
        "total_size_bytes": 1024,
        "metadata": {},
    }
    temp_db.store_recording(rec)

    # 1. Place judicial hold
    success = temp_db.set_recording_judicial_hold(
        recording_id="rec_hold_001",
        hold=True,
        reason="Court Order Subpoena #4092",
        operator_id="investigator_smith",
        case_id="CASE-2026-09",
    )
    assert success is True

    # 2. Verify hold status
    fetched = temp_db.get_recording("rec_hold_001")
    assert fetched is not None
    assert fetched["metadata"]["judicial_hold"] is True
    assert fetched["metadata"]["judicial_hold_reason"] == "Court Order Subpoena #4092"
    assert fetched["metadata"]["judicial_hold_case_id"] == "CASE-2026-09"

    # 3. Attempt deletion while hold is active -> must raise ValueError
    with pytest.raises(ValueError, match="active judicial hold"):
        temp_db.delete_recording("rec_hold_001")

    # 4. Release judicial hold
    rel_success = temp_db.set_recording_judicial_hold(
        recording_id="rec_hold_001",
        hold=False,
        reason="Subpoena case concluded",
        operator_id="judge_adams",
    )
    assert rel_success is True

    # 5. Deletion now succeeds
    del_success = temp_db.delete_recording("rec_hold_001")
    assert del_success is True
    assert temp_db.get_recording("rec_hold_001") is None


def test_nvr_recording_engine_quota_purge_preserves_judicial_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that quota retention purging strictly skips recordings with judicial hold."""
    db_path = tmp_path / "nvr_purge_test.db"
    store = SQLiteStore(str(db_path))
    storage_dir = tmp_path / "nvr_recordings"
    storage_dir.mkdir(parents=True)

    engine = NVRRecordingEngine(
        store=store,
        storage_dir=storage_dir,
        segment_duration_seconds=10.0,
        quota_max_usage_percent=80.0,
    )

    # Create 2 recordings on disk
    rec1_file = storage_dir / "rec1_seg1.mp4"
    rec1_file.write_bytes(b"DATA_REC_1_EVIDENCE_LOCKED")
    rec2_file = storage_dir / "rec2_seg1.mp4"
    rec2_file.write_bytes(b"DATA_REC_2_EXPIRED_ROUTINE")

    store.store_recording({
        "recording_id": "rec_locked",
        "camera_id": "cam_01",
        "start_time_utc": "2026-11-15T08:00:00Z",
        "end_time_utc": "2026-11-15T09:00:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
        "total_size_bytes": len(b"DATA_REC_1_EVIDENCE_LOCKED"),
        "metadata": {"judicial_hold": True, "judicial_hold_reason": "Police investigation"},
    })
    store.store_recording_segment({
        "segment_id": "seg_locked_01",
        "recording_id": "rec_locked",
        "camera_id": "cam_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T08:00:00Z",
        "end_time_utc": "2026-11-15T09:00:00Z",
        "duration_seconds": 3600.0,
        "file_path": str(rec1_file),
        "file_size_bytes": len(b"DATA_REC_1_EVIDENCE_LOCKED"),
        "sha256_hash": "dummyhash1",
    })

    store.store_recording({
        "recording_id": "rec_routine",
        "camera_id": "cam_01",
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T10:00:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
        "total_size_bytes": len(b"DATA_REC_2_EXPIRED_ROUTINE"),
        "metadata": {},
    })
    store.store_recording_segment({
        "segment_id": "seg_routine_01",
        "recording_id": "rec_routine",
        "camera_id": "cam_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T10:00:00Z",
        "duration_seconds": 3600.0,
        "file_path": str(rec2_file),
        "file_size_bytes": len(b"DATA_REC_2_EXPIRED_ROUTINE"),
        "sha256_hash": "dummyhash2",
    })

    # Simulate 95% disk usage
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda path: (1000, 950, 50))

    purged = engine.purge_expired_recordings()
    # Routine recording was purged, but locked recording was preserved
    assert purged == 1
    assert rec1_file.exists() is True
    assert store.get_recording("rec_locked") is not None
    assert rec2_file.exists() is False
    assert store.get_recording("rec_routine") is None


# ---------------------------------------------------------------------------
# Unit & Integration Tests: Playback Forensic Export & Dual-Control Quorum
# ---------------------------------------------------------------------------

def test_playback_forensic_export_with_ed25519_and_verification(tmp_path: Path) -> None:
    """Test generating a court-admissible forensic ZIP package and verifying with EvidenceVerifier."""
    db_path = tmp_path / "forensic_export_test.db"
    store = SQLiteStore(str(db_path))
    engine = PlaybackTimelineEngine(store=store)

    seg_file = tmp_path / "seg_export.mp4"
    payload = b"\x00\x00\x00\x20ftypmp42" + b"A" * 1024
    seg_file.write_bytes(payload)

    store.store_recording({
        "recording_id": "rec_forensic_01",
        "camera_id": "cam_gate",
        "start_time_utc": "2026-11-15T12:00:00Z",
        "end_time_utc": "2026-11-15T12:10:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
    })
    store.store_recording_segment({
        "segment_id": "seg_gate_01",
        "recording_id": "rec_forensic_01",
        "camera_id": "cam_gate",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T12:00:00Z",
        "end_time_utc": "2026-11-15T12:10:00Z",
        "duration_seconds": 600.0,
        "file_path": str(seg_file),
        "file_size_bytes": len(payload),
        "sha256_hash": "mocksha",
    })

    signer = ForensicSigner()
    out_zip = tmp_path / "evidence_output.zip"

    manifest = engine.export_forensic_package(
        camera_id="cam_gate",
        start_time_utc="2026-11-15T12:00:00Z",
        end_time_utc="2026-11-15T12:10:00Z",
        output_zip=out_zip,
        operator_id="sgt_baker",
        case_id="CR-2026-888",
        signer=signer,
    )

    assert out_zip.exists()
    assert manifest["camera_id"] == "cam_gate"
    assert manifest["case_id"] == "CR-2026-888"
    assert manifest["segments_count"] == 1
    assert "public_key_pem" in manifest

    # Audit the package using EvidenceVerifier
    verifier = EvidenceVerifier()
    res = verifier.verify_package(out_zip, trusted_public_key_pem=manifest["public_key_pem"])
    assert res.is_valid is True
    assert res.manifest_hash_match is True
    assert res.signature_valid is True
    assert "evidence_clip.mp4" in res.files_checked
    assert "segments_index.json" in res.files_checked


def test_playback_forensic_export_dual_control_raw_refusal(tmp_path: Path) -> None:
    """Test that requesting unmasked raw video export strictly fails without dual-control quorum."""
    db_path = tmp_path / "forensic_dual_control.db"
    store = SQLiteStore(str(db_path))
    engine = PlaybackTimelineEngine(store=store)

    seg_file = tmp_path / "seg_gate_raw.mp4"
    seg_file.write_bytes(b"VIDEO_RAW_UNMASKED_PII_PROTECTED")

    store.store_recording({
        "recording_id": "rec_raw_01",
        "camera_id": "cam_secure",
        "start_time_utc": "2026-11-15T14:00:00Z",
        "end_time_utc": "2026-11-15T14:05:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
    })
    store.store_recording_segment({
        "segment_id": "seg_sec_01",
        "recording_id": "rec_raw_01",
        "camera_id": "cam_secure",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T14:00:00Z",
        "end_time_utc": "2026-11-15T14:05:00Z",
        "duration_seconds": 300.0,
        "file_path": str(seg_file),
        "file_size_bytes": len(b"VIDEO_RAW_UNMASKED_PII_PROTECTED"),
        "sha256_hash": "raw_hash",
    })

    out_zip = tmp_path / "unauthorized_raw.zip"

    # Attempt raw export without dual quorum approval -> must raise ExportAuthorizationError
    with pytest.raises(ExportAuthorizationError, match="dual-control quorum authorization"):
        engine.export_forensic_package(
            camera_id="cam_secure",
            start_time_utc="2026-11-15T14:00:00Z",
            end_time_utc="2026-11-15T14:05:00Z",
            output_zip=out_zip,
            operator_id="operator_single",
            include_raw=True,
            dual_quorum_approved=False,
        )

    # When dual quorum is approved, raw export succeeds
    approved_zip = tmp_path / "authorized_raw.zip"
    manifest = engine.export_forensic_package(
        camera_id="cam_secure",
        start_time_utc="2026-11-15T14:00:00Z",
        end_time_utc="2026-11-15T14:05:00Z",
        output_zip=approved_zip,
        operator_id="operator_primary",
        include_raw=True,
        dual_quorum_approved=True,
    )
    assert manifest["include_raw"] is True
    assert manifest["dual_quorum_approved"] is True
    assert approved_zip.exists()


# ---------------------------------------------------------------------------
# Integration Tests: REST Endpoints (Judicial Hold & Forensic Export)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_api_judicial_hold_and_deletion_guard(client: TestClient) -> None:
    """Test API endpoint for placing/releasing judicial hold and enforcing deletion guard."""
    # Obtain admin token
    res = client.post("/api/v1/auth/token", json={"username": "admin", "password": "admin_password"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Seed recording in app state SQLiteStore
    store: SQLiteStore = getattr(client.app.state, "sqlite_store")
    rec_id = "rec_api_test_hold"
    store.store_recording({
        "recording_id": rec_id,
        "camera_id": "cam_api_01",
        "start_time_utc": "2026-11-15T15:00:00Z",
        "end_time_utc": "2026-11-15T15:30:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
    })

    # 1. Place judicial hold via API
    hold_req = {
        "hold": True,
        "reason": "Judicial Seizure Warrant #771",
        "case_id": "CASE-WAR-771",
    }
    res_hold = client.post(f"/api/v1/recordings/{rec_id}/judicial-hold", json=hold_req, headers=headers)
    assert res_hold.status_code == 200
    data = res_hold.json()
    assert data["recording_id"] == rec_id
    assert data["judicial_hold"] is True
    assert data["reason"] == "Judicial Seizure Warrant #771"

    # 2. Attempt to DELETE recording while hold is active -> must fail with 400 Bad Request
    res_del_fail = client.delete(f"/api/v1/recordings/{rec_id}", headers=headers)
    assert res_del_fail.status_code == 400
    assert "active judicial hold" in res_del_fail.json()["detail"]

    # 3. Release judicial hold via API
    rel_req = {
        "hold": False,
        "reason": "Warrant expired by court order",
    }
    res_rel = client.post(f"/api/v1/recordings/{rec_id}/judicial-hold", json=rel_req, headers=headers)
    assert res_rel.status_code == 200
    assert res_rel.json()["judicial_hold"] is False

    # 4. Now DELETE succeeds
    res_del_ok = client.delete(f"/api/v1/recordings/{rec_id}", headers=headers)
    assert res_del_ok.status_code == 200
    assert res_del_ok.json()["deleted"] is True


@pytest.mark.integration
def test_api_forensic_export_dual_control_quorum(client: TestClient) -> None:
    """Test API endpoint for forensic export enforcing dual-control quorum for raw video."""
    auth_mgr: AuthManager = getattr(client.app.state, "auth_manager")
    admin_token = get_token_for_user(auth_mgr, "admin_user", Role.ADMIN)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Seed segment in app state store
    store: SQLiteStore = getattr(client.app.state, "sqlite_store")
    test_seg_path = Path("data/test_seg_forensic.mp4")
    test_seg_path.parent.mkdir(parents=True, exist_ok=True)
    test_seg_path.write_bytes(b"TEST_VIDEO_CHUNK_FOR_EXPORT")

    store.store_recording({
        "recording_id": "rec_api_exp",
        "camera_id": "cam_forensic_01",
        "start_time_utc": "2026-11-15T16:00:00Z",
        "end_time_utc": "2026-11-15T16:15:00Z",
        "recording_type": "continuous",
        "status": "completed",
        "storage_tier": "operational_fast",
    })
    store.store_recording_segment({
        "segment_id": "seg_forensic_01",
        "recording_id": "rec_api_exp",
        "camera_id": "cam_forensic_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T16:00:00Z",
        "end_time_utc": "2026-11-15T16:15:00Z",
        "duration_seconds": 900.0,
        "file_path": str(test_seg_path),
        "file_size_bytes": len(b"TEST_VIDEO_CHUNK_FOR_EXPORT"),
        "sha256_hash": "dummyhash",
    })

    # 1. Standard derivative forensic export (without raw) -> succeeds
    req_derivative = {
        "camera_id": "cam_forensic_01",
        "start_time_utc": "2026-11-15T16:00:00Z",
        "end_time_utc": "2026-11-15T16:15:00Z",
        "case_id": "CASE-LEGAL-01",
        "include_raw": False,
    }
    res_der = client.post("/api/v1/recordings/export-forensic", json=req_derivative, headers=headers)
    assert res_der.status_code == 200
    assert res_der.json()["include_raw"] is False
    assert res_der.json()["segments_count"] == 1

    # 2. Raw unmasked export without co-signer token -> 403 Forbidden
    req_raw_no_cosigner = {
        "camera_id": "cam_forensic_01",
        "start_time_utc": "2026-11-15T16:00:00Z",
        "end_time_utc": "2026-11-15T16:15:00Z",
        "case_id": "CASE-LEGAL-01",
        "include_raw": True,
    }
    res_raw_fail = client.post("/api/v1/recordings/export-forensic", json=req_raw_no_cosigner, headers=headers)
    assert res_raw_fail.status_code == 403
    assert "Dual-control authorization required" in res_raw_fail.json()["detail"]

    # 3. Raw unmasked export with valid co-signer token from forensic investigator
    cosigner_token = get_token_for_user(auth_mgr, "forensic_officer_9", "forensic_investigator")
    req_raw_valid = {
        "camera_id": "cam_forensic_01",
        "start_time_utc": "2026-11-15T16:00:00Z",
        "end_time_utc": "2026-11-15T16:15:00Z",
        "case_id": "CASE-LEGAL-01",
        "include_raw": True,
        "co_signer_token": cosigner_token,
    }
    res_raw_ok = client.post("/api/v1/recordings/export-forensic", json=req_raw_valid, headers=headers)
    assert res_raw_ok.status_code == 200
    assert res_raw_ok.json()["include_raw"] is True
    assert res_raw_ok.json()["dual_quorum_approved"] is True

    # Clean up test file
    if test_seg_path.exists():
        test_seg_path.unlink()
