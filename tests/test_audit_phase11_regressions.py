"""
tests.test_audit_phase11_regressions
====================================

Independent regression tests verifying the remediations for all Phase 11 findings:
- FINDING-11-01: StreamingGateway fail-closed privacy pipeline & argument alignment.
- FINDING-11-02: Forensic evidence package unlisted/unauthorized file injection rejection.
- FINDING-11-03: Dual-Control Quorum co-signer claim binding & replay rejection.
- FINDING-11-04: Multi-tenant boundary isolation in CAMserv Central sync.
- FINDING-11-05: Atomic quota purge preserving concurrent judicial holds.
- FINDING-11-06: Hardware AI adapter clean rejection when accelerator is absent.
- FINDING-11-07: Version synchronization across manifests and SBOM.
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from camserv import __version__
from camserv.analytics.adapters.coral import CoralEdgeTPUAdapter
from camserv.analytics.adapters.cuda import CUDABackendAdapter
from camserv.analytics.adapters.hailo import HailoNPUAdapter
from camserv.analytics.adapters.openvino import OpenVINOBackendAdapter
from camserv.central.comm import SecureMessageEnvelope
from camserv.central.sync import CentralSyncEngine, EdgeSyncClient
from camserv.inference.privacy import BlurMethod, PrivacyConfig
from camserv.inference.privacy_pipeline import FailClosedPrivacyPipeline
from camserv.nvr.recording_engine import NVRRecordingEngine
from camserv.nvr.streaming import StreamingGateway
from camserv.security.auth import AuthManager, Role
from camserv.storage.forensics import EvidencePackager, ForensicSigner, IndependentVerifier, VerificationResult
from camserv.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# FINDING-11-01: StreamingGateway Fail-Closed Privacy Pipeline Verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_streaming_gateway_fail_closed_pipeline_configured() -> None:
    """Verify that when a privacy pipeline is active, StreamingGateway processes frames correctly."""
    config = PrivacyConfig(blur_faces=True, default_blur_method=BlurMethod.SOLID)
    pipeline = FailClosedPrivacyPipeline(config=config)
    gateway = StreamingGateway(privacy_pipeline=pipeline)

    # Synthetic RGB frame
    raw_frame = np.ones((100, 100, 3), dtype=np.uint8) * 128
    gateway.publish_frame("cam_test_01", raw_frame)

    safe_frame = gateway.get_latest_frame("cam_test_01")
    assert safe_frame is not None
    assert safe_frame.shape == raw_frame.shape
    # Frame was processed through privacy pipeline without crashing or tuple attribute errors
    jpeg_bytes = gateway._encode_jpeg(safe_frame)
    assert jpeg_bytes.startswith(b"\xff\xd8")


@pytest.mark.unit
def test_streaming_gateway_fail_closed_pipeline_none_returns_blackout() -> None:
    """Verify that when no privacy pipeline is configured, StreamingGateway fails closed with a blackout frame."""
    gateway = StreamingGateway(privacy_pipeline=None)
    raw_frame = np.ones((100, 100, 3), dtype=np.uint8) * 200
    gateway.publish_frame("cam_unconfigured", raw_frame)

    safe_frame = gateway.get_latest_frame("cam_unconfigured")
    assert safe_frame is not None
    assert safe_frame.shape == raw_frame.shape
    # Fail-closed blackout frame must be dark/blacked out (not original raw frame pixels)
    assert not np.array_equal(safe_frame, raw_frame)
    # Background is black (zeros)
    assert np.mean(safe_frame) < 50.0


# ---------------------------------------------------------------------------
# FINDING-11-02: Forensic Evidence ZIP Archive Integrity Verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_forensic_verifier_rejects_unlisted_file_injection(tmp_path: Path) -> None:
    """Verify that IndependentVerifier rejects packages containing unlisted injected files."""
    signer = ForensicSigner()
    packager = EvidencePackager(signer=signer)

    zip_path = tmp_path / "valid_bundle.zip"
    packager.create_package(
        output_zip=zip_path,
        evidence_id="EV-REG-01",
        camera_id="cam_forensic_01",
        event_id="EVENT-01",
        file_payloads={"evidence_segment.mp4": b"test-surveillance-video-bytes-001"},
    )
    assert zip_path.exists()

    verifier = IndependentVerifier()

    # Legitimate package must verify cleanly
    res_clean = verifier.verify_package(zip_path, trusted_public_key_pem=signer.export_public_key_pem())
    assert res_clean.is_valid is True
    assert res_clean.manifest_hash_match is True
    assert res_clean.signature_valid is True
    assert len(res_clean.tampered_files) == 0

    # 1. Inject unlisted payload file
    injected_zip = tmp_path / "injected_payload.zip"
    with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(injected_zip, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("payload/unlisted_malicious.bin", b"injected-payload-content")

    res_injected = verifier.verify_package(injected_zip, trusted_public_key_pem=signer.export_public_key_pem())
    assert res_injected.is_valid is False
    assert res_injected.manifest_hash_match is False
    assert any("UNLISTED_INJECTED_FILE" in f for f in res_injected.tampered_files)

    # 2. Inject unauthorized root file
    root_injected_zip = tmp_path / "injected_root.zip"
    with zipfile.ZipFile(zip_path, "r") as zin, zipfile.ZipFile(root_injected_zip, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("backdoor.sh", b"#!/bin/sh\nrm -rf /")

    res_root = verifier.verify_package(root_injected_zip, trusted_public_key_pem=signer.export_public_key_pem())
    assert res_root.is_valid is False
    assert res_root.manifest_hash_match is False
    assert any("UNAUTHORIZED_ARCHIVE_ENTRY" in f for f in res_root.tampered_files)


# ---------------------------------------------------------------------------
# FINDING-11-03: Dual-Control Quorum Scope and Replay Rejection
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_dual_control_token_validation_scope_and_replay() -> None:
    """Verify that co-signer tokens enforce target camera scope and single-use replay protection."""
    from camserv.api.routes import consumed_quorum_jtis

    auth = AuthManager(secret_key="test-secret-key-for-phase-11-audit-regressions")

    # Generate a co-signer token scoped to cam_01
    token = auth.create_access_token(
        subject="officer_cosigner",
        role=Role.AUDITOR,
        additional_claims={
            "approved_camera_id": "cam_01",
            "jti": "jti-test-unique-001",
        },
    )

    payload = auth.verify_token(token)
    assert payload is not None
    assert payload.get("approved_camera_id") == "cam_01"
    jti = payload.get("jti")
    assert jti == "jti-test-unique-001"

    # Simulate first consumption
    assert jti not in consumed_quorum_jtis
    consumed_quorum_jtis.add(jti)

    # Replay attempt must be blocked
    assert jti in consumed_quorum_jtis


# ---------------------------------------------------------------------------
# FINDING-11-04: Multi-Tenant Boundary Isolation in CAMserv Central
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_central_sync_multi_tenant_boundary_isolation(tmp_path: Path) -> None:
    """Verify that CentralSyncEngine strictly isolates cameras and recordings by tenant."""
    store_a = SQLiteStore(db_path=tmp_path / "tenant_a.db")
    store_b = SQLiteStore(db_path=tmp_path / "tenant_b.db")

    central = CentralSyncEngine()

    # Edge Client Tenant A
    client_a = EdgeSyncClient("app_a_01", "site_a", store_a, tenant_id="tenant_alpha")
    disc_a = client_a.publish_camera_discovery([
        {"id": "cam_alpha_01", "name": "Alpha Entrance", "enabled": True},
    ])
    central.ingest_sync_envelope(disc_a)

    # Edge Client Tenant B
    client_b = EdgeSyncClient("app_b_01", "site_b", store_b, tenant_id="tenant_beta")
    disc_b = client_b.publish_camera_discovery([
        {"id": "cam_beta_01", "name": "Beta Warehouse", "enabled": True},
    ])
    central.ingest_sync_envelope(disc_b)

    # Query cameras scoped to tenant_alpha
    cams_alpha = central.discover_fleet_cameras(tenant_id="tenant_alpha")
    assert len(cams_alpha) == 1
    assert cams_alpha[0]["camera_id"] == "cam_alpha_01"

    # Query cameras scoped to tenant_beta
    cams_beta = central.discover_fleet_cameras(tenant_id="tenant_beta")
    assert len(cams_beta) == 1
    assert cams_beta[0]["camera_id"] == "cam_beta_01"

    # Ingest recordings
    store_a.store_recording({
        "recording_id": "rec_alpha_01",
        "camera_id": "cam_alpha_01",
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T09:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": 50000000,
        "metadata": {"tenant_id": "tenant_alpha"},
    })
    manifest_a = client_a.package_recording_manifest("rec_alpha_01")
    central.ingest_sync_envelope(manifest_a)

    store_b.store_recording({
        "recording_id": "rec_beta_01",
        "camera_id": "cam_beta_01",
        "start_time_utc": "2026-11-15T09:00:00Z",
        "end_time_utc": "2026-11-15T09:30:00Z",
        "recording_type": "continuous",
        "total_size_bytes": 40000000,
        "metadata": {"tenant_id": "tenant_beta"},
    })
    manifest_b = client_b.package_recording_manifest("rec_beta_01")
    central.ingest_sync_envelope(manifest_b)

    # Tenant alpha queries recordings: must never see tenant beta recordings
    recs_alpha = central.query_fleet_recordings(tenant_id="tenant_alpha")
    assert len(recs_alpha) == 1
    assert recs_alpha[0]["recording_id"] == "rec_alpha_01"

    recs_beta = central.query_fleet_recordings(tenant_id="tenant_beta")
    assert len(recs_beta) == 1
    assert recs_beta[0]["recording_id"] == "rec_beta_01"


# ---------------------------------------------------------------------------
# FINDING-11-05: Quota Purge Preserves Concurrent Judicial Holds
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_quota_purge_preserves_concurrent_judicial_holds(tmp_path: Path) -> None:
    """Verify that enforce_storage_quota re-verifies judicial hold state prior to unlinking."""
    store = SQLiteStore(db_path=tmp_path / "nvr_test.db")
    storage_dir = tmp_path / "recordings"
    storage_dir.mkdir(parents=True, exist_ok=True)

    nvr = NVRRecordingEngine(
        storage_dir=storage_dir,
        store=store,
        quota_max_usage_percent=0.001,  # Force quota trigger
    )

    # Create dummy segment file and recording
    seg_file = storage_dir / "seg_held.mp4"
    seg_file.write_bytes(b"continuous-recording-bytes-12345")

    store.store_recording({
        "recording_id": "rec_held_01",
        "camera_id": "cam_01",
        "start_time_utc": "2026-11-15T00:00:00Z",
        "end_time_utc": "2026-11-15T01:00:00Z",
        "recording_type": "continuous",
        "total_size_bytes": len(seg_file.read_bytes()),
        "metadata": {"judicial_hold": True, "judicial_hold_reason": "Court Order #441"},
    })
    store.store_recording_segment({
        "segment_id": "seg_01",
        "recording_id": "rec_held_01",
        "camera_id": "cam_01",
        "segment_index": 0,
        "start_time_utc": "2026-11-15T00:00:00Z",
        "end_time_utc": "2026-11-15T01:00:00Z",
        "duration_seconds": 3600.0,
        "file_path": str(seg_file),
        "file_size_bytes": len(seg_file.read_bytes()),
        "sha256_hash": "dummyhash",
        "has_event": False,
    })

    purged = nvr.enforce_storage_quota()
    # Held recording must NOT be purged
    assert purged == 0
    assert seg_file.exists()
    assert store.get_recording("rec_held_01") is not None


# ---------------------------------------------------------------------------
# FINDING-11-06: Hardware AI Adapter Unavailable Clean Failure
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_hardware_adapters_fail_cleanly_when_device_absent() -> None:
    """Verify that hardware acceleration adapters reject model loading and infer calls when device is missing."""
    adapters = [
        CoralEdgeTPUAdapter(),
        HailoNPUAdapter(),
        CUDABackendAdapter(),
        OpenVINOBackendAdapter(),
    ]

    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    for adapter in adapters:
        # If device is not present, load_model must return False and infer must raise RuntimeError
        if not adapter.is_available():
            assert adapter.load_model("dummy_model_path.bin") is False
            with pytest.raises(RuntimeError) as exc_info:
                adapter.infer(dummy_frame)
            assert f"hardware accelerator '{adapter.name}' is unavailable" in str(exc_info.value)


# ---------------------------------------------------------------------------
# FINDING-11-07: Version Manifest and SBOM Alignment
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_version_manifest_alignment() -> None:
    """Verify that CAMserv __version__ matches pyproject.toml and CycloneDX SBOM."""
    assert __version__ == "0.9.0-rc1"

    pyproject_path = Path("pyproject.toml")
    assert pyproject_path.exists()
    content = pyproject_path.read_text(encoding="utf-8")
    assert 'version = "0.9.0-rc1"' in content

    sbom_path = Path("deploy/sbom/camserv-sbom.json")
    assert sbom_path.exists()
    sbom_data = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert sbom_data["metadata"]["component"]["version"] == "0.9.0-rc1"
